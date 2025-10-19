# app.py
"""
SlickOfficials HQ — single-file app with password-protected dashboard,
scheduler, affiliate discovery stubs, AI caption integration (OpenAI),
and Publer posting. Copy & paste into repo and deploy.
"""

import os
import json
import csv
import random
import traceback
from datetime import datetime, timedelta
from threading import Thread

import requests
from flask import (
    Flask, render_template_string, request, redirect, url_for, session, jsonify
)
from apscheduler.schedulers.background import BackgroundScheduler

# -------------------------
# CONFIG - environment (set these in Render for production)
# -------------------------
# Required for posting
PUBLER_API_KEY = os.getenv("PUBLER_API_KEY")
PUBLER_ID = os.getenv("PUBLER_ID")

# Optional AI captions (if provided)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Affiliates (optional)
AWIN_API_TOKEN = os.getenv("AWIN_API_TOKEN")
AWIN_PUBLISHER_ID = os.getenv("AWIN_PUBLISHER_ID")
RAKUTEN_WEBSERVICES_TOKEN = os.getenv("RAKUTEN_WEBSERVICES_TOKEN")
RAKUTEN_SCOPE_ID = os.getenv("RAKUTEN_SCOPE_ID")
RAKUTEN_SECURITY_TOKEN = os.getenv("RAKUTEN_SECURITY_TOKEN")

# Admin credentials (use env vars in Render for security)
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "Slickofficials HQ")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Asset@22")  # fallback for immediate copy/paste use

# Session secret (set in Render as SECRET_KEY; fallback auto-generate)
SECRET_KEY = os.getenv("SECRET_KEY", None)

POSTS_CSV = os.getenv("POSTS_FILE", "data/posts.csv")
POSTED_LOG = os.getenv("POSTED_LOG", "data/posted_log.json")
PENDING_PROGRAMS = os.getenv("PENDING_PROGRAMS_FILE", "data/pending_programs.json")

DEFAULT_IMAGE_URL = os.getenv("DEFAULT_IMAGE_URL", "https://i.imgur.com/fitness1.jpg")

POST_INTERVAL_HOURS = int(os.getenv("POST_INTERVAL_HOURS", "4"))
APPROVAL_POLL_HOURS = int(os.getenv("APPROVAL_POLL_HOURS", "2"))
APPLY_INTERVAL_HOURS = int(os.getenv("APPLY_INTERVAL_HOURS", "24"))

MANUAL_RUN_TOKEN = os.getenv("MANUAL_RUN_TOKEN", "")

# Ensure folders
os.makedirs(os.path.dirname(POSTS_CSV) or ".", exist_ok=True)
os.makedirs(os.path.dirname(POSTED_LOG) or ".", exist_ok=True)
os.makedirs(os.path.dirname(PENDING_PROGRAMS) or ".", exist_ok=True)

# -------------------------
# FLASK APP
# -------------------------
app = Flask(__name__)
app.secret_key = SECRET_KEY or os.urandom(24)

# -------------------------
# Utilities
# -------------------------
def read_posts_csv():
    posts = []
    try:
        with open(POSTS_CSV, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                posts.append(r)
    except FileNotFoundError:
        posts = []
    except Exception as e:
        print("[read_posts_csv] error:", e)
        posts = []
    return posts

def write_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print("[write_json] err:", e)

def read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

# -------------------------
# AI captioning (OpenAI) + fallback generator
# -------------------------
def fallback_generate(product_name, num=3):
    leads = ["Limited time", "Hot pick", "Top pick", "Don't miss out", "Just dropped"]
    hooks = ["#Deal #Ad", "#Sale", "#SlickOfficials", "#Limited", "✨"]
    variants = []
    for i in range(num):
        variants.append(f"{random.choice(leads)} — {product_name}! {random.choice(hooks)} [Link]")
    return variants

def generate_ai_captions(product, platforms=None, n=3):
    # Use OpenAI if API key provided; otherwise fallback
    if not OPENAI_API_KEY:
        return fallback_generate(product, n)
    try:
        prompt = (
            f"Write {n} short, diverse social-media captions for promoting '{product}'. "
            "Include [Link] token where the affiliate deep link will be inserted. "
            "Make them suitable for Instagram, TikTok, Facebook, and X (vary tone). "
            "Return a JSON array of strings only."
        )
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": "gpt-4o-mini",
            "messages": [{"role":"user","content":prompt}],
            "temperature": 0.9,
            "max_tokens": 300
        }
        r = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=20)
        if r.status_code != 200:
            print("[generate_ai_captions] openai error:", r.status_code, r.text[:300])
            return fallback_generate(product, n)
        data = r.json()
        content = data["choices"][0]["message"]["content"]
        # try parse JSON array
        try:
            arr = json.loads(content)
            if isinstance(arr, list):
                return arr[:n]
        except Exception:
            lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
            if lines:
                return lines[:n]
    except Exception as e:
        print("[generate_ai_captions] err:", e)
    return fallback_generate(product, n)

