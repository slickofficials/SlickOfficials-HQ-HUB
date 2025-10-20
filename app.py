import os
import io
import smtplib
import traceback
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
    send_file,
)
from flask_sqlalchemy import SQLAlchemy
from itsdangerous import URLSafeTimedSerializer, BadTimeSignature, SignatureExpired
from werkzeug.utils import secure_filename

# ---------------- ENV & APP SETUP ----------------
load_dotenv()

app = Flask(__name__, template_folder="templates", static_folder="static")
app.secret_key = os.getenv("APP_SECRET_KEY", "supersecretkey")

# DB config (auto switch postgres url format)
db_url = os.getenv("DATABASE_URL", "sqlite:///local.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://")
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Uploads (for images)
UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "mp4", "mov"}

db = SQLAlchemy(app)

# ---------------- ENV VARS ----------------
PUBLER_API_KEY = os.getenv("PUBLER_API_KEY")
PUBLER_WORKSPACE_ID = os.getenv("PUBLER_WORKSPACE_ID")

# Social tokens (you'll add these to .env)
META_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN")
META_PAGE_ID = os.getenv("META_PAGE_ID")
INSTAGRAM_BUSINESS_ID = os.getenv("INSTAGRAM_BUSINESS_ID")

TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN")
TWITTER_API_KEY = os.getenv("TWITTER_API_KEY")
TWITTER_API_SECRET = os.getenv("TWITTER_API_SECRET")
TWITTER_ACCESS_TOKEN = os.getenv("TWITTER_ACCESS_TOKEN")
TWITTER_ACCESS_SECRET = os.getenv("TWITTER_ACCESS_SECRET")

TIKTOK_ACCESS_TOKEN = os.getenv("TIKTOK_ACCESS_TOKEN")
TIKTOK_USER_ID = os.getenv("TIKTOK_USER_ID")

SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "password")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "")

# ---------------- MODELS ----------------
class Analytics(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    metric_name = db.Column(db.String(100))
    metric_value = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200))
    body = db.Column(db.Text)
    image_filename = db.Column(db.String(300), nullable=True)
    platforms = db.Column(db.String(200))  # CSV: instagram,facebook,x,tiktok
    scheduled_for = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(50), default="pending")  # pending, posted, failed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    result_log = db.Column(db.Text, nullable=True)


# ensure tables created at start (safe context)
with app.app_context():
    db.create_all()


# ---------------- HELPERS ----------------
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def append_log(post: Post, text: str):
    now = datetime.now(timezone.utc).astimezone().isoformat()
    post.result_log = (post.result_log or "") + f"\n[{now}] {text}"
    db.session.add(post)
    db.session.commit()


# ---------------- PLATFORM POSTING (STUBS) ----------------
# These functions contain example flows. Replace / expand with real API calls for production.
# They must return dict {"ok": True/False, "msg": "...", "meta": {...}}

def post_to_facebook(text: str, image_path: str | None):
    try:
        # Example: Post to Facebook Page using Graph API (page access token)
        if not META_ACCESS_TOKEN or not META_PAGE_ID:
            return {"ok": False, "msg": "Missing Facebook/META credentials"}

        url = f"https://graph.facebook.com/{META_PAGE_ID}/feed"
        payload = {"message": text, "access_token": META_ACCESS_TOKEN}
        if image_path:
            # Note: real media upload is multi-step. This is a simplified placeholder.
            payload["message"] = text + "\n\n(Has image — upload logic skipped in stub)"
        r = requests.post(url, data=payload, timeout=15)
        if r.status_code in (200, 201):
            return {"ok": True, "msg": "Posted to Facebook", "meta": r.json()}
        return {"ok": False, "msg": f"FB error {r.status_code} {r.text}"}
    except Exception as e:
        return {"ok": False, "msg": f"Exception: {e}"}


def post_to_instagram(text: str, image_path: str | None):
    try:
        # Instagram Graph API requires container creation, publishing. This stub mimics success/failure.
        if not INSTAGRAM_BUSINESS_ID or not META_ACCESS_TOKEN:
            return {"ok": False, "msg": "Missing Instagram credentials"}
        # Stub: pretend we posted
        return {"ok": True, "msg": "Posted to Instagram (stub)", "meta": {}}
    except Exception as e:
        return {"ok": False, "msg": f"Exception: {e}"}


def post_to_twitter(text: str, image_path: str | None):
    try:
        if not TWITTER_BEARER_TOKEN:
            return {"ok": False, "msg": "Missing Twitter/X credentials"}
        # Stub: pretend we posted
        return {"ok": True, "msg": "Posted to X/Twitter (stub)", "meta": {}}
    except Exception as e:
        return {"ok": False, "msg": f"Exception: {e}"}


