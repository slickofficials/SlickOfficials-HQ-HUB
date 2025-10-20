from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from dotenv import load_dotenv
import os
import requests

# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "supersecretkey")

# Database setup
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///dashboard.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# User credentials (from environment)
APP_USERNAME = os.getenv("APP_USERNAME", "admin")
APP_PASSWORD = os.getenv("APP_PASSWORD", "12345")

# Publer credentials
PUBLER_API_KEY = os.getenv("PUBLER_API_KEY")
PUBLER_WORKSPACE_ID = os.getenv("PUBLER_WORKSPACE_ID")
PUBLER_USER_ID = os.getenv("PUBLER_USER_ID")

# ------------------ DATABASE MODEL ------------------
class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    platform = db.Column(db.String(50))
    content = db.Column(db.Text)
    status = db.Column(db.String(20))
    publer_id = db.Column(db.String(100))

with app.app_context():
    db.create_all()

# ------------------ ROUTES ------------------

@app.route('/')
def home():
    if 'logged_in' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

# LOGIN
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if username == APP_USERNAME and password == APP_PASSWORD:
            session['logged_in'] = True
            return redirect(url_for('dashboard'))
        else:
            flash("Invalid username or password", "error")
            return render_template('login.html')
    return render_template('login.html')

# LOGOUT
@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

# DASHBOARD
@app.route('/dashboard')
def dashboard():
    if 'logged_in' not in session:
        return redirect(url_for('login'))
    posts = Post.query.all()
    return render_template('dashboard.html', posts=posts)

# CREATE POST
@app.route('/create_post', methods=['GET', 'POST'])
def create_post():
    if 'logged_in' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        platform = request.form.get('platform')
        content = request.form.get('content')

        headers = {
            "Authorization": f"Bearer {PUBLER_API_KEY}",
            "Content-Type": "application/json"
        }

        data = {
            "workspace_id": PUBLER_WORKSPACE_ID,
            "user_id": PUBLER_USER_ID,
            "accounts": [platform],
            "content": {
                "text": content
            }
        }

        response = requests.post(
            "https://api.publer.io/v1/posts",
            json=data,
            headers=headers
        )

        if response.status_code in [200, 201]:
            resp_data = response.json()
            publer_id = resp_data.get("data", {}).get("id", "unknown")
            new_post = Post(platform=platform, content=content, status="posted", publer_id=publer_id)
            db.session.add(new_post)
            db.session.commit()
            flash("Post published successfully!", "success")
        else:
            flash(f"Publer Error: {response.text}", "error")

        return redirect(url_for('dashboard'))

    return render_template('create_post.html')

# TEST PUBLER CONNECTION
@app.route('/test_publer')
def test_publer():
    headers = {
        "Authorization": f"Bearer {PUBLER_API_KEY}"
    }
    response = requests.get("https://api.publer.io/v1/me", headers=headers)
    if response.status_code == 200:
        return jsonify({"status": "success", "data": response.json()})
    return jsonify({"status": "failed", "response": response.text}), response.status_code

# ------------------ RUN APP ------------------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