# -------------------------
# Affiliate discovery & apply (best-effort)
# -------------------------
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
            entries = data if isinstance(data, list) else data.get("programmes", [])
            for p in entries:
                found.append({"network":"awin","id":p.get("programmeId") or p.get("id"), "name":p.get("programmeName") or p.get("merchantName"), "url":p.get("clickThroughUrl")})
    except Exception as e:
        print("[discover_awin_programmes] err:", e)
    return found

def discover_rakuten_programmes():
    found = []
    if not (RAKUTEN_WEBSERVICES_TOKEN):
        return found
    try:
        url = "https://api.rakutenmarketing.com/affiliate/1.0/getAdvertisers"
        params = {"wsToken": RAKUTEN_WEBSERVICES_TOKEN, "scopeId": RAKUTEN_SCOPE_ID, "approvalStatus": "available"}
        r = requests.get(url, params=params, timeout=20)
        if r.status_code == 200:
            data = r.json()
            advertisers = data.get("advertisers", []) if isinstance(data, dict) else []
            for a in advertisers:
                found.append({"network":"rakuten","id":a.get("advertiserId") or a.get("id"), "name":a.get("advertiserName"), "url":a.get("siteUrl")})
    except Exception as e:
        print("[discover_rakuten_programmes] err:", e)
    return found

def apply_to_program(program):
    try:
        net = program.get("network")
        pid = program.get("id")
        if net == "awin":
            endpoint = f"https://api.awin.com/publishers/{AWIN_PUBLISHER_ID}/programmes/{pid}/apply"
            headers = {"Authorization": f"Bearer {AWIN_API_TOKEN}", "Content-Type": "application/json"}
            r = requests.post(endpoint, headers=headers, json={"publisherId":AWIN_PUBLISHER_ID}, timeout=20)
            return r.status_code in (200,201,202), r.text
        if net == "rakuten":
            endpoint = "https://api.rakutenmarketing.com/affiliate/1.0/apply"
            params = {"wsToken":RAKUTEN_WEBSERVICES_TOKEN, "advertiserId":pid, "scopeId":RAKUTEN_SCOPE_ID}
            r = requests.post(endpoint, params=params, timeout=20)
            return r.status_code in (200,201,202), r.text
    except Exception as e:
        return False, str(e)
    return False, "unsupported network"

# -------------------------
# Create posts from approvals
# -------------------------
def poll_awin_approvals(_=None):
    try:
        from affiliates.awin import poll_awin_approvals as helper
        return helper(_)
    except Exception:
        return discover_awin_programmes()

def poll_rakuten_approvals(_=None):
    try:
        from affiliates.rakuten import poll_rakuten_approvals as helper
        return helper(_)
    except Exception:
        return discover_rakuten_programmes()

