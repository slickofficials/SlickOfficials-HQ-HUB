import os
import requests
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("APP_SECRET_KEY", "fallback_secret")

# Database config
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

# ---------------- Helpers ---------------- #
PUBLER_API_KEY = os.getenv("PUBLER_API_KEY")
PUBLER_WORKSPACE_ID = os.getenv("PUBLER_WORKSPACE_ID")
PUBLER_BASE = "https://api.publer.io/v1"

def get_publer_headers():
    return {"Authorization": f"Bearer {PUBLER_API_KEY}", "Content-Type": "application/json"}

# ---------------- Routes ---------------- #
@app.route("/ping")
def ping():
    return jsonify({"status": "ok", "message": "Slickofficials HQ running smoothly 🚀"})

# --- Login --- #
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        if username == os.getenv("APP_USERNAME") and password == os.getenv("APP_PASSWORD"):
            session["user"] = username
            flash("Welcome back, " + username + "!", "success")
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid login credentials", "danger")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("user", None)
    flash("You’ve been logged out.", "info")
    return redirect(url_for("login"))

# --- Dashboard --- #
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

# --- Publer Test --- #
@app.route("/test-publer")
def test_publer():
    if not PUBLER_API_KEY or not PUBLER_WORKSPACE_ID:
        return jsonify({"error": "Missing Publer credentials"}), 400
    try:
        res = requests.get(f"{PUBLER_BASE}/workspaces/{PUBLER_WORKSPACE_ID}", headers=get_publer_headers())
        return jsonify(res.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- Recent Posts --- #
@app.route("/recent-posts")
def recent_posts():
    if not PUBLER_API_KEY or not PUBLER_WORKSPACE_ID:
        return jsonify({"error": "Missing Publer credentials"}), 400
    try:
        res = requests.get(f"{PUBLER_BASE}/posts?workspace_id={PUBLER_WORKSPACE_ID}&limit=5", headers=get_publer_headers())
        return jsonify(res.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --- Scheduler --- #
def update_data():
    with app.app_context():
        new_entry = Analytics(platform="Awin", clicks=120, impressions=3000, conversions=5, revenue=78.23)
        db.session.add(new_entry)
        db.session.commit()
        print(f"[Scheduler] Data updated at {datetime.utcnow()}")

scheduler = BackgroundScheduler()
scheduler.add_job(update_data, "interval", hours=6)
scheduler.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
