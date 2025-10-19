# app.py
from flask import Flask, render_template, jsonify, request
import os, pandas as pd
from datetime import datetime
from affiliates.awin import poll_awin_approvals
from affiliates.rakuten import poll_rakuten_approvals

app = Flask(__name__)

POSTS_FILE = os.getenv("POSTS_FILE", "data/posts.csv")

def safe_load_csv(path, default_columns=None):
    import os
    if not os.path.exists(os.path.dirname(path)) and os.path.dirname(path) != "":
        os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        if default_columns:
            pd.DataFrame(columns=default_columns).to_csv(path, index=False)
        else:
            pd.DataFrame().to_csv(path, index=False)
    try:
        return pd.read_csv(path)
    except Exception as e:
        print(f"[App] Error reading {path}: {e}")
        return pd.DataFrame()

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/dashboard")
def dashboard():
    df = safe_load_csv(POSTS_FILE, default_columns=["post_text","platform","link","image_url"])
    config = safe_load_csv("config.yaml") if False else {}
    return render_template("dashboard.html", posts=df.to_dict(orient="records"), config={})

@app.route("/manual_reload", methods=["POST"])
def manual_reload():
    """
    Manually poll Awin & Rakuten and append new posts immediately.
    """
    awin = poll_awin_approvals()
    rakuten = poll_rakuten_approvals()
    from auto_scheduler import append_new_posts
    added = append_new_posts(awin + rakuten)
    return jsonify({"status": "ok", "added": added}), 200

@app.route("/health")
def health():
    return jsonify({"status": "ok", "checked_at": datetime.utcnow().isoformat() + "Z"}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
