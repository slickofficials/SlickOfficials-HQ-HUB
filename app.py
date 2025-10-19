from flask import Flask, render_template, jsonify, request
import os, random, requests, pandas as pd, yaml
from datetime import datetime
from apscheduler.schedulers.background import BackgroundScheduler
import pytz

# Initialize Flask
app = Flask(__name__)

# Load config safely
def load_config():
    try:
        with open("config.yaml", "r") as file:
            return yaml.safe_load(file)
    except Exception as e:
        print("Error loading config:", e)
        return {}

# Environment setup
PUBLER_API_KEY = os.getenv("PUBLER_API_KEY")
PUBLER_ACCOUNT_ID = os.getenv("PUBLER_ACCOUNT_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ALLOWED_DOMAINS = os.getenv("ALLOWED_DOMAINS", "awin1.com,rakuten.com").split(",")
POSTS_FILE = os.getenv("POSTS_FILE", "data/posts.csv")
DEFAULT_POST_TEXT = os.getenv("DEFAULT_POST_TEXT", "🔥 Hot affiliate deal — check it out before it’s gone!")
TZ_PRIMARY = os.getenv("TIMEZONE_PRIMARY", "Africa/Lagos")
TZ_SECONDARY = os.getenv("TIMEZONE_SECONDARY", "America/New_York")

# -------- Helper: AI caption generator --------
def generate_ai_caption(link):
    """Generate a smart promo caption using OpenAI."""
    if not OPENAI_API_KEY:
        return DEFAULT_POST_TEXT

    prompt = f"Write a short, catchy social media caption (with emojis) promoting this affiliate deal: {link}"
    try:
        res = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 50
            }
        )
        data = res.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception as e:
        print("AI caption error:", e)
        return DEFAULT_POST_TEXT

# -------- Helper: fetch optional image from Unsplash --------
def get_promo_image(link):
    access_key = os.getenv("UNSPLASH_ACCESS_KEY")
    if not access_key:
        return None
    try:
        keyword = link.split("/")[2].replace("www.", "")
        res = requests.get(f"https://api.unsplash.com/photos/random?query={keyword}&client_id={access_key}")
        if res.status_code == 200:
            return res.json()["urls"]["regular"]
    except Exception as e:
        print("Image fetch error:", e)
    return None

# -------- Filter affiliate links --------
def load_affiliate_links():
    if not os.path.exists(POSTS_FILE):
        print(f"{POSTS_FILE} not found.")
        return []

    df = pd.read_csv(POSTS_FILE)
    links = [url for url in df["url"].dropna() if any(domain in url for domain in ALLOWED_DOMAINS)]
    return links

# -------- Send post to Publer --------
def post_to_publer(link):
    caption = generate_ai_caption(link)
    image_url = get_promo_image(link)

    headers = {
        "Authorization": f"Bearer {PUBLER_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "accounts": [PUBLER_ACCOUNT_ID],
        "content": {"text": f"{caption}\n\n{link}"}
    }

    if image_url:
        payload["content"]["media_urls"] = [image_url]

    res = requests.post("https://api.publer.io/v1/posts", headers=headers, json=payload)
    print(f"Publer status {res.status_code}: {res.text}")
    return res.status_code == 201

# -------- Scheduler job --------
def auto_post_job():
    links = load_affiliate_links()
    if not links:
        print("⚠️ No affiliate links found.")
        return

    link = random.choice(links)
    success = post_to_publer(link)
    print(f"✅ Posted: {link}" if success else f"❌ Failed to post {link}")

# -------- Dashboard routes --------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/dashboard")
def dashboard():
    try:
        posts_df = pd.read_csv(POSTS_FILE)
        return render_template("dashboard.html", posts=posts_df.to_dict(orient="records"))
    except Exception as e:
        return f"Error loading dashboard: {e}"

# -------- Scheduler setup --------
scheduler = BackgroundScheduler()
scheduler.add_job(auto_post_job, "interval", hours=12, timezone=TZ_PRIMARY)
scheduler.add_job(auto_post_job, "interval", hours=12, timezone=TZ_SECONDARY)
scheduler.start()

# Run app
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
