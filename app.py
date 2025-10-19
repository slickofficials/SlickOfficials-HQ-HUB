# app.py
"""
SlickOfficials Auto HQ - enhanced
- Pulls AWIN & Rakuten programs (all categories)
- Attempts to generate deep/tracking links via helpers if available
- Auto-generate multi-diverse captions
- Deduplicate and store posts
- Post to Publer every POST_INTERVAL_HOURS (default 4)
- Dashboard + /status + manual endpoints
"""

import os
import time
import json
import random
import traceback
from datetime import datetime, timedelta
from threading import Thread

import requests
from flask import Flask, render_template, jsonify, request
from apscheduler.schedulers.background import BackgroundScheduler

# Try to use local affiliate helpers if present in repo (optional)
try:
    from affiliates.awin import generate_awin_link as awin_generate_link
    from affiliates.awin import poll_awin_approvals as awin_poll_helper
except Exception:
    awin_generate_link = None
    awin_poll_helper = None

try:
    from affiliates.rakuten import generate_rakuten_link as rakuten_generate_link
    from affiliates.rakuten import poll_rakuten_approvals as rakuten_poll_helper
except Exception:
    rakuten_generate_link = None
    rakuten_poll_helper = None

app = Flask(__name__, template_folder="templates", static_folder="static")

# ------- CONFIG / ENV -------
POSTS_CSV = os.getenv("POSTS_FILE", "data/posts.csv")
POSTED_LOG = os.getenv("POSTED_LOG", "data/posted_log.json")
PENDING_PROGRAMS = os.getenv("PENDING_PROGRAMS_FILE", "data/pending_programs.json")

AWIN_TOKEN = os.getenv("AWIN_API_TOKEN")
AWIN_PUBLISHER_ID = os.getenv("AWIN_PUBLISHER_ID")
RAKUTEN_TOKEN = os.getenv("RAKUTEN_WEBSERVICES_TOKEN")
RAKUTEN_SCOPE_ID = os.getenv("RAKUTEN_SCOPE_ID")
RAKUTEN_SECURITY_TOKEN = os.getenv("RAKUTEN_SECURITY_TOKEN")

PUBLER_API_KEY = os.getenv("PUBLER_API_KEY")
PUBLER_ID = os.getenv("PUBLER_ID")  # Publer account/workspace id - fill from Render

DEFAULT_IMAGE = os.getenv("DEFAULT_IMAGE_URL", "https://i.imgur.com/fitness1.jpg")

POST_INTERVAL_HOURS = int(os.getenv("POST_INTERVAL_HOURS", "4"))
APPLY_INTERVAL_HOURS = int(os.getenv("APPLY_INTERVAL_HOURS", "24"))
APPROVAL_POLL_HOURS = int(os.getenv("APPROVAL_POLL_HOURS", "2"))

SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO")

MANUAL_RUN_TOKEN = os.getenv("MANUAL_RUN_TOKEN", "")

# Ensure data directories exist
os.makedirs(os.path.dirname(POSTS_CSV) or ".", exist_ok=True)

