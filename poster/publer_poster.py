# poster/publer_poster.py
import os
import requests
import pandas as pd
from datetime import datetime
import random

PUBLER_API_KEY = os.getenv("PUBLER_API_KEY")
PUBLER_ID = os.getenv("PUBLER_ID")  # your Publer account id env name
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
    posted = pd.read_csv(POSTED_LOG)["link"].astype(str).tolist() if os.path.exists(POSTED_LOG) else []
    pending = df[~df["link"].astype(str).isin(posted)] if "link" in df.columns else df
    return pending.to_dict(orient="records")

def post_to_publer(post):
    """Let Publer generate captions/media (Business plan feature)"""
    if not PUBLER_API_KEY or not PUBLER_ID:
        print("[Publer] Missing credentials")
        return False, None

    # Prepare caption: replace placeholder and include link
    caption = post.get("post_text", "").replace("[Link]", post.get("link", ""))
    payload = {
        "accounts": [PUBLER_ID],
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
        if r.status_code in (200, 201):
            return True, r.json() if r.text else {}
        return False, r.text
    except Exception as e:
        print(f"[Publer] exception: {e}")
        return False, None

def mark_posted(link):
    ensure_posted_log()
    df = pd.read_csv(POSTED_LOG) if os.path.exists(POSTED_LOG) else pd.DataFrame(columns=["link","posted_at"])
    df = pd.concat([df, pd.DataFrame([{"link": str(link), "posted_at": datetime.utcnow().isoformat() + "Z"}])], ignore_index=True)
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

def append_new_posts_if_any(new_posts):
    """
    Append new posts to POSTS_FILE avoiding duplicates.
    Accepts a list of dicts with keys: post_text, link, image_url, category (optional)
    Returns number of items appended.
    """
    if not new_posts:
        return 0
    os.makedirs(os.path.dirname(POSTS_FILE) or ".", exist_ok=True)
    df = pd.read_csv(POSTS_FILE) if os.path.exists(POSTS_FILE) else pd.DataFrame(columns=["post_text","platform","link","image_url"])
    existing = set(df["link"].astype(str).tolist()) if "link" in df.columns else set()
    added = 0
    rows = []
    for p in new_posts:
        link = p.get("link") or p.get("url")
        if not link or str(link) in existing:
            continue
        rows.append({
            "post_text": p.get("post_text", "Check this out! [Link]"),
            "platform": "instagram,facebook,twitter,tiktok",
            "link": link,
            "image_url": p.get("image_url", "")
        })
        existing.add(str(link))
        added += 1
    if rows:
        df = pd.concat([df, pd.DataFrame(rows)], ignore_index=True)
        df.to_csv(POSTS_FILE, index=False)
    return added
