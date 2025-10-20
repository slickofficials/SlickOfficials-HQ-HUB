# app.py
import os
import json
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Text, JSON
from sqlalchemy.orm import declarative_base, sessionmaker
from apscheduler.schedulers.background import BackgroundScheduler

# Optional affiliate/poster adapter imports (if you keep those modules)
try:
    from affiliates.awin import poll_awin_approvals, generate_awin_link
except Exception:
    poll_awin_approvals = None
    generate_awin_link = None

try:
    from affiliates.rakuten import poll_rakuten_approvals, generate_rakuten_link
except Exception:
    poll_rakuten_approvals = None
    generate_rakuten_link = None

try:
    from poster.publer_poster import post_content
except Exception:
    post_content = None

# App init
app = Flask(__name__)
app.secret_key = os.getenv("APP_SECRET_KEY", os.getenv("FLASK_SECRET", "change-me-please"))

# Auth config (simple)
APP_USERNAME = os.getenv("APP_USERNAME", "Slickofficials HQ")
APP_PASSWORD = os.getenv("APP_PASSWORD", "Asset@22")  # keep this secret, use Render env

# DB setup (SQLAlchemy). Use DATABASE_URL from Render or fallback to SQLite for local testing.
DATABASE_URL = os.getenv("DATABASE_URL")
if DATABASE_URL:
    engine = create_engine(DATABASE_URL, echo=False, future=True)
else:
    # fallback to local sqlite (for dev)
    engine = create_engine("sqlite:///slickofficials.db", echo=False, future=True)

Base = declarative_base()
DBSession = sessionmaker(bind=engine)

# Models
class AffiliateStat(Base):
    __tablename__ = "affiliate_stats"
    id = Column(Integer, primary_key=True)
    network = Column(String(50))  # awin / rakuten
    merchant = Column(String(256))
    metric = Column(String(64))  # e.g., clicks, sales, approvals
    value = Column(Integer)
    meta = Column(JSON, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)

class PostLog(Base):
    __tablename__ = "post_logs"
    id = Column(Integer, primary_key=True)
    platform = Column(String(128))  # comma separated or single
    post_text = Column(Text)
    link = Column(String(1024))
    image_url = Column(String(1024))
    status = Column(String(64))  # scheduled / posted / failed / skipped
    response = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Settings(Base):
    __tablename__ = "settings"
    id = Column(Integer, primary_key=True)
    key = Column(String(128), unique=True, nullable=False)
    value = Column(Text)

def init_db():
    Base.metadata.create_all(engine)

# init DB on startup
init_db()

# Simple login required decorator
def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return wrapped

# ---------------------------------------------------------
# Routes: Login / Logout
# ---------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        u = request.form.get("username")
        p = request.form.get("password")
        if u == APP_USERNAME and p == APP_PASSWORD:
            session["logged_in"] = True
            session["user"] = u
            return redirect(url_for("index"))
        error = "Invalid credentials"
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# ---------------------------------------------------------
# Dashboard & API
# ---------------------------------------------------------
@app.route("/")
@login_required
def index():
    # get top 10 recent posts and last 30 affiliate stats
    db = DBSession()
    posts = db.query(PostLog).order_by(PostLog.created_at.desc()).limit(10).all()
    stats = db.query(AffiliateStat).order_by(AffiliateStat.timestamp.desc()).limit(50).all()
    db.close()
    return render_template("dashboard.html", posts=posts, stats=stats, username=session.get("user"))

@app.route("/status")
@login_required
def status():
    db = DBSession()
    total_posts = db.query(PostLog).count()
    posted = db.query(PostLog).filter(PostLog.status == "posted").count()
    failed = db.query(PostLog).filter(PostLog.status == "failed").count()
    db.close()
    return jsonify({
        "total_posts": total_posts,
        "posted": posted,
        "failed": failed,
        "service": "SlickOfficials HQ",
        "time": datetime.utcnow().isoformat() + "Z"
    })