# ------- Utilities -------
def read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def write_json(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def read_posts_csv():
    posts = []
    if not os.path.exists(POSTS_CSV):
        return posts
    import csv
    with open(POSTS_CSV, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for r in reader:
            posts.append(r)
    return posts

def append_posts_csv(rows):
    import csv, os
    file_exists = os.path.exists(POSTS_CSV)
    os.makedirs(os.path.dirname(POSTS_CSV) or ".", exist_ok=True)
    with open(POSTS_CSV, "a", newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=["post_text","platform","link","image_url"])
        if not file_exists:
            writer.writeheader()
        for r in rows:
            writer.writerow({
                "post_text": r.get("post_text",""),
                "platform": r.get("platform","instagram,facebook,twitter,tiktok"),
                "link": r.get("link",""),
                "image_url": r.get("image_url", DEFAULT_IMAGE)
            })

# ------- Caption generator (multi-diverse) -------
CAP_TEMPLATES = [
    "{lead} {product} — snag it here: [Link] {hooks}",
    "Limited time: {product} — {lead}! [Link] {hooks}",
    "{lead} — {product}. See it now: [Link] {hooks}",
    "{product} is trending 🔥 {lead}. Get it: [Link] {hooks}",
]

LEADERS = [
    "Huge deal", "Don't miss out", "Just dropped", "Hot pick", "Boss move", "Pro tip",
    "Exclusive", "Handpicked for you", "Top rated"
]

HOOKS = [
    "#Deal #Limited", "#Sale #Affiliate", "#SlickOfficials #Promo", "#HotFind #ShopNow",
    "✨Limited stock✨", "Free shipping may apply", "Best price guaranteed"
]

EMOJIS = ["🔥","🚀","✨","💯","🛍️","🎯","🌟"]

def generate_caption(product_name):
    t = random.choice(CAP_TEMPLATES)
    lead = random.choice(LEADERS)
    hooks = f"{random.choice(EMOJIS)} {random.choice(HOOKS)}"
    return t.format(lead=lead, product=product_name, hooks=hooks).replace("[Link]","[Link]")

# Platform-specific shortener (basic trimming)
def caption_for_platform(caption, platform):
    if platform.lower() == "twitter" or platform.lower() == "x":
        return caption[:250]
    if platform.lower() == "tiktok":
        return caption[:600]
    return caption

# ------- Affiliate discovery (AWIN & Rakuten) -------
def discover_awin_programmes():
    found = []
    if not (AWIN_TOKEN and AWIN_PUBLISHER_ID):
        return found
    try:
        endpoint = f"https://api.awin.com/publishers/{AWIN_PUBLISHER_ID}/programmes"
        headers = {"Authorization": f"Bearer {AWIN_TOKEN}"}
        r = requests.get(endpoint, headers=headers, timeout=20)
        if r.status_code == 200:
            data = r.json()
            progs = data if isinstance(data, list) else data.get("programmes", data)
            for p in progs:
                found.append({
                    "network":"awin",
                    "id": p.get("programmeId") or p.get("id"),
                    "name": p.get("programmeName") or p.get("merchantName") or p.get("name"),
                    "url": p.get("clickThroughUrl") or p.get("website") or p.get("merchantWebsite"),
                    "category": p.get("category") or ""
                })
    except Exception as e:
        print("[awin discover] error:", e)
    return found

def discover_rakuten_programmes():
    found = []
    if not RAKUTEN_TOKEN:
        return found
    try:
        endpoint = "https://api.rakutenmarketing.com/affiliate/1.0/getAdvertisers"
        params = {"wsToken": RAKUTEN_TOKEN, "scopeId": RAKUTEN_SCOPE_ID, "approvalStatus": "available"}
        r = requests.get(endpoint, params=params, timeout=20)
        if r.status_code == 200:
            data = r.json()
            advertisers = data.get("advertisers", []) if isinstance(data, dict) else data or []
            for a in advertisers:
                found.append({
                    "network":"rakuten",
                    "id": a.get("advertiserId") or a.get("id"),
                    "name": a.get("advertiserName") or a.get("name"),
                    "url": a.get("siteUrl") or a.get("domain"),
                    "category": a.get("category") or ""
                })
    except Exception as e:
        print("[rakuten discover] error:", e)
    return found

# ------- Auto-apply (best-effort) -------
def apply_to_program(program):
    net = program.get("network")
    pid = program.get("id")
    try:
        if net == "awin":
            endpoint = f"https://api.awin.com/publishers/{AWIN_PUBLISHER_ID}/programmes/{pid}/apply"
            headers = {"Authorization": f"Bearer {AWIN_TOKEN}", "Content-Type":"application/json"}
            r = requests.post(endpoint, headers=headers, json={"publisherId": AWIN_PUBLISHER_ID}, timeout=20)
            return r.status_code in (200,201,202), r.text
        elif net == "rakuten":
            endpoint = "https://api.rakutenmarketing.com/affiliate/1.0/apply"
            params = {"wsToken": RAKUTEN_TOKEN, "advertiserId": pid, "scopeId": RAKUTEN_SCOPE_ID}
            r = requests.post(endpoint, params=params, timeout=20)
            return r.status_code in (200,201,202), r.text
    except Exception as e:
        return False, str(e)
    return False, "unsupported network"

# ------- Poll approvals and create posts -------
def poll_and_create_posts():
    created = []
    # AWIN approvals
    try:
        if awin_poll_helper:
            new = awin_poll_helper([])
            if isinstance(new, list):
                created.extend(new)
        else:
            if AWIN_TOKEN and AWIN_PUBLISHER_ID:
                endpoint = f"https://api.awin.com/publishers/{AWIN_PUBLISHER_ID}/programmes"
                headers = {"Authorization": f"Bearer {AWIN_TOKEN}"}
                params = {"relationship":"joined"}
                r = requests.get(endpoint, headers=headers, params=params, timeout=20)
                if r.status_code == 200:
                    data = r.json()
                    progs = data if isinstance(data, list) else data.get("programmes", data)
                    for p in progs:
                        pid = p.get("programmeId") or p.get("id")
                        if not pid:
                            continue
                        link = None
                        try:
                            if awin_generate_link:
                                link = awin_generate_link(pid, p.get("clickThroughUrl") or p.get("website",""))
                        except Exception:
                            link = p.get("clickThroughUrl") or p.get("website","")
                        caption = generate_caption(p.get("programmeName") or p.get("programmeName", "AWIN Offer"))
                        created.append({
                            "post_text": caption.replace("[Link]", link or ""),
                            "platform": "instagram,facebook,twitter,tiktok",
                            "link": link or p.get("clickThroughUrl") or p.get("website",""),
                            "image_url": p.get("logo") or DEFAULT_IMAGE
                        })
    except Exception as e:
        print("[poll_awin] err:", e)

    # RAKUTEN approvals
    try:
        if rakuten_poll_helper:
            new = rakuten_poll_helper([])
            if isinstance(new, list):
                created.extend(new)
        else:
            if RAKUTEN_TOKEN:
                endpoint = "https://api.rakutenmarketing.com/affiliate/1.0/getAdvertisers"
                params = {"wsToken": RAKUTEN_TOKEN, "scopeId": RAKUTEN_SCOPE_ID, "approvalStatus":"accepted"}
                r = requests.get(endpoint, params=params, timeout=20)
                if r.status_code == 200:
                    data = r.json()
                    advertisers = data.get("advertisers", []) if isinstance(data, dict) else data or []
                    for a in advertisers:
                        aid = a.get("advertiserId") or a.get("id")
                        if not aid:
                            continue
                        link = None
                        try:
                            if rakuten_generate_link:
                                link = rakuten_generate_link(aid, a.get("siteUrl",""))
                        except Exception:
                            link = a.get("siteUrl","")
                        caption = generate_caption(a.get("advertiserName") or a.get("name","Rakuten offer"))
                        created.append({
                            "post_text": caption.replace("[Link]", link or ""),
                            "platform": "instagram,facebook,twitter,tiktok",
                            "link": link or a.get("siteUrl",""),
                            "image_url": a.get("logo") or DEFAULT_IMAGE
                        })
    except Exception as e:
        print("[poll_rakuten] err:", e)

    # Append deduped
    if created:
        added = append_new_posts_dedup(created)
        if added > 0:
            print(f"[poll_and_create_posts] added {added} posts from approvals.")
    return created

# ------- Dedupe + append helpers -------
def append_new_posts_dedup(new_posts):
    # new_posts: list of dicts with keys post_text, platform, link, image_url
    existing_links = {p.get("link") for p in read_posts_csv()}
    rows = []
    added = 0
    for p in new_posts:
        link = p.get("link") or ""
        if not link or link in existing_links:
            continue
        rows.append(p)
        existing_links.add(link)
        added += 1
    if rows:
        append_posts_csv(rows)
    return added

# ------- Publish logic (Publer) -------
def publish_one():
    """
    Posts one unposted post (tracks posted links in POSTED_LOG)
    """
    try:
        posts = read_posts_csv()
        posted = read_json(POSTED_LOG, {"links": [], "last_posted_at": None})
        posted_links = set(posted.get("links", []))
        for p in posts:
            link = p.get("link") or ""
            if not link or link in posted_links:
                continue
            # Build caption (use already-generated text but ensure [Link] replaced)
            text = p.get("post_text") or ""
            if "[Link]" in text:
                text = text.replace("[Link]", link)
            else:
                text = f"{text}\n{link}"

            # Generate platform-specific captions; we'll use the same caption for all via Publer
            payload = {
                "accounts": [PUBLER_ID] if PUBLER_ID else [],
                "content": {
                    "text": text
                }
            }
            if p.get("image_url"):
                # Publer accepts mediaUrls or media entries depending on the plan; use mediaUrls
                payload["content"]["mediaUrls"] = [p.get("image_url")]

            headers = {"Authorization": f"Bearer {PUBLER_API_KEY}", "Content-Type": "application/json"}
            try:
                if not PUBLER_API_KEY or not PUBLER_ID:
                    print("[publish_one] missing PUBLER_API_KEY or PUBLER_ID; skipping actual API call.")
                    # Simulate success for now
                    success = True
                    res_status = "simulated"
                else:
                    r = requests.post("https://api.publer.io/v1/posts", headers=headers, json=payload, timeout=20)
                    success = r.status_code in (200,201)
                    res_status = r.status_code
                if success:
                    posted_links.add(link)
                    posted["links"] = list(posted_links)
                    posted["last_posted_at"] = datetime.utcnow().isoformat() + "Z"
                    write_json(POSTED_LOG, posted)
                    print("[publish_one] posted:", link, "status:", res_status)
                    return True
                else:
                    print("[publish_one] publer failed:", res_status)
            except Exception as e:
                print("[publish_one] exception:", e)
                traceback.print_exc()
        print("[publish_one] nothing to post or all posted links used")
    except Exception as e:
        print("[publish_one] exception outer:", e)
    return False

# ------- Scheduler jobs -------
def job_discover_apply():
    print("[job] discover & apply", datetime.utcnow().isoformat())
    # discover
    found = []
    found.extend(discover_awin_programmes())
    found.extend(discover_rakuten_programmes())
    # write to pending programs file (append simple JSON list)
    pending = read_json(PENDING_PROGRAMS, [])
    existing = {(p.get("network"), str(p.get("id"))) for p in pending}
    for f in found:
        key = (f.get("network"), str(f.get("id")))
        if key not in existing:
            pending.append({"network": f.get("network"), "id": f.get("id"), "name": f.get("name"), "url": f.get("url"), "detected_at": datetime.utcnow().isoformat()})
            existing.add(key)
    write_json(PENDING_PROGRAMS, pending)
    # attempt apply
    for p in pending:
        if p.get("applied_at") or p.get("approved"):
            continue
        ok, resp = apply_to_program(p)
        if ok:
            p["applied_at"] = datetime.utcnow().isoformat()
        else:
            p.setdefault("apply_error", str(resp)[:400])
    write_json(PENDING_PROGRAMS, pending)
    return len(found)

def job_poll_approvals_and_create():
    print("[job] poll approvals", datetime.utcnow().isoformat())
    created = poll_and_create_posts()
    # try to publish one after approvals
    publish_one()
    return created

def job_posting_cycle():
    print("[job] posting cycle", datetime.utcnow().isoformat())
    publish_one()

# Start scheduler
scheduler = BackgroundScheduler()
scheduler.add_job(job_discover_apply, "interval", hours=APPLY_INTERVAL_HOURS, next_run_time=datetime.utcnow())
scheduler.add_job(job_poll_approvals_and_create, "interval", hours=APPROVAL_POLL_HOURS, next_run_time=datetime.utcnow())
scheduler.add_job(job_posting_cycle, "interval", hours=POST_INTERVAL_HOURS, next_run_time=datetime.utcnow())
scheduler.start()
print("[scheduler] started:", {"apply_h": APPLY_INTERVAL_HOURS, "approval_poll_h": APPROVAL_POLL_HOURS, "post_h": POST_INTERVAL_HOURS})

# ------- HTTP endpoints -------
@app.route("/")
def home():
    # simple landing
    return render_template("index.html")

@app.route("/dashboard")
def dashboard():
    posts = read_posts_csv()
    config = {
        "AWIN_PUBLISHER_ID": AWIN_PUBLISHER_ID,
        "RAKUTEN_SCOPE_ID": RAKUTEN_SCOPE_ID,
        "PUBLER_ID": PUBLER_ID,
        "POST_INTERVAL_HOURS": POST_INTERVAL_HOURS
    }
    return render_template("dashboard.html", posts=posts[:50], config=config)

@app.route("/status")
def status():
    posted = read_json(POSTED_LOG, {"links": [], "last_posted_at": None})
    pending = read_json(PENDING_PROGRAMS, [])
    posts = read_posts_csv()
    next_eta = None
    if posted.get("last_posted_at"):
        last = datetime.fromisoformat(posted["last_posted_at"].replace("Z",""))
        next_eta = (last + timedelta(hours=POST_INTERVAL_HOURS) - datetime.utcnow()).total_seconds()
        if next_eta < 0:
            next_eta = 0
    return jsonify({
        "status": "running",
        "time_utc": datetime.utcnow().isoformat() + "Z",
        "total_posts_csv": len(posts),
        "posted_count": len(posted.get("links", [])),
        "pending_programs": len(pending),
        "next_post_eta_seconds": next_eta
    })

@app.route("/manual_trigger_posts", methods=["POST"])
def manual_trigger_posts():
    token = request.args.get("token") or request.headers.get("X-MANUAL-TOKEN")
    if MANUAL_RUN_TOKEN and token != MANUAL_RUN_TOKEN:
        return jsonify({"error":"unauthorized"}), 403
    Thread(target=job_posting_cycle, daemon=True).start()
    return jsonify({"status":"started posting job"}), 200

@app.route("/manual_discover", methods=["POST"])
def manual_discover():
    token = request.args.get("token") or request.headers.get("X-MANUAL-TOKEN")
    if MANUAL_RUN_TOKEN and token != MANUAL_RUN_TOKEN:
        return jsonify({"error":"unauthorized"}), 403
    Thread(target=job_discover_apply, daemon=True).start()
    return jsonify({"status":"started discover job"}), 200

# Run
if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)
