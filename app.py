import os
import time
import requests
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from flask_sqlalchemy import SQLAlchemy
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from dotenv import load_dotenv
from flask_mail import Mail, Message
import secrets

# ------------------- CONFIG -------------------
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("APP_SECRET_KEY", "supersecretkey")

db_url = os.getenv("DATABASE_URL", "sqlite:///local.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://")
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

# Mail Config
app.config["MAIL_SERVER"] = "smtp.gmail.com"
app.config["MAIL_PORT"] = 587
app.config["MAIL_USE_TLS"] = True
app.config["MAIL_USERNAME"] = os.getenv("MAIL_USERNAME")
app.config["MAIL_PASSWORD"] = os.getenv("MAIL_PASSWORD")
mail = Mail(app)

db = SQLAlchemy(app)

PUBLER_API_KEY = os.getenv("PUBLER_API_KEY")
PUBLER_WORKSPACE_ID = os.getenv("PUBLER_WORKSPACE_ID")

# ------------------- MODELS -------------------
class Analytics(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    metric_name = db.Column(db.String(100))
    metric_value = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    reset_token = db.Column(db.String(255), nullable=True)
    failed_attempts = db.Column(db.Integer, default=0)
    lockout_until = db.Column(db.DateTime, nullable=True)

# ------------------- AUTO CREATE ADMIN -------------------
@app.before_first_request
def create_admin():
    db.create_all()
    admin = User.query.filter_by(username="admin").first()
    if not admin:
        admin = User(username="admin", password=generate_password_hash("password"))
        db.session.add(admin)
        db.session.commit()
        print("✅ Admin user created: username='admin' password='password'")

# ------------------- PUBLER API -------------------
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

scheduler = BackgroundScheduler()
scheduler.add_job(fetch_publer_stats, "interval", hours=3)
scheduler.start()

# ------------------- ROUTES -------------------
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = request.form["username"]
        pwd = request.form["password"]
        admin = User.query.filter_by(username=user).first()

        if not admin:
            flash("Invalid login.")
            return render_template("login.html")

        # Lockout Check
        if admin.lockout_until and datetime.utcnow() < admin.lockout_until:
            remaining = (admin.lockout_until - datetime.utcnow()).seconds // 60
            flash(f"Account locked. Try again in {remaining} minute(s).")
            return render_template("login.html")

        # Password Check
        if check_password_hash(admin.password, pwd):
            admin.failed_attempts = 0
            admin.lockout_until = None
            db.session.commit()
            session["user"] = admin.username
            return redirect(url_for("dashboard"))
        else:
            admin.failed_attempts += 1
            if admin.failed_attempts >= 5:
                admin.lockout_until = datetime.utcnow() + timedelta(minutes=5)
                flash("Too many failed attempts. Locked for 5 minutes.")
            else:
                flash("Wrong password.")
            db.session.commit()
            return render_template("login.html")

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("user", None)
    flash("You’ve been logged out.")
    return redirect(url_for("login"))

@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))
    analytics = Analytics.query.order_by(Analytics.created_at.desc()).limit(10).all()
    return render_template("dashboard.html", analytics=analytics)

@app.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        username = request.form["username"]
        user = User.query.filter_by(username=username).first()
        if user:
            token = secrets.token_hex(16)
            user.reset_token = token
            db.session.commit()
            reset_link = url_for("reset_with_token", token=token, _external=True)

            msg = Message("Password Reset - Slickofficials HQ",
                          sender=app.config["MAIL_USERNAME"],
                          recipients=[app.config["MAIL_USERNAME"]])
            msg.body = f"Hello Admin,\n\nClick below to reset your password:\n{reset_link}\n\nThis link expires in 10 minutes."
            mail.send(msg)
            flash("Password reset link sent to admin email.")
        else:
            flash("User not found.")
    return render_template("reset_password.html")

@app.route("/reset/<token>", methods=["GET", "POST"])
def reset_with_token(token):
    user = User.query.filter_by(reset_token=token).first()
    if not user:
        flash("Invalid or expired token.")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        new_password = request.form["password"]
        user.password = generate_password_hash(new_password)
        user.reset_token = None
        db.session.commit()
        flash("Password successfully reset. You can now log in.")
        return redirect(url_for("login"))
    return render_template("reset_with_token.html")

@app.route("/test_publer")
def test_publer():
    if "user" not in session:
        return redirect(url_for("login"))
    headers = {"Authorization": f"Bearer {PUBLER_API_KEY}"}
    url = f"https://api.publer.io/v1/workspaces/{PUBLER_WORKSPACE_ID}/posts"
    r = requests.get(url, headers=headers)
    return jsonify(r.json())

@app.route("/json/analytics")
def json_analytics():
    if "user" not in session:
        return redirect(url_for("login"))
    all_data = Analytics.query.all()
    return jsonify([
        {"metric": a.metric_name, "value": a.metric_value, "created": a.created_at.isoformat()}
        for a in all_data
    ])

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
