# app.py
from flask import Flask, render_template, jsonify, request
import os
import pandas as pd
from datetime import datetime
import random
from apscheduler.schedulers.background import BackgroundScheduler
import pytz

# affiliate polling + poster modules (keep these in affiliates/ and poster/)
from affiliates.awin import poll_awin_approvals
from affiliates.rakuten import poll_rakuten_approvals
from poster.publer_poster import post_next, append_new_posts_if_any, ensure_posted_log

app = Flask(__name__)

# Config / env
POSTS_FILE = os.getenv("POSTS_FILE", "data/posts.csv")
POSTED_LOG = os.getenv("POSTED_LOG", "data/posted_log.csv")
TZ_PRIMARY = os.getenv("TIMEZONE_PRIMARY", "Africa/Lagos")
TZ_SECONDARY = os.getenv("TIMEZONE_SECONDARY", "America/New_York")
POST_INTERVAL_HOURS = int(os.getenv("POST_INTERVAL_HOURS", 4))  # you asked for every 4 hours

def safe_load_csv(path, default_columns=None):
    if not os.path.exists(os.path.dirname(path)) and os.path.dirname(path) != "":
        os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        if default_columns:
            pd.DataFrame(columns=default_columns).to_csv(path, index=False)
        else:
            pd.DataFrame().to_csv(path, index=False)
    try:
        return pd.read_csv(path)
    except Exception as e:
        print(f"[App] Error reading {path}: {e}")
        return pd.DataFrame()

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/dashboard")
def dashboard():
    df = safe_load_csv(POSTS_FILE, default_columns=["post_text","platform","link","image_url"])
    # show last 10 posted entries too
    ensure_posted_log()
    posted_df = safe_load_csv(POSTED_LOG, default_columns=["link","posted_at"])
    posted_recent = posted_df.tail(10).to_dict(orient="records") if not posted_df.empty else []
    return render_template("dashboard.html", posts=df.to_dict(orient="records"), posted_recent=posted_recent)

@app.route("/manual_reload", methods=["POST"])
def manual_reload():
    """
    Manually poll Awin & Rakuten and append new posts immediately.
    """
    awin = poll_awin_approvals()
    rakuten = poll_rakuten_approvals()
    added = append_new_posts_if_any(awin + rakuten)
    return jsonify({"status": "ok", "added": added}), 200

@app.route("/manual_post", methods=["POST"])
def manual_post():
    """
    Manually trigger a single post (posts next pending item).
    """
    ok = post_next()
    return jsonify({"status": "posted" if ok else "failed"}), (200 if ok else 500)

@app.route("/health")
def health():
    return jsonify({"status": "ok", "time": datetime.utcnow().isoformat() + "Z"}), 200

# Scheduler jobs: poll affiliates every 4 hours, attempt to post every 4 hours (staggered)
def poll_and_append_job():
    print("[Scheduler] Polling affiliates for approvals...")
    awin_posts = poll_awin_approvals()
    rakuten_posts = poll_rakuten_approvals()
    added = append_new_posts_if_any(awin_posts + rakuten_posts)
    print(f"[Scheduler] Added {added} new posts from affiliates.")

def posting_job():
    print("[Scheduler] Attempting to post next pending item...")
    ok = post_next()
    print("[Scheduler] Post result:", ok)

def start_scheduler():
    tz_primary = pytz.timezone(TZ_PRIMARY)
    scheduler = BackgroundScheduler(timezone=tz_primary)
    # Poll affiliates every 4 hours
    scheduler.add_job(poll_and_append_job, 'interval', hours=4, next_run_time=datetime.utcnow())
    # Try to post every 4 hours (this will attempt to post if there are pending items)
    scheduler.add_job(posting_job, 'interval', hours=4, next_run_time=datetime.utcnow())
    scheduler.start()
    print("[Scheduler] Started (every 4 hours)")

if __name__ == "__main__":
    start_scheduler()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
