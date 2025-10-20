import os
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Initialize Flask app
app = Flask(__name__)

# Secret key for session
app.secret_key = os.environ.get("SECRET_KEY", "supersecretkey")

# Database setup
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///site.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# Admin credentials (stored in Render Environment)
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")

# Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)

# Routes
@app.route("/")
def home():
    if "logged_in" in session:
        return render_template("dashboard.html")
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["logged_in"] = True
            flash("Welcome back, Admin!", "success")
            return redirect(url_for("home"))
        else:
            flash("Invalid username or password.", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("logged_in", None)
    flash("You’ve been logged out.", "info")
    return redirect(url_for("login"))

# Forgot password route
@app.route("/forgot_password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email")
        send_reset_email(email)
        flash("If that email exists, a reset link has been sent!", "info")
        return redirect(url_for("login"))
    return render_template("forgot_password.html")

# Helper function: send reset email
def send_reset_email(to_email):
    smtp_user = os.environ.get("SMTP_EMAIL")
    smtp_pass = os.environ.get("SMTP_PASSWORD")

    if not smtp_user or not smtp_pass:
        print("⚠️ SMTP credentials not set.")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Password Reset"
    msg["From"] = smtp_user
    msg["To"] = to_email
    text = "Click here to reset your password."
    msg.attach(MIMEText(text, "plain"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(smtp_user, smtp_pass)
            server.send_message(msg)
            print(f"✅ Reset email sent to {to_email}")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")

# Ensure tables are created
with app.app_context():
    db.create_all()

# Run on Render’s assigned port
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