def poll_and_create_posts():
    created = []
    try:
        awin = poll_awin_approvals()
        for p in awin:
            link = p.get("url","")
            if not link:
                continue
            captions = generate_ai_captions(p.get("name","AWIN Offer"))
            caption = captions[0] if captions else fallback_generate(p.get("name"))[0]
            created.append({"post_text": caption.replace("[Link]", link), "platform":"instagram,facebook,twitter,tiktok", "link":link, "image_url":p.get("logo", DEFAULT_IMAGE_URL)})
    except Exception as e:
        print("[poll_and_create_posts.awin] err:", e)

    try:
        rak = poll_rakuten_approvals()
        for a in rak:
            link = a.get("url","")
            if not link:
                continue
            captions = generate_ai_captions(a.get("name","Rakuten Offer"))
            caption = captions[0] if captions else fallback_generate(a.get("name"))[0]
            created.append({"post_text": caption.replace("[Link]", link), "platform":"instagram,facebook,twitter,tiktok", "link":link, "image_url": a.get("logo", DEFAULT_IMAGE_URL)})
    except Exception as e:
        print("[poll_and_create_posts.rakuten] err:", e)

    if created:
        added = append_new_posts_dedup(created)
        if added:
            print(f"[poll_and_create_posts] appended {added} new posts.")
    return created

