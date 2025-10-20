import os
import requests
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from flask_sqlalchemy import SQLAlchemy
from flask_mail import Mail, Message
from apscheduler.schedulers.background import BackgroundScheduler
from itsdangerous import URLSafeTimedSerializer
from datetime import datetime
from dotenv import load_dotenv

# Load .env variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("APP_SECRET_KEY", "supersecretkey")

# ---------------- DATABASE ----------------
db_url = os.getenv("DATABASE_URL", "sqlite:///local.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://")

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# ---------------- EMAIL SETUP ----------------
app.config["MAIL_SERVER"] = "smtp.gmail.com"
app.config["MAIL_PORT"] = 587
app.config["MAIL_USE_TLS"] = True
app.config["MAIL_USERNAME"] = os.getenv("MAIL_USERNAME")  # your gmail
app.config["MAIL_PASSWORD"] = os.getenv("MAIL_PASSWORD")  # your app password
app.config["MAIL_DEFAULT_SENDER"] = os.getenv("MAIL_USERNAME")
mail = Mail(app)

# Token serializer for password reset
s = URLSafeTimedSerializer(app.secret_key)

# ---------------- PUBLER API ----------------
PUBLER_API_KEY = os.getenv("PUBLER_API_KEY")
PUBLER_WORKSPACE_ID = os.getenv("PUBLER_WORKSPACE_ID")

class Analytics(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    metric_name = db.Column(db.String(100))
    metric_value = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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

# ---------------- AUTH ----------------
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = request.form["username"]
        pwd = request.form["password"]
        if user == os.getenv("ADMIN_USERNAME", "admin") and pwd == os.getenv("ADMIN_PASSWORD", "password"):
            session["user"] = user
            return redirect(url_for("dashboard"))
        return render_template("login.html", error="Invalid login. Try again.")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("login"))

# ---------------- PASSWORD RESET ----------------
@app.route("/reset_password", methods=["GET", "POST"])
def reset_password():
    if request.method == "POST":
        email = request.form["email"]
        token = s.dumps(email, salt="email-reset")
        link = url_for("reset_with_token", token=token, _external=True)

        msg = Message("Slickofficials HQ Password Reset", recipients=[email])
        msg.body = f"Hello!\n\nClick the link below to reset your password:\n{link}\n\nIf you didn’t request this, please ignore this email."
        mail.send(msg)

        return render_template("reset_password.html", message="✅ Password reset link sent to your email.")
    return render_template("reset_password.html")

@app.route("/reset/<token>", methods=["GET", "POST"])
def reset_with_token(token):
    try:
        email = s.loads(token, salt="email-reset", max_age=600)
    except:
        return "<h3>❌ Invalid or expired token. Try again.</h3>"

    if request.method == "POST":
        new_password = request.form["password"]
        os.environ["ADMIN_PASSWORD"] = new_password  # Demo only (replace with DB update)
        return "<h3>✅ Password updated successfully! <a href='/'>Login here</a>.</h3>"
    return render_template("reset_with_token.html", email=email)

# ---------------- DASHBOARD ----------------
@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))
    analytics = Analytics.query.order_by(Analytics.created_at.desc()).limit(10).all()
    return render_template("dashboard.html", analytics=analytics)

# ---------------- API ----------------
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

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
