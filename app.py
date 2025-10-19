# app.py
"""
SlickOfficials HQ — All-in-one auto affiliate manager & Publer poster
Copy & paste this file into your repo. Set sensitive environment variables in Render.
"""

import os
import csv
import json
import random
import traceback
from datetime import datetime, timedelta
from threading import Thread

import requests
from flask import Flask, request, redirect, url_for, session, render_template_string, jsonify
from apscheduler.schedulers.background import BackgroundScheduler

# ----------------------------
# CONFIG / ENV
# ----------------------------
# Admin (fallback values for immediate copy/paste)
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "Slickofficials HQ")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Asset@22")
SECRET_KEY = os.getenv("SECRET_KEY", None)

# Affiliates & posting
AWIN_PUBLISHER_ID = os.getenv("AWIN_PUBLISHER_ID")
AWIN_API_TOKEN = os.getenv("AWIN_API_TOKEN")
RAKUTEN_SCOPE_ID = os.getenv("RAKUTEN_SCOPE_ID")
RAKUTEN_WEBSERVICES_TOKEN = os.getenv("RAKUTEN_WEBSERVICES_TOKEN")
RAKUTEN_SECURITY_TOKEN = os.getenv("RAKUTEN_SECURITY_TOKEN")

PUBLER_API_KEY = os.getenv("PUBLER_API_KEY")
PUBLER_ID = os.getenv("PUBLER_ID")  # Publer account id
MANUAL_RUN_TOKEN = os.getenv("MANUAL_RUN_TOKEN", "")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # optional for better captions

# Files
POSTS_CSV = os.getenv("POSTS_FILE", "data/posts.csv")
POSTED_LOG_JSON = os.getenv("POSTED_LOG", "data/posted_log.json")
PENDING_PROGRAMS_FILE = os.getenv("PENDING_PROGRAMS_FILE", "data/pending_programs.json")

DEFAULT_IMAGE_URL = os.getenv("DEFAULT_IMAGE_URL", "https://i.imgur.com/fitness1.jpg")

# Intervals
POST_INTERVAL_HOURS = int(os.getenv("POST_INTERVAL_HOURS", "4"))
APPROVAL_POLL_HOURS = int(os.getenv("APPROVAL_POLL_HOURS", "2"))
DISCOVER_INTERVAL_HOURS = int(os.getenv("DISCOVER_INTERVAL_HOURS", "24"))

# Ensure directories exist
for path in [POSTS_CSV, POSTED_LOG_JSON, PENDING_PROGRAMS_FILE]:
    dirp = os.path.dirname(path) or "."
    try:
        os.makedirs(dirp, exist_ok=True)
    except Exception:
        pass

# ----------------------------
# Flask app
# ----------------------------
app = Flask(__name__)
app.secret_key = SECRET_KEY or os.urandom(24)