def append_posts_csv(rows):
    import os as _os
    fieldnames = ["post_text","platform","link","image_url"]
    file_exists = _os.path.exists(POSTS_CSV)
    os.makedirs(_os.path.dirname(POSTS_CSV) or ".", exist_ok=True)
    with open(POSTS_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        for r in rows:
            writer.writerow({
                "post_text": r.get("post_text",""),
                "platform": r.get("platform","instagram,facebook,twitter,tiktok"),
                "link": r.get("link",""),
                "image_url": r.get("image_url", DEFAULT_IMAGE_URL)
            })

def append_new_posts_dedup(new_posts):
    existing = {p.get("link") for p in read_posts_csv()}
    rows = []
    added = 0
    for p in new_posts:
        link = p.get("link") or ""
        if not link or link in existing:
            continue
        rows.append(p)
        existing.add(link)
        added += 1
    if rows:
        append_posts_csv(rows)
    return added

# -------------------------
# Publish via Publer
# -------------------------
def publish_one():
    try:
        posts = read_posts_csv()
        if not posts:
            print("[publish_one] no posts to publish")
            return False
        posted_log = read_json(POSTED_LOG, {"links": [], "last_posted_at": None})
        posted_links = set(posted_log.get("links", []))
        for p in posts:
            link = (p.get("link") or "").strip()
            if not link or link in posted_links:
                continue
            text = p.get("post_text", "")
            if "[Link]" in text:
                text = text.replace("[Link]", link)
            else:
                if link not in text:
                    text = f"{text}\n{link}"
            payload = {"accounts":[PUBLER_ID] if PUBLER_ID else [], "content":{"text": text}}
            if p.get("image_url"):
                # Publer accepts mediaUrls in certain endpoints; older docs vary — try this shape first
                payload["content"]["mediaUrls"] = [p.get("image_url")]
            # If credentials missing, simulate and mark as posted
            if not PUBLER_API_KEY or not PUBLER_ID:
                print("[publish_one] Publer creds missing — simulation mode, marking posted.")
                posted_links.add(link)
                posted_log["links"] = list(posted_links)
                posted_log["last_posted_at"] = datetime.utcnow().isoformat() + "Z"
                write_json(POSTED_LOG, posted_log)
                return True
            headers = {"Authorization": f"Bearer {PUBLER_API_KEY}", "Content-Type": "application/json"}
            try:
                r = requests.post("https://api.publer.io/v1/posts", headers=headers, json=payload, timeout=20)
                if r.status_code in (200,201):
                    print("[publish_one] posted ->", link)
                    posted_links.add(link)
                    posted_log["links"] = list(posted_links)
                    posted_log["last_posted_at"] = datetime.utcnow().isoformat() + "Z"
                    write_json(POSTED_LOG, posted_log)
                    return True
                else:
                    print("[publish_one] publer error", r.status_code, r.text[:300])
            except Exception as e:
                print("[publish_one] exception posting:", e)
    except Exception as e:
        print("[publish_one] outer exception:", e)
    return False

# -------------------------
# Scheduler Jobs
# -------------------------
def job_discover_apply():
    print("[job_discover_apply] running", datetime.utcnow().isoformat())
    found = discover_awin_programmes() + discover_rakuten_programmes()
    pending = read_json(PENDING_PROGRAMS, [])
    existing = {(p.get("network"), str(p.get("id"))) for p in pending}
    for f in found:
        key = (f.get("network"), str(f.get("id")))
        if key not in existing:
            pending.append({"network": f.get("network"), "id": f.get("id"), "name": f.get("name"), "url": f.get("url"), "detected_at": datetime.utcnow().isoformat()})
            existing.add(key)
    # attempt best-effort apply
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

def job_poll_approvals_and_make_posts():
    print("[job_poll_approvals_and_make_posts] running", datetime.utcnow().isoformat())
    poll_and_create_posts()
    publish_one()

def job_posting_cycle():
    print("[job_posting_cycle] running", datetime.utcnow().isoformat())
    publish_one()

# Start scheduler and schedule immediate run on boot
scheduler = BackgroundScheduler()
scheduler.add_job(job_discover_apply, "interval", hours=APPLY_INTERVAL_HOURS, next_run_time=datetime.utcnow())
scheduler.add_job(job_poll_approvals_and_make_posts, "interval", hours=APPROVAL_POLL_HOURS, next_run_time=datetime.utcnow())
scheduler.add_job(job_posting_cycle, "interval", hours=POST_INTERVAL_HOURS, next_run_time=datetime.utcnow())
scheduler.start()
print("[scheduler] started: discover/apply every %dh; approvals every %dh; posts every %dh" % (APPLY_INTERVAL_HOURS, APPROVAL_POLL_HOURS, POST_INTERVAL_HOURS))

# Trigger immediate posting on boot in a background thread so server continues starting quickly
def boot_post():
    try:
        print("[boot_post] immediate posting started")
        publish_one()
    except Exception as e:
        print("[boot_post] err", e)
Thread(target=boot_post, daemon=True).start()

# -------------------------
# Dashboard & Auth (embedded templates)
# -------------------------
LOGIN_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>SlickOfficials HQ — Login</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <style>
    body{font-family:Inter,Arial,Helvetica,sans-serif;background:linear-gradient(120deg,#0f172a,#0b1220);color:#e6eef8;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
    .card{width:380px;background:linear-gradient(180deg, rgba(255,255,255,0.03), rgba(255,255,255,0.02));border-radius:14px;padding:24px;box-shadow:0 8px 30px rgba(2,6,23,0.7);}
    h1{margin:0 0 8px;font-size:18px;letter-spacing:0.6px}
    p.sub{margin:0 0 18px;color:#9fb0d6;font-size:13px}
    input{width:100%;padding:10px 12px;margin:8px 0;border-radius:8px;border:1px solid rgba(255,255,255,0.06);background:rgba(255,255,255,0.02);color:#fff}
    button{width:100%;padding:10px;border-radius:10px;border:0;background:#06b6d4;color:#062726;font-weight:700;margin-top:8px;cursor:pointer}
    .note{font-size:12px;color:#9fb0d6;margin-top:10px}
    footer{font-size:11px;color:#7fa6d6;margin-top:12px;text-align:center}
  </style>
</head>
<body>
  <div class="card">
    <h1>SlickOfficials HQ — Admin Sign in</h1>
    <p class="sub">Secure dashboard for managing posts, approvals, and manual triggers.</p>
    {% if error %}<div style="color:#ffd2d2;background:#3b0b0b;padding:8px;border-radius:6px">{{ error }}</div>{% endif %}
    <form method="post" action="{{ url_for('login') }}">
      <label>Username</label>
      <input name="username" placeholder="Username" required />
      <label>Password</label>
      <input type="password" name="password" placeholder="Password" required />
      <button type="submit">Sign in</button>
      <div class="note">Last login attempt: {{ last_attempt }}</div>
      <footer>Powered by SlickOfficials • Secure access only</footer>
    </form>
  </div>
</body>
</html>
"""

DASHBOARD_HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>SlickOfficials HQ — Dashboard</title>
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <style>
    :root{--bg:#071129;--card:#0b2540;--muted:#9fb0d6;--accent:#06b6d4}
    body{font-family:Inter,Arial,Helvetica,sans-serif;background:linear-gradient(180deg,#041123,#071129);color:#eaf6ff;margin:0;padding:20px}
    header{display:flex;align-items:center;justify-content:space-between}
    h1{margin:0;font-size:20px}
    .controls{display:flex;gap:10px;align-items:center}
    button{background:var(--accent);border:none;color:#032022;padding:8px 12px;border-radius:8px;font-weight:700;cursor:pointer}
    .grid{display:grid;grid-template-columns: 1fr 360px;gap:18px;margin-top:18px}
    .card{background:linear-gradient(180deg, rgba(255,255,255,0.03), rgba(255,255,255,0.02));padding:16px;border-radius:12px;box-shadow:0 8px 30px rgba(2,6,23,0.6)}
    .small{font-size:13px;color:var(--muted)}
    ul{list-style:none;padding:0;margin:8px 0}
    li{padding:10px;border-bottom:1px solid rgba(255,255,255,0.03)}
    .post-text{font-weight:600}
    .meta{font-size:12px;color:var(--muted)}
    .status{display:flex;gap:10px;align-items:center}
    .pill{background:rgba(255,255,255,0.03);padding:6px 8px;border-radius:8px;font-weight:700}
    form.inline{display:inline}
  </style>
</head>
<body>
  <header>
    <div>
      <h1>SlickOfficials HQ — Control Center</h1>
      <div class="small">Auto-run: every {{ post_interval }}h • Approvals: every {{ approval_interval }}h • Discover: every {{ discover_interval }}h</div>
    </div>
    <div class="controls">
      <div class="status">
        <div class="pill">Publer: {{ "Connected" if publer_connected else "Not connected" }}</div>
        <div class="pill">OpenAI: {{ "Connected" if openai_connected else "Not connected" }}</div>
      </div>
      <form method="post" action="{{ url_for('logout') }}" class="inline"><button>Sign out</button></form>
    </div>
  </header>

  <div class="grid">
    <section class="card">
      <h3>Recent posts (CSV preview)</h3>
      <ul>
        {% for p in posts[:20] %}
          <li>
            <div class="post-text">{{ p.post_text }}</div>
            <div class="meta">Platforms: {{ p.platform }} • Link: <a href="{{ p.link }}" target="_blank" style="color:var(--accent)">{{ p.link[:60] }}</a></div>
          </li>
        {% else %}
          <li class="small">No posts in posts.csv</li>
        {% endfor %}
      </ul>

      <div style="margin-top:12px;display:flex;gap:10px">
        <form method="post" action="{{ url_for('manual_trigger_posts') }}"><button type="submit">Post now</button></form>
        <form method="post" action="{{ url_for('manual_discover') }}"><button type="submit">Discover & apply</button></form>
        <button onclick="location.href='{{ url_for('status') }}'">Refresh status</button>
      </div>
    </section>

    <aside class="card">
      <h3>Activity & Logs</h3>
      <div class="small">Last posted: {{ last_posted or 'Never' }}</div>
      <div style="margin-top:10px;height:340px;overflow:auto;background:rgba(0,0,0,0.15);padding:10px;border-radius:8px;">
        {% for l in logs %}
          <div style="font-family:monospace;color:#dff8ff;margin-bottom:6px">{{ l }}</div>
        {% else %}
          <div class="small">No logs yet</div>
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

# -------------------------
# Auth routes
# -------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    last = session.get("last_attempt", "never")
    error = None
    if request.method == "POST":
        u = request.form.get("username", "")
        p = request.form.get("password", "")
        # Compare with environment-driven creds (trim spaces)
        if u.strip() == (ADMIN_USERNAME or "").strip() and p == (ADMIN_PASSWORD or ""):
            session["admin"] = True
            session["last_attempt"] = datetime.utcnow().isoformat()
            return redirect(url_for("dashboard"))
        else:
            error = "Invalid credentials"
            session["last_attempt"] = datetime.utcnow().isoformat()
    return render_template_string(LOGIN_HTML, error=error, last_attempt=session.get("last_attempt", "never"))

@app.route("/logout", methods=["POST"])
def logout():
    session.pop("admin", None)
    return redirect(url_for("login"))

def require_admin():
    if not session.get("admin"):
        return redirect(url_for("login"))

# -------------------------
# Dashboard routes (protected)
# -------------------------
@app.route("/dashboard")
def dashboard():
    if not session.get("admin"):
        return redirect(url_for("login"))
    posts = read_posts_csv()
    posted = read_json(POSTED_LOG, {"links":[], "last_posted_at": None})
    pending = read_json(PENDING_PROGRAMS, [])
    # Read simple logs from a rotating log area: take most recent lines from Render log file if available, else use posted_log
    logs = []
    try:
        # attempt to read a local 'app.log' if present
        if os.path.exists("app.log"):
            with open("app.log", "r", encoding="utf-8") as f:
                lines = f.readlines()[-200:]
                logs = [ln.strip() for ln in lines[::-1]]
    except Exception:
        logs = []
    return render_template_string(DASHBOARD_HTML,
                                  posts=posts,
                                  publer_connected=bool(PUBLER_API_KEY and PUBLER_ID),
                                  openai_connected=bool(OPENAI_API_KEY),
                                  post_interval=POST_INTERVAL_HOURS,
                                  approval_interval=APPROVAL_POLL_HOURS,
                                  discover_interval=APPLY_INTERVAL_HOURS,
                                  logs=logs,
                                  last_posted=posted.get("last_posted_at"),
                                  pending=pending)

# -------------------------
# Public control endpoints (but require admin session or manual token)
# -------------------------
@app.route("/manual_trigger_posts", methods=["POST"])
def manual_trigger_posts():
    # allow X-MANUAL-TOKEN header or admin session
    token = request.args.get("token") or request.headers.get("X-MANUAL-TOKEN")
    if MANUAL_RUN_TOKEN and token != MANUAL_RUN_TOKEN and not session.get("admin"):
        return jsonify({"error":"unauthorized"}), 403
    Thread(target=job_posting_cycle, daemon=True).start()
    return jsonify({"status":"started posting job"}), 200

@app.route("/manual_discover", methods=["POST"])
def manual_discover():
    token = request.args.get("token") or request.headers.get("X-MANUAL-TOKEN")
    if MANUAL_RUN_TOKEN and token != MANUAL_RUN_TOKEN and not session.get("admin"):
        return jsonify({"error":"unauthorized"}), 403
    Thread(target=job_discover_apply, daemon=True).start()
    return jsonify({"status":"started discover job"}), 200

@app.route("/status")
def status():
    posted = read_json(POSTED_LOG, {"links":[], "last_posted_at":None})
    pending = read_json(PENDING_PROGRAMS, [])
    posts = read_posts_csv()
    next_eta = None
    if posted.get("last_posted_at"):
        try:
            last = datetime.fromisoformat(posted["last_posted_at"].replace("Z",""))
            next_eta = (last + timedelta(hours=POST_INTERVAL_HOURS) - datetime.utcnow()).total_seconds()
            if next_eta < 0:
                next_eta = 0
        except Exception:
            next_eta = None
    return jsonify({
        "status":"running",
        "time_utc": datetime.utcnow().isoformat()+"Z",
        "total_posts_csv": len(posts),
        "posted_count": len(posted.get("links", [])),
        "pending_programs": len(pending),
        "next_post_eta_seconds": next_eta,
        "publer_connected": bool(PUBLER_API_KEY and PUBLER_ID),
        "openai_connected": bool(OPENAI_API_KEY)
    })

# -------------------------
# Simple root
# -------------------------
@app.route("/")
def home():
    if session.get("admin"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

# -------------------------
# Run server
# -------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print("Starting SlickOfficials HQ on port", port)
    app.run(host="0.0.0.0", port=port)
