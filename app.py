# app.py
"""
Auto-affiliate manager (All categories, copy-and-paste ready)
Features:
 - Discover Awin & Rakuten programs (all categories)
 - Best-effort auto-apply to discovered programs
 - Poll approvals and generate tracking/deep links
 - Append deduplicated posts to data/posts.csv
 - Post to Publer every POST_INTERVAL_HOURS
 - Email alerts via Gmail (SMTP app password)
 - Manual endpoints for control
Notes:
 - Some affiliate "apply" endpoints are account-specific; apply calls are best-effort.
 - Watch Render logs and your ALERT_EMAIL_TO for notifications.
"""

import os
import time
import json
import random
import traceback
from datetime import datetime
from threading import Thread

import requests
import pandas as pd
import pytz
from flask import Flask, jsonify, render_template, request
from apscheduler.schedulers.background import BackgroundScheduler
import smtplib
from email.mime.text import MIMEText

# Optional helper imports if you already have the modules
try:
    from affiliates.awin import generate_awin_link, poll_awin_approvals as awin_poll_helper, generate_awin_link as awin_link_helper
except Exception:
    generate_awin_link = None
    awin_poll_helper = None
    awin_link_helper = None

try:
    from affiliates.rakuten import generate_rakuten_link, poll_rakuten_approvals as rakuten_poll_helper
except Exception:
    generate_rakuten_link = None
    rakuten_poll_helper = None

try:
    from poster.publer_poster import append_new_posts_if_any, post_next, post_to_publer as poster_post_to_publer
except Exception:
    append_new_posts_if_any = None
    post_next = None
    poster_post_to_publer = None

# -------------------------
# Config / Environment
# -------------------------
POSTS_FILE = os.getenv("POSTS_FILE", "data/posts.csv")
POSTED_LOG = os.getenv("POSTED_LOG", "data/posted_log.csv")
PENDING_PROGRAMS_FILE = os.getenv("PENDING_PROGRAMS_FILE", "data/pending_programs.csv")
DEFAULT_IMAGE = os.getenv("DEFAULT_IMAGE_URL", "https://i.imgur.com/fitness1.jpg")

AWIN_TOKEN = os.getenv("AWIN_API_TOKEN")
AWIN_PUBLISHER_ID = os.getenv("AWIN_PUBLISHER_ID")
RAKUTEN_TOKEN = os.getenv("RAKUTEN_WEBSERVICES_TOKEN")
RAKUTEN_SCOPE_ID = os.getenv("RAKUTEN_SCOPE_ID")
RAKUTEN_SECURITY_TOKEN = os.getenv("RAKUTEN_SECURITY_TOKEN")

PUBLER_API_KEY = os.getenv("PUBLER_API_KEY")
PUBLER_ID = os.getenv("PUBLER_ID")

SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
ALERT_EMAIL_TO = os.getenv("ALERT_EMAIL_TO")

POST_INTERVAL_HOURS = int(os.getenv("POST_INTERVAL_HOURS", 4))
APPLY_INTERVAL_HOURS = int(os.getenv("APPLY_INTERVAL_HOURS", 24))
APPROVAL_POLL_HOURS = int(os.getenv("APPROVAL_POLL_HOURS", 2))

TZ_PRIMARY = os.getenv("TIMEZONE_PRIMARY", "Africa/Lagos")
TZ_SECONDARY = os.getenv("TIMEZONE_SECONDARY", "America/New_York")

app = Flask(__name__)

# -------------------------
# Ensure data files exist
# -------------------------
def ensure_data_files():
    os.makedirs(os.path.dirname(POSTS_FILE) or ".", exist_ok=True)
    os.makedirs(os.path.dirname(PENDING_PROGRAMS_FILE) or ".", exist_ok=True)
    os.makedirs(os.path.dirname(POSTED_LOG) or ".", exist_ok=True)
    if not os.path.exists(POSTS_FILE):
        pd.DataFrame(columns=["post_text","platform","link","image_url"]).to_csv(POSTS_FILE, index=False)
    if not os.path.exists(PENDING_PROGRAMS_FILE):
        pd.DataFrame(columns=["network","program_id","name","url","category","notes","detected_at","applied_at","approved","approved_at"]).to_csv(PENDING_PROGRAMS_FILE, index=False)
    if not os.path.exists(POSTED_LOG):
        pd.DataFrame(columns=["link","posted_at"]).to_csv(POSTED_LOG, index=False)

