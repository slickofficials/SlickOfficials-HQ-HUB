import os
import csv
import json
import random
import datetime
from flask import Flask, jsonify, render_template

app = Flask(__name__)

# --- CONFIG ---
POST_INTERVAL_HOURS = 4
DATA_FILE = "data/posts.csv"
LAST_POST_FILE = "data/last_post.json"


def read_posts():
    """Read all posts from CSV"""
    posts = []
    try:
        with open(DATA_FILE, newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                posts.append(row)
    except FileNotFoundError:
        posts = []
    return posts


def read_last_post():
    """Read last post timestamp"""
    try:
        with open(LAST_POST_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"last_post_time": None, "posted_links": []}


def save_last_post(data):
    """Save last post info"""
    os.makedirs(os.path.dirname(LAST_POST_FILE), exist_ok=True)
    with open(LAST_POST_FILE, "w") as f:
        json.dump(data, f)


@app.route("/")
def home():
    return "<h2>✅ SlickOfficials Auto Poster Running Smooth</h2><p>Visit <a href='/dashboard'>Dashboard</a> or <a href='/status'>Status</a>.</p>"


@app.route("/dashboard")
def dashboard():
    posts = read_posts()
    config = {
        "AWIN_PUBLISHER_ID": os.getenv("AWIN_PUBLISHER_ID"),
        "RAKUTEN_SCOPE_ID": os.getenv("RAKUTEN_SCOPE_ID"),
        "PUBLER_ID": os.getenv("PUBLER_ID"),
        "POST_INTERVAL_HOURS": POST_INTERVAL_HOURS,
    }
    return render_template("dashboard.html", posts=posts[:10], config=config)


@app.route("/status")
def status():
    """System status endpoint"""
    last_data = read_last_post()
    last_post_time = last_data.get("last_post_time")

    # Compute next run time
    if last_post_time:
        last_time = datetime.datetime.fromisoformat(last_post_time)
        next_time = last_time + datetime.timedelta(hours=POST_INTERVAL_HOURS)
        remaining = next_time - datetime.datetime.utcnow()
    else:
        last_time = None
        remaining = datetime.timedelta(0)

    status_data = {
        "status": "online",
        "server_time_utc": datetime.datetime.utcnow().isoformat(),
        "last_post_time": last_post_time,
        "next_post_eta": str(remaining),
        "total_posts_in_csv": len(read_posts()),
        "posted_links": last_data.get("posted_links", []),
        "env_summary": {
            "AWIN_PUBLISHER_ID": os.getenv("AWIN_PUBLISHER_ID"),
            "RAKUTEN_SCOPE_ID": os.getenv("RAKUTEN_SCOPE_ID"),
            "PUBLER_ID": os.getenv("PUBLER_ID"),
        },
    }

    # Safe JSON serialization
    return jsonify(status_data)


@app.route("/run_post_now")
def manual_run():
    """Simulate posting logic manually"""
    posts = read_posts()
    if not posts:
        return jsonify({"error": "No posts available in CSV"})

    post = random.choice(posts)
    last_data = read_last_post()

    if post["link"] in last_data.get("posted_links", []):
        return jsonify({"message": "Post already published", "post": post})

    last_data["posted_links"].append(post["link"])
    last_data["last_post_time"] = datetime.datetime.utcnow().isoformat()
    save_last_post(last_data)

    return jsonify({"message": "Simulated post successful", "post": post})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
