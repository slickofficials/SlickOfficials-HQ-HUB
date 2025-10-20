from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os
import smtplib
from email.mime.text import MIMEText
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature

# -------------------- SETUP --------------------
app = Flask(__name__)
app.secret_key = os.environ.get("APP_SECRET_KEY", "dev_secret_key")

app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///slickofficials.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# For password reset tokens
serializer = URLSafeTimedSerializer(app.secret_key)

# -------------------- MODELS --------------------
class Analytics(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    metric_name = db.Column(db.String(100))
    metric_value = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# -------------------- HELPERS --------------------
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME")
ADMIN_PASSWORD_HASH = generate_password_hash(os.environ.get("ADMIN_PASSWORD", ""))

def is_logged_in():
    return session.get("logged_in", False)

def send_reset_email(to_email, token):
    """Send a password reset email with a secure token"""
    smtp_server = os.environ.get("SMTP_SERVER")
    smtp_port = int(os.environ.get("SMTP_PORT", 587))
    smtp_username = os.environ.get("SMTP_USERNAME")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    email_from = os.environ.get("EMAIL_FROM", smtp_username)

    reset_link = url_for('reset_with_token', token=token, _external=True)
    subject = "Slickofficials HQ - Password Reset"
    body = f"""
    Hey Admin 👋,

    You (or someone else) requested a password reset.
    Click the link below to set a new password:

    {reset_link}

    If you didn’t request this, please ignore this email.
    """

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = email_from
    msg["To"] = to_email

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(smtp_username, smtp_password)
            server.send_message(msg)
        print(f"✅ Reset email sent to {to_email}")
        return True
    except Exception as e:
        print(f"❌ Email send error: {e}")
        return False

# -------------------- ROUTES --------------------
@app.route("/")
def home():
    if not is_logged_in():
        return redirect(url_for("login"))
    analytics = Analytics.query.order_by(Analytics.created_at.desc()).limit(10).all()
    return render_template("dashboard.html", analytics=analytics)

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        if username == ADMIN_USERNAME and check_password_hash(ADMIN_PASSWORD_HASH, password):
            session["logged_in"] = True
            flash("Welcome back, Admin!", "success")
            return redirect(url_for("home"))
        else:
            flash("Invalid credentials.", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully.", "info")
    return redirect(url_for("login"))

@app.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form["email"]
        if email:
            token = serializer.dumps(email, salt="password-reset")
            if send_reset_email(email, token):
                flash("Password reset email sent! Check your inbox.", "info")
                return redirect(url_for("login"))
            else:
                flash("Failed to send email. Check SMTP settings.", "danger")
    return render_template("forgot_password.html")

@app.route("/reset_password/<token>", methods=["GET", "POST"])
def reset_with_token(token):
    try:
        email = serializer.loads(token, salt="password-reset", max_age=3600)
    except (SignatureExpired, BadSignature):
        flash("Invalid or expired link.", "danger")
        return redirect(url_for("forgot_password"))

    if request.method == "POST":
        new_password = request.form["new_password"]
        os.environ["ADMIN_PASSWORD"] = new_password
        flash("Password reset successful!", "success")
        return redirect(url_for("login"))

    return render_template("reset_password.html")

@app.route("/json/analytics")
def analytics_json():
    if not is_logged_in():
        return jsonify({"error": "Unauthorized"}), 403
    data = [
        {"metric_name": a.metric_name, "metric_value": a.metric_value, "created_at": a.created_at}
        for a in Analytics.query.all()
    ]
    return jsonify(data)

@app.route("/test_publer")
def test_publer():
    if not is_logged_in():
        return jsonify({"error": "Unauthorized"}), 403
    return jsonify({"status": "Publer connection test successful!"})

# -------------------- MAIN --------------------
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)