ensure_data_files()

# -------------------------
# Pending programs helpers
# -------------------------
def load_pending_programs():
    try:
        return pd.read_csv(PENDING_PROGRAMS_FILE).to_dict(orient="records")
    except Exception:
        return []

def save_pending_programs(records):
    pd.DataFrame(records).to_csv(PENDING_PROGRAMS_FILE, index=False)

def add_pending_program(rec):
    programs = load_pending_programs()
    keys = {(str(p.get("network")), str(p.get("program_id"))) for p in programs}
    key = (str(rec.get("network")), str(rec.get("program_id")))
    if key in keys:
        return False
    programs.append(rec)
    save_pending_programs(programs)
    return True

def mark_program_applied(network, program_id):
    progs = load_pending_programs()
    changed = False
    for p in progs:
        if str(p.get("network")) == str(network) and str(p.get("program_id")) == str(program_id):
            p["applied_at"] = datetime.utcnow().isoformat() + "Z"
            changed = True
    if changed:
        save_pending_programs(progs)
    return changed

def mark_program_approved(network, program_id):
    progs = load_pending_programs()
    changed = False
    for p in progs:
        if str(p.get("network")) == str(network) and str(p.get("program_id")) == str(program_id):
            p["approved"] = True
            p["approved_at"] = datetime.utcnow().isoformat() + "Z"
            changed = True
    if changed:
        save_pending_programs(progs)
    return changed

# -------------------------
# Email alerts
# -------------------------
def send_email(subject, body):
    if not (SMTP_USER and SMTP_PASS and ALERT_EMAIL_TO):
        print("[email] SMTP not configured; skipping email.")
        return False
    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = SMTP_USER
        msg["To"] = ALERT_EMAIL_TO
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as s:
            s.starttls()
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
        print("[email] Sent:", subject)
        return True
    except Exception as e:
        print("[email] Failed:", e)
        return False

# -------------------------
# Discover programs (Awin / Rakuten) - all categories
# -------------------------
def discover_awin_programs():
    found = []
    if not (AWIN_TOKEN and AWIN_PUBLISHER_ID):
        print("[awin] token/publisher missing")
        return found
    try:
        endpoint = f"https://api.awin.com/publishers/{AWIN_PUBLISHER_ID}/programmes"
        headers = {"Authorization": f"Bearer {AWIN_TOKEN}"}
        r = requests.get(endpoint, headers=headers, timeout=20)
        if r.status_code == 200:
            data = r.json()
            progs = data if isinstance(data, list) else data.get("programmes", data)
            for p in progs:
                pid = p.get("programmeId") or p.get("id")
                rec = {
                    "network": "awin",
                    "program_id": pid,
                    "name": p.get("programmeName") or p.get("name") or p.get("merchantName") or "",
                    "url": p.get("clickThroughUrl") or p.get("merchantWebsite") or p.get("siteUrl") or "",
                    "category": p.get("category") or p.get("vertical") or "",
                    "notes": "",
                    "detected_at": datetime.utcnow().isoformat() + "Z",
                    "applied_at": "",
                    "approved": False,
                    "approved_at": ""
                }
                if pid:
                    added = add_pending_program(rec)
                    if added:
                        found.append(rec)
        else:
            print("[awin] discover failed:", r.status_code, r.text)
    except Exception as e:
        print("[awin] discover exception:", e)
    return found

