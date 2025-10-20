from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import requests, os

app = Flask(__name__)
app.secret_key = "supersecretkey"

# Database config
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("DATABASE_URL", "sqlite:///slickhq.db")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(100), nullable=False)

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# Initialize DB
with app.app_context():
    db.create_all()

# ----------------- AUTH -----------------
@app.route('/')
def home():
    if 'user' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username'], password=request.form['password']).first()
        if user:
            session['user'] = user.username
            return redirect(url_for('dashboard'))
        else:
            return render_template('login.html', error="Invalid login credentials")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('user', None)
    return redirect(url_for('login'))

# ----------------- DASHBOARD -----------------
@app.route('/dashboard')
def dashboard():
    if 'user' not in session:
        return redirect(url_for('login'))
    posts = Post.query.order_by(Post.created_at.desc()).all()
    return render_template('dashboard.html', posts=posts)

# ----------------- CREATE POST -----------------
@app.route('/create_post', methods=['GET', 'POST'])
def create_post():
    if 'user' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        content = request.form['content']
        new_post = Post(content=content)
        db.session.add(new_post)
        db.session.commit()
        return redirect(url_for('dashboard'))

    return render_template('create_post.html')

# ----------------- PUBLER TEST -----------------
@app.route('/test_publer')
def test_publer():
    headers = {"Authorization": f"Bearer {os.getenv('PUBLER_API_KEY', '')}"}
    try:
        response = requests.get("https://api.publer.io/v1/me", headers=headers, timeout=5)
        data = response.json()
        return jsonify(data)
    except Exception as e:
        return jsonify({"status": "error", "message": "Publer API not reachable from Render, but your app is fine."})

# ----------------- RECENT POSTS API -----------------
@app.route('/get_recent_posts')
def get_recent_posts():
    posts = Post.query.order_by(Post.created_at.desc()).limit(5).all()
    return jsonify([{"id": p.id, "content": p.content, "created_at": p.created_at.isoformat()} for p in posts])

# ----------------- RUN -----------------
if __name__ == '__main__':
    app.run(debug=True)