# ----------------------------
# Utilities: read/write storage
# ----------------------------
def read_posts_csv():
    posts = []
    try:
        with open(POSTS_CSV, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                posts.append(r)
    except FileNotFoundError:
        return []
    except Exception as e:
        print("[read_posts_csv] err", e)
        return []
    return posts

def append_posts_csv(rows):
    fieldnames = ["post_text", "platform", "link", "image_url"]
    file_exists = os.path.exists(POSTS_CSV)
    os.makedirs(os.path.dirname(POSTS_CSV) or ".", exist_ok=True)
    with open(POSTS_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        for r in rows:
            writer.writerow({
                "post_text": r.get("post_text", ""),
                "platform": r.get("platform", "instagram,facebook,twitter,tiktok"),
                "link": r.get("link", ""),
                "image_url": r.get("image_url", DEFAULT_IMAGE_URL)
            })

def read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def write_json(path, data):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ----------------------------
# Caption generation
# ----------------------------
def fallback_generate(product_name, n=3):
    leads = ["Hot pick", "Limited time", "Top pick", "Just dropped", "Fan favorite"]
    hooks = ["#ad", "#deal", "#Limited", "#SlickOfficials", "✨"]
    out = []
    for _ in range(n):
        out.append(f"{random.choice(leads)} — {product_name}! {random.choice(hooks)} [Link]")
    return out

def generate_ai_captions(product_name, n=3):
    # If OPENAI_API_KEY present, attempt a short Chat Completion call; otherwise fallback
    if not OPENAI_API_KEY:
        return fallback_generate(product_name, n)
    try:
        prompt = (
            f"Write {n} short, varied social-media captions to promote '{product_name}'. "
            "Include the token [Link] where the affiliate link should be placed. "
            "Make them suitable for Instagram, TikTok, Facebook, and X with different tones."
        )
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": "gpt-4o-mini",
            "messages": [{"role":"user","content":prompt}],
            "temperature": 0.8,
            "max_tokens": 300
        }
        r = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=20)
        if r.status_code != 200:
            print("[OpenAI] non-200:", r.status_code, r.text[:300])
            return fallback_generate(product_name, n)
        data = r.json()
        text = data["choices"][0]["message"]["content"]
        # try parse JSON/lines
        try:
            arr = json.loads(text)
            if isinstance(arr, list):
                return arr[:n]
        except Exception:
            lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
            if lines:
                return lines[:n]
        return fallback_generate(product_name, n)
    except Exception as e:
        print("[generate_ai_captions] err", e)
        return fallback_generate(product_name, n)

# ----------------------------
# AWIN / Rakuten helpers (discovery / apply / generate deep links)
# ----------------------------
def discover_awin_programmes():
    found = []
    if not (AWIN_API_TOKEN and AWIN_PUBLISHER_ID):
        return found
    try:
        url = f"https://api.awin.com/publishers/{AWIN_PUBLISHER_ID}/programmes"
        headers = {"Authorization": f"Bearer {AWIN_API_TOKEN}"}
        r = requests.get(url, headers=headers, timeout=20)
        if r.status_code == 200:
            data = r.json()
            # API shape may vary; try likely fields
            entries = data if isinstance(data, list) else data.get("programmes") or data.get("results") or []
            for e in entries:
                pid = e.get("programmeId") or e.get("id")
                name = e.get("programmeName") or e.get("merchantName") or e.get("name")
                url_target = e.get("clickThroughUrl") or e.get("siteUrl") or ""
                found.append({"network":"awin","id":pid,"name":name,"url":url_target})
    except Exception as e:
        print("[discover_awin_programmes] err", e)
    return found

def discover_rakuten_programmes():
    found = []
    if not RAKUTEN_WEBSERVICES_TOKEN:
        return found
    try:
        url = "https://api.rakutenmarketing.com/affiliate/1.0/getAdvertisers"
        params = {"wsToken": RAKUTEN_WEBSERVICES_TOKEN, "scopeId": RAKUTEN_SCOPE_ID, "approvalStatus": "available"}
        r = requests.get(url, params=params, timeout=20)
        if r.status_code == 200:
            data = r.json()
            advertisers = data.get("advertisers", []) if isinstance(data, dict) else []
            for a in advertisers:
                found.append({"network":"rakuten","id":a.get("advertiserId"), "name": a.get("advertiserName"), "url": a.get("siteUrl")})
    except Exception as e:
        print("[discover_rakuten_programmes] err", e)
    return found

def apply_to_program(program):
    net = program.get("network")
    pid = program.get("id")
    try:
        if net == "awin":
            if not (AWIN_API_TOKEN and AWIN_PUBLISHER_ID):
                return False, "missing awin creds"
            endpoint = f"https://api.awin.com/publishers/{AWIN_PUBLISHER_ID}/programmes/{pid}/apply"
            headers = {"Authorization": f"Bearer {AWIN_API_TOKEN}", "Content-Type": "application/json"}
            r = requests.post(endpoint, headers=headers, json={"publisherId": AWIN_PUBLISHER_ID}, timeout=20)
            return r.status_code in (200,201,202), r.text
        if net == "rakuten":
            if not RAKUTEN_WEBSERVICES_TOKEN:
                return False, "missing rakuten creds"
            endpoint = "https://api.rakutenmarketing.com/affiliate/1.0/apply"
            params = {"wsToken": RAKUTEN_WEBSERVICES_TOKEN, "advertiserId": pid, "scopeId": RAKUTEN_SCOPE_ID}
            r = requests.post(endpoint, params=params, timeout=20)
            return r.status_code in (200,201,202), r.text
    except Exception as e:
        return False, str(e)
    return False, "unsupported network"

