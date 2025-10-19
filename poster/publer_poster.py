# poster/publer_poster.py
import os
import requests
import pandas as pd
from datetime import datetime
import random

PUBLER_API_KEY = os.getenv("PUBLER_API_KEY")
PUBLER_ACCOUNT_ID = os.getenv("PUBLER_ACCOUNT_ID")

POSTS_FILE = os.getenv("POSTS_FILE", "data/posts.csv")
POSTED_LOG = os.getenv("POSTED_LOG", "data/posted_log.csv")

def ensure_posted_log():
    if not os.path.exists(POSTED_LOG):
        pd.DataFrame(columns=["link", "posted_at"]).to_csv(POSTED_LOG, index=False)

def load_pending_posts():
    if not os.path.exists(POSTS_FILE):
        return []
    df = pd.read_csv(POSTS_FILE)
    ensure_posted_log()
    posted = pd.read_csv(POSTED_LOG)["link"].tolist()
    pending = df[~df["link"].isin(posted)] if "link" in df.columns else df
    return pending.to_dict(orient="records")

def post_to_publer(post):
    """Let Publer generate captions/media (Business plan feature)"""
    if not PUBLER_API_KEY or not PUBLER_ACCOUNT_ID:
        print("[Publer] Missing credentials")
        return False, None

    caption = post.get("post_text", "").replace("[Link]", post.get("link", ""))
    payload = {
        "accounts": [PUBLER_ACCOUNT_ID],
        "content": {
            "text": caption,
            "auto_generated_captions": True,
            "auto_generated_media": True
        }
    }
    headers = {
        "Authorization": f"Bearer {PUBLER_API_KEY}",
        "Content-Type": "application/json"
    }
    try:
        r = requests.post("https://api.publer.io/v1/posts", json=payload, headers=headers, timeout=20)
        print(f"[Publer] status {r.status_code}: {r.text}")
        return (r.status_code == 201), r.json() if r.text else None
    except Exception as e:
        print(f"[Publer] exception: {e}")
        return False, None

def mark_posted(link):
    ensure_posted_log()
    df = pd.read_csv(POSTED_LOG)
    df = pd.concat([df, pd.DataFrame([{"link": link, "posted_at": datetime.utcnow()}])], ignore_index=True)
    df.to_csv(POSTED_LOG, index=False)

def post_next():
    pending = load_pending_posts()
    if len(pending) == 0:
        print("[Poster] No pending posts")
        return False
    post = random.choice(pending)
    ok, resp = post_to_publer(post)
    if ok:
        mark_posted(post["link"])
        print(f"[Poster] Posted and logged: {post['link']}")
        return True
    print("[Poster] Post failed")
    return False
