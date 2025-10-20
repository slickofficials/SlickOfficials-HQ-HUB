from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from flask_sqlalchemy import SQLAlchemy
import os
import requests
from datetime import datetime

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.getenv("APP_SECRET_KEY", "change_me")

# Database config
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///data.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# ====== MODELS ======
class Analytics(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    clicks = db.Column(db.Integer)
    conversions = db.Column(db.Integer)
    revenue = db.Column(db.Float)
    date = db.Column(db.String(50))

    def to_dict(self):
        return {
            "id": self.id,
            "clicks": self.clicks,
            "conversions": self.conversions,
            "revenue": self.revenue,
            "date": self.date,
        }

with app.app_context():
    db.create_all()

# ====== ENV VARIABLES ======
PUBLER_API_KEY = os.getenv("PUBLER_API_KEY")
PUBLER_WORKSPACE_ID = os.getenv("PUBLER_WORKSPACE_ID")
PUBLER_USER_ID = os.getenv("PUBLER_USER_ID")

# ====== ROUTES ======
@app.route("/")
def home():
    if "user" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username == os.getenv("ADMIN_USER") and password == os.getenv("ADMIN_PASS"):
            session["user"] = username
            return redirect(url_for("dashboard"))
        return render_template("login.html", error="Invalid credentials.")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("login"))

@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))
    return render_template("dashboard.html")

# ====== TEST PUBLER ======
@app.route("/test-publer")
def test_publer():
    if not PUBLER_API_KEY or not PUBLER_WORKSPACE_ID:
        return jsonify({"error": "Missing Publer credentials in .env"}), 400

    url = f"https://api.publer.io/v1/workspaces/{PUBLER_WORKSPACE_ID}/users"
    headers = {"Authorization": f"Bearer {PUBLER_API_KEY}"}

    try:
        response = requests.get(url, headers=headers, timeout=10)
        return jsonify(response.json())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ====== RECENT POSTS ======
@app.route("/recent-posts")
def recent_posts():
    if not PUBLER_API_KEY or not PUBLER_WORKSPACE_ID:
        return jsonify({"error": "Missing Publer credentials"}), 400

    url = f"https://api.publer.io/v1/workspaces/{PUBLER_WORKSPACE_ID}/posts"
    headers = {"Authorization": f"Bearer {PUBLER_API_KEY}"}

    try:
        response = requests.get(url, headers=headers, timeout=10)
        data = response.json()
        posts = data.get("data", [])[:5]
        return jsonify(posts)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ====== ANALYTICS (DB STORAGE) ======
@app.route("/get-analytics")
def get_analytics():
    try:
        records = Analytics.query.order_by(Analytics.id.desc()).limit(10).all()
        return jsonify([r.to_dict() for r in records])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/save-analytics", methods=["POST"])
def save_analytics():
    try:
        data = request.get_json()
        new_record = Analytics(
            clicks=data.get("clicks", 0),
            conversions=data.get("conversions", 0),
            revenue=data.get("revenue", 0.0),
            date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        db.session.add(new_record)
        db.session.commit()
        return jsonify({"message": "Analytics saved."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ====== LEGAL NOTICE ======
@app.route("/legal")
def legal():
    return """
    <h2>🔒 Legal & Ownership</h2>
    <p>All trademarks, digital systems, and integrations under the
    <strong>Slickofficials HQ</strong> brand are proprietary to
    <strong>Amson Multi Global Ltd</strong>.</p>
    <p>© 2025 Slickofficials HQ | All Rights Reserved.</p>
    """

# ====== MAIN ======
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
