import os
import requests
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("APP_SECRET_KEY", "supersecretkey")

# Auto-switch DB for local/Render
db_url = os.getenv("DATABASE_URL", "sqlite:///local.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://")

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

PUBLER_API_KEY = os.getenv("PUBLER_API_KEY")
PUBLER_WORKSPACE_ID = os.getenv("PUBLER_WORKSPACE_ID")

# ---------------- DATABASE MODELS ----------------
class Analytics(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    metric_name = db.Column(db.String(100))
    metric_value = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ---------------- PUBLER API CALL ----------------
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

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
