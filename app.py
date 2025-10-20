import os
import json
from datetime import datetime
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    jsonify,
)
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text, inspect
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
import requests

# Load .env in local/dev. In Render you set env vars in the dashboard.
load_dotenv()

app = Flask(__name__, template_folder="templates")
app.secret_key = os.getenv("APP_SECRET_KEY", "fallback_dev_secret_key_please_change")

# ---------------- Database configuration ----------------
db_url = os.getenv("DATABASE_URL", "sqlite:///local.db")
# Allow common Heroku-style DATABASE_URL fix
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://")
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)


# ---------------- Models ---------------- #
class Analytics(db.Model):
    __tablename__ = "analytics"
    id = db.Column(db.Integer, primary_key=True)
    platform = db.Column(db.String(50), nullable=True)
    clicks = db.Column(db.Integer, nullable=True, default=0)
    impressions = db.Column(db.Integer, nullable=True, default=0)
    conversions = db.Column(db.Integer, nullable=True, default=0)
    revenue = db.Column(db.Float, nullable=True, default=0.0)
    date = db.Column(db.DateTime, default=datetime.utcnow)


def ensure_columns():
    """
    If the table exists but columns are missing (e.g. after code changes),
    add them with ALTER TABLE. This keeps simple deploys from crashing.
    """
    inspector = inspect(db.engine)
    if "analytics" in inspector.get_table_names():
        cols = [c["name"] for c in inspector.get_columns("analytics")]
        with db.engine.begin() as conn:
            if "conversions" not in cols:
                conn.execute(text("ALTER TABLE analytics ADD COLUMN conversions INTEGER"))
            if "revenue" not in cols:
                conn.execute(text("ALTER TABLE analytics ADD COLUMN revenue FLOAT"))
    else:
        # create fresh tables
        db.create_all()


with app.app_context():
    # create tables or add missing columns
    ensure_columns()
    print("[init_db] Tables initialized or updated ✅")


# ---------------- Authentication helpers ---------------- #
def valid_credentials(username, password):
    env_user = os.getenv("APP_USERNAME")
    env_pass = os.getenv("APP_PASSWORD")
    # If username/password not set in env, fall back to a secure default for local dev
    if not env_user or not env_pass:
        # NOTE: change this in production! This fallback is only for local dev.
        env_user = env_user or "admin"
        env_pass = env_pass or "admin"
    return username == env_user and password == env_pass


# ---------------- Routes: Login / Logout ---------------- #
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        if valid_credentials(username, password):
            session["user"] = username
            flash(f"Welcome back, {username}!", "success")
            # support redirect after login
            next_url = request.args.get("next") or url_for("dashboard")
            return redirect(next_url)
        else:
            flash("Invalid username or password.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.pop("user", None)
    flash("You’ve been logged out.", "info")
    return redirect(url_for("login"))


# ---------------- Dashboard ---------------- #
@app.route("/")
@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("login", next=request.path))

    data = Analytics.query.order_by(Analytics.date.desc()).limit(20).all()
    total_clicks = sum((d.clicks or 0) for d in data)
    total_revenue = sum((d.revenue or 0.0) for d in data)

    return render_template(
        "dashboard.html",
        user=session.get("user"),
        analytics=data,
        total_clicks=total_clicks,
        total_revenue=total_revenue,
    )


# ---------------- Create Post (UI) ---------------- #
@app.route("/create_post", methods=["GET", "POST"])
def create_post():
    if "user" not in session:
        return redirect(url_for("login", next=request.path))

    if request.method == "POST":
        # this is a placeholder that would call Publer API to create a post
        title = request.form.get("title", "")
        content = request.form.get("content", "")
        flash("Post submitted (demo). In production this would send to Publer.", "success")
        return redirect(url_for("dashboard"))

    return render_template("create_post.html")


# ---------------- Publer Quick Actions ----------------
PUBLER_BASE = "https://api.publer.io/v1"
PUBLER_API_KEY = os.getenv("PUBLER_API_KEY")
PUBLER_WORKSPACE_ID = os.getenv("PUBLER_WORKSPACE_ID")
PUBLER_USER_ID = os.getenv("PUBLER_USER_ID")


def publer_headers():
    return {"Authorization": f"Bearer {PUBLER_API_KEY}", "Content-Type": "application/json"}


@app.route("/test_publer")
def test_publer():
    """Simple test endpoint to verify Publer auth & connectivity."""
    if not PUBLER_API_KEY:
        flash("PUBLER_API_KEY is not set in environment.", "warning")
        return redirect(url_for("dashboard"))

    try:
        res = requests.get(f"{PUBLER_BASE}/me", headers=publer_headers(), timeout=8)
        res.raise_for_status()
        data = res.json()
        flash("Publer API reachable — check console for details.", "success")
        return jsonify(data)
    except requests.exceptions.RequestException as exc:
        # Friendly error to user + logs
        app.logger.exception("Publer test failed")
        flash(f"Publer test failed: {str(exc)}", "danger")
        return jsonify({"error": "Publer request failed", "detail": str(exc)}), 500


@app.route("/get_recent_posts")
def get_recent_posts():
    """Return recent posts from Publer (JSON)."""
    if not PUBLER_API_KEY or not PUBLER_WORKSPACE_ID:
        return jsonify({"error": "PUBLER_API_KEY or PUBLER_WORKSPACE_ID missing"}), 400
    try:
        url = f"{PUBLER_BASE}/workspaces/{PUBLER_WORKSPACE_ID}/posts?limit=10"
        res = requests.get(url, headers=publer_headers(), timeout=8)
        res.raise_for_status()
        return jsonify(res.json())
    except requests.exceptions.RequestException as exc:
        app.logger.exception("get_recent_posts failed")
        return jsonify({"error": "request failed", "detail": str(exc)}), 500


@app.route("/affiliate_stats")
def affiliate_stats():
    """Simple placeholder to show affiliate stats JSON from analytics table."""
    rows = Analytics.query.order_by(Analytics.date.desc()).limit(30).all()
    out = [
        {
            "id": r.id,
            "platform": r.platform,
            "clicks": r.clicks,
            "impressions": r.impressions,
            "conversions": r.conversions,
            "revenue": r.revenue,
            "date": r.date.isoformat() if r.date else None,
        }
        for r in rows
    ]
    return jsonify(out)


# ---------------- Helper: Add fake analytics (scheduler demo) ---------------- #
def update_data():
    with app.app_context():
        new_entry = Analytics(
            platform="DemoPlatform",
            clicks=100,
            impressions=2000,
            conversions=3,
            revenue=42.5,
        )
        db.session.add(new_entry)
        db.session.commit()
        app.logger.info(f"[Scheduler] Demo analytics added at {datetime.utcnow().isoformat()}")


# Start scheduler once
if not app.config.get("SCHEDULER_STARTED"):
    scheduler = BackgroundScheduler()
    scheduler.add_job(update_data, "interval", hours=6, next_run_time=datetime.utcnow())
    scheduler.start()
    app.config["SCHEDULER_STARTED"] = True
    app.logger.info("[scheduler] started")


# ---------------- Error handlers ---------------- #
@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404


# ---------------- Run ---------------- #
if __name__ == "__main__":
    # only used when running locally
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=False)
