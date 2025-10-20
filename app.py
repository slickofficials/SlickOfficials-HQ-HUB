import os
import requests
import openai
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, render_template_string, redirect, request, session, url_for
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
from dotenv import load_dotenv

# Load env
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("APP_SECRET_KEY", "supersecret")

DATABASE_URL = os.getenv("DATABASE_URL")

def get_db():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    return conn

def init_db():
    if not DATABASE_URL:
        print("[init_db] No DATABASE_URL, skipping DB init")
        return
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS posts (
        id SERIAL PRIMARY KEY,
        platform VARCHAR(50),
        caption TEXT,
        image_url TEXT,
        affiliate_link TEXT,
        timestamp TIMESTAMP DEFAULT NOW()
    );
    CREATE TABLE IF NOT EXISTS analytics (
        id SERIAL PRIMARY KEY,
        platform VARCHAR(50),
        clicks INT DEFAULT 0,
        impressions INT DEFAULT 0,
        engagement_rate FLOAT DEFAULT 0,
        timestamp TIMESTAMP DEFAULT NOW()
    );
    """)
    conn.commit()
    cur.close()
    conn.close()
    print("[init_db] Tables initialized ✅")

init_db()

APP_USERNAME = os.getenv("APP_USERNAME")
APP_PASSWORD = os.getenv("APP_PASSWORD")
AWIN_PUBLISHER_ID = os.getenv("AWIN_PUBLISHER_ID")
RAKUTEN_SCOPE_ID = os.getenv("RAKUTEN_SCOPE_ID")
PUBLER_USER_ID = os.getenv("PUBLER_USER_ID")
PUBLER_API_KEY = os.getenv("PUBLER_API_KEY")
openai.api_key = os.getenv("OPENAI_API_KEY")

def ai_caption(name, source):
    prompt = f"Create a short, catchy multi-tone caption promoting {name} from {source}."
    r = openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=70,
    )
    return r.choices[0].message.content.strip()

def save_post(platform, caption, image, link):
    if not DATABASE_URL: return
    conn = get_db()
    cur = conn.cursor()
    cur.execute("INSERT INTO posts (platform, caption, image_url, affiliate_link) VALUES (%s,%s,%s,%s)",
                (platform, caption, image, link))
    conn.commit()
    cur.close(); conn.close()

def fetch_awin():
    try:
        url = f"https://api.awin.com/publishers/{AWIN_PUBLISHER_ID}/adverts"
        headers = {"Authorization": f"Bearer {os.getenv('AWIN_ACCESS_TOKEN','')}"}
        r = requests.get(url, headers=headers, timeout=30)
        if r.status_code == 200:
            print("[AWIN] offers ✅"); return r.json()
        print("[AWIN] fail", r.text)
    except Exception as e: print("[AWIN]", e)
    return []

def fetch_rakuten():
    try:
        url = f"https://api.rakutenmarketing.com/productsearch/1.0?scopeid={RAKUTEN_SCOPE_ID}"
        headers = {"Authorization": f"Bearer {os.getenv('RAKUTEN_ACCESS_TOKEN','')}"}
        r = requests.get(url, headers=headers, timeout=30)
        if r.status_code == 200:
            print("[Rakuten] offers ✅"); return r.json()
        print("[Rakuten] fail", r.text)
    except Exception as e: print("[Rakuten]", e)
    return []

def send_publer(platform, caption, image):
    try:
        url = "https://api.publer.io/v1/posts"
        headers = {"Authorization": f"Bearer {PUBLER_API_KEY}", "Content-Type": "application/json"}
        payload = {"user_id": PUBLER_USER_ID, "content": caption, "media": [image], "accounts": [platform]}
        r = requests.post(url, json=payload, headers=headers, timeout=30)
        if r.status_code == 200:
            print(f"[Publer] {platform} ✅")
        else: print("[Publer] fail", r.text)
    except Exception as e: print("[Publer]", e)

def post_cycle():
    print(f"[cycle] {datetime.utcnow().isoformat()}")
    for offer in fetch_awin()[:1]:
        name = offer.get("name","AWIN Product")
        link = offer.get("clickThroughUrl","#")
        image = offer.get("logo","")
        cap = ai_caption(name,"AWIN")
        send_publer("facebook",cap,image)
        save_post("facebook",cap,image,link)

scheduler = BackgroundScheduler()
scheduler.add_job(post_cycle, "interval", hours=4)
scheduler.start()

@app.route("/")
def home():
    if "user" not in session: return redirect("/login")
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT * FROM posts ORDER BY timestamp DESC LIMIT 10"); posts = cur.fetchall()
    cur.execute("SELECT * FROM analytics ORDER BY timestamp DESC LIMIT 10"); analytics = cur.fetchall()
    cur.close(); conn.close()
    html = """
    <html><head>
    <title>SlickOfficials HQ Hub</title>
    <style>
    body{font-family:Inter,Arial;background:#0e0e10;color:#fafafa;margin:0}
    header{padding:20px;background:#121212;text-align:center;font-size:24px;font-weight:700}
    .grid{display:grid;grid-template-columns:1fr 1fr;gap:20px;padding:20px}
    .card{background:#1b1b1e;border-radius:16px;padding:20px;box-shadow:0 0 10px #0003}
    .caption{font-size:14px;margin:10px 0}
    a{color:#00acee}
    </style></head><body>
    <header>⚡ SlickOfficials HQ Control Hub</header>
    <div class='grid'>
      <div class='card'><h3>Recent Posts</h3>
        {% for p in posts %}
          <div class='caption'>📣 {{p.platform}} – {{p.caption[:60]}}... <a href='{{p.affiliate_link}}'>link</a></div>
        {% endfor %}
      </div>
      <div class='card'><h3>Analytics Snapshot</h3>
        {% for a in analytics %}
          <div>📊 {{a.platform}} | clicks {{a.clicks}} | eng. {{a.engagement_rate}}%</div>
        {% endfor %}
      </div>
    </div>
    <center><a href='/logout'>Logout</a></center>
    </body></html>
    """
    return render_template_string(html, posts=posts, analytics=analytics)

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method=="POST":
        if request.form["username"]==APP_USERNAME and request.form["password"]==APP_PASSWORD:
            session["user"]=APP_USERNAME; return redirect("/")
        return "Invalid credentials"
    return """<form method='POST' style='margin:100px auto;width:300px;text-align:center'>
    <h3>HQ Login</h3>
    <input name='username' placeholder='Username'><br><br>
    <input name='password' type='password' placeholder='Password'><br><br>
    <button type='submit'>Enter</button></form>"""

@app.route("/logout")
def logout():
    session.pop("user",None)
    return redirect("/login")

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",5000)))