# Endpoint to trigger a posting cycle manually
@app.route("/run_post_cycle", methods=["POST"])
@login_required
def run_post_cycle():
    try:
        run_posting_cycle()
        return jsonify({"status": "ok", "message": "Posting cycle triggered."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# Test Publer / list accounts (uses PUBLER_API_KEY)
@app.route("/test_publer", methods=["GET"])
@login_required
def test_publer_api():
    publer_key = os.getenv("PUBLER_API_KEY")
    if not publer_key:
        return jsonify({"status": "error", "message": "PUBLER_API_KEY not set"}), 400
    import requests
    headers = {"Authorization": f"Bearer {publer_key}", "Content-Type": "application/json"}
    url = "https://api.publer.io/v1/accounts"
    r = requests.get(url, headers=headers, timeout=20)
    try:
        return jsonify({"status": "ok", "response": r.json(), "code": r.status_code})
    except Exception:
        return jsonify({"status": "ok", "text": r.text, "code": r.status_code})

# ---------------------------------------------------------
# Internal job functions
# ---------------------------------------------------------
def save_affiliate_stat(network, merchant, metric, value, meta=None):
    db = DBSession()
    stat = AffiliateStat(network=network, merchant=merchant, metric=metric, value=value, meta=meta or {})
    db.add(stat)
    db.commit()
    db.close()

def log_post(platform, post_text, link, image_url, status="scheduled", response=None):
    db = DBSession()
    pl = PostLog(platform=platform, post_text=post_text, link=link,
                 image_url=image_url, status=status, response=response or {})
    db.add(pl)
    db.commit()
    db.close()

# Poll Awin approvals and create PostLog entries
def job_poll_awin():
    app.logger.info("Running Awin approvals poll...")
    try:
        if poll_awin_approvals:
            new_posts = poll_awin_approvals([])  # if your module expects templates, adapt accordingly
            for p in new_posts:
                log_post(p.get("platform", "instagram"), p.get("post_text"), p.get("link"), p.get("image_url"), status="scheduled")
            app.logger.info(f"Awin: added {len(new_posts)} new posts")
        else:
            app.logger.info("Awin module not available; skipping.")
    except Exception as e:
        app.logger.error(f"Error in job_poll_awin: {e}")

# Poll Rakuten approvals and create PostLog entries
def job_poll_rakuten():
    app.logger.info("Running Rakuten approvals poll...")
    try:
        if poll_rakuten_approvals:
            new_posts = poll_rakuten_approvals([])
            for p in new_posts:
                log_post(p.get("platform", "instagram"), p.get("post_text"), p.get("link"), p.get("image_url"), status="scheduled")
            app.logger.info(f"Rakuten: added {len(new_posts)} new posts")
        else:
            app.logger.info("Rakuten module not available; skipping.")
    except Exception as e:
        app.logger.error(f"Error in job_poll_rakuten: {e}")

# Main posting cycle: take scheduled posts and send to Publer (or mark scheduled)
def run_posting_cycle():
    db = DBSession()
    # pick up to N scheduled posts (configurable)
    max_batch = int(os.getenv("MAX_POSTS_PER_CYCLE", "10"))
    candidates = db.query(PostLog).filter(PostLog.status == "scheduled").order_by(PostLog.created_at.asc()).limit(max_batch).all()
    publer_key = os.getenv("PUBLER_API_KEY")
    publer_workspace = os.getenv("PUBLER_WORKSPACE_ID")
    publer_user = os.getenv("PUBLER_USER_ID") or os.getenv("PUBLER_ID") or os.getenv("PUBLER_ACCOUNT_ID")
    if not candidates:
        app.logger.info("No scheduled posts found.")
        db.close()
        return

    # If poster.publer_poster.post_content exists, use it (it expects posts list & templates param)
    if post_content:
        try:
            # Make a shallow posts list for the poster module
            posts_to_send = []
            for p in candidates:
                posts_to_send.append({
                    "post_text": p.post_text,
                    "platform": p.platform,
                    "link": p.link,
                    "image_url": p.image_url
                })
            # Use the poster module to schedule (module should handle API key from env)
            post_content(posts_to_send, templates=[])
            # mark as posted (best-effort; poster module might handle)
            for p in candidates:
                p.status = "posted"
            db.commit()
            app.logger.info(f"Posted {len(candidates)} via poster.post_content.")
        except Exception as e:
            app.logger.error(f"Error using poster.post_content: {e}")
            # fallback to marking failed
            for p in candidates:
                p.status = "failed"
                p.response = {"error": str(e)}
            db.commit()
    else:
        # Fallback implementation - Post to Publer directly if API key present, otherwise just mark as scheduled/log
        if publer_key and publer_workspace and publer_user:
            import requests
            endpoint = "https://api.publer.io/v1/posts"
            headers = {"Authorization": f"Bearer {publer_key}", "Content-Type": "application/json"}
            for p in candidates:
                payload = {
                    "accounts": [publer_user],
                    "content": {"text": p.post_text},
                    # Publer accepts media in a different shape; many accounts use image URLs or upload first.
                }
                try:
                    r = requests.post(endpoint, headers=headers, json=payload, timeout=20)
                    if r.status_code in (200, 201):
                        p.status = "posted"
                        p.response = {"status": r.status_code, "body": r.json()}
                    else:
                        p.status = "failed"
                        p.response = {"status": r.status_code, "text": r.text}
                except Exception as e:
                    p.status = "failed"
                    p.response = {"error": str(e)}
            db.commit()
            app.logger.info(f"Attempted to post {len(candidates)} via Publer API.")
        else:
            # No API keys — keep them scheduled and just log
            app.logger.info("PUBLER not configured; skipping external post. Leaving posts scheduled.")
    db.close()

# ---------------------------------------------------------
# Scheduler setup (APScheduler)
# ---------------------------------------------------------
scheduler = BackgroundScheduler()

# Poll affiliate approvals every 2 hours
scheduler.add_job(job_poll_awin, 'interval', hours=2, id='poll_awin', next_run_time=datetime.utcnow())
scheduler.add_job(job_poll_rakuten, 'interval', hours=2, id='poll_rakuten', next_run_time=datetime.utcnow())

# Posting cycle every 4 hours (user requested every 4h)
scheduler.add_job(run_posting_cycle, 'interval', hours=4, id='posting_cycle', next_run_time=datetime.utcnow())

# Optional discovery job (auto-apply or other) every 24 hours (placeholder)
def job_discover_and_apply():
    app.logger.info("Running discovery & auto-apply (placeholder).")
    # Implement auto-apply using affiliate APIs carefully; this is a non-trivial action requiring approvals.
    # For now we log that it ran.
scheduler.add_job(job_discover_and_apply, 'interval', hours=24, id='discover_apply', next_run_time=datetime.utcnow())

scheduler.start()

# ---------------------------------------------------------
# Small API to view recent logs (helpful for debugging)
# ---------------------------------------------------------
@app.route("/api/recent_posts")
@login_required
def api_recent_posts():
    db = DBSession()
    posts = db.query(PostLog).order_by(PostLog.created_at.desc()).limit(100).all()
    db.close()
    return jsonify([{
        "id": p.id,
        "platform": p.platform,
        "post_text": p.post_text,
        "link": p.link,
        "image_url": p.image_url,
        "status": p.status,
        "response": p.response,
        "created_at": p.created_at.isoformat()
    } for p in posts])

@app.route("/api/affiliate_stats")
@login_required
def api_affiliate_stats():
    db = DBSession()
    stats = db.query(AffiliateStat).order_by(AffiliateStat.timestamp.desc()).limit(200).all()
    db.close()
    return jsonify([{
        "id": s.id,
        "network": s.network,
        "merchant": s.merchant,
        "metric": s.metric,
        "value": s.value,
        "meta": s.meta,
        "timestamp": s.timestamp.isoformat()
    } for s in stats])

# ---------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------
@app.route("/health")
def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat() + "Z"}

# ---------------------------------------------------------
# Startup
# ---------------------------------------------------------
if __name__ == "__main__":
    # helpful info on startup
    app.logger.info("Starting SlickOfficials HQ app...")
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