# AWIN link generator (if possible)
def generate_awin_link(programme_id, destination_url):
    try:
        if not (AWIN_API_TOKEN and AWIN_PUBLISHER_ID):
            return None
        endpoint = f"https://api.awin.com/publishers/{AWIN_PUBLISHER_ID}/cread/links"
        headers = {"Authorization": f"Bearer {AWIN_API_TOKEN}"}
        payload = {"campaign": "globalbot", "destination": destination_url, "programmeId": programme_id}
        r = requests.post(endpoint, json=payload, headers=headers, timeout=20)
        if r.status_code == 200:
            return r.json().get("link")
    except Exception as e:
        print("[generate_awin_link] err", e)
    return None

# Rakuten link generator (if possible)
def generate_rakuten_link(advertiser_id, destination_url):
    try:
        if not RAKUTEN_WEBSERVICES_TOKEN:
            return None
        endpoint = "https://api.rakutenmarketing.com/linklocator/1.0/getTrackingLink"
        params = {
            "wsToken": RAKUTEN_WEBSERVICES_TOKEN,
            "securityToken": RAKUTEN_SECURITY_TOKEN or "",
            "scopeId": RAKUTEN_SCOPE_ID,
            "advertiserId": advertiser_id,
            "url": destination_url,
            "u1": "globalbot"
        }
        r = requests.get(endpoint, params=params, timeout=20)
        if r.status_code == 200:
            return r.json().get("trackingLink")
    except Exception as e:
        print("[generate_rakuten_link] err", e)
    return None

# ----------------------------
# Poll approvals & create posts
# ----------------------------
def poll_awin_approvals_fallback():
    # Try to import helper from affiliates/ if present (existing repo had one)
    try:
        from affiliates.awin import poll_awin_approvals as helper
        return helper([])
    except Exception:
        return []

def poll_rakuten_approvals_fallback():
    try:
        from affiliates.rakuten import poll_rakuten_approvals as helper
        return helper([])
    except Exception:
        return []

def poll_and_create_posts():
    created = []
    # AWIN approvals
    try:
        awin_list = poll_awin_approvals_fallback()
        for a in awin_list:
            url = a.get("clickThroughUrl") or a.get("url") or a.get("link") or a.get("siteUrl")
            if a.get("programmeId"):
                link = generate_awin_link(a.get("programmeId"), url) or url
            else:
                link = url
            img = a.get("logo") or a.get("imageUrl") or DEFAULT_IMAGE_URL
            captions = generate_ai_captions(a.get("programmeName") or a.get("merchantName") or a.get("name","AWIN Offer"))
            caption = captions[0] if captions else fallback_generate(a.get("name","AWIN Offer"))[0]
            created.append({"post_text": caption.replace("[Link]", link), "platform":"instagram,facebook,twitter,tiktok", "link": link, "image_url": img})
    except Exception as e:
        print("[poll_and_create_posts.awin] err", e)

    # Rakuten approvals
    try:
        rak_list = poll_rakuten_approvals_fallback()
        for r in rak_list:
            url = r.get("siteUrl") or r.get("url") or r.get("link")
            if r.get("advertiserId"):
                link = generate_rakuten_link(r.get("advertiserId"), url) or url
            else:
                link = url
            img = r.get("logo") or DEFAULT_IMAGE_URL
            captions = generate_ai_captions(r.get("advertiserName") or r.get("name","Rakuten Offer"))
            caption = captions[0] if captions else fallback_generate(r.get("name"))[0]
            created.append({"post_text": caption.replace("[Link]", link), "platform":"instagram,facebook,twitter,tiktok", "link": link, "image_url": img})
    except Exception as e:
        print("[poll_and_create_posts.rakuten] err", e)

    if created:
        added = append_new_posts_dedup(created)
        return created, added
    return created, 0

