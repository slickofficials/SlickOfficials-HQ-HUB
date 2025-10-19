# app.py
"""
SlickOfficials HQ — Full app with PostgreSQL analytics for clicks & conversions.
Copy & paste this file into your repo (replaces previous app.py).
Set DATABASE_URL in Render environment (provided instructions below).
"""

import os
import json
import random
from datetime import datetime, date, timedelta
from threading import Thread

import requests
from flask import (
    Flask, request, redirect, url_for, session,
    render_template_string, jsonify, abort
)

from apscheduler.schedulers.background import BackgroundScheduler

# SQLAlchemy + PostgreSQL
from sqlalchemy import (
    create_engine, Column, Integer, String, Text, DateTime, Float, ForeignKey, func
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

# -----------------------------
# CONFIG & ENV
# -----------------------------
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "Slickofficials HQ")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "Asset@22")
MANUAL_RUN_TOKEN = os.getenv("MANUAL_RUN_TOKEN", "")
DATABASE_URL = os.getenv("DATABASE_URL")  # Render Postgres provides this
PUBLER_API_KEY = os.getenv("PUBLER_API_KEY")
PUBLER_ID = os.getenv("PUBLER_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")  # optional

POSTS_CSV = os.getenv("POSTS_FILE", "data/posts.csv")
DEFAULT_IMAGE_URL = os.getenv("DEFAULT_IMAGE_URL", "https://i.imgur.com/fitness1.jpg")
POST_INTERVAL_HOURS = int(os.getenv("POST_INTERVAL_HOURS", "4"))
APPROVAL_POLL_HOURS = int(os.getenv("APPROVAL_POLL_HOURS", "2"))
DISCOVER_INTERVAL_HOURS = int(os.getenv("DISCOVER_INTERVAL_HOURS", "24"))

# -----------------------------
# App Init
# -----------------------------
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", os.urandom(24))

# -----------------------------
# Database setup
# -----------------------------
if not DATABASE_URL:
    print("WARNING: DATABASE_URL not set. Analytics will not be persisted to Postgres.")
else:
    # Ensure SQLAlchemy uses the right postgres scheme if Render gives postgres://
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

Base = declarative_base()
engine = create_engine(DATABASE_URL, echo=False, future=True) if DATABASE_URL else None
SessionLocal = sessionmaker(bind=engine) if engine else None