def discover_rakuten_programs():
    found = []
    if not RAKUTEN_TOKEN:
        print("[rakuten] token missing")
        return found
    try:
        endpoint = "https://api.rakutenmarketing.com/affiliate/1.0/getAdvertisers"
        params = {"wsToken": RAKUTEN_TOKEN, "scopeId": RAKUTEN_SCOPE_ID, "approvalStatus": "available"}
        r = requests.get(endpoint, params=params, timeout=20)
        if r.status_code == 200:
            data = r.json()
            advertisers = data.get("advertisers", []) if isinstance(data, dict) else data or []
            for a in advertisers:
                aid = a.get("advertiserId") or a.get("id")
                rec = {
                    "network": "rakuten",
                    "program_id": aid,
                    "name": a.get("advertiserName") or a.get("name") or "",
                    "url": a.get("siteUrl") or a.get("domain") or "",
                    "category": a.get("category") or "",
                    "notes": "",
                    "detected_at": datetime.utcnow().isoformat() + "Z",
                    "applied_at": "",
                    "approved": False,
                    "approved_at": ""
                }
                if aid:
                    added = add_pending_program(rec)
                    if added:
                        found.append(rec)
        else:
            print("[rakuten] discover failed:", r.status_code, r.text)
    except Exception as e:
        print("[rakuten] discover exception:", e)
    return found

# -------------------------
# Auto-apply (best-effort)
# -------------------------
def apply_to_awin(program_id):
    if not (AWIN_TOKEN and AWIN_PUBLISHER_ID):
        return False, "missing_awin_creds"
    try:
        # best-effort apply endpoint (may not exist on all accounts)
        endpoint = f"https://api.awin.com/publishers/{AWIN_PUBLISHER_ID}/programmes/{program_id}/apply"
        headers = {"Authorization": f"Bearer {AWIN_TOKEN}", "Content-Type": "application/json"}
        payload = {"publisherId": AWIN_PUBLISHER_ID}
        r = requests.post(endpoint, headers=headers, json=payload, timeout=20)
        if r.status_code in (200, 201, 202):
            mark_program_applied("awin", program_id)
            send_email("AWIN Auto-Apply Submitted", f"Applied to AWIN programme {program_id}.")
            return True, r.text
        else:
            return False, f"{r.status_code}: {r.text}"
    except Exception as e:
        return False, str(e)

def apply_to_rakuten(advertiser_id):
    if not RAKUTEN_TOKEN:
        return False, "missing_rakuten_token"
    try:
        # best-effort apply; some accounts don't support programmatic apply
        endpoint = "https://api.rakutenmarketing.com/affiliate/1.0/apply"
        params = {"wsToken": RAKUTEN_TOKEN, "advertiserId": advertiser_id, "scopeId": RAKUTEN_SCOPE_ID}
        r = requests.post(endpoint, params=params, timeout=20)
        if r.status_code in (200,201,202):
            mark_program_applied("rakuten", advertiser_id)
            send_email("Rakuten Auto-Apply Submitted", f"Applied to Rakuten advertiser {advertiser_id}.")
            return True, r.text
        else:
            return False, f"{r.status_code}: {r.text}"
    except Exception as e:
        return False, str(e)

# -------------------------
# Poll approvals & generate posts
# -------------------------
def poll_awin_for_approvals():
    results = []
    try:
        if awin_poll_helper:
            new_posts = awin_poll_helper([])  # if helper expects templates it may ignore arg
            if isinstance(new_posts, list):
                results.extend(new_posts)
        else:
            endpoint = f"https://api.awin.com/publishers/{AWIN_PUBLISHER_ID}/programmes"
            headers = {"Authorization": f"Bearer {AWIN_TOKEN}"}
            params = {"relationship": "joined"}
            r = requests.get(endpoint, headers=headers, params=params, timeout=20)
            if r.status_code == 200:
                data = r.json()
                progs = data if isinstance(data, list) else data.get("programmes", data)
                for p in progs:
                    pid = p.get("programmeId") or p.get("id")
                    if not pid:
                        continue
                    mark_program_approved("awin", pid)
                    link = None
                    try:
                        if generate_awin_link:
                            link = generate_awin_link(pid, p.get("clickThroughUrl") or p.get("website") or "")
                    except Exception:
                        link = p.get("clickThroughUrl") or p.get("website") or ""
                    post = {
                        "post_text": f"🔥 {p.get('programmeName', p.get('name', 'AWIN Offer'))} — grab it now! [Link]",
                        "platform": "instagram,facebook,twitter,tiktok",
                        "link": link or p.get("clickThroughUrl", ""),
                        "image_url": p.get("logo") or DEFAULT_IMAGE
                    }
                    results.append(post)
            else:
                print("[poll_awin_for_approvals] failed:", r.status_code, r.text)
    except Exception as e:
        print("[poll_awin_for_approvals] exception:", e)
    return results

