import os
import requests
import smtplib
from email.mime.text import MIMEText
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from flask_sqlalchemy import SQLAlchemy
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
import secrets

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("APP_SECRET_KEY", "supersecretkey")

# ---------------- DATABASE CONFIG ----------------
db_url = os.getenv("DATABASE_URL", "sqlite:///local.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://")

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# ---------------- MODELS ----------------
class Admin(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True)
    password_hash = db.Column(db.String(200))

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class ResetToken(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(200), unique=True)
    expires_at = db.Column(db.DateTime)

class Analytics(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    metric_name = db.Column(db.String(100))
    metric_value = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ---------------- PUBLER API ----------------
PUBLER_API_KEY = os.getenv("PUBLER_API_KEY")
PUBLER_WORKSPACE_ID = os.getenv("PUBLER_WORKSPACE_ID")

def fetch_publer_stats():
    headers = {"Authorization": f"Bearer {PUBLER_API_KEY}"}
    url = f"https://api.publer.io/v1/workspaces/{PUBLER_WORKSPACE_ID}/posts"
    try:
        response = requests.get(url, headers=headers)
        data = response.json()
        count = len(data.get("data", []))
        new_metric = Analytics(metric_name="Total Posts", metric_value=str(count))
        db.session.add(new_metric)
        db.session.commit()
    except Exception as e:
        print("Error fetching Publer data:", e)

# ---------------- SCHEDULER ----------------
scheduler = BackgroundScheduler()
scheduler.add_job(fetch_publer_stats, "interval", hours=3)
scheduler.start()

# ---------------- UTIL: SEND EMAIL ----------------
def send_reset_email(link):
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", 587))
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASS")
    to_email = os.getenv("ALERT_EMAIL_TO", smtp_user)

    subject = "🔐 Slickofficials HQ Password Reset Link"
    body = f"""
    Hello Admin,

    A password reset was requested for your Slickofficials HQ dashboard.
    Click below to reset your password (valid for 10 minutes):

    {link}

    If you did not request this, please ignore this email.

    — Slickofficials HQ Security
    """

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = to_email

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
        print("✅ Password reset email sent successfully.")
    except Exception as e:
        print("❌ Error sending email:", e)

# ---------------- AUTH ----------------
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = request.form["username"]
        pwd = request.form["password"]
        admin = Admin.query.filter_by(username=user).first()
        if admin and admin.check_password(pwd):
            session["user"] = user
            return redirect(url_for("dashboard"))
        return render_template("login.html", error="Invalid login. Try again.")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("login"))

# ---------------- FORGOT PASSWORD ----------------
@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        token = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + timedelta(minutes=10)
        db.session.add(ResetToken(token=token, expires_at=expires_at))
        db.session.commit()

        reset_link = f"{request.url_root}reset-password/{token}"
        send_reset_email(reset_link)

        flash("✅ Password reset link sent to your email!", "success")
        return render_template("forgot_password.html", success="Check your inbox for the reset link.")
    return render_template("forgot_password.html")

# ---------------- RESET PASSWORD ----------------
@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    reset = ResetToken.query.filter_by(token=token).first()
    if not reset or reset.expires_at < datetime.utcnow():
        return render_template("reset_password.html", error="❌ Token expired or invalid.")

    if request.method == "POST":
        new_pass = request.form["password"]
        admin = Admin.query.filter_by(username="admin").first()
        if not admin:
            admin = Admin(username="admin")
            db.session.add(admin)
        admin.set_password(new_pass)
        db.session.commit()

        db.session.delete(reset)
        db.session.commit()

        return render_template("reset_password.html", success="✅ Password reset successful! You can now log in.")
    return render_template("reset_password.html")

# ---------------- DASHBOARD ----------------
@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))
    analytics = Analytics.query.order_by(Analytics.created_at.desc()).limit(10).all()
    return render_template("dashboard.html", analytics=analytics)

# ---------------- QUICK ACTIONS ----------------
@app.route("/test_publer")
def test_publer():
    if not PUBLER_API_KEY or not PUBLER_WORKSPACE_ID:
        return jsonify({"error": "Missing Publer credentials."}), 400
    headers = {"Authorization": f"Bearer {PUBLER_API_KEY}"}
    url = f"https://api.publer.io/v1/workspaces/{PUBLER_WORKSPACE_ID}/posts"
    r = requests.get(url, headers=headers)
    return jsonify(r.json())

@app.route("/json/analytics")
def json_analytics():
    all_data = Analytics.query.all()
    return jsonify([
        {"metric": a.metric_name, "value": a.metric_value, "created": a.created_at.isoformat()}
        for a in all_data
    ])

# ---------------- INIT ----------------
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        if not Admin.query.filter_by(username="admin").first():
            admin = Admin(username="admin")
            admin.set_password("password123")
            db.session.add(admin)
            db.session.commit()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