# Models
class Product(Base):
    __tablename__ = "products"
    id = Column(Integer, primary_key=True)
    name = Column(String(512), nullable=False)
    affiliate_link = Column(Text, nullable=False)
    network = Column(String(64), nullable=True)
    category = Column(String(128), nullable=True)
    image_url = Column(String(1024), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    clicks = relationship("Click", back_populates="product")
    conversions = relationship("Conversion", back_populates="product")

class Click(Base):
    __tablename__ = "clicks"
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    utm = Column(String(512), nullable=True)
    referer = Column(String(1024), nullable=True)
    ip = Column(String(128), nullable=True)
    user_agent = Column(String(1024), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    product = relationship("Product", back_populates="clicks")

class Conversion(Base):
    __tablename__ = "conversions"
    id = Column(Integer, primary_key=True)
    product_id = Column(Integer, ForeignKey("products.id"), nullable=False)
    revenue = Column(Float, nullable=True)               # optional revenue reported
    order_id = Column(String(256), nullable=True)
    status = Column(String(64), nullable=True)
    raw_payload = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    product = relationship("Product", back_populates="conversions")

# Create tables if DB exists
def init_db():
    if engine:
        Base.metadata.create_all(engine)
        print("[init_db] Tables created / ensured")
    else:
        print("[init_db] No DATABASE_URL, skipping DB init")

init_db()

# -----------------------------
# Storage helpers (CSV fallback)
# -----------------------------
import csv
def read_posts_csv(limit=None):
    rows = []
    try:
        if not os.path.exists(POSTS_CSV):
            return []
        with open(POSTS_CSV, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                rows.append(r)
                if limit and len(rows) >= limit:
                    break
    except Exception as e:
        print("[read_posts_csv] err", e)
    return rows

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

# -----------------------------
# Affiliate logic helpers (simplified)
# -----------------------------
def get_product_by_link(db, link):
    return db.query(Product).filter(Product.affiliate_link == link).first()

def ensure_product(db, p):
    """p: dict with name, link, network, category, image_url"""
    prod = db.query(Product).filter(Product.affiliate_link == p["link"]).first()
    if prod:
        return prod
    prod = Product(
        name=p.get("name") or p.get("product") or "Offer",
        affiliate_link=p["link"],
        network=p.get("network"),
        category=p.get("category"),
        image_url=p.get("image_url", DEFAULT_IMAGE_URL)
    )
    db.add(prod)
    db.commit()
    db.refresh(prod)
    return prod

# -----------------------------
# Click redirect endpoint
# -----------------------------
@app.route("/r/<int:product_id>")
def redirect_affiliate(product_id):
    """
    Redirect endpoint to track clicks.
    Usage: use /r/<product_id> as your short link instead of raw affiliate link.
    Example: https://yourapp.onrender.com/r/123
    """
    referer = request.headers.get("Referer")
    ua = request.headers.get("User-Agent")
    ip = request.headers.get("X-Forwarded-For", request.remote_addr)
    utm = request.args.get("utm_source") or request.args.get("utm_medium") or request.args.get("utm_campaign")
    # Lookup product
    if not engine:
        # If no DB, fall back to CSV rows: find by numeric index
        posts = read_posts_csv()
        idx = next((i for i,p in enumerate(posts) if (i+1)==product_id), None)
        if idx is None:
            abort(404)
        link = posts[idx]["link"]
        # No DB tracking
        return redirect(link, code=302)

    db = SessionLocal()
    try:
        prod = db.query(Product).filter(Product.id == product_id).first()
        if not prod:
            abort(404)
        click = Click(product_id=prod.id, utm=utm, referer=referer, ip=ip, user_agent=ua)
        db.add(click)
        db.commit()
        # Redirect to affiliate link
        return redirect(prod.affiliate_link, code=302)
    except Exception as e:
        db.rollback()
        print("[redirect_affiliate] err", e)
        return redirect(prod.affiliate_link if 'prod' in locals() and prod else "/", code=302)
    finally:
        db.close()

# -----------------------------
# Conversion webhook
# -----------------------------
@app.route("/conversion", methods=["POST"])
def conversion_webhook():
    """
    POST webhook to notify of conversions.
    Expected JSON: { "affiliate_link": "...", "order_id":"", "revenue": 12.34, "status":"confirmed" }
    This endpoint should be protected in production (shared secret).
    """
    payload = request.get_json() or {}
    affiliate_link = payload.get("affiliate_link") or payload.get("link")
    order_id = payload.get("order_id") or payload.get("order")
    revenue = payload.get("revenue")
    status = payload.get("status", "confirmed")
    if not affiliate_link:
        return jsonify({"error": "missing affiliate_link"}), 400

    if not engine:
        # store locally as JSON log when DB not present
        os.makedirs("data", exist_ok=True)
        path = "data/conversions_local.json"
        records = []
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    records = json.load(f)
        except Exception:
            records = []
        records.append({"affiliate_link": affiliate_link, "order_id": order_id, "revenue": revenue, "status": status, "ts": datetime.utcnow().isoformat()})
        with open(path, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
        return jsonify({"status":"logged_local"}), 200

    db = SessionLocal()
    try:
        prod = db.query(Product).filter(Product.affiliate_link == affiliate_link).first()
        if not prod:
            # Optionally create product record for unknown link
            prod = Product(name=payload.get("product_name","Unknown"), affiliate_link=affiliate_link, category=payload.get("category"))
            db.add(prod)
            db.commit()
            db.refresh(prod)
        conv = Conversion(product_id=prod.id, revenue=revenue, order_id=order_id, status=status, raw_payload=json.dumps(payload))
        db.add(conv)
        db.commit()
        return jsonify({"status":"ok", "product_id": prod.id}), 200
    except Exception as e:
        db.rollback()
        print("[conversion_webhook] err", e)
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()

# -----------------------------
# Dashboard (protected)
# -----------------------------
LOGIN_HTML = """
<!doctype html><html><head><meta charset="utf-8"><title>Login</title>
<style>body{font-family:Inter,Arial;background:#081226;color:#eaf6ff;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
.card{background:linear-gradient(180deg,rgba(255,255,255,0.02),rgba(255,255,255,0.01));padding:26px;border-radius:12px;width:420px}
input{width:100%;padding:10px;margin:8px 0;border-radius:8px;border:1px solid rgba(255,255,255,0.05);background:transparent;color:#fff}
button{width:100%;padding:10px;background:#06b6d4;border:none;border-radius:8px;color:#022}
.error{background:#330000;padding:8px;border-radius:8px;color:#ffd2d2}</style></head><body>
<div class="card"><h2>SlickOfficials HQ — Login</h2>{% if error %}<div class="error">{{ error }}</div>{% endif %}
<form method="post"><input name="username" placeholder="Username" required /><input name="password" type="password" placeholder="Password" required />
<button type="submit">Log in</button></form></div></body></html>
"""

DASHBOARD_HTML = """
<!doctype html><html><head><meta charset="utf-8"><title>Dashboard</title>
<style>body{font-family:Inter,Arial;background:linear-gradient(180deg,#021022,#071028);color:#eaf6ff;margin:0;padding:20px}
.header{display:flex;justify-content:space-between;align-items:center}h1{margin:0}
.card{background:rgba(255,255,255,0.03);padding:16px;border-radius:12px;margin-top:14px}
.grid{display:grid;grid-template-columns:1fr 360px;gap:18px}
.list{max-height:420px;overflow:auto}
.small{color:#9fb0d6;font-size:13px}
a{color:#06b6d4}
button{background:#06b6d4;color:#022;padding:8px;border-radius:8px;border:none}
.stat{font-size:22px;font-weight:700}
</style></head><body>
<div class="header"><div><h1>SlickOfficials HQ — Analytics</h1><div class="small">Permanent analytics via Postgres</div></div><div>
<form method="post" action="{{ url_for('logout') }}"><button>Logout</button></form></div></div>

<div class="grid">
  <section class="card">
    <h3>Summary</h3>
    <div style="display:flex;gap:18px;margin-top:8px">
      <div><div class="stat">{{ totals.clicks }}</div><div class="small">Clicks (all-time)</div></div>
      <div><div class="stat">{{ totals.conversions }}</div><div class="small">Conversions</div></div>
      <div><div class="stat">${{ "{:.2f}".format(totals.revenue or 0) }}</div><div class="small">Revenue (reported)</div></div>
    </div>

    <h3 style="margin-top:12px">Top Products</h3>
    <div class="list">
      {% for p in top_products %}
        <div style="padding:10px;border-bottom:1px solid rgba(255,255,255,0.03)">
          <div style="font-weight:700">{{ p.name }}</div>
          <div class="small">Clicks: {{ p.clicks }} • Conversions: {{ p.conversions }} • Revenue: ${{ "{:.2f}".format(p.revenue or 0) }}</div>
          <div class="small">Link: <a href="{{ p.affiliate_link }}" target="_blank">{{ p.affiliate_link[:80] }}</a></div>
          <div style="margin-top:6px"><a href="/r/{{ p.id }}" target="_blank">Short link → /r/{{ p.id }}</a></div>
        </div>
      {% else %}
        <div class="small">No products yet</div>
      {% endfor %}
    </div>
  </section>

  <aside class="card">
    <h3>Recent Events</h3>
    <div style="max-height:420px;overflow:auto">
      {% for e in events %}
        <div style="font-family:monospace;font-size:13px;margin-bottom:8px">{{ e }}</div>
      {% else %}
        <div class="small">No events recorded</div>
      {% endfor %}
    </div>
  </aside>
</div>
</body></html>
"""

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        u = request.form.get("username","")
        p = request.form.get("password","")
        if u == os.getenv("ADMIN_USERNAME", ADMIN_USERNAME) and p == os.getenv("ADMIN_PASSWORD", ADMIN_PASSWORD):
            session["admin"] = True
            return redirect(url_for("dashboard"))
        error = "Invalid credentials"
    return render_template_string(LOGIN_HTML, error=error)

@app.route("/logout", methods=["POST"])
def logout():
    session.pop("admin", None)
    return redirect(url_for("login"))

def require_admin():
    if not session.get("admin"):
        return redirect(url_for("login"))

@app.route("/")
def root():
    if session.get("admin"):
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

@app.route("/dashboard")
def dashboard():
    if not session.get("admin"):
        return redirect(url_for("login"))
    totals = {"clicks": 0, "conversions": 0, "revenue": 0.0}
    top_products = []
    events = []
    if engine:
        db = SessionLocal()
        try:
            totals["clicks"] = db.query(func.count(Click.id)).scalar() or 0
            totals["conversions"] = db.query(func.count(Conversion.id)).scalar() or 0
            totals["revenue"] = db.query(func.coalesce(func.sum(Conversion.revenue), 0.0)).scalar() or 0.0

            # Top products by conversions then clicks
            prod_stats = db.query(
                Product.id, Product.name, Product.affiliate_link,
                func.count(Click.id).label("clicks"),
                func.count(Conversion.id).label("conversions"),
                func.coalesce(func.sum(Conversion.revenue), 0.0).label("revenue")
            ).outerjoin(Click, Click.product_id == Product.id
            ).outerjoin(Conversion, Conversion.product_id == Product.id
            ).group_by(Product.id).order_by(func.coalesce(func.sum(Conversion.revenue),0.0).desc(), func.count(Conversion.id).desc()).limit(20).all()

            for row in prod_stats:
                top_products.append({
                    "id": row.id,
                    "name": row.name,
                    "affiliate_link": row.affiliate_link,
                    "clicks": int(row.clicks or 0),
                    "conversions": int(row.conversions or 0),
                    "revenue": float(row.revenue or 0.0)
                })

            # Recent events: last 100 clicks and conversions
            recent_clicks = db.query(Click).order_by(Click.created_at.desc()).limit(50).all()
            recent_convs = db.query(Conversion).order_by(Conversion.created_at.desc()).limit(50).all()
            for c in recent_clicks:
                events.append(f"CLICK | pid={c.product_id} ts={c.created_at.isoformat()} ip={c.ip} referer={c.referer or '-'}")
            for c in recent_convs:
                events.append(f"CONV  | pid={c.product_id} ts={c.created_at.isoformat()} order={c.order_id or '-'} rev={c.revenue or 0}")
            # Sort events by newest first
            events = sorted(events, reverse=True)[:200]
        except Exception as e:
            print("[dashboard] err", e)
        finally:
            db.close()
    else:
        # No DB: show CSV-based sample
        posts = read_posts_csv(limit=20)
        top_products = [{"id": i+1, "name": p.get("post_text")[:60], "affiliate_link": p.get("link"), "clicks": 0, "conversions": 0, "revenue": 0.0} for i,p in enumerate(posts)]
    return render_template_string(DASHBOARD_HTML, totals=type("T", (), totals)(), top_products=top_products, events=events)

# -----------------------------
# Manual endpoints / status
# -----------------------------
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

@app.route("/status")
def status():
    posted = 0
    pending = 0
    total_posts = len(read_posts_csv())
    if engine:
        db = SessionLocal()
        try:
            posted = db.query(func.count(Conversion.id)).scalar() or 0
            pending = db.query(func.count(Product.id)).scalar() or 0
        finally:
            db.close()
    return jsonify({
        "status":"running",
        "utc": datetime.utcnow().isoformat()+"Z",
        "total_posts_csv": total_posts,
        "conversions": posted,
        "products": pending
    })

# -----------------------------
# (Placeholder) Affiliate polling & posting jobs
# -----------------------------
def job_discover_and_apply():
    print("[job] discover/apply executed", datetime.utcnow().isoformat())
    # kept intentionally minimal — earlier logic for auto-apply / discovery exists in previous files
    # if you want, we can call your previous discovery functions here

def job_poll_approvals_and_make_posts():
    print("[job] poll approvals & create posts", datetime.utcnow().isoformat())
    # reuse publishing flow (placeholder) — adapt to your previous publisher code

def job_posting_cycle():
    print("[job] posting cycle", datetime.utcnow().isoformat())
    # For safety, we don't auto-run Publer here without credentials - keep your existing logic
    # Optionally, mark posts as promoted in DB when published

# Scheduler bootstrap
scheduler = BackgroundScheduler()
scheduler.add_job(job_discover_and_apply, "interval", hours=DISCOVER_INTERVAL_HOURS, next_run_time=datetime.utcnow())
scheduler.add_job(job_poll_approvals_and_make_posts, "interval", hours=APPROVAL_POLL_HOURS, next_run_time=datetime.utcnow())
scheduler.add_job(job_posting_cycle, "interval", hours=POST_INTERVAL_HOURS, next_run_time=datetime.utcnow())
scheduler.start()
print("[scheduler] started")

# Boot tasks
def boot_tasks():
    try:
        print("[boot] running immediate poll")
        Thread(target=job_poll_approvals_and_make_posts, daemon=True).start()
    except Exception as e:
        print("[boot_tasks] err", e)
Thread(target=boot_tasks, daemon=True).start()

# -----------------------------
# Start
# -----------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print("SlickOfficials HQ starting on port", port)
    app.run(host="0.0.0.0", port=port)
