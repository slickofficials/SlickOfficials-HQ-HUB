from flask import Flask, render_template, jsonify
import os, yaml, random, pandas as pd
from affiliates.awin import poll_awin_approvals
from affiliates.rakuten import poll_rakuten_approvals
from poster.publer_poster import post_content

app = Flask(__name__)

# Load config
with open("config.yaml", "r") as f:
    config = yaml.safe_load(f)

# Load posts and templates
def load_data():
    try:
        posts_df = pd.read_csv("data/posts.csv")
        posts = posts_df.to_dict("records")
    except Exception:
        posts = []
    try:
        templates_df = pd.read_csv("data/templates.csv")
        templates = templates_df.to_dict("records")
    except Exception:
        templates = []
    random.shuffle(posts)
    return posts, templates

posts, templates = load_data()

def save_posts():
    pd.DataFrame(posts).to_csv("data/posts.csv", index=False)

def check_approvals():
    """Poll affiliates for new approvals and append generated posts."""
    new_posts = []
    try:
        new_posts.extend(poll_awin_approvals(templates))
    except Exception as e:
        print(f"Awin poll error: {e}")
    try:
        new_posts.extend(poll_rakuten_approvals(templates))
    except Exception as e:
        print(f"Rakuten poll error: {e}")
    if new_posts:
        posts.extend(new_posts)
        save_posts()
    return new_posts

def post_batch():
    """Post a batch (up to 10 posts) to Publer via poster.publer_poster.post_content."""
    try:
        post_content(posts, templates)
        save_posts()
        return True
    except Exception as e:
        print(f"Posting error: {e}")
        return False

@app.route('/')
def health():
    return "SlickOfficials bot is live! Use /run/<token> and /post/<token> for cron triggers."

@app.route('/links')
def links():
    return jsonify({"offers": [p for p in posts if p.get("link")]})

@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html', posts=posts[:10], config=config)

@app.route('/run/<token>')
def run(token):
    if token != os.getenv("MANUAL_RUN_TOKEN"):
        return ("Invalid token!", 403)
    new = check_approvals()
    return {"added": len(new)}

@app.route('/post/<token>')
def post_now(token):
    if token != os.getenv("MANUAL_RUN_TOKEN"):
        return ("Invalid token!", 403)
    ok = post_batch()
    return ({"posted": ok})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv("PORT", 5000)))
