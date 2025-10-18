import os
from flask import Flask, render_template, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
import pandas as pd
from dotenv import load_dotenv
import logging

# =========================
# Load environment variables
# =========================
load_dotenv()

AWIN_API_KEY = os.getenv("AWIN_API_KEY")
RAKUTEN_API_KEY = os.getenv("RAKUTEN_API_KEY")
PUBLISHER_ID = os.getenv("PUBLER_ACCOUNT_ID")
PUBLER_API_KEY = os.getenv("PUBLER_API_KEY")

# =========================
# Flask Setup
# =========================
app = Flask(__name__)

# =========================
# Logging Config
# =========================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# =========================
# ROUTES
# =========================

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/dashboard')
def dashboard():
    import os
    import pandas as pd

    posts_path = os.path.join(os.getcwd(), 'data', 'posts.csv')
    templates_path = os.path.join(os.getcwd(), 'data', 'templates.csv')

    posts, templates = [], []

    try:
        if os.path.exists(posts_path) and os.path.getsize(posts_path) > 0:
            posts = pd.read_csv(posts_path).to_dict(orient='records')
        else:
            posts = [{"title": "No posts found", "content": "Upload your first post!"}]
    except Exception as e:
        logger.error(f"Error loading posts.csv: {e}")
        posts = [{"title": "Error loading posts", "content": str(e)}]

    try:
        if os.path.exists(templates_path) and os.path.getsize(templates_path) > 0:
            templates = pd.read_csv(templates_path).to_dict(orient='records')
        else:
            templates = [{"name": "Default Template", "text": "Start adding templates."}]
    except Exception as e:
        logger.error(f"Error loading templates.csv: {e}")
        templates = [{"name": "Error loading templates", "text": str(e)}]

    return render_template('dashboard.html', posts=posts, templates=templates)


@app.route('/health')
def health_check():
    """Simple health endpoint for Render"""
    return jsonify({"status": "ok"})


# =========================
# JOB: Auto Post Scheduler
# =========================
def auto_post():
    logger.info("Auto-post job started 🚀")
    try:
        from poster.publer_poster import publish_post
        publish_post()
        logger.info("Auto-post job completed ✅")
    except Exception as e:
        logger.error(f"Auto-post failed: {e}")


# =========================
# Scheduler Setup
# =========================
scheduler = BackgroundScheduler()
scheduler.add_job(auto_post, 'interval', hours=6)
scheduler.start()


# =========================
# MAIN
# =========================
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
