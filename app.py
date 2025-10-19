# app.py
import os, random, requests, pandas as pd
from flask import Flask, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

# ========== ENV CONFIG ==========
AWIN_PUBLISHER_ID = os.getenv("AWIN_PUBLISHER_ID")
AWIN_API_TOKEN = os.getenv("AWIN_API_TOKEN")
RAKUTEN_SCOPE_ID = os.getenv("RAKUTEN_SCOPE_ID")
RAKUTEN_SECURITY_TOKEN = os.getenv("RAKUTEN_SECURITY_TOKEN")
PUBLER_API_KEY = os.getenv("PUBLER_API_KEY")
PUBLER_ID = os.getenv("PUBLER_ID")
DEFAULT_IMAGE_URL = os.getenv("DEFAULT_IMAGE_URL", "https://i.imgur.com/fitness1.jpg")

# ========== HELPERS ==========
def ai_caption_from_deal(name, cat):
    templates = [
        f"🔥 {name} is trending in {cat}! Grab your exclusive deal now 👉 [Link]",
        f"Your next {cat} upgrade? It’s here: {name} 😍 [Link]",
        f"{name} = game changer 💥 Click to shop now! [Link]",
        f"Don’t miss {name} — perfect for {cat.lower()} lovers 🛍️ [Link]",
    ]
    return random.choice(templates)

def post_to_publer(text, link, image):
    if not PUBLER_API_KEY or not PUBLER_ID:
        print("[publish_one] missing Publer credentials, skipping actual post.")
        return
    try:
        payload = {
            "text": text.replace("[Link]", link),
            "accounts": [PUBLER_ID],
            "media": [{"type": "image", "url": image}],
        }
        headers = {
            "Authorization": f"Bearer {PUBLER_API_KEY}",
            "Content-Type": "application/json",
        }
        r = requests.post("https://api.publer.io/v1/posts", headers=headers, json=payload)
        print("[Publer]", r.status_code, r.text)
    except Exception as e:
        print("[Publer error]", e)

# ========== AFFILIATE DISCOVERY MOCK ==========
def fetch_affiliate_deals():
    # In production, replace with AWIN + Rakuten API calls
    deals = [
        {"name": "Kila Custom Insoles", "cat": "Fitness", "link": "https://tidd.ly/3J1KeV2", "img": "https://i.imgur.com/insoles1.jpg"},
        {"name": "Kapitalwise Wealth Builder", "cat": "Finance", "link": "https://tidd.ly/43ibfu7", "img": "https://i.imgur.com/finance1.jpg"},
        {"name": "Diamond Smile FR", "cat": "Dental", "link": "https://tidd.ly/4nanmAp", "img": "https://i.imgur.com/dental1.jpg"},
        {"name": "Bell’s Reines Cookies", "cat": "Food", "link": "https://tidd.ly/3Jb6cEV", "img": "https://i.imgur.com/food1.jpg"},
        {"name": "Awin USD Affiliate", "cat": "Business", "link": "https://tidd.ly/46RRifY", "img": "https://i.imgur.com/affiliate1.jpg"},
    ]
    return deals

def generate_and_post():
    print("[job_posting_cycle] Starting posting cycle...")
    deals = fetch_affiliate_deals()
    for d in deals:
        caption = ai_caption_from_deal(d["name"], d["cat"])
        post_to_publer(caption, d["link"], d["img"])
    print("[job_posting_cycle] Done posting.")

def poll_approvals():
    print("[poll_approvals] Checking AWIN & Rakuten approvals...")
    # future: auto-poll affiliate approval status
    pass

def discover_new_deals():
    print("[discover_new_deals] Discovering new AWIN/Rakuten deals...")
    # future: use APIs to add new deals dynamically
    pass

# ========== FLASK ROUTES ==========
@app.route("/")
def index():
    return jsonify({
        "status": "running",
        "message": "SlickOfficials HQ Auto Affiliate Engine active",
        "last_update": datetime.utcnow().isoformat()
    })

@app.route("/manual-post")
def manual_post():
    generate_and_post()
    return jsonify({"status": "manual trigger success"})

@app.route("/status")
def status():
    return jsonify({
        "AWIN_PUBLISHER_ID": AWIN_PUBLISHER_ID,
        "RAKUTEN_SCOPE_ID": RAKUTEN_SCOPE_ID,
        "PUBLER_ID": PUBLER_ID,
        "running": True
    })

# ========== SCHEDULER ==========
scheduler = BackgroundScheduler()
scheduler.add_job(discover_new_deals, "interval", hours=24)
scheduler.add_job(poll_approvals, "interval", hours=2)
scheduler.add_job(generate_and_post, "interval", hours=4)
scheduler.start()
print("[scheduler] started: discover=24h, approvals=2h, post=4h")

# ========== AUTO START ON BOOT ==========
generate_and_post()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