def post_to_tiktok(text: str, image_path: str | None):
    try:
        if not TIKTOK_ACCESS_TOKEN:
            return {"ok": False, "msg": "Missing TikTok credentials"}
        # Stub: pretend we posted
        return {"ok": True, "msg": "Posted to TikTok (stub)", "meta": {}}
    except Exception as e:
        return {"ok": False, "msg": f"Exception: {e}"}


# ---------------- SCHEDULER JOBS ----------------
def process_pending_posts():
    """Find posts with status 'pending' and scheduled_for <= now (or immediate), and publish them."""
    try:
        now = datetime.utcnow()
        candidates = Post.query.filter(
            Post.status == "pending",
            (Post.scheduled_for == None) | (Post.scheduled_for <= now),
        ).order_by(Post.scheduled_for.asc().nullsfirst()).all()

        for p in candidates:
            append_log(p, f"Processing post id={p.id} platforms={p.platforms}")
            platforms = [s.strip().lower() for s in (p.platforms or "").split(",") if s.strip()]

            overall_ok = True
            for platform in platforms:
                try:
                    if platform == "facebook":
                        res = post_to_facebook(p.body or p.title or "", os.path.join(app.config["UPLOAD_FOLDER"], p.image_filename) if p.image_filename else None)
                    elif platform == "instagram":
                        res = post_to_instagram(p.body or p.title or "", os.path.join(app.config["UPLOAD_FOLDER"], p.image_filename) if p.image_filename else None)
                    elif platform in ("x", "twitter"):
                        res = post_to_twitter(p.body or p.title or "", os.path.join(app.config["UPLOAD_FOLDER"], p.image_filename) if p.image_filename else None)
                    elif platform == "tiktok":
                        res = post_to_tiktok(p.body or p.title or "", os.path.join(app.config["UPLOAD_FOLDER"], p.image_filename) if p.image_filename else None)
                    else:
                        res = {"ok": False, "msg": f"Unknown platform: {platform}"}
                except Exception as e:
                    res = {"ok": False, "msg": f"Exception while posting to {platform}: {e}"}

                append_log(p, f"platform={platform} -> {res.get('msg')}")
                if not res.get("ok"):
                    overall_ok = False

            p.status = "posted" if overall_ok else "failed"
            db.session.add(p)
            db.session.commit()
    except Exception:
        print("Error in process_pending_posts:")
        traceback.print_exc()


def fetch_basic_analytics():
    """Example analytics job — pull follower counts or post counts and save to Analytics."""
    try:
        # Example Publer stats (if available)
        if PUBLER_API_KEY and PUBLER_WORKSPACE_ID:
            headers = {"Authorization": f"Bearer {PUBLER_API_KEY}"}
            url = f"https://api.publer.io/v1/workspaces/{PUBLER_WORKSPACE_ID}/posts"
            try:
                r = requests.get(url, headers=headers, timeout=10)
                json_data = r.json()
                count = len(json_data.get("data", []))
                db.session.add(Analytics(metric_name="Publer posts", metric_value=str(count)))
                db.session.commit()
            except Exception:
                append_generic = False
        # Also example other platform follower fetch stubs
        # Instagram followers stub:
        if INSTAGRAM_BUSINESS_ID and META_ACCESS_TOKEN:
            # Real fetch requires Graph API calls — stubbed
            db.session.add(Analytics(metric_name="IG followers (stub)", metric_value="n/a"))
            db.session.commit()

    except Exception:
        print("Error in fetch_basic_analytics:")
        traceback.print_exc()


# Start APScheduler, but guard to avoid double start under multiple gunicorn workers.
scheduler = BackgroundScheduler(timezone="UTC")
if os.environ.get("RUN_SCHEDULER", "true").lower() == "true":
    try:
        # Add jobs if not already present
        if not any(job.id == "process_posts" for job in scheduler.get_jobs()):
            scheduler.add_job(process_pending_posts, "interval", seconds=15, id="process_posts", max_instances=1)
        if not any(job.id == "fetch_analytics" for job in scheduler.get_jobs()):
            scheduler.add_job(fetch_basic_analytics, "interval", minutes=15, id="fetch_analytics", max_instances=1)
        # Start only if not running
        if not scheduler.running:
            scheduler.start()
    except Exception:
        # If scheduler can't start (e.g. at import time under weird env), print but continue.
        print("Warning: could not start scheduler (maybe already running in worker).")
        traceback.print_exc()


# ---------------- EMAIL RESET ----------------
def send_reset_email(user_email):
    try:
        s = URLSafeTimedSerializer(app.secret_key)
        token = s.dumps(user_email, salt="password-reset-salt")
        reset_link = f"{request.url_root}reset_password/{token}"

        html_body = render_template("reset_email.html", reset_link=reset_link)

        msg = MIMEMultipart("alternative")
        msg["Subject"] = "🔐 Reset Your Slickofficials HQ Password"
        msg["From"] = SMTP_USERNAME or "no-reply@example.com"
        msg["To"] = user_email
        msg.attach(MIMEText(html_body, "html"))

        if not SMTP_USERNAME or not SMTP_PASSWORD:
            append = "SMTP not configured — would print email contents to logs"
            print(append)
            print(html_body)
            return {"ok": True, "msg": "SMTP not configured - check logs (development)"}

        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=20) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)

        return {"ok": True, "msg": "Reset email sent"}
    except Exception as exc:
        traceback.print_exc()
        return {"ok": False, "msg": f"Error sending email: {exc}"}


