from flask import Flask, render_template, jsonify, request
import os
import pandas as pd
import yaml
import requests

# Initialize Flask
app = Flask(__name__)

# ---------------------------------------------------------
# Load configuration
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
        templates_df = pd.read_csv("data/templates.csv")

        # Convert any datetime/timedelta to string for JSON safety
        posts_df = posts_df.applymap(lambda x: str(x) if isinstance(x, (pd.Timestamp, pd.Timedelta)) else x)
        templates_df = templates_df.applymap(lambda x: str(x) if isinstance(x, (pd.Timestamp, pd.Timedelta)) else x)

        config = load_config()

        return render_template(
            "dashboard.html",
            posts=posts_df.to_dict(orient="records"),
            templates=templates_df.to_dict(orient="records"),
            config=config
        )
    except Exception as e:
        return f"Error loading dashboard: {e}", 500

# ---------------------------------------------------------
# Publer API: Test connection
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
# Publer API: Test post
# ---------------------------------------------------------
@app.route("/test_post", methods=["POST"])
def test_post():
    api_key = os.getenv("PUBLER_API_KEY")
    account_id = os.getenv("PUBLER_ACCOUNT_ID")

    if not api_key or not account_id:
        return jsonify({"status": "error", "message": "Missing PUBLER_API_KEY or PUBLER_ACCOUNT_ID"}), 400

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "accounts": [account_id],
        "content": {
            "text": "🚀 Test post from SlickOfficials Auto HQ — connected via Publer API!"
        }
    }

    url = "https://api.publer.io/v1/posts"
    res = requests.post(url, headers=headers, json=payload)

    if res.status_code == 201:
        return jsonify({
            "status": "success",
            "post": res.json()
        }), 201
    else:
        return jsonify({
            "status": "error",
            "response": res.text
        }), res.status_code

# ---------------------------------------------------------
# Health Check (for Render)
# ---------------------------------------------------------
@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200

# ---------------------------------------------------------
# Run the app
# ---------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