def append_new_posts_dedup(new_posts):
    existing = {p.get("link") for p in read_posts_csv()}
    rows = []
    added = 0
    for p in new_posts:
        link = (p.get("link") or "").strip()
        if not link or link in existing:
            continue
        rows.append(p)
        existing.add(link)
        added += 1
    if rows:
        append_posts_csv(rows)
    return added

# ----------------------------
# Publish via Publer
# ----------------------------
def publish_one_batch(batch_size=5):
    posts = read_posts_csv()
    if not posts:
        print("[publish_one_batch] no posts available")
        return 0
    posted_log = read_json(POSTED_LOG_JSON, {"links": [], "last_posted_at": None})
    posted_links = set(posted_log.get("links", []))
    count = 0
    for p in posts:
        if count >= batch_size:
            break
        link = (p.get("link") or "").strip()
        if not link or link in posted_links:
            continue
        text = p.get("post_text", "")
        if "[Link]" in text:
            text = text.replace("[Link]", link)
        else:
            if link not in text:
                text = text + "\n" + link
        payload = {
            "accounts": [PUBLER_ID] if PUBLER_ID else [],
            "content": {
                "text": text
            }
        }
        if p.get("image_url"):
            payload["content"]["mediaUrls"] = [p.get("image_url")]
        # If missing credentials, simulate posting and mark as posted locally
        if not PUBLER_API_KEY or not PUBLER_ID:
            print("[publish_one_batch] Publer credentials missing — simulation mode. Marking as posted:", link)
            posted_links.add(link)
            count += 1
            continue
        # Try two supported endpoints (some Publer setups use app.publer or api.publer)
        headers = {"Authorization": f"Bearer {PUBLER_API_KEY}", "Content-Type": "application/json"}
        success = False
        try:
            # Try public API
            r = requests.post("https://api.publer.io/v1/posts", headers=headers, json=payload, timeout=20)
            if r.status_code in (200,201):
                success = True
            else:
                # try alternate schedule endpoint
                alt = requests.post("https://app.publer.com/api/v1/posts/schedule", headers={
                    "Authorization": f"Bearer-API {PUBLER_API_KEY}",
                    "Publer-Workspace-Id": os.getenv("PUBLER_WORKSPACE_ID","")
                }, json={"bulk": {"state": "scheduled", "posts": [payload["content"]] }}, timeout=20)
                if alt.status_code in (200,201):
                    success = True
            if success:
                posted_links.add(link)
                count += 1
                print("[publish_one_batch] posted ->", link)
            else:
                print("[publish_one_batch] publer returned", r.status_code, r.text[:300])
        except Exception as e:
            print("[publish_one_batch] exception when posting:", e)
    # Update log
    posted_log["links"] = list(posted_links)
    posted_log["last_posted_at"] = datetime.utcnow().isoformat() + "Z"
    write_json(POSTED_LOG_JSON, posted_log)
    return count

# ----------------------------
# Scheduler jobs
# ----------------------------
def job_discover_and_apply():
    print("[job_discover_and_apply] running", datetime.utcnow().isoformat())
    found_awin = discover_awin_programmes()
    found_rak = discover_rakuten_programmes()
    found = found_awin + found_rak
    if not found:
        print("[job_discover_and_apply] nothing found")
        return
    pending = read_json(PENDING_PROGRAMS_FILE, [])
    known = {(p.get("network"), str(p.get("id"))) for p in pending}
    for f in found:
        key = (f.get("network"), str(f.get("id")))
        if key not in known:
            f["detected_at"] = datetime.utcnow().isoformat()
            pending.append(f)
            known.add(key)
    # attempt auto-apply for new pending
    for p in pending:
        if p.get("applied_at") or p.get("apply_attempted"):
            continue
        ok, resp = apply_to_program(p)
        p["apply_attempted"] = datetime.utcnow().isoformat()
        p["apply_result"] = str(resp)[:800]
        if ok:
            p["applied_at"] = datetime.utcnow().isoformat()
    write_json(PENDING_PROGRAMS_FILE, pending)
    print(f"[job_discover_and_apply] found {len(found)} programs, pending now {len(pending)}")

