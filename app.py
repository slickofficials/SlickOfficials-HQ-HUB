import os
import requests
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("APP_SECRET_KEY", "fallback_secret")

# ---------------- Database Config ---------------- #
db_url = os.getenv("DATABASE_URL", "sqlite:///local.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://")

app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# ---------------- Models ---------------- #
class Analytics(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    platform = db.Column(db.String(50))
    clicks = db.Column(db.Integer)
    impressions = db.Column(db.Integer)
    conversions = db.Column(db.Integer)
    revenue = db.Column(db.Float)
    date = db.Column(db.DateTime, default=datetime.utcnow)

with app.app_context():
    db.create_all()
    print("[init_db] Tables initialized ✅")

# ---------------- Login ---------------- #
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        if (
            username == os.getenv("APP_USERNAME")
            and password == os.getenv("APP_PASSWORD")
        ):
            session["user"] = username
            flash(f"Welcome back, {username}!", "success")
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid login credentials", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("user", None)
    flash("You’ve been logged out.", "info")
    return redirect(url_for("login"))

# ---------------- Dashboard ---------------- #
@app.route("/")
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))

    data = Analytics.query.order_by(Analytics.date.desc()).limit(10).all()
    total_clicks = sum(d.clicks for d in data)
    total_revenue = sum(d.revenue for d in data)
    return render_template(
        "dashboard.html",
        user=session["user"],
        analytics=data,
        total_clicks=total_clicks,
        total_revenue=total_revenue,
    )

# ---------------- Publer API Quick Actions ---------------- #
@app.route("/test-publer")
def test_publer():
    api_key = os.getenv("PUBLER_API_KEY")
    workspace_id = os.getenv("PUBLER_WORKSPACE_ID")
    if not api_key or not workspace_id:
        return jsonify({"error": "Missing Publer credentials"}), 400

    headers = {"Authorization": f"Bearer {api_key}"}
    url = f"https://api.publer.io/v1/workspaces/{workspace_id}"
    res = requests.get(url, headers=headers)
    return jsonify(res.json())

@app.route("/recent-posts")
def recent_posts():
    api_key = os.getenv("PUBLER_API_KEY")
    workspace_id = os.getenv("PUBLER_WORKSPACE_ID")
    if not api_key or not workspace_id:
        return jsonify({"error": "Missing Publer credentials"}), 400

    headers = {"Authorization": f"Bearer {api_key}"}
    url = f"https://api.publer.io/v1/workspaces/{workspace_id}/posts?limit=5"
    res = requests.get(url, headers=headers)
    return jsonify(res.json())

# ---------------- Analytics Scheduler ---------------- #
def update_data():
    with app.app_context():
        new_entry = Analytics(
            platform="Awin",
            clicks=120,
            impressions=3000,
            conversions=5,
            revenue=78.23,
        )
        db.session.add(new_entry)
        db.session.commit()
        print(f"[Scheduler] Data updated at {datetime.utcnow()}")

# ---------------- Keep Render Alive ---------------- #
def ping_self():
    try:
        url = os.getenv("RENDER_EXTERNAL_URL")
        if url:
            requests.get(f"{url}/ping")
            print(f"[Heartbeat] Pinged {url}/ping ❤️")
    except Exception as e:
        print(f"[Heartbeat Error] {e}")

scheduler = BackgroundScheduler()
scheduler.add_job(update_data, "interval", hours=6)
scheduler.add_job(ping_self, "interval", minutes=10)
scheduler.start()

# ---------------- Health Check ---------------- #
@app.route("/ping")
def ping():
    return jsonify({"status": "ok", "message": "Slickofficials HQ running smoothly 🚀"}), 200

# ---------------- Run ---------------- #
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