def poll_rakuten_for_approvals():
    results = []
    try:
        if rakuten_poll_helper:
            new_posts = rakuten_poll_helper([])
            if isinstance(new_posts, list):
                results.extend(new_posts)
        else:
            endpoint = "https://api.rakutenmarketing.com/affiliate/1.0/getAdvertisers"
            params = {"wsToken": RAKUTEN_TOKEN, "scopeId": RAKUTEN_SCOPE_ID, "approvalStatus": "accepted"}
            r = requests.get(endpoint, params=params, timeout=20)
            if r.status_code == 200:
                data = r.json()
                advertisers = data.get("advertisers", []) if isinstance(data, dict) else data or []
                for a in advertisers:
                    aid = a.get("advertiserId") or a.get("id")
                    if not aid:
                        continue
                    mark_program_approved("rakuten", aid)
                    link = None
                    try:
                        if generate_rakuten_link:
                            link = generate_rakuten_link(aid, a.get("siteUrl") or "")
                    except Exception:
                        link = a.get("siteUrl") or ""
                    post = {
                        "post_text": f"🛍️ {a.get('advertiserName', a.get('name', 'Rakuten Offer'))} — special offer inside! [Link]",
                        "platform": "instagram,facebook,twitter,tiktok",
                        "link": link or a.get("siteUrl", ""),
                        "image_url": a.get("logo") or DEFAULT_IMAGE
                    }
                    results.append(post)
            else:
                print("[poll_rakuten_for_approvals] failed:", r.status_code, r.text)
    except Exception as e:
        print("[poll_rakuten_for_approvals] exception:", e)
    return results

# -------------------------
# Append posts (dedupe) and publishing
# -------------------------
def append_posts(posts):
    if not posts:
        return 0
    try:
        if append_new_posts_if_any:
            return append_new_posts_if_any(posts)
        # fallback direct CSV append while deduplicating by link
        df_existing = pd.read_csv(POSTS_FILE) if os.path.exists(POSTS_FILE) else pd.DataFrame(columns=["post_text","platform","link","image_url"])
        existing_links = set(df_existing["link"].astype(str).tolist()) if "link" in df_existing.columns else set()
        rows = []
        added = 0
        for p in posts:
            link = p.get("link") or p.get("url")
            if not link or str(link) in existing_links:
                continue
            rows.append({
                "post_text": p.get("post_text") or p.get("title") or p.get("name") or "",
                "platform": p.get("platform", "instagram,facebook,twitter,tiktok"),
                "link": link,
                "image_url": p.get("image_url") or DEFAULT_IMAGE
            })
            existing_links.add(str(link))
            added += 1
        if rows:
            df = pd.concat([df_existing, pd.DataFrame(rows)], ignore_index=True)
            df.to_csv(POSTS_FILE, index=False)
        return added
    except Exception as e:
        print("[append_posts] exception:", e)
        return 0

def generate_caption(base_text):
    emojis = ["🔥","🚀","💥","✨","💡","💯","🛍️"]
    tags = ["#Deals","#Promo","#Affiliate","#ShopSmart","#LimitedTime","#SlickOfficials"]
    caption = f"{base_text}\n\n{random.choice(emojis)} {random.choice(tags)} {random.choice(tags)}"
    return caption

