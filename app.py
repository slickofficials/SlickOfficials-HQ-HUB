from flask import Flask, render_template, request, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
import os

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "supersecretkey")

# Database setup
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///data.db")
db = SQLAlchemy(app)

# Example model
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

with app.app_context():
    db.create_all()

# Scheduler job
def auto_post_job():
    print(f"[{datetime.utcnow()}] Auto-post job running...")

scheduler = BackgroundScheduler()
scheduler.add_job(auto_post_job, "interval", minutes=30)
scheduler.start()

@app.route("/")
def home():
    if "user" not in session:
        return redirect(url_for("login"))
    return f"Welcome {session['user']}! HQ Dashboard live 🚀"

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        user = User.query.filter_by(username=username, password=password).first()
        if user:
            session["user"] = user.username
            return redirect(url_for("home"))
        else:
            return "Invalid credentials"
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("login"))

if __name__ == "__main__":
    app.run(debug=True)
