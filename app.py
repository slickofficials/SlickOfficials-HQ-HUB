import os
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from sqlalchemy import inspect, text

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("APP_SECRET_KEY", "fallback_secret")

# ---------------- Database Configuration ---------------- #
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

# ---------------- DB Auto-Healing ---------------- #
def ensure_columns_exist():
    """Ensures all expected columns exist in the Analytics table."""
    with app.app_context():
        inspector = inspect(db.engine)
        columns = [col["name"] for col in inspector.get_columns("analytics")]

        required_columns = {
            "platform": "TEXT",
            "clicks": "INTEGER",
            "impressions": "INTEGER",
            "conversions": "INTEGER",
            "revenue": "FLOAT",
            "date": "TIMESTAMP"
        }

        for col_name, col_type in required_columns.items():
            if col_name not in columns:
                try:
                    db.session.execute(text(f"ALTER TABLE analytics ADD COLUMN {col_name} {col_type};"))
                    db.session.commit()
                    print(f"✅ Added missing column: {col_name}")
                except Exception as e:
                    print(f"⚠️ Could not add column '{col_name}': {e}")

with app.app_context():
    db.create_all()
    ensure_columns_exist()
    print("[init_db] Tables initialized and verified ✅")

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

# ---------------- Scheduler ---------------- #
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

scheduler = BackgroundScheduler()
scheduler.add_job(update_data, "interval", hours=6)
scheduler.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