def job_poll_approvals_and_make_posts():
    print("[job_poll_approvals_and_make_posts] running", datetime.utcnow().isoformat())
    created, added = poll_and_create_posts()
    print(f"[job_poll_approvals_and_make_posts] created {len(created)}, added {added}")
    posted = publish_one_batch(batch_size=10)
    print(f"[job_poll_approvals_and_make_posts] posted {posted}")

def job_posting_cycle():
    print("[job_posting_cycle] running", datetime.utcnow().isoformat())
    posted = publish_one_batch(batch_size=10)
    print(f"[job_posting_cycle] posted {posted}")

# Init scheduler and schedule immediate runs on boot
scheduler = BackgroundScheduler()
scheduler.add_job(job_discover_and_apply, "interval", hours=DISCOVER_INTERVAL_HOURS, next_run_time=datetime.utcnow())
scheduler.add_job(job_poll_approvals_and_make_posts, "interval", hours=APPROVAL_POLL_HOURS, next_run_time=datetime.utcnow())
scheduler.add_job(job_posting_cycle, "interval", hours=POST_INTERVAL_HOURS, next_run_time=datetime.utcnow())
scheduler.start()
print("[scheduler] started: discover=%dh, approvals=%dh, post=%dh" % (DISCOVER_INTERVAL_HOURS, APPROVAL_POLL_HOURS, POST_INTERVAL_HOURS))

# Also trigger boot tasks in background so server starts quickly
def boot_tasks():
    try:
        print("[boot_tasks] immediate poll & post starting")
        job_poll_approvals_and_make_posts()
    except Exception as e:
        print("[boot_tasks] err", e)
Thread(target=boot_tasks, daemon=True).start()

# ----------------------------
# Dashboard & Auth (embedded templates)
# ----------------------------
LOGIN_HTML = """
<!doctype html>
<html>
<head><meta charset="utf-8"><title>SlickOfficials HQ — Login</title>
<style>
 body{font-family:Inter,Arial,Helvetica,sans-serif;background:linear-gradient(120deg,#021022,#071028);color:#e6eef8;margin:0;display:flex;align-items:center;justify-content:center;height:100vh}
 .card{width:420px;background:linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0.01));border-radius:12px;padding:22px;box-shadow:0 10px 30px rgba(0,0,0,0.6)}
 h1{margin:0 0 6px;font-size:20px;color:#aeeefc}
 p.sub{margin:0 0 14px;color:#8fb6d5}
 input{width:100%;padding:10px;margin:8px 0;border-radius:8px;border:1px solid rgba(255,255,255,0.05);background:rgba(255,255,255,0.02);color:#fff}
 button{width:100%;padding:10px;border-radius:8px;border:0;background:#06b6d4;color:#04282a;font-weight:700}
 .note{font-size:12px;color:#9fb0d6;margin-top:8px}
</style>
</head>
<body>
<div class="card">
 <h1>SlickOfficials HQ — Admin</h1>
 <p class="sub">Secure control panel for your affiliate posting engine.</p>
 {% if error %}<div style="background:#3b0b0b;color:#ffd2d2;padding:8px;border-radius:6px">{{ error }}</div>{% endif %}
 <form method="post" action="{{ url_for('login') }}">
   <label>Username</label>
   <input name="username" placeholder="Username" required />
   <label>Password</label>
   <input type="password" name="password" placeholder="Password" required />
   <button type="submit">Sign in</button>
 </form>
 <div class="note">Use strong credentials in Render env vars for production.</div>
</div>
</body>
</html>
"""