def publish_cycle():
    try:
        # If poster helper has post_next, use that (it should handle batch posting)
        if post_next:
            ok = post_next()
            print("[publish_cycle] used post_next ->", ok)
            return
        # fallback: inline posting: post one unposted item
        df = pd.read_csv(POSTS_FILE)
        posted_df = pd.read_csv(POSTED_LOG)
        posted_links = set(posted_df["link"].astype(str).tolist()) if "link" in posted_df.columns else set()
        for _, row in df.iterrows():
            link = row["link"]
            if str(link) in posted_links:
                continue
            base_text = row.get("post_text", "") or "Check this deal!"
            caption = generate_caption(base_text)
            headers = {"Authorization": f"Bearer {PUBLER_API_KEY}", "Content-Type": "application/json"}
            payload = {"accounts": [PUBLER_ID], "content": {"text": f"{caption}\n{link}"}}
            try:
                r = requests.post("https://api.publer.io/v1/posts", headers=headers, json=payload, timeout=20)
                if r.status_code in (200,201):
                    posted_df = pd.concat([posted_df, pd.DataFrame([{"link": str(link), "posted_at": datetime.utcnow().isoformat() + "Z"}])], ignore_index=True)
                    posted_df.to_csv(POSTED_LOG, index=False)
                    send_email("Post Published", f"{base_text}\n{link}")
                    print("[publish_cycle] Posted:", link)
                    return
                else:
                    print("[publish_cycle] Publer failed:", r.status_code, r.text)
            except Exception as e:
                print("[publish_cycle] Publer exception:", e)
            # if failed, continue to next item
    except Exception as e:
        print("[publish_cycle] exception:", e)
        traceback.print_exc()

# -------------------------
# Scheduler jobs
# -------------------------
def job_discover_and_apply():
    try:
        print("[job] discover_and_apply:", datetime.utcnow().isoformat())
        found = []
        found.extend(discover_awin_programs())
        found.extend(discover_rakuten_programs())
        if found:
            lines = [f"{p['network'].upper()}: {p['name']} ({p['program_id']})" for p in found]
            send_email("New affiliate programmes discovered", "\n".join(lines))
        # attempt to auto-apply to pending programs that are not applied
        pending = load_pending_programs()
        for p in pending:
            if p.get("applied_at") or p.get("approved"):
                continue
            net = p.get("network")
            pid = p.get("program_id")
            if net == "awin":
                ok, resp = apply_to_awin(pid)
            elif net == "rakuten":
                ok, resp = apply_to_rakuten(pid)
            else:
                ok, resp = False, "unknown network"
            print(f"[job] apply {net}/{pid}: {ok} resp:{str(resp)[:200]}")
            time.sleep(1)
    except Exception as e:
        print("[job_discover_and_apply] exception:", e)
        traceback.print_exc()

def job_poll_approvals_and_make_posts():
    try:
        print("[job] poll_approvals:", datetime.utcnow().isoformat())
        new_posts = []
        new_posts.extend(poll_awin_for_approvals())
        new_posts.extend(poll_rakuten_for_approvals())
        if new_posts:
            added = append_posts(new_posts)
            send_email("New approved programs added", f"Added {added} new posts from approvals.")
            print("[job] approvals appended posts:", added)
        # try posting after approvals
        publish_cycle()
    except Exception as e:
        print("[job_poll_approvals_and_make_posts] exception:", e)
        traceback.print_exc()

def job_posting_cycle():
    try:
        print("[job] posting_cycle:", datetime.utcnow().isoformat())
        publish_cycle()
    except Exception as e:
        print("[job_posting_cycle] exception:", e)
        traceback.print_exc()

# -------------------------
# HTTP control endpoints
# -------------------------
@app.route("/")
def index():
    if os.path.exists("templates/index.html"):
        return render_template("index.html")
    return jsonify({"status":"ok","message":"Auto-affiliate manager running"})

