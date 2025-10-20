import os
import smtplib
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from flask_sqlalchemy import SQLAlchemy
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadTimeSignature
from dotenv import load_dotenv
import requests

# ---------------- ENV SETUP ----------------
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

# ✅ Ensure tables always exist (Render-friendly)
with app.app_context():
    db.create_all()

# ---------------- ENV VARIABLES ----------------
PUBLER_API_KEY = os.getenv("PUBLER_API_KEY")
PUBLER_WORKSPACE_ID = os.getenv("PUBLER_WORKSPACE_ID")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "password")

# ---------------- DATABASE MODELS ----------------
class Analytics(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    metric_name = db.Column(db.String(100))
    metric_value = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ---------------- PUBLER FETCH ----------------
def fetch_publer_stats():
    if not PUBLER_API_KEY or not PUBLER_WORKSPACE_ID:
        print("⚠️ Missing Publer credentials, skipping fetch.")
        return
    headers = {"Authorization": f"Bearer {PUBLER_API_KEY}"}
    url = f"https://api.publer.io/v1/workspaces/{PUBLER_WORKSPACE_ID}/posts"
    try:
        response = requests.get(url, headers=headers)
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
scheduler.add_job(fetch_publer_stats, "interval", hours=3)
scheduler.start()

# ---------------- PASSWORD RESET EMAIL ----------------
def send_reset_email(user_email):
    try:
        s = URLSafeTimedSerializer(app.secret_key)
        token = s.dumps(user_email, salt="password-reset-salt")
        reset_link = f"{request.url_root}reset_password/{token}"

        html_body = render_template("reset_email.html", reset_link=reset_link)

        sender_email = os.getenv("SMTP_USERNAME")
        app_password = os.getenv("SMTP_PASSWORD")
        smtp_server = os.getenv("SMTP_SERVER", "smtp.gmail.com")
        smtp_port = int(os.getenv("SMTP_PORT", 587))

        msg = MIMEMultipart("alternative")
        msg["Subject"] = "🔐 Reset Your Slickofficials HQ Password"
        msg["From"] = sender_email
        msg["To"] = user_email
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender_email, app_password)
            server.send_message(msg)

        print("✅ Reset email sent successfully!")
        flash("Password reset email sent! Check your inbox.", "success")

    except Exception as e:
        print(f"❌ Error sending reset email: {e}")
        flash("Error sending reset email.", "danger")

# ---------------- AUTH ROUTES ----------------
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = request.form["username"]
        pwd = request.form["password"]

        if user == ADMIN_USERNAME and pwd == ADMIN_PASSWORD:
            session["user"] = user
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid login. Try again.", "danger")

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("user", None)
    flash("Logged out successfully.", "info")
    return redirect(url_for("login"))

# ---------------- FORGOT PASSWORD ----------------
@app.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email")

        if email == ADMIN_EMAIL:
            send_reset_email(email)
        else:
            flash("Unauthorized email.", "danger")

    return render_template("forgot_password.html")

# ---------------- RESET PASSWORD ----------------
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
        if email == ADMIN_EMAIL:
            os.environ["ADMIN_PASSWORD"] = new_password
            flash("✅ Password reset successful. Please log in.", "success")
            return redirect(url_for("login"))

    return render_template("reset_password.html")

# ---------------- DASHBOARD ----------------
@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))

    analytics = Analytics.query.order_by(Analytics.created_at.desc()).limit(10).all()
    return render_template("dashboard.html", analytics=analytics)

# ---------------- JSON ROUTES ----------------
@app.route("/json/analytics")
def json_analytics():
    all_data = Analytics.query.all()
    return jsonify([
        {"metric": a.metric_name, "value": a.metric_value, "created": a.created_at.isoformat()}
        for a in all_data
    ])

# ---------------- RUN APP ----------------
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