DASHBOARD_HTML = """
<!doctype html>
<html>
<head><meta charset="utf-8"><title>SlickOfficials HQ — Dashboard</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#041123;--card:#082033;--muted:#9fb0d6;--accent:#06b6d4}
body{font-family:Inter,Arial,Helvetica,sans-serif;background:linear-gradient(180deg,#041123,#071129);color:#eaf6ff;margin:0;padding:20px}
header{display:flex;align-items:center;justify-content:space-between}
h1{margin:0;font-size:20px}
.controls{display:flex;gap:10px;align-items:center}
button{background:var(--accent);border:none;color:#032022;padding:8px 12px;border-radius:8px;font-weight:700;cursor:pointer}
.grid{display:grid;grid-template-columns:1fr 360px;gap:18px;margin-top:18px}
.card{background:linear-gradient(180deg, rgba(255,255,255,0.03), rgba(255,255,255,0.02));padding:16px;border-radius:12px;box-shadow:0 8px 30px rgba(2,6,23,0.6)}
.small{font-size:13px;color:var(--muted)}
ul{list-style:none;padding:0;margin:8px 0}
li{padding:10px;border-bottom:1px solid rgba(255,255,255,0.03)}
.meta{font-size:12px;color:var(--muted)}
.link{color:var(--accent);text-decoration:none}
.footer{margin-top:14px;color:#9fb0d6;font-size:13px}
</style>
</head>
<body>
<header>
  <div>
    <h1>SlickOfficials HQ — Control Center</h1>
    <div class="small">Auto-post: every {{ post_interval }}h • Approvals: every {{ approval_interval }}h • Discover: every {{ discover_interval }}h</div>
  </div>
  <div class="controls">
    <div class="small">Publer: <strong>{{ 'Connected' if publer_connected else 'Not connected' }}</strong></div>
    <form method="post" action="{{ url_for('logout') }}"><button>Sign out</button></form>
  </div>
</header>

<div class="grid">
  <section class="card">
    <h3>Recent posts (CSV)</h3>
    <ul>
      {% for p in posts[:20] %}
        <li>
          <div style="font-weight:700">{{ p.post_text }}</div>
          <div class="meta">Platforms: {{ p.platform }} • Link: <a class="link" href="{{ p.link }}" target="_blank">{{ p.link[:80] }}</a></div>
        </li>
      {% else %}
        <li class="small">No posts yet — run Discover & Apply or wait for approvals.</li>
      {% endfor %}
    </ul>

    <div style="display:flex;gap:10px;margin-top:12px">
      <form method="post" action="{{ url_for('manual_trigger_posts') }}"><button type="submit">Post now</button></form>
      <form method="post" action="{{ url_for('manual_discover') }}"><button type="submit">Discover & Apply</button></form>
      <form method="post" action="{{ url_for('manual_poll_and_create') }}"><button type="submit">Poll approvals & create posts</button></form>
    </div>
    <div class="footer">Tip: Use <code>MANUAL_RUN_TOKEN</code> for secure API triggers without login.</div>
  </section>

  <aside class="card">
    <h3>Activity & Health</h3>
    <div class="small">Last posted: {{ last_posted or 'Never' }}</div>
    <div style="margin-top:10px;height:280px;overflow:auto;background:rgba(0,0,0,0.12);padding:10px;border-radius:8px;">
      {% for l in logs[:200] %}
        <div style="font-family:monospace;color:#dff8ff;margin-bottom:6px">{{ l }}</div>
      {% else %}
        <div class="small">No logs available</div>
      {% endfor %}
    </div>

    <h4 style="margin-top:12px">Pending programs ({{ pending|length }})</h4>
    <ul>
      {% for p in pending[:10] %}
        <li class="small">{{ p.network }} • {{ p.name or p.id }} <div class="meta">Detected: {{ p.detected_at }}</div></li>
      {% else %}
        <li class="small">No pending programs</li>
      {% endfor %}
    </ul>
  </aside>
</div>
</body>
</html>
"""

# ----------------------------
# Auth helpers / routes
# ----------------------------
def check_admin(creds_username, creds_password):
    return (creds_username == (os.getenv("ADMIN_USERNAME") or ADMIN_USERNAME)) and (creds_password == (os.getenv("ADMIN_PASSWORD") or ADMIN_PASSWORD))

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        u = request.form.get("username","").strip()
        p = request.form.get("password","")
        if check_admin(u, p):
            session["admin"] = True
            return redirect(url_for("dashboard"))
        error = "Invalid credentials"
    return render_template_string(LOGIN_HTML, error=error)