@app.route("/status")
def status():
    try:
        tz_a = pytz.timezone(TZ_PRIMARY)
        tz_b = pytz.timezone(TZ_SECONDARY)
        now_a = datetime.now(tz_a).strftime("%Y-%m-%d %H:%M:%S")
        now_b = datetime.now(tz_b).strftime("%Y-%m-%d %H:%M:%S")
        posts_total = 0
        posted_total = 0
        try:
            posts_total = len(pd.read_csv(POSTS_FILE))
        except Exception:
            posts_total = 0
        try:
            posted_total = len(pd.read_csv(POSTED_LOG))
        except Exception:
            posted_total = 0
        pending = load_pending_programs()
        return jsonify({
            "status":"running",
            "time_africa": now_a,
            "time_usa": now_b,
            "posts_total": posts_total,
            "posted_total": posted_total,
            "pending_programs": len(pending)
        })
    except Exception as e:
        return jsonify({"status":"error","error": str(e)}), 500

@app.route("/pending_programs", methods=["GET"])
def http_pending_programs():
    return jsonify({"pending": load_pending_programs()})

@app.route("/approve_program", methods=["POST"])
def http_approve_program():
    payload = request.get_json() or {}
    net = payload.get("network")
    pid = payload.get("program_id")
    if not net or not pid:
        return jsonify({"error":"network and program_id required"}), 400
    progs = load_pending_programs()
    match = None
    for p in progs:
        if str(p.get("network")) == str(net) and str(p.get("program_id")) == str(pid):
            match = p
            break
    if not match:
        return jsonify({"error":"program not found"}), 404
    # attempt to generate tracking link
    tracking = None
    if net == "awin" and generate_awin_link:
        try:
            tracking = generate_awin_link(pid, match.get("url"))
        except Exception as e:
            print("[approve_program] awin generate failed:", e)
    if net == "rakuten" and generate_rakuten_link:
        try:
            tracking = generate_rakuten_link(pid, match.get("url"))
        except Exception as e:
            print("[approve_program] rakuten generate failed:", e)
    if not tracking:
        tracking = match.get("url")
    post = {
        "post_text": f"🔥 Deal: {match.get('name')} — get it here! [Link]",
        "platform": "instagram,facebook,twitter,tiktok",
        "link": tracking,
        "image_url": match.get("url") or DEFAULT_IMAGE
    }
    added = append_posts([post])
    # mark approved and remove from pending
    mark_program_approved(net, pid)
    progs = [p for p in progs if not (str(p.get("network"))==str(net) and str(p.get("program_id"))==str(pid))]
    save_pending_programs(progs)
    return jsonify({"status":"ok","added_posts":added,"tracking":tracking})

@app.route("/manual_run_discover", methods=["POST"])
def manual_run_discover():
    Thread(target=job_discover_and_apply, daemon=True).start()
    return jsonify({"message":"discover & apply started"}), 200

@app.route("/manual_run_post", methods=["POST"])
def manual_run_post():
    Thread(target=job_posting_cycle, daemon=True).start()
    return jsonify({"message":"posting cycle started"}), 200

# -------------------------
# Start background scheduler
# -------------------------
def start_scheduler():
    tz = None
    try:
        tz = pytz.timezone(TZ_PRIMARY)
    except Exception:
        tz = None
    scheduler = BackgroundScheduler(timezone=tz)
    scheduler.add_job(job_discover_and_apply, "interval", hours=APPLY_INTERVAL_HOURS, next_run_time=datetime.utcnow())
    scheduler.add_job(job_poll_approvals_and_make_posts, "interval", hours=APPROVAL_POLL_HOURS, next_run_time=datetime.utcnow())
    scheduler.add_job(job_posting_cycle, "interval", hours=POST_INTERVAL_HOURS, next_run_time=datetime.utcnow())
    scheduler.start()
    print("[scheduler] started (discover/apply every", APPLY_INTERVAL_HOURS, "h; approvals every", APPROVAL_POLL_HOURS, "h; posts every", POST_INTERVAL_HOURS, "h)")

start_scheduler()

print("Auto-affiliate manager booted. Check /status and logs.")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, threaded=True)
