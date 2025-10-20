import os
import smtplib
import json
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from flask_sqlalchemy import SQLAlchemy
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadTimeSignature
from dotenv import load_dotenv
import requests
from werkzeug.security import generate_password_hash, check_password_hash

# ---------------- ENV SETUP ----------------
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("APP_SECRET_KEY", "supersecretkey")

# ---------------- DATABASE CONFIG ----------------
db_url = os.getenv("DATABASE_URL", "sqlite:///local.db")
if db_url.startswith("postgres://"):
    # SQLAlchemy prefers postgresql://
    db_url = db_url.replace("postgres://", "postgresql://")
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# ---------------- MODELS ----------------
class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(120), unique=True, nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def check_password(self, raw):
        return check_password_hash(self.password_hash, raw)

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

class Analytics(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    metric_name = db.Column(db.String(100))
    metric_value = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ---------------- ENSURE DB/TABLES EXIST ----------------
with app.app_context():
    db.create_all()

# ---------------- CREATE ADMIN IF MISSING (from env) ----------------
def ensure_admin_from_env():
    env_user = os.getenv("ADMIN_USERNAME")
    env_email = os.getenv("ADMIN_EMAIL")
    env_pass = os.getenv("ADMIN_PASSWORD")
    if not env_user or not env_email or not env_pass:
        # If any missing, do nothing here — must be set for admin creation from env
        return

    existing = Admin.query.filter_by(username=env_user).first()
    if existing is None:
        admin = Admin(username=env_user, email=env_email, password_hash="")
        admin.set_password(env_pass)
        db.session.add(admin)
        db.session.commit()
        print("✅ Admin created from environment variables.")
    else:
        # If admin exists but password in DB differs from env_pass (not checked for security),
        # we will not overwrite. Admin should control reset via email.
        print("ℹ️ Admin already exists in database.")

with app.app_context():
    ensure_admin_from_env()

# ---------------- ENV VARS ----------------
PUBLER_API_KEY = os.getenv("PUBLER_API_KEY")
PUBLER_WORKSPACE_ID = os.getenv("PUBLER_WORKSPACE_ID")

# ---------------- PUBLER FETCH ----------------
def fetch_publer_stats():
    if not PUBLER_API_KEY or not PUBLER_WORKSPACE_ID:
        print("⚠️ Missing Publer credentials, skipping fetch.")
        return
    headers = {"Authorization": f"Bearer {PUBLER_API_KEY}"}
    url = f"https://api.publer.io/v1/workspaces/{PUBLER_WORKSPACE_ID}/posts"
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        data = response.json()
        count = len(data.get("data", []))
        new_metric = Analytics(metric_name="Total Posts", metric_value=str(count))
        db.session.add(new_metric)
        db.session.commit()
        print(f"✅ Publer stats fetched — {count} posts saved.")
    except Exception as e:
        print("❌ Error fetching Publer data:", e)

# ---------------- SCHEDULER ----------------
scheduler = BackgroundScheduler()
scheduler.add_job(fetch_publer_stats, "interval", hours=3, next_run_time=datetime.utcnow())
scheduler.start()

# ---------------- EMAIL (RESET) ----------------
def send_reset_email(user_email):
    try:
        s = URLSafeTimedSerializer(app.secret_key)
        token = s.dumps(user_email, salt="password-reset-salt")
        reset_link = f"{request.url_root.rstrip('/')}/reset_password/{token}"

        html_body = render_template("reset_email.html", reset_link=reset_link)

        sender_email = os.getenv("SMTP_USERNAME")
        app_password = os.getenv("SMTP_PASSWORD")
        smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        smtp_port = int(os.getenv("SMTP_PORT", 587))

        if not sender_email or not app_password:
            raise RuntimeError("SMTP_USERNAME and SMTP_PASSWORD must be set in environment to send email.")

        msg = MIMEMultipart("alternative")
        msg["Subject"] = "🔐 Reset Your Slickofficials HQ Password"
        msg["From"] = sender_email
        msg["To"] = user_email
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(smtp_server, smtp_port, timeout=15) as server:
            server.starttls()
            server.login(sender_email, app_password)
            server.send_message(msg)

        print("✅ Reset email sent successfully!")
        return True, "Password reset email sent! Check your inbox."
    except Exception as e:
        print(f"❌ Error sending reset email: {e}")
        return False, f"Error sending reset email: {e}"

# ---------------- AUTH ROUTES ----------------
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = request.form.get("username", "").strip()
        pwd = request.form.get("password", "")
        admin = Admin.query.filter_by(username=user).first()
        if admin and admin.check_password(pwd):
            session["user_id"] = admin.id
            session["username"] = admin.username
            flash("Welcome back.", "success")
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid username or password.", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("user_id", None)
    session.pop("username", None)
    flash("Logged out successfully.", "info")
    return redirect(url_for("login"))

# ---------------- FORGOT PASSWORD ----------------
@app.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        admin = Admin.query.filter_by(email=email).first()
        if admin:
            ok, msg = send_reset_email(email)
            if ok:
                flash(msg, "success")
            else:
                flash(msg, "danger")
        else:
            flash("No admin account with that email.", "danger")
    return render_template("forgot_password.html")

# ---------------- RESET PASSWORD ----------------
@app.route("/reset_password/<token>", methods=["GET", "POST"])
def reset_password(token):
    s = URLSafeTimedSerializer(app.secret_key)
    try:
        email = s.loads(token, salt="password-reset-salt", max_age=1800)  # 30 minutes
    except SignatureExpired:
        flash("Link expired. Please request a new one.", "danger")
        return redirect(url_for("forgot_password"))
    except BadTimeSignature:
        flash("Invalid or tampered link.", "danger")
        return redirect(url_for("forgot_password"))

    admin = Admin.query.filter_by(email=email).first()
    if not admin:
        flash("No admin account for that email.", "danger")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        new_password = request.form.get("password", "")
        if not new_password or len(new_password) < 6:
            flash("Password must be at least 6 characters.", "danger")
            return render_template("reset_password.html", token=token)
        admin.set_password(new_password)
        db.session.commit()
        flash("Admin password reset successfully.", "success")
        return redirect(url_for("login"))

    return render_template("reset_password.html", token=token)

# ---------------- DASHBOARD ----------------
def require_login():
    if "user_id" not in session:
        return False
    return True

@app.route("/dashboard")
def dashboard():
    if not require_login():
        return redirect(url_for("login"))
    # initial render will include current top 10 analytics
    analytics = Analytics.query.order_by(Analytics.created_at.desc()).limit(10).all()
    return render_template("dashboard.html", analytics=analytics, username=session.get("username"))

# Endpoint to get latest analytics (AJAX)
@app.route("/analytics/latest")
def analytics_latest():
    if not require_login():
        return jsonify({"error": "unauthorized"}), 401
    analytics = Analytics.query.order_by(Analytics.created_at.desc()).limit(10).all()
    out = [
        {"metric_name": a.metric_name, "metric_value": a.metric_value, "created_at": a.created_at.isoformat()}
        for a in analytics
    ]
    return jsonify(out)

# ---------------- QUICK ACTIONS ----------------
@app.route("/test_publer")
def test_publer():
    if not require_login():
        return jsonify({"error": "unauthorized"}), 401
    if not PUBLER_API_KEY or not PUBLER_WORKSPACE_ID:
        return jsonify({"error": "Missing Publer credentials."}), 400
    headers = {"Authorization": f"Bearer {PUBLER_API_KEY}"}
    url = f"https://api.publer.io/v1/workspaces/{PUBLER_WORKSPACE_ID}/posts"
    try:
        r = requests.get(url, headers=headers, timeout=15)
        r.raise_for_status()
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/json/analytics")
def json_analytics():
    if not require_login():
        return jsonify({"error": "unauthorized"}), 401
    all_data = Analytics.query.order_by(Analytics.created_at.desc()).all()
    return jsonify([
        {"metric": a.metric_name, "value": a.metric_value, "created": a.created_at.isoformat()}
        for a in all_data
    ])

# ---------------- RUN (dev) ----------------
if __name__ == "__main__":
    # safe create tables in case deploy cmd doesn't run app.app_context() separately
    with app.app_context():
        db.create_all()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
