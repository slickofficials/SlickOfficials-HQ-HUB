from flask import Flask, render_template, jsonify, request
import os
import pandas as pd
import yaml
import requests
import random
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize Flask
app = Flask(__name__)

# ---------------------------------------------------------
# Load configuration (optional)
# ---------------------------------------------------------
def load_config():
    try:
        with open("config.yaml", "r") as file:
            config = yaml.safe_load(file)
        return config
    except Exception as e:
        print(f"Error loading config.yaml: {e}")
        return {}

# ---------------------------------------------------------
# Routes
# ---------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/dashboard")
def dashboard():
    try:
        posts_df = pd.read_csv("data/posts.csv")
        config = load_config()
        return render_template(
            "dashboard.html",
            posts=posts_df.to_dict(orient="records"),
            config=config
        )
    except Exception as e:
        return f"Error loading dashboard: {e}", 500

# ---------------------------------------------------------
# Test Publer connection
# ---------------------------------------------------------
@app.route("/test_publer", methods=["GET"])
def test_publer():
    api_key = os.getenv("PUBLER_API_KEY")
    account_id = os.getenv("PUBLER_ACCOUNT_ID")

    if not api_key:
        return jsonify({"status": "error", "message": "PUBLER_API_KEY not found in environment"}), 400

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    url = "https://api.publer.io/v1/accounts"
    res = requests.get(url, headers=headers)

    if res.status_code == 200:
        return jsonify({
            "status": "success",
            "accounts": res.json(),
            "current_account_id": account_id
        }), 200
    else:
        return jsonify({
            "status": "error",
            "response": res.text
        }), res.status_code

# ---------------------------------------------------------
# Auto Post Affiliate Links to Publer
# ---------------------------------------------------------
@app.route("/auto_post", methods=["POST"])
def auto_post():
    api_key = os.getenv("PUBLER_API_KEY")
    account_id = os.getenv("PUBLER_ACCOUNT_ID")

    if not api_key or not account_id:
        return jsonify({"status": "error", "message": "Missing PUBLER_API_KEY or PUBLER_ACCOUNT_ID"}), 400

    # Load affiliate posts
    try:
        df = pd.read_csv("data/posts.csv")  # must have 'post_text' and 'deep_link' columns
    except Exception as e:
        return jsonify({"status": "error", "message": f"Error loading posts.csv: {e}"}), 500

    if df.empty:
        return jsonify({"status": "error", "message": "posts.csv is empty"}), 400

    # Choose a random post
    post = df.sample(1).iloc[0]
    caption = f"{post['post_text']}\n\n👉 {post['deep_link']}"

    # Prepare Publer payload
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "accounts": [account_id],
        "content": {
            "text": caption
        }
    }

    res = requests.post("https://api.publer.io/v1/posts", headers=headers, json=payload)

    if res.status_code == 201:
        return jsonify({
            "status": "success",
            "posted": caption,
            "response": res.json()
        }), 201
    else:
        return jsonify({
            "status": "error",
            "response": res.text
        }), res.status_code

# ---------------------------------------------------------
# Run Flask with Gunicorn
# ---------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
