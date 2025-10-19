from flask import Flask, render_template, jsonify, request
import os
import pandas as pd
import yaml
import requests
import threading
import time
import random
from datetime import datetime
import pytz

app = Flask(__name__)

# ---------------------------------------------------------
# Load configuration
# ---------------------------------------------------------
def load_config():
    try:
        with open("config.yaml", "r") as file:
            return yaml.safe_load(file)
    except Exception:
        return {}

# ---------------------------------------------------------
# Utility: Smart AI-style caption generator
# ---------------------------------------------------------
def generate_caption(base_text, category="General"):
    """
    Simple AI-like remix: adds emojis, hashtags & punchlines dynamically.
    """
    taglines = [
        "🔥 Don't sleep on this deal!",
        "💡 Smart picks only!",
        "💥 Level up your lifestyle.",
        "🚀 Trending right now!",
        "💰 Your wallet will thank you!"
    ]
    hashtags = [
        "#TrendingNow", "#SmartDeals", "#GlobalFinds", "#AffiliateWin", "#ShopSmart",
        "#LifestyleUpgrade", "#BossMove", "#SlickOfficials"
    ]
    caption = f"{base_text}\n\n{random.choice(taglines)} {random.choice(hashtags)}"
    return caption

# ---------------------------------------------------------
# Affiliate Feed: AWIN + Rakuten
# ---------------------------------------------------------
def fetch_affiliate_links():
    posts = []

    # AWIN
    awin_token = os.getenv("AWIN_API_TOKEN")
    awin_publisher = os.getenv("AWIN_PUBLISHER_ID")
    if awin_token and awin_publisher:
        print("Fetching Awin offers...")
        awin_url = f"https://api.awin.com/publishers/{awin_publisher}/programmes?accessToken={awin_token}"
        try:
            res = requests.get(awin_url)
            if res.status_code == 200:
                for item in res.json()[:3]:  # sample top 3
                    posts.append({
                        "post_text": f"🌟 {item.get('name', 'Awin Offer')} — grab it now!",
                        "link": item.get("clickThroughUrl", ""),
                        "image_url": os.getenv("DEFAULT_IMAGE_URL", ""),
                        "platform": "instagram,facebook,twitter,tiktok"
                    })
        except Exception as e:
            print(f"Awin fetch failed: {e}")

    # RAKUTEN
    rakuten_token = os.getenv("RAKUTEN_SECURITY_TOKEN")
    if rakuten_token:
        print("Fetching Rakuten offers...")
        try:
            rakuten_url = "https://api.rakutenmarketing.com/affiliate/links"
            headers = {"Authorization": f"Bearer {rakuten_token}"}
            res = requests.get(rakuten_url, headers=headers)
            if res.status_code == 200 and isinstance(res.json(), list):
                for link in res.json()[:3]:
                    posts.append({
                        "post_text": f"🛍️ {link.get('mid', 'Rakuten Deal')} — special offer inside!",
                        "link": link.get("clickUrl", ""),
                        "image_url": os.getenv("DEFAULT_IMAGE_URL", ""),
                        "platform": "instagram,facebook,twitter,tiktok"
                    })
        except Exception as e:
            print(f"Rakuten fetch failed: {e}")

    return posts

# ---------------------------------------------------------
# Publer Poster
# ---------------------------------------------------------
def post_to_publer(post):
    api_key = os.getenv("PUBLER_API_KEY")
    account_id = os.getenv("PUBLER_ID")

    if not api_key or not account_id:
        print("Missing Publer credentials.")
        return

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    caption = generate_caption(post["post_text"])
    payload = {
        "accounts": [account_id],
        "content": {
            "text": f"{caption}\n{post['link']}",
            "media": [{"url": post["image_url"]}]
        }
    }

    try:
        res = requests.post("https://api.publer.io/v1/posts", headers=headers, json=payload)
        print(f"📢 Posted: {post['post_text']} — Status {res.status_code}")
        if res.status_code not in [200, 201]:
            print(res.text)
    except Exception as e:
        print(f"Publer post failed: {e}")

# ---------------------------------------------------------
# Posting Loop
# ---------------------------------------------------------
def run_auto_post():
    try:
        df = pd.read_csv("data/posts.csv")
        posted_log = set()

        for _, row in df.iterrows():
            link = row["link"]
            if link in posted_log:
                continue
            post_to_publer(row)
            posted_log.add(link)
            time.sleep(15)

        print("✅ Cycle complete. Refreshing new offers...")
        new_posts = fetch_affiliate_links()
        if new_posts:
            new_df = pd.DataFrame(new_posts)
            new_df.to_csv("data/posts.csv", index=False)
            print("🆕 Posts refreshed with latest affiliate links.")
    except Exception as e:
        print(f"❌ Error in auto post: {e}")

# ---------------------------------------------------------
# Background Scheduler (every 4 hours)
# ---------------------------------------------------------
def scheduler():
    while True:
        now_lagos = datetime.now(pytz.timezone("Africa/Lagos")).strftime("%Y-%m-%d %H:%M:%S")
        now_usa = datetime.now(pytz.timezone("America/New_York")).strftime("%Y-%m-%d %H:%M:%S")
        print(f"🕓 Auto post triggered — Lagos: {now_lagos} | USA: {now_usa}")
        run_auto_post()
        print("⏳ Waiting 4 hours before next run...")
        time.sleep(4 * 60 * 60)

# ---------------------------------------------------------
# Manual Control Routes
# ---------------------------------------------------------
@app.route("/manual_post", methods=["POST"])
def manual_post():
    threading.Thread(target=run_auto_post).start()
    return jsonify({"message": "Manual post triggered successfully!"})

@app.route("/manual_reload", methods=["POST"])
def manual_reload():
    posts = fetch_affiliate_links()
    if posts:
        df = pd.DataFrame(posts)
        df.to_csv("data/posts.csv", index=False)
        return jsonify({"message": "Affiliate links reloaded successfully!"})
    return jsonify({"message": "No new offers found."})

@app.route("/status", methods=["GET"])
def system_status():
    now_lagos = datetime.now(pytz.timezone("Africa/Lagos")).strftime("%Y-%m-%d %H:%M:%S")
    now_usa = datetime.now(pytz.timezone("America/New_York")).strftime("%Y-%m-%d %H:%M:%S")
    return jsonify({
        "status": "running",
        "next_run": "Every 4 hours",
        "time_africa": now_lagos,
        "time_usa": now_usa
    })

# ---------------------------------------------------------
# Scheduler Thread Start
# ---------------------------------------------------------
threading.Thread(target=scheduler, daemon=True).start()

# ---------------------------------------------------------
# Run App
# ---------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