@app.route("/logout", methods=["POST"])
def logout():
    session.pop("admin", None)
    return redirect(url_for("login"))

def require_admin_redirect():
    if not session.get("admin"):
        return redirect(url_for("login"))

# ----------------------------
# Dashboard endpoints
# ----------------------------
@app.route("/")
def home():
    if session.get("admin"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

@app.route("/dashboard")
def dashboard():
    if not session.get("admin"):
        return redirect(url_for("login"))
    posts = read_posts_csv()
    pending = read_json(PENDING_PROGRAMS_FILE, [])
    posted_log = read_json(POSTED_LOG_JSON, {"links": [], "last_posted_at": None})
    # load simple app.log lines if present
    logs = []
    try:
        if os.path.exists("app.log"):
            with open("app.log", "r", encoding="utf-8") as f:
                logs = [ln.strip() for ln in f.readlines()][-200:][::-1]
    except Exception:
        logs = []
    return render_template_string(DASHBOARD_HTML,
                                  posts=posts,
                                  pending=pending,
                                  logs=logs,
                                  last_posted=posted_log.get("last_posted_at"),
                                  post_interval=POST_INTERVAL_HOURS,
                                  approval_interval=APPROVAL_POLL_HOURS,
                                  discover_interval=DISCOVER_INTERVAL_HOURS,
                                  publer_connected=bool(PUBLER_API_KEY and PUBLER_ID))

# ----------------------------
# Manual control endpoints (token or session)
# ----------------------------
def authorize_manual():
    token = request.args.get("token") or request.headers.get("X-MANUAL-TOKEN")
    if MANUAL_RUN_TOKEN:
        return (token == MANUAL_RUN_TOKEN) or session.get("admin")
    return session.get("admin")

@app.route("/manual_trigger_posts", methods=["POST"])
def manual_trigger_posts():
    if not authorize_manual():
        return jsonify({"error":"unauthorized"}), 403
    Thread(target=job_posting_cycle, daemon=True).start()
    return jsonify({"status":"started posting job"}), 200

@app.route("/manual_discover", methods=["POST"])
def manual_discover():
    if not authorize_manual():
        return jsonify({"error":"unauthorized"}), 403
    Thread(target=job_discover_and_apply, daemon=True).start()
    return jsonify({"status":"started discover job"}), 200

@app.route("/manual_poll_and_create", methods=["POST"])
def manual_poll_and_create():
    if not authorize_manual():
        return jsonify({"error":"unauthorized"}), 403
    Thread(target=job_poll_approvals_and_make_posts, daemon=True).start()
    return jsonify({"status":"started poll/create job"}), 200

@app.route("/status")
def status():
    posted_log = read_json(POSTED_LOG_JSON, {"links": [], "last_posted_at": None})
    pending = read_json(PENDING_PROGRAMS_FILE, [])
    posts = read_posts_csv()
    next_eta = None
    try:
        if posted_log.get("last_posted_at"):
            last = datetime.fromisoformat(posted_log["last_posted_at"].replace("Z",""))
            next_dt = last + timedelta(hours=POST_INTERVAL_HOURS)
            next_eta = max(0, int((next_dt - datetime.utcnow()).total_seconds()))
    except Exception:
        next_eta = None
    return jsonify({
        "status":"running",
        "time_utc": datetime.utcnow().isoformat()+"Z",
        "total_posts_csv": len(posts),
        "posted_count": len(posted_log.get("links", [])),
        "pending_programs": len(pending),
        "next_post_eta_seconds": next_eta,
        "publer_connected": bool(PUBLER_API_KEY and PUBLER_ID),
        "openai_connected": bool(OPENAI_API_KEY)
    })

# ----------------------------
# Start app
# ----------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print("SlickOfficials HQ starting on port", port)
    # run flask builtin for immediate convenience on Render (Render uses gunicorn automatically if configured)
    app.run(host="0.0.0.0", port=port)