# ---------------- ROUTES ----------------
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = request.form.get("username", "")
        pwd = request.form.get("password", "")

        if user == ADMIN_USERNAME and pwd == ADMIN_PASSWORD:
            session["user"] = user
            flash("Welcome back, admin.", "success")
            return redirect(url_for("dashboard"))
        flash("Invalid login. Try again.", "danger")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("user", None)
    flash("Logged out.", "info")
    return redirect(url_for("login"))


@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))
    # initial rendering of dashboard (analytics table will be updated by JS auto-refresh)
    analytics = Analytics.query.order_by(Analytics.created_at.desc()).limit(10).all()
    posts = Post.query.order_by(Post.created_at.desc()).limit(10).all()
    return render_template("dashboard.html", analytics=analytics, posts=posts)


@app.route("/upload/<filename>")
def upload_file(filename):
    path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    if not os.path.exists(path):
        return ("Not found", 404)
    return send_file(path)


@app.route("/create_post", methods=["GET", "POST"])
def create_post():
    if "user" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        title = request.form.get("title")
        body = request.form.get("body")
        platforms = request.form.getlist("platforms")
        scheduled_for_str = request.form.get("scheduled_for")
        scheduled_for = None
        if scheduled_for_str:
            try:
                scheduled_for = datetime.fromisoformat(scheduled_for_str)
            except Exception:
                scheduled_for = None

        image = request.files.get("image")
        filename = None
        if image and image.filename and allowed_file(image.filename):
            filename = f"{int(datetime.utcnow().timestamp())}_{secure_filename(image.filename)}"
            path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            image.save(path)

        p = Post(
            title=title,
            body=body,
            image_filename=filename,
            platforms=",".join(platforms),
            scheduled_for=scheduled_for,
            status="pending",
        )
        db.session.add(p)
        db.session.commit()
        flash("Post created and queued.", "success")
        return redirect(url_for("dashboard"))

    return render_template("create_post.html")


@app.route("/posts/<int:post_id>")
def view_post(post_id):
    if "user" not in session:
        return redirect(url_for("login"))
    p = Post.query.get_or_404(post_id)
    return render_template("view_post.html", post=p)


@app.route("/api/analytics")
def api_analytics():
    # returns JSON for auto-refresh every 3 seconds
    data = Analytics.query.order_by(Analytics.created_at.desc()).limit(20).all()
    return jsonify([
        {"metric": a.metric_name, "value": a.metric_value, "created": a.created_at.isoformat()}
        for a in data
    ])


@app.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email")
        if not ADMIN_EMAIL:
            flash("No admin email configured on server.", "danger")
            return render_template("forgot_password.html")
        if email != ADMIN_EMAIL:
            flash("Unauthorized email.", "danger")
            return render_template("forgot_password.html")
        res = send_reset_email(email)
        if res.get("ok"):
            flash("Password reset email sent. Check logs/inbox.", "success")
        else:
            flash("Error sending reset email: " + res.get("msg", ""), "danger")
    return render_template("forgot_password.html")


@app.route("/reset_password/<token>", methods=["GET", "POST"])
def reset_password(token):
    s = URLSafeTimedSerializer(app.secret_key)
    try:
        email = s.loads(token, salt="password-reset-salt", max_age=1800)
    except SignatureExpired:
        return "⚠️ Link expired. Please request a new one."
    except BadTimeSignature:
        return "⚠️ Invalid or tampered link."

    if request.method == "POST":
        new_password = request.form.get("password")
        # For single-admin site, update the environment variable in runtime (note: ephemeral)
        if email == ADMIN_EMAIL:
            # In production, store password in a vault or DB; env var edit here is ephemeral
            os.environ["ADMIN_PASSWORD"] = new_password
            flash("Admin password reset successfully.", "success")
            return redirect(url_for("login"))
        else:
            flash("Unauthorized.", "danger")
    return render_template("reset_password.html")


@app.route("/test_publer")
def test_publer():
    if not PUBLER_API_KEY or not PUBLER_WORKSPACE_ID:
        return jsonify({"error": "Missing Publer credentials."}), 400
    headers = {"Authorization": f"Bearer {PUBLER_API_KEY}"}
    url = f"https://api.publer.io/v1/workspaces/{PUBLER_WORKSPACE_ID}/posts"
    try:
        r = requests.get(url, headers=headers, timeout=10)
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ---------------- MAIN ----------------
if __name__ == "__main__":
    # Only run the dev server here; production should use gunicorn
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=False)
