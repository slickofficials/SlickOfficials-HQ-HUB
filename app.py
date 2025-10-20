import os
import secrets
import requests
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from flask_sqlalchemy import SQLAlchemy
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

# ---------------- LOAD ENV ----------------
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

# ---------------- ENV KEYS ----------------
PUBLER_API_KEY = os.getenv("PUBLER_API_KEY")
PUBLER_WORKSPACE_ID = os.getenv("PUBLER_WORKSPACE_ID")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "password")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@slickofficials.com")

# ---------------- DATABASE MODELS ----------------
class Analytics(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    metric_name = db.Column(db.String(100))
    metric_value = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class PasswordResetToken(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(100), unique=True)
    email = db.Column(db.String(120))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ---------------- PUBLER FETCH ----------------
def fetch_publer_stats():
    if not PUBLER_API_KEY or not PUBLER_WORKSPACE_ID:
        print("Missing Publer credentials.")
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
        print("✅ Publer stats updated successfully.")
    except Exception as e:
        print("Error fetching Publer data:", e)

# ---------------- SCHEDULER ----------------
scheduler = BackgroundScheduler()
scheduler.add_job(fetch_publer_stats, "interval", hours=3)
scheduler.start()

# ---------------- AUTH ROUTES ----------------
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = request.form["username"]
        pwd = request.form["password"]
        if user == ADMIN_USERNAME and pwd == ADMIN_PASSWORD:
            session["user"] = user
            return redirect(url_for("dashboard"))
        flash("Invalid credentials, try again.", "error")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("login"))

# ---------------- FORGOT PASSWORD ----------------
@app.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form["email"]
        if email != ADMIN_EMAIL:
            flash("Email not recognized.", "error")
            return redirect(url_for("forgot_password"))

        token = secrets.token_hex(16)
        reset_entry = PasswordResetToken(token=token, email=email)
        db.session.add(reset_entry)
        db.session.commit()
        reset_link = url_for("reset_with_token", token=token, _external=True)
        print(f"🔐 Password reset link: {reset_link}")  # Normally sent via email
        flash("Password reset link generated! Check console/logs.", "info")
        return redirect(url_for("login"))

    return render_template("forgot_password.html")

# ---------------- RESET PASSWORD ----------------
@app.route("/reset/<token>", methods=["GET", "POST"])
def reset_with_token(token):
    reset_token = PasswordResetToken.query.filter_by(token=token).first()
    if not reset_token:
        flash("Invalid or expired token.", "error")
        return redirect(url_for("login"))

    if datetime.utcnow() - reset_token.created_at > timedelta(hours=2):
        db.session.delete(reset_token)
        db.session.commit()
        flash("Token expired, please request a new one.", "error")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        pwd = request.form["password"]
        confirm_pwd = request.form["confirm_password"]
        if pwd != confirm_pwd:
            flash("Passwords do not match.", "error")
            return redirect(url_for("reset_with_token", token=token))

        os.environ["ADMIN_PASSWORD"] = pwd
        db.session.delete(reset_token)
        db.session.commit()
        flash("Password successfully reset! You can log in now.", "success")
        return redirect(url_for("login"))

    return render_template("reset_with_token.html")

# ---------------- DASHBOARD ----------------
@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))
    analytics = Analytics.query.order_by(Analytics.created_at.desc()).limit(10).all()
    return render_template("dashboard.html", analytics=analytics)

# ---------------- JSON ENDPOINTS ----------------
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
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
