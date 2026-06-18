from flask import Flask, render_template, request, jsonify, session, Response, make_response, redirect, url_for, flash
import json, os, sqlite3, re, subprocess, sys, tempfile, threading, io, hashlib, secrets, datetime
from functools import wraps
import requests
from dotenv import load_dotenv

# Always resolve paths relative to this file's location
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)  # ensure working directory is always pylab-ai/

# Load environment variables
load_dotenv(os.path.join(BASE_DIR, ".env"))

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "pylab_ai_secret_2024")

DB_PATH = os.path.join(BASE_DIR, "database.db")

def get_db():
    """Get a database connection with timeout to avoid lock errors."""
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    return conn

# â”€â”€ Gemini AI setup (optional â€” works without key, falls back to smart mock) â”€
try:
    import google.generativeai as genai
    _GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "")
    if _GEMINI_KEY:
        genai.configure(api_key=_GEMINI_KEY)
        _gemini_model = genai.GenerativeModel("gemini-1.5-flash")
        GEMINI_AVAILABLE = True
    else:
        GEMINI_AVAILABLE = False
except ImportError:
    GEMINI_AVAILABLE = False

def call_gemini(prompt: str) -> str:
    """Call Gemini API; returns None on failure so caller can fall back."""
    if not GEMINI_AVAILABLE:
        return None
    try:
        response = _gemini_model.generate_content(prompt)
        return response.text
    except Exception as e:
        return None


def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS progress (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        topic TEXT,
        completed INTEGER DEFAULT 0,
        score INTEGER DEFAULT 0
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS bookmarks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        question_id TEXT,
        question_text TEXT
    )''')
    # Dashboard â€” projects completed by a user
    c.execute('''CREATE TABLE IF NOT EXISTS projects_done (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        project_slug TEXT,
        project_title TEXT,
        completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    # Streak / XP tracking â€” created once here, not inside route functions
    c.execute('''CREATE TABLE IF NOT EXISTS streaks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        date TEXT,
        xp INTEGER DEFAULT 0,
        problems_solved INTEGER DEFAULT 0
    )''')
    # Users â€” for login/register
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        salt TEXT NOT NULL,
        display_name TEXT DEFAULT NULL,
        bio TEXT DEFAULT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    # Add new columns to existing DBs without breaking them
    for col, definition in [("display_name", "TEXT DEFAULT NULL"), ("bio", "TEXT DEFAULT NULL")]:
        try:
            c.execute(f"ALTER TABLE users ADD COLUMN {col} {definition}")
        except Exception:
            pass
    conn.commit()
    conn.close()

init_db()

# ── Supabase Integration & Configuration ──
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
GOOGLE_SCRIPT_URL = os.environ.get("GOOGLE_SCRIPT_URL", "")
SUPABASE_CONFIGURED = bool(SUPABASE_URL and SUPABASE_KEY and not SUPABASE_URL.startswith("https://your-project"))

def get_supabase_headers():
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }

def get_supabase_user(identifier):
    """Query user by username or email in Supabase."""
    if not SUPABASE_CONFIGURED:
        return None
    import urllib.parse
    quoted_id = urllib.parse.quote(identifier)
    url = f"{SUPABASE_URL}/rest/v1/users?or=(username.eq.{quoted_id},email.eq.{quoted_id})"
    headers = get_supabase_headers()
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            users = response.json()
            return users[0] if users else None
        print(f"Supabase GET user response: {response.status_code} - {response.text}")
        return None
    except Exception as e:
        print(f"Supabase GET user connection error: {e}")
        return None

def update_supabase_password(username, password_hash, salt):
    """Update password in Supabase for user reset/change."""
    if not SUPABASE_CONFIGURED:
        return False
    url = f"{SUPABASE_URL}/rest/v1/users?username=eq.{username}"
    headers = get_supabase_headers()
    data = {
        "password_hash": password_hash,
        "salt": salt
    }
    try:
        response = requests.patch(url, headers=headers, json=data, timeout=10)
        return response.status_code in [200, 204]
    except Exception as e:
        print(f"Failed to update Supabase password: {e}")
        return False

def update_supabase_profile(username, email, display_name, bio):
    """Update profile data in Supabase users table."""
    if not SUPABASE_CONFIGURED:
        return False
    url = f"{SUPABASE_URL}/rest/v1/users?username=eq.{username}"
    headers = get_supabase_headers()
    data = {
        "email": email,
        "display_name": display_name,
        "bio": bio
    }
    try:
        response = requests.patch(url, headers=headers, json=data, timeout=10)
        return response.status_code in [200, 204]
    except Exception as e:
        print(f"Failed to update Supabase profile: {e}")
        return False

def delete_supabase_user(username):
    """Delete a user account in Supabase users table."""
    if not SUPABASE_CONFIGURED:
        return False
    url = f"{SUPABASE_URL}/rest/v1/users?username=eq.{username}"
    headers = get_supabase_headers()
    try:
        response = requests.delete(url, headers=headers, timeout=10)
        return response.status_code in [200, 204]
    except Exception as e:
        print(f"Failed to delete user from Supabase: {e}")
        return False

def insert_supabase_user(username, email, password_hash, salt, display_name=None, bio=None):
    """Insert a new user record into Supabase."""
    if not SUPABASE_CONFIGURED:
        return None
    url = f"{SUPABASE_URL}/rest/v1/users"
    headers = get_supabase_headers()
    data = {
        "username": username,
        "email": email,
        "password_hash": password_hash,
        "salt": salt,
        "display_name": display_name,
        "bio": bio
    }
    try:
        response = requests.post(url, headers=headers, json=data, timeout=10)
        if response.status_code in [200, 201]:
            users = response.json()
            return users[0] if users else data
        print(f"Supabase POST user response: {response.status_code} - {response.text}")
        return None
    except Exception as e:
        print(f"Supabase POST user connection error: {e}")
        return None

def supabase_log_activity(username, email, action, timestamp):
    """Log an activity to Supabase activity_logs table."""
    if not SUPABASE_CONFIGURED:
        return False
    url = f"{SUPABASE_URL}/rest/v1/activity_logs"
    headers = get_supabase_headers()
    data = {
        "username": username,
        "email": email,
        "action": action,
        "timestamp": timestamp
    }
    try:
        response = requests.post(url, headers=headers, json=data, timeout=10)
        return response.status_code in [200, 201]
    except Exception as e:
        print(f"Failed to log activity to Supabase: {e}")
        return False

def send_to_google_sheet_webhook(username, email, action, timestamp):
    """POST log to Google Apps Script webhook to append to Google Sheets."""
    if not GOOGLE_SCRIPT_URL or GOOGLE_SCRIPT_URL.startswith("https://script.google.com/macros/s/your-script"):
        print("GOOGLE_SCRIPT_URL not configured. Skipping Google Sheet append.")
        return False
    data = {
        "username": username,
        "email": email,
        "action": action,
        "timestamp": timestamp
    }
    try:
        response = requests.post(GOOGLE_SCRIPT_URL, json=data, timeout=15)
        return response.status_code == 200
    except Exception as e:
        print(f"Failed to trigger Google Sheet webhook: {e}")
        return False

def sync_user_to_sqlite(username, email, password_hash, salt, display_name=None, bio=None):
    """Sync user details to local SQLite DB so local features (streaks, progress) don't break."""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT id FROM users WHERE username=?", (username,))
        row = c.fetchone()
        if row:
            uid = row[0]
            c.execute("UPDATE users SET email=?, password_hash=?, salt=?, display_name=?, bio=? WHERE id=?",
                      (email, password_hash, salt, display_name, bio, uid))
        else:
            c.execute("INSERT INTO users (username, email, password_hash, salt, display_name, bio) VALUES (?,?,?,?,?,?)",
                      (username, email, password_hash, salt, display_name, bio))
            uid = c.lastrowid
        conn.commit()
        conn.close()
        return uid
    except Exception as e:
        print(f"Failed to sync user to SQLite: {e}")
        return 9999

def process_activity_log(payload):
    """Sync activity logs asynchronously: post to Supabase and Apps Script."""
    username = payload.get("username")
    email = payload.get("email")
    action = payload.get("action")
    timestamp = payload.get("timestamp") or datetime.datetime.utcnow().isoformat() + "Z"
    
    if not username or not email or not action:
        return False
        
    # 1. Log to Supabase
    if SUPABASE_CONFIGURED:
        supabase_log_activity(username, email, action, timestamp)
        
    # 2. Log to Google Sheet
    send_to_google_sheet_webhook(username, email, action, timestamp)
    return True

def trigger_webhook_activity(username, email, action):
    """Triggers event log in a non-blocking background thread."""
    payload = {
        "username": username,
        "email": email,
        "action": action,
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z"
    }
    threading.Thread(target=process_activity_log, args=(payload,), daemon=True).start()

# ── Auth helpers ──

def hash_password(password: str, salt: str) -> str:
    return hashlib.sha256((salt + password).encode()).hexdigest()

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        uid = session.get("user_id")
        if not uid or uid == "guest":
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return decorated

# â”€â”€ Routes â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.route("/")
def home():
    if not session.get("user_id"):
        return redirect(url_for("login"))
    return render_template("index.html")

# â”€â”€ Auth Routes â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id") and session.get("user_id") != "guest":
        return redirect(url_for("home"))
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        
        # 1. Attempt Supabase Authentication
        if SUPABASE_CONFIGURED:
            user = get_supabase_user(username)
            if user and user.get("password_hash") == hash_password(password, user.get("salt")):
                uid = sync_user_to_sqlite(
                    user["username"], 
                    user["email"], 
                    user["password_hash"], 
                    user["salt"], 
                    user.get("display_name"), 
                    user.get("bio")
                )
                session["user_id"] = user["username"]
                session["uid"] = uid
                trigger_webhook_activity(user["username"], user["email"], "login")
                next_url = request.args.get("next", url_for("home"))
                return redirect(next_url)
            else:
                error = "Invalid username or password."
        else:
            # Local SQLite fallback
            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT id, username, password_hash, salt, email FROM users WHERE username=? OR email=?",
                      (username, username))
            user = c.fetchone()
            conn.close()
            if user and user[2] == hash_password(password, user[3]):
                session["user_id"] = user[1]
                session["uid"] = user[0]
                trigger_webhook_activity(user[1], user[4], "login")
                next_url = request.args.get("next", url_for("home"))
                return redirect(next_url)
            error = "Invalid username or password."
            
    return render_template("login.html", error=error)

@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id") and session.get("user_id") != "guest":
        return redirect(url_for("home"))
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm  = request.form.get("confirm", "")
        if len(username) < 3:
            error = "Username must be at least 3 characters."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        elif password != confirm:
            error = "Passwords do not match."
        else:
            salt = secrets.token_hex(16)
            pw_hash = hash_password(password, salt)
            
            # 1. Register with Supabase if configured
            if SUPABASE_CONFIGURED:
                existing_user = get_supabase_user(username) or get_supabase_user(email)
                if existing_user:
                    error = "Username or email already taken."
                else:
                    new_user = insert_supabase_user(username, email, pw_hash, salt)
                    if new_user:
                        uid = sync_user_to_sqlite(username, email, pw_hash, salt)
                        session["user_id"] = username
                        session["uid"] = uid
                        trigger_webhook_activity(username, email, "signup")
                        flash("Account created successfully! Welcome to PyLab AI 🎉", "success")
                        return redirect(url_for("dashboard"))
                    else:
                        error = "Database error creating user. Please try again."
            else:
                # Local SQLite Register fallback
                try:
                    conn = get_db()
                    c = conn.cursor()
                    c.execute("INSERT INTO users (username, email, password_hash, salt) VALUES (?,?,?,?)",
                              (username, email, pw_hash, salt))
                    conn.commit()
                    new_uid = c.lastrowid
                    conn.close()
                    session["user_id"] = username
                    session["uid"] = new_uid
                    trigger_webhook_activity(username, email, "signup")
                    flash("Account created successfully! Welcome to PyLab AI 🎉", "success")
                    return redirect(url_for("dashboard"))
                except sqlite3.IntegrityError:
                    error = "Username or email already taken."
    return render_template("login.html", mode="register", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if session.get("user_id") and session.get("user_id") != "guest":
        return redirect(url_for("home"))
    error = None
    success = None
    if request.method == "POST":
        identifier = request.form.get("identifier", "").strip()
        new_password = request.form.get("new_password", "")
        confirm = request.form.get("confirm", "")
        if len(new_password) < 6:
            error = "Password must be at least 6 characters."
        elif new_password != confirm:
            error = "Passwords do not match."
        else:
            if SUPABASE_CONFIGURED:
                user = get_supabase_user(identifier)
                if not user:
                    error = "No account found with that username or email."
                else:
                    new_salt = secrets.token_hex(16)
                    new_hash = hash_password(new_password, new_salt)
                    if update_supabase_password(user["username"], new_hash, new_salt):
                        sync_user_to_sqlite(user["username"], user["email"], new_hash, new_salt, user.get("display_name"), user.get("bio"))
                        success = "Password reset! You can now log in."
                    else:
                        error = "Failed to update password in database. Please try again."
            else:
                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT id, username, email FROM users WHERE username=? OR email=?",
                          (identifier, identifier.lower()))
                user = c.fetchone()
                if not user:
                    error = "No account found with that username or email."
                else:
                    new_salt = secrets.token_hex(16)
                    new_hash = hash_password(new_password, new_salt)
                    c.execute("UPDATE users SET password_hash=?, salt=? WHERE id=?",
                              (new_hash, new_salt, user[0]))
                    conn.commit()
                    success = "Password reset! You can now log in."
                conn.close()
    return render_template("login.html", mode="forgot", error=error, success=success)


@app.route("/guest")
def guest():
    """Let users browse without an account â€” sets a guest session."""
    session["user_id"] = "guest"
    return redirect(url_for("home"))

@app.route("/profile")
def profile():
    user_id = session.get("user_id", "guest")
    if user_id == "guest":
        return redirect(url_for("login"))
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT username, email, created_at, display_name, bio FROM users WHERE username=?", (user_id,))
    user = c.fetchone()
    c.execute("SELECT COUNT(*) FROM progress WHERE user_id=? AND completed=1", (user_id,))
    topics_count = c.fetchone()[0] or 0
    c.execute("SELECT COUNT(*) FROM projects_done WHERE user_id=?", (user_id,))
    projects_count = c.fetchone()[0] or 0
    c.execute("SELECT SUM(xp) FROM streaks WHERE user_id=?", (user_id,))
    total_xp = c.fetchone()[0] or 0
    from datetime import date, timedelta
    c.execute("SELECT date FROM streaks WHERE user_id=? ORDER BY date DESC", (user_id,))
    dates = [r[0] for r in c.fetchall()]
    streak = 0
    check = date.today()
    for d in dates:
        if d == check.isoformat():
            streak += 1
            check -= timedelta(days=1)
        else:
            break
    conn.close()
    return render_template("profile.html",
        username=user[0] if user else user_id,
        email=user[1] if user else "",
        joined=user[2][:10] if user and user[2] else "â€”",
        display_name=user[3] if user and user[3] else (user[0] if user else user_id),
        bio=user[4] if user and user[4] else "",
        topics_count=topics_count,
        projects_count=projects_count,
        total_xp=total_xp,
        streak=streak,
        msg=request.args.get("msg"),
        msg_type=request.args.get("msg_type", "success"),
        active_panel=request.args.get("panel","stats")
    )

@app.route("/profile/update", methods=["POST"])
def profile_update():
    user_id = session.get("user_id")
    if not user_id or user_id == "guest":
        return redirect(url_for("login"))
    email        = request.form.get("email", "").strip().lower()
    display_name = request.form.get("display_name", "").strip()
    bio          = request.form.get("bio", "").strip()
    if not email:
        return redirect(url_for("profile", msg="Email cannot be empty.", msg_type="error", panel="account"))
    if len(bio) > 300:
        return redirect(url_for("profile", msg="Bio must be under 300 characters.", msg_type="error", panel="account"))
    
    # 1. Update Supabase if configured
    if SUPABASE_CONFIGURED:
        other_user = get_supabase_user(email)
        if other_user and other_user["username"] != user_id:
            return redirect(url_for("profile", msg="That email is already taken.", msg_type="error", panel="account"))
        update_supabase_profile(user_id, email, display_name or None, bio or None)
        
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("UPDATE users SET email=?, display_name=?, bio=? WHERE username=?",
                  (email, display_name or None, bio or None, user_id))
        conn.commit()
        conn.close()
        return redirect(url_for("profile", msg="Profile updated successfully! ✅", panel="account"))
    except sqlite3.IntegrityError:
        return redirect(url_for("profile", msg="That email is already taken.", msg_type="error", panel="account"))

@app.route("/profile/change-password", methods=["POST"])
def change_password():
    user_id = session.get("user_id")
    if not user_id or user_id == "guest":
        return redirect(url_for("login"))
    current = request.form.get("current_password", "")
    new_pw  = request.form.get("new_password", "")
    confirm = request.form.get("confirm_password", "")
    if len(new_pw) < 6:
        return redirect(url_for("profile", msg="New password must be at least 6 characters.", msg_type="error", panel="password"))
    if new_pw != confirm:
        return redirect(url_for("profile", msg="New passwords do not match.", msg_type="error", panel="password"))
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT password_hash, salt FROM users WHERE username=?", (user_id,))
    row = c.fetchone()
    if not row or row[0] != hash_password(current, row[1]):
        conn.close()
        return redirect(url_for("profile", msg="Current password is incorrect.", msg_type="error", panel="password"))
    new_salt = secrets.token_hex(16)
    new_hash = hash_password(new_pw, new_salt)
    
    # Update Supabase password if configured
    if SUPABASE_CONFIGURED:
        update_supabase_password(user_id, new_hash, new_salt)
        
    c.execute("UPDATE users SET password_hash=?, salt=? WHERE username=?", (new_hash, new_salt, user_id))
    conn.commit()
    conn.close()
    return redirect(url_for("profile", msg="Password changed successfully! 🔒", panel="password"))

@app.route("/profile/delete-account", methods=["POST"])
def delete_account():
    user_id = session.get("user_id")
    if not user_id or user_id == "guest":
        return redirect(url_for("login"))
    confirm_pw = request.form.get("confirm_delete_password", "")
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT password_hash, salt FROM users WHERE username=?", (user_id,))
    row = c.fetchone()
    if not row or row[0] != hash_password(confirm_pw, row[1]):
        conn.close()
        return redirect(url_for("profile", msg="Incorrect password. Account not deleted.", msg_type="error", panel="danger"))
        
    # Delete from Supabase if configured
    if SUPABASE_CONFIGURED:
        delete_supabase_user(user_id)
        
    # Delete all user data
    for table in ["progress", "bookmarks", "projects_done", "streaks"]:
        c.execute(f"DELETE FROM {table} WHERE user_id=?", (user_id,))
    c.execute("DELETE FROM users WHERE username=?", (user_id,))
    conn.commit()
    conn.close()
    session.clear()
    return redirect(url_for("login") + "?msg=Account+deleted+successfully.")

@app.route("/learn")
def learn():
    return render_template("learn.html")

@app.route("/learn/<topic>")
def topic_detail(topic):
    content = load_topic(topic)
    if not content:
        return render_template("404.html"), 404
    return render_template("topic.html", topic=topic, content=content)

@app.route("/practice")
def practice():
    level = request.args.get("level", "beginner")
    topic = request.args.get("topic", "all")
    problems = load_problems(level, topic)
    return render_template("practice.html", problems=problems, level=level, topic=topic)

@app.route("/ai-mentor")
def ai_mentor():
    return render_template("ai_mentor.html")

@app.route("/games")
def games():
    return render_template("games.html")

@app.route("/libraries")
def libraries():
    return render_template("libraries.html")

@app.route("/roadmap")
def roadmap():
    return render_template("roadmap.html")

@app.route("/editor")
def editor():
    return render_template("editor.html")

@app.route("/visualizer")
def visualizer():
    return render_template("visualizer.html")

@app.route("/api/get-topic-code", methods=["POST"])
def get_topic_code():
    data = request.json or {}
    topic = data.get("topic", "").lower().strip()
    if not topic:
        return jsonify({"code": "# Enter a topic to get sample code"}), 400
    
    # Try local database of explanations first
    topic_data = TOPIC_EXPLANATIONS.get(topic, None)
    if topic_data and "code" in topic_data:
        return jsonify({"code": topic_data["code"]})
        
    # If not found, check aliases
    for key, val in TOPIC_EXPLANATIONS.items():
        if topic in key or key in topic:
            if "code" in val:
                return jsonify({"code": val["code"]})
                
    # Dynamic generation using Gemini if available
    if GEMINI_AVAILABLE:
        prompt = (
            f"You are a Python instructor. Generate a short, clean, beginner-friendly Python code example "
            f"(max 10-15 lines) that clearly demonstrates the concept of '{topic}'. "
            f"Write highly commented code so a student can understand it step by step. "
            f"Output ONLY the raw Python code, without markdown formatting, backticks, or other text."
        )
        generated = call_gemini(prompt)
        if generated:
            # Clean potential backticks if any
            clean_code = re.sub(r"^```python\s*|```$", "", generated.strip(), flags=re.MULTILINE)
            return jsonify({"code": clean_code})
            
    # Fallback default code
    fallback_code = f"# Concept: {topic.title()}\n# No pre-configured code sample available.\n\nprint('Learning about {topic}...')"
    return jsonify({"code": fallback_code})

@app.route("/lab")
def lab():
    return render_template("experiment.html")


@app.route("/experiment")
def experiment():
    return render_template("experiment.html")

@app.route("/notes")
def notes():
    return render_template("notes.html")

@app.route("/notes/<topic>")
def notes_topic(topic):
    content = load_topic(topic)
    notes_data = load_notes(topic)
    if not content and not notes_data:
        return render_template("404.html"), 404
    return render_template("notes_topic.html", topic=topic, content=content, notes=notes_data)

@app.route("/api/notes-pdf/<topic>")
def notes_pdf(topic):
    content = load_topic(topic)
    notes_data = load_notes(topic)
    html = render_template("pdf_template.html", topic=topic, content=content, notes=notes_data)
    return Response(html, mimetype="text/html",
                    headers={"Content-Disposition": f"inline; filename={topic}_notes.html"})

# â”€â”€ API Endpoints â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@app.route("/api/ai-mentor", methods=["POST"])
def ai_mentor_api():
    data = request.json
    code = data.get("code", "")
    action = data.get("action", "explain")
    question = data.get("question", "")
    topic = data.get("topic", "")

    if action == "ask":
        result = ai_answer_question(question, topic)
    elif action == "dryrun":
        result = ai_dry_run(code)
    elif action == "explain_perfect":
        result = ai_perfect_explanation(topic or code)
    else:
        result = real_ai_response(code, action)
    return jsonify({"result": result})

@app.route("/api/progress", methods=["POST"])
def save_progress():
    data = request.json
    user_id = session.get("user_id", "guest")
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO progress (user_id, topic, completed, score) VALUES (?,?,?,?)",
              (user_id, data["topic"], data["completed"], data.get("score", 0)))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})

@app.route("/api/bookmark", methods=["POST"])
def bookmark():
    data = request.json
    user_id = session.get("user_id", "guest")
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO bookmarks (user_id, question_id, question_text) VALUES (?,?,?)",
              (user_id, data["question_id"], data["question_text"]))
    conn.commit()
    conn.close()
    return jsonify({"status": "bookmarked"})

@app.route("/api/game/predict", methods=["POST"])
def game_predict():
    data = request.json
    answer = data.get("answer", "").strip()
    correct = data.get("correct", "").strip()
    return jsonify({"correct": answer == correct, "expected": correct})

@app.route("/api/run-code", methods=["POST"])
def run_code():
    data = request.json
    code = data.get("code", "")
    stdin_data = data.get("stdin", "")

    # Security: block ALL dangerous patterns â€” no whitelisting
    blocked_patterns = [
        r"\bimport\s+os\b", r"\bimport\s+sys\b", r"\bimport\s+subprocess\b",
        r"\bimport\s+shutil\b", r"\bimport\s+pathlib\b", r"\bimport\s+socket\b",
        r"\bimport\s+ctypes\b", r"\bimport\s+multiprocessing\b",
        r"\bfrom\s+os\b", r"\bfrom\s+sys\b", r"\bfrom\s+subprocess\b",
        r"\b__import__\s*\(", r"\bopen\s*\(", r"\bexec\s*\(", r"\beval\s*\(",
        r"\bcompile\s*\(", r"\bgetattr\s*\(", r"\bglobals\s*\(", r"\blocals\s*\(",
        r"\b__builtins__\b", r"\b__class__\b.*\b__bases__\b",
    ]
    for pattern in blocked_patterns:
        if re.search(pattern, code, re.IGNORECASE):
            return jsonify({"output": "", "error": f"SecurityError: Unsafe operation detected. Use only standard Python constructs."})


    try:
        tmp_path = None
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(code)
            tmp_path = f.name

        result = subprocess.run(
            [sys.executable, tmp_path],
            input=stdin_data,
            capture_output=True,
            text=True,
            timeout=10,
            encoding="utf-8"
        )
        output = result.stdout
        error = result.stderr

        # Clean up traceback path for cleaner display
        if error:
            error = error.replace(tmp_path, "main.py")

        return jsonify({"output": output, "error": error})

    except subprocess.TimeoutExpired:
        return jsonify({"output": "", "error": "TimeoutError: Code took too long (>10s). Check for infinite loops."})
    except Exception as e:
        return jsonify({"output": "", "error": str(e)})
    finally:
        try:
            if tmp_path:
                os.unlink(tmp_path)
        except:
            pass


@app.route("/api/visualize-code", methods=["POST"])
def visualize_code():
    data = request.json or {}
    code = data.get("code", "")
    stdin = data.get("stdin", "")

    # Security: block ALL dangerous patterns (same check as run-code)
    blocked_patterns = [
        r"\bimport\s+os\b", r"\bimport\s+sys\b", r"\bimport\s+subprocess\b",
        r"\bimport\s+shutil\b", r"\bimport\s+pathlib\b", r"\bimport\s+socket\b",
        r"\bimport\s+ctypes\b", r"\bimport\s+multiprocessing\b",
        r"\bfrom\s+os\b", r"\bfrom\s+sys\b", r"\bfrom\s+subprocess\b",
        r"\b__import__\s*\(", r"\bopen\s*\(", r"\bexec\s*\(", r"\beval\s*\(",
        r"\bcompile\s*\(", r"\bgetattr\s*\(", r"\bglobals\s*\(", r"\blocals\s*\(",
        r"\b__builtins__\b", r"\b__class__\b.*\b__bases__\b",
    ]
    for pattern in blocked_patterns:
        if re.search(pattern, code, re.IGNORECASE):
            return jsonify({"steps": [], "error": f"SecurityError: Unsafe operation detected. Use only standard Python constructs."})

    try:
        runner_path = os.path.join(BASE_DIR, "tracer_runner.py")
        payload = json.dumps({"code": code, "stdin": stdin})
        result = subprocess.run(
            [sys.executable, runner_path],
            input=payload,
            capture_output=True,
            text=True,
            timeout=5,
            encoding="utf-8"
        )
        
        if result.returncode != 0:
            return jsonify({"steps": [], "error": result.stderr or f"Tracer exit code: {result.returncode}"})

        try:
            parsed = json.loads(result.stdout)
            steps = parsed.get("steps", [])
            lines = code.split("\n")
            for step in steps:
                lineno = step.get("line")
                if 1 <= lineno <= len(lines):
                    line_code = lines[lineno - 1]
                    explanation = analyze_line(line_code.strip(), step.get("locals", {}).copy(), lineno)
                    step["explanation"] = explanation
                else:
                    step["explanation"] = "Executing line..."
            return jsonify(parsed)
        except json.JSONDecodeError:
            return jsonify({"steps": [], "error": f"Tracer output parse error: {result.stdout[:500]}"})

    except subprocess.TimeoutExpired:
        return jsonify({"steps": [], "error": "TimeoutError: Visualizer took too long (>5s). Check for infinite loops."})
    except Exception as e:
        return jsonify({"steps": [], "error": str(e)})


@app.route("/api/mark-complete", methods=["POST"])
def mark_complete():
    data = request.json
    user_id = session.get("user_id", "guest")
    topic = data.get("topic", "")
    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO progress (user_id, topic, completed, score) VALUES (?,?,1,100)", (user_id, topic))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})

@app.route("/api/get-progress")
def get_progress():
    user_id = session.get("user_id", "guest")
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT topic FROM progress WHERE user_id=? AND completed=1", (user_id,))
    completed = [row[0] for row in c.fetchall()]
    conn.close()
    total = 19
    return jsonify({"completed": completed, "count": len(completed), "total": total, "percent": int(len(completed)/total*100)})

@app.route("/api/last-topic")
def last_topic():
    user_id = session.get("user_id", "guest")
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT topic FROM progress WHERE user_id=? ORDER BY id DESC LIMIT 1", (user_id,))
    row = c.fetchone()
    conn.close()
    return jsonify({"last": row[0] if row else "introduction"})


@app.route("/static/data/<filename>")
def serve_data(filename):
    path = os.path.join(BASE_DIR, "static", "data", filename)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        return Response(content, mimetype="application/json")
    return jsonify({"error": "not found"}), 404


@app.route("/streak")
def streak():
    return render_template("streak.html")

@app.route("/api/streak/checkin", methods=["POST"])
def streak_checkin():
    user_id = session.get("user_id", "guest")
    from datetime import datetime, date
    today = date.today().isoformat()
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT date FROM streaks WHERE user_id=? ORDER BY date DESC LIMIT 1", (user_id,))
    row = c.fetchone()
    already_checked = False
    if row and row[0] == today:
        already_checked = True
    else:
        c.execute("INSERT INTO streaks (user_id, date, xp, problems_solved) VALUES (?,?,?,?)",
                  (user_id, today, 10, 0))
        conn.commit()
    c.execute("SELECT date FROM streaks WHERE user_id=? ORDER BY date DESC", (user_id,))
    dates = [r[0] for r in c.fetchall()]
    streak = 0
    from datetime import timedelta
    check = date.today()
    for d in dates:
        if d == check.isoformat():
            streak += 1
            check -= timedelta(days=1)
        else:
            break
    c.execute("SELECT SUM(xp) FROM streaks WHERE user_id=?", (user_id,))
    total_xp = c.fetchone()[0] or 0
    c.execute("SELECT COUNT(*) FROM streaks WHERE user_id=?", (user_id,))
    total_days = c.fetchone()[0] or 0
    conn.close()
    return jsonify({"streak": streak, "total_xp": total_xp, "total_days": total_days,
                    "today": today, "already_checked": already_checked})

@app.route("/api/streak/status")
def streak_status():
    user_id = session.get("user_id", "guest")
    from datetime import date, timedelta
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT date, xp, problems_solved FROM streaks WHERE user_id=? ORDER BY date DESC LIMIT 30", (user_id,))
    rows = c.fetchall()
    dates = [r[0] for r in rows]
    streak = 0
    check = date.today()
    for d in dates:
        if d == check.isoformat():
            streak += 1
            check -= timedelta(days=1)
        else:
            break
    c.execute("SELECT SUM(xp) FROM streaks WHERE user_id=?", (user_id,))
    total_xp = c.fetchone()[0] or 0
    c.execute("SELECT COUNT(*) FROM streaks WHERE user_id=?", (user_id,))
    total_days = c.fetchone()[0] or 0
    today = date.today().isoformat()
    checked_today = today in dates
    history = [{"date": r[0], "xp": r[1], "problems": r[2]} for r in rows]
    conn.close()
    return jsonify({"streak": streak, "total_xp": total_xp, "total_days": total_days,
                    "checked_today": checked_today, "history": history})

@app.route("/api/streak/solve", methods=["POST"])
def streak_solve():
    user_id = session.get("user_id", "guest")
    from datetime import date
    today = date.today().isoformat()
    xp_earned = request.json.get("xp", 10)
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM streaks WHERE user_id=? AND date=?", (user_id, today))
    row = c.fetchone()
    if row:
        c.execute("UPDATE streaks SET xp=xp+?, problems_solved=problems_solved+1 WHERE user_id=? AND date=?",
                  (xp_earned, user_id, today))
    else:
        c.execute("INSERT INTO streaks (user_id, date, xp, problems_solved) VALUES (?,?,?,1)",
                  (user_id, today, xp_earned))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok", "xp_earned": xp_earned})


@app.route("/projects")
def projects():
    return render_template("projects.html")

@app.route("/projects/<slug>")
def project_detail(slug):
    proj = load_project(slug)
    if not proj:
        return render_template("404.html"), 404
    return render_template("project_detail.html", project=proj, slug=slug)

@app.route("/api/ai-project-help", methods=["POST"])
def ai_project_help():
    data = request.json
    project_name = data.get("project", "")
    question = data.get("question", "")
    step = data.get("step", "")
    result = generate_project_help(project_name, question, step)
    return jsonify({"result": result})


# ── Webhook, Upload, and Project Creation APIs ──

@app.route("/api/user/session")
def user_session_api():
    """Retrieve session details for global JavaScript rendering (e.g. dynamic navbar)."""
    user_id = session.get("user_id")
    if user_id:
        return jsonify({
            "logged_in": True,
            "user_id": user_id,
            "role": "admin" if user_id == "admin" else "user"
        })
    return jsonify({"logged_in": False})


@app.route("/api/webhook/activity", methods=["POST"])
def activity_webhook():
    """External/Internal Webhook endpoint to log activity events."""
    data = request.json or {}
    username = data.get("username")
    email = data.get("email")
    action = data.get("action")
    timestamp = data.get("timestamp") or datetime.datetime.utcnow().isoformat() + "Z"
    
    if not username or not email or not action:
        return jsonify({"error": "Missing required fields: username, email, action"}), 400
        
    success = process_activity_log({
        "username": username,
        "email": email,
        "action": action,
        "timestamp": timestamp
    })
    
    if success:
        return jsonify({"status": "success", "message": "Webhook processed activity log successfully!"}), 200
    else:
        return jsonify({"error": "Failed to log event"}), 500

@app.route("/api/custom-project/create", methods=["POST"])
def create_custom_project():
    """Creates a custom project entry and logs the action."""
    user_id = session.get("user_id")
    if not user_id or user_id == "guest":
        return jsonify({"error": "User must be logged in to create custom projects"}), 401
        
    # Get user email
    user_email = "anonymous@pylab.ai"
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT email FROM users WHERE username=?", (user_id,))
    row = c.fetchone()
    if row:
        user_email = row[0]
    conn.close()
    
    data = request.json or {}
    title = data.get("title", "").strip()
    description = data.get("description", "").strip()
    level = data.get("level", "beginner").strip()
    
    if not title:
        return jsonify({"error": "Project title is required"}), 400
        
    # Save custom project to Supabase if configured
    if SUPABASE_CONFIGURED:
        url = f"{SUPABASE_URL}/rest/v1/custom_projects"
        headers = get_supabase_headers()
        project_data = {
            "user_id": user_id,
            "title": title,
            "description": description,
            "level": level
        }
        try:
            requests.post(url, headers=headers, json=project_data, timeout=10)
        except Exception as e:
            print(f"Failed to save custom project in Supabase: {e}")
            
    # Trigger log activity
    trigger_webhook_activity(user_id, user_email, f"create_project:{title}")
    
    return jsonify({"status": "success", "message": f"Custom project '{title}' created successfully!"}), 200

@app.route("/api/upload-file", methods=["POST"])
def upload_file():
    """Receives file upload, logs the action, and returns file content."""
    user_id = session.get("user_id", "guest")
    user_email = "guest@pylab.ai"
    
    if user_id != "guest":
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT email FROM users WHERE username=?", (user_id,))
        row = c.fetchone()
        if row:
            user_email = row[0]
        conn.close()
        
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
        
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400
        
    if file and file.filename.endswith(".py"):
        try:
            content = file.read().decode("utf-8")
            # Trigger log activity
            trigger_webhook_activity(user_id, user_email, f"upload_file:{file.filename}")
            
            return jsonify({
                "status": "success",
                "filename": file.filename,
                "content": content,
                "message": f"File '{file.filename}' uploaded successfully!"
            })
        except Exception as e:
            return jsonify({"error": f"Failed to read file: {str(e)}"}), 500
    else:
        return jsonify({"error": "Only Python (.py) files are allowed"}), 400


# ── Admin Panel & Stats APIs ──

def supabase_get_user_count():
    """Retrieve exact user count from Supabase."""
    if not SUPABASE_CONFIGURED:
        return 0
    url = f"{SUPABASE_URL}/rest/v1/users?select=id"
    headers = get_supabase_headers()
    headers["Prefer"] = "count=exact"
    try:
        response = requests.get(url, headers=headers, timeout=10)
        content_range = response.headers.get("Content-Range", "")
        if "/" in content_range:
            return int(content_range.split("/")[-1])
        if response.status_code == 200:
            return len(response.json())
        return 0
    except Exception as e:
        print(f"Failed to query Supabase user count: {e}")
        return 0

def get_total_users():
    """Wrapper to query total registered users."""
    if SUPABASE_CONFIGURED:
        return supabase_get_user_count()
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    count = c.fetchone()[0]
    conn.close()
    return count

def get_daily_active_users():
    """Query daily active users (active today) from Supabase logs."""
    today_start = datetime.date.today().isoformat() + "T00:00:00Z"
    if SUPABASE_CONFIGURED:
        url = f"{SUPABASE_URL}/rest/v1/activity_logs?timestamp=gte.{today_start}"
        headers = get_supabase_headers()
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                logs = response.json()
                active_users = {log["username"] for log in logs}
                return len(active_users)
            return 0
        except Exception as e:
            print(f"Failed to query Supabase DAU: {e}")
            return 0
    conn = get_db()
    c = conn.cursor()
    today_str = datetime.date.today().isoformat()
    c.execute("SELECT COUNT(DISTINCT user_id) FROM streaks WHERE date=?", (today_str,))
    count = c.fetchone()[0]
    conn.close()
    return count

def get_event_counts():
    """Aggregate event counts by actions."""
    counts = {"login": 0, "signup": 0, "create_project": 0, "upload_file": 0}
    if SUPABASE_CONFIGURED:
        url = f"{SUPABASE_URL}/rest/v1/activity_logs?order=timestamp.desc&limit=2000"
        headers = get_supabase_headers()
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                logs = response.json()
                for log in logs:
                    action = log.get("action", "")
                    if action == "login":
                        counts["login"] += 1
                    elif action == "signup":
                        counts["signup"] += 1
                    elif action.startswith("create_project"):
                        counts["create_project"] += 1
                    elif action.startswith("upload_file"):
                        counts["upload_file"] += 1
        except Exception as e:
            print(f"Failed to load event counts: {e}")
    else:
        # SQLite approximate values
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users")
        counts["signup"] = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM projects_done")
        counts["create_project"] = c.fetchone()[0]
        c.execute("SELECT SUM(problems_solved) FROM streaks")
        counts["login"] = c.fetchone()[0] or 0
        conn.close()
    return counts

def get_recent_activities(limit=30):
    """Retrieve last N activity logs."""
    if SUPABASE_CONFIGURED:
        url = f"{SUPABASE_URL}/rest/v1/activity_logs?order=timestamp.desc&limit={limit}"
        headers = get_supabase_headers()
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                return response.json()
            return []
        except Exception as e:
            print(f"Failed to query recent activities: {e}")
            return []

    # Local SQLite fallback - construct activity logs from users and project completions
    conn = get_db()
    c = conn.cursor()
    
    activities = []
    try:
        # Fetch user registrations
        c.execute("SELECT username, email, created_at FROM users ORDER BY created_at DESC LIMIT ?", (limit,))
        for row in c.fetchall():
            activities.append({
                "username": row[0],
                "email": row[1],
                "action": "signup",
                "timestamp": row[2]
            })
            
        # Fetch project completions
        c.execute("SELECT user_id, project_title, completed_at FROM projects_done ORDER BY completed_at DESC LIMIT ?", (limit,))
        for row in c.fetchall():
            activities.append({
                "username": row[0],
                "email": "(local db)",
                "action": f"completed_project: {row[1]}",
                "timestamp": row[2]
            })
    except Exception as e:
        print(f"Failed to query SQLite stats: {e}")
    finally:
        conn.close()
        
    # Sort activities by timestamp descending and slice to limit
    activities.sort(key=lambda x: x["timestamp"] or "", reverse=True)
    return activities[:limit]

@app.route("/admin/dashboard")
def admin_dashboard():
    """Page route for admin interface (requires admin login session)."""
    user_id = session.get("user_id")
    if not user_id or user_id != "admin":
        flash("Admin credentials required to view this panel.", "error")
        return redirect(url_for("login"))
        
    return render_template("admin_dashboard.html")

@app.route("/api/admin/stats")
def admin_stats_api():
    """API endpoint returning statistical aggregates for admin panel."""
    user_id = session.get("user_id")
    if not user_id or user_id != "admin":
        return jsonify({"error": "Unauthorized"}), 401
        
    try:
        total_users = get_total_users()
        dau = get_daily_active_users()
        events = get_event_counts()
        recent = get_recent_activities()
        
        return jsonify({
            "status": "success",
            "total_users": total_users,
            "daily_active_users": dau,
            "event_stats": events,
            "recent_activities": recent
        })
    except Exception as e:
        return jsonify({"error": f"Failed to compute admin statistics: {str(e)}"}), 500


# ── Progress & Dashboard APIs ──

@app.route("/dashboard")
def dashboard():
    user_id = session.get("user_id", "guest")
    conn = get_db()
    c = conn.cursor()
    
    # Topics completed
    c.execute("SELECT topic FROM progress WHERE user_id=? AND completed=1", (user_id,))
    topics_done = [r[0] for r in c.fetchall()]
    
    # Projects completed
    c.execute("SELECT project_slug, project_title, completed_at FROM projects_done WHERE user_id=? ORDER BY completed_at DESC", (user_id,))
    projects_done = [{"slug":r[0],"title":r[1],"date":r[2]} for r in c.fetchall()]
    
    # Streak
    from datetime import date, timedelta
    c.execute("SELECT date, xp, problems_solved FROM streaks WHERE user_id=? ORDER BY date DESC LIMIT 30", (user_id,))
    streak_rows = c.fetchall()
    streak_dates = [r[0] for r in streak_rows]
    streak = 0
    check = date.today()
    for d in streak_dates:
        if d == check.isoformat():
            streak += 1
            check -= timedelta(days=1)
        else:
            break
    
    c.execute("SELECT SUM(xp) FROM streaks WHERE user_id=?", (user_id,))
    total_xp = c.fetchone()[0] or 0
    
    c.execute("SELECT COUNT(*) FROM streaks WHERE user_id=?", (user_id,))
    total_days = c.fetchone()[0] or 0
    
    conn.close()
    
    return render_template("dashboard.html",
        topics_done=topics_done,
        topics_total=19,
        projects_done=projects_done,
        streak=streak,
        total_xp=total_xp,
        total_days=total_days,
        streak_history=[{"date":r[0],"xp":r[1],"problems":r[2]} for r in streak_rows]
    )

@app.route("/api/complete-project", methods=["POST"])
def complete_project():
    data = request.json
    user_id = session.get("user_id", "guest")
    slug = data.get("slug","")
    title = data.get("title","")
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM projects_done WHERE user_id=? AND project_slug=?", (user_id, slug))
    if not c.fetchone():
        c.execute("INSERT INTO projects_done (user_id, project_slug, project_title) VALUES (?,?,?)", (user_id, slug, title))
        # Award XP
        from datetime import date
        today = date.today().isoformat()
        c.execute("SELECT id FROM streaks WHERE user_id=? AND date=?", (user_id, today))
        if c.fetchone():
            c.execute("UPDATE streaks SET xp=xp+20 WHERE user_id=? AND date=?", (user_id, today))
        else:
            c.execute("INSERT INTO streaks (user_id, date, xp) VALUES (?,?,20)", (user_id, today))
        conn.commit()
        conn.close()
        return jsonify({"status":"completed","xp_earned":20,"message":"Project completed! +20 XP"})
    conn.close()
    return jsonify({"status":"already_done","message":"Already completed!"})

@app.route("/api/leaderboard")
def leaderboard():
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT user_id, SUM(xp) as total_xp, COUNT(*) as active_days
        FROM streaks GROUP BY user_id ORDER BY total_xp DESC LIMIT 10
    """)
    rows = c.fetchall()
    
    # Get streak for each user
    from datetime import date, timedelta
    leaders = []
    for user_id, xp, days in rows:
        c.execute("SELECT date FROM streaks WHERE user_id=? ORDER BY date DESC", (user_id,))
        dates = [r[0] for r in c.fetchall()]
        streak = 0
        check = date.today()
        for d in dates:
            if d == check.isoformat():
                streak += 1
                check -= timedelta(days=1)
            else:
                break
        leaders.append({"user_id": user_id, "xp": xp or 0, "streak": streak, "days": days})
    
    conn.close()
    return jsonify({"leaders": leaders})

@app.route("/api/full-progress")
def full_progress():
    user_id = session.get("user_id", "guest")
    conn = get_db()
    c = conn.cursor()
    
    c.execute("SELECT topic FROM progress WHERE user_id=? AND completed=1", (user_id,))
    topics = [r[0] for r in c.fetchall()]
    
    c.execute("SELECT project_slug FROM projects_done WHERE user_id=?", (user_id,))
    projects = [r[0] for r in c.fetchall()]
    
    c.execute("SELECT SUM(xp) FROM streaks WHERE user_id=?", (user_id,))
    xp = c.fetchone()[0] or 0
    
    conn.close()
    return jsonify({
        "topics_completed": topics,
        "projects_completed": projects,
        "total_xp": xp,
        "topics_count": len(topics),
        "projects_count": len(projects)
    })

@app.route("/notebook")
def notebook():
    return render_template("notebook.html")

# â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def load_topic(topic):
    path = os.path.join(BASE_DIR, "content", f"{topic}.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None

def load_notes(topic):
    path = os.path.join(BASE_DIR, "notes", f"{topic}.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None

def generate_pdf_html(title, content, notes_data):
    sections = []
    if content:
        sections.append(f"<h1>{content.get('icon','')} {title}</h1>")
        sections.append(f"<div class='badge'>{content.get('level','').upper()}</div>")
        sections.append(f"<h2>Definition</h2><p>{content.get('simple_definition','')}</p>")
        sections.append(f"<h2>Technical Definition</h2><p>{content.get('technical_definition','')}</p>")
        if content.get('analogy'):
            sections.append(f"<h2>Real-World Analogy</h2><p>{content.get('analogy','')}</p>")
        sections.append(f"<h2>Syntax</h2><pre><code>{content.get('syntax','')}</code></pre>")
        sections.append(f"<h2>Code Example</h2><pre><code>{content.get('code_example','')}</code></pre>")
        if content.get('output'):
            sections.append(f"<h2>Output</h2><pre>{content.get('output','')}</pre>")
        if content.get('logic_steps'):
            sections.append("<h2>Logic Breakdown</h2><ol>")
            for s in content['logic_steps']:
                sections.append(f"<li>{s}</li>")
            sections.append("</ol>")
        if content.get('subtopics'):
            for sub in content['subtopics']:
                sections.append(f"<h2>{sub.get('icon','')} {sub.get('title','')}</h2>")
                sections.append(f"<p>{sub.get('explanation','')}</p>")
                sections.append(f"<pre><code>{sub.get('syntax','')}</code></pre>")
                sections.append(f"<pre><code>{sub.get('code','')}</code></pre>")
                if sub.get('output'):
                    sections.append(f"<pre>Output:\n{sub.get('output','')}</pre>")
                if sub.get('tip'):
                    sections.append(f"<div class='tip'>ðŸ’¡ {sub.get('tip','')}</div>")
        if content.get('edge_cases'):
            sections.append("<h2>Edge Cases</h2><ul>")
            for e in content['edge_cases']:
                sections.append(f"<li>{e}</li>")
            sections.append("</ul>")
        if content.get('common_mistakes'):
            sections.append("<h2>Common Mistakes</h2><ul>")
            for m in content['common_mistakes']:
                sections.append(f"<li>{m}</li>")
            sections.append("</ul>")
        if content.get('interview_tips'):
            sections.append("<h2>Interview Tips</h2><ul>")
            for t in content['interview_tips']:
                sections.append(f"<li>{t}</li>")
            sections.append("</ul>")
        if content.get('practice'):
            sections.append("<h2>Practice Questions</h2>")
            for level in ['easy','medium','hard']:
                qs = content['practice'].get(level,[])
                if qs:
                    sections.append(f"<h3>{level.title()}</h3><ol>")
                    for q in qs:
                        sections.append(f"<li><strong>{q.get('question','')}</strong><br><em>Hint: {q.get('hint','')}</em></li>")
                    sections.append("</ol>")
    if notes_data:
        sections.append("<h2>Extended Notes</h2>")
        for section in notes_data.get('sections', []):
            sections.append(f"<h3>{section.get('title','')}</h3>")
            sections.append(f"<p>{section.get('content','')}</p>")
            if section.get('code'):
                sections.append(f"<pre><code>{section.get('code','')}</code></pre>")
    body = "\n".join(sections)
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<title>{title} - PyLab AI Notes</title>
<style>
body{{font-family:Georgia,serif;max-width:900px;margin:0 auto;padding:2rem;color:#1a1a2e;line-height:1.8;}}
h1{{color:#0066cc;font-size:2.2rem;border-bottom:3px solid #0066cc;padding-bottom:.5rem;}}
h2{{color:#003399;font-size:1.4rem;margin-top:2rem;border-left:4px solid #0066cc;padding-left:.75rem;}}
h3{{color:#0055aa;font-size:1.1rem;margin-top:1.5rem;}}
pre{{background:#f0f4f8;border:1px solid #ccd;border-radius:8px;padding:1rem;overflow-x:auto;font-family:Fira Code,monospace;font-size:.88rem;}}
code{{font-family:Fira Code,monospace;background:#e8f0f8;padding:.1rem .3rem;border-radius:3px;}}
pre code{{background:none;padding:0;}}
.badge{{display:inline-block;background:#0066cc;color:#fff;padding:.25rem .75rem;border-radius:20px;font-size:.8rem;font-weight:700;margin-bottom:1rem;text-transform:uppercase;}}
.tip{{background:#e8f8e8;border:1px solid #4caf50;border-radius:8px;padding:.75rem 1rem;margin:1rem 0;}}
li{{margin-bottom:.5rem;}}
@media print{{body{{padding:1rem;}}h2{{page-break-before:auto;}}.no-print{{display:none;}}}}
</style>
</head><body>
<div class="no-print" style="background:#0066cc;color:#fff;padding:1rem;border-radius:8px;margin-bottom:2rem;display:flex;justify-content:space-between;align-items:center;">
  <strong>ðŸ“„ PyLab AI Notes â€” {title}</strong>
  <button onclick="window.print()" style="background:#fff;color:#0066cc;border:none;padding:.5rem 1.5rem;border-radius:6px;font-weight:700;cursor:pointer;">ðŸ–¨ï¸ Print / Save as PDF</button>
</div>
{body}
<div style="margin-top:3rem;padding-top:1rem;border-top:2px solid #0066cc;text-align:center;color:#666;font-size:.85rem;">
  Generated by PyLab AI â€” Learn, Experiment, Master Python â­
</div>
</body></html>"""


def load_problems(level, topic):
    path = os.path.join(BASE_DIR, "practice", f"{level}.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if topic == "all":
                return data
            return [p for p in data if p.get("topic") == topic]
    return []

def real_ai_response(code, action):
    """Try Gemini first; fall back to mock_ai_response if unavailable."""
    action_prompts = {
        "explain": (
            "You are a Python tutor. Explain the following Python code clearly and concisely "
            "for a beginner. Break it down line by line, describe what each part does, identify "
            "the key concepts used, and end with a short tip.\n\nCode:\n```python\n{code}\n```"
        ),
        "error": (
            "You are a Python debugger. Analyze the following Python code for bugs, syntax errors, "
            "logic errors, and bad practices. List each issue found with the line/reason, and provide "
            "a corrected version of the code.\n\nCode:\n```python\n{code}\n```"
        ),
        "hint": (
            "You are a Python mentor. Give a helpful hint (NOT the full solution) to guide a student "
            "solving this code problem. Help them think through the logic step by step.\n\n"
            "Code:\n```python\n{code}\n```"
        ),
        "improve": (
            "You are a Python expert. Rewrite the following code in a more Pythonic, clean, and efficient "
            "way. Show the original vs improved version, explain each improvement, and mention any relevant "
            "Python built-ins or idioms used.\n\nCode:\n```python\n{code}\n```"
        ),
        "optimize": (
            "You are a Python performance expert. Analyze the following code for performance bottlenecks "
            "and optimize it. Show before/after, explain the complexity improvement, and add comments.\n\n"
            "Code:\n```python\n{code}\n```"
        ),
    }
    prompt_template = action_prompts.get(action, action_prompts["explain"])
    prompt = prompt_template.format(code=code[:3000] if code else "# No code provided")

    result = call_gemini(prompt)
    if result:
        return result
    # Fallback to static mock when Gemini is unavailable
    return mock_ai_response(code, action)


def mock_ai_response(code, action):
    responses = {
        "explain": f"""ðŸ¤– **AI Code Explanation**

Here's what your code does step by step:

```
{code[:200] if code else '# No code provided'}
```

**Line-by-line breakdown:**
- The code initializes variables and sets up the logic flow
- Each operation is executed sequentially
- The output is produced based on the input conditions

**Key concepts used:** Variables, Control Flow, Functions

ðŸ’¡ **Tip:** Understanding the flow of execution is key to mastering Python!""",

        "error": f"""ðŸ” **Error Analysis**

Scanning your code for issues...

**Potential Issues Found:**
1. Check for proper indentation (Python is indent-sensitive)
2. Verify all variables are defined before use
3. Ensure parentheses and brackets are balanced
4. Check string quotes are properly closed

**Common Fix:** Run `python -m py_compile your_file.py` to check syntax errors.

âœ… **Best Practice:** Use a linter like `pylint` or `flake8` for automatic error detection.""",

        "hint": f"""ðŸ’¡ **Logic Hint**

Without giving away the full solution, here's how to think about this:

**Step 1:** Break the problem into smaller parts
**Step 2:** Identify what inputs you have and what output you need
**Step 3:** Think about which Python structures fit best (loop? condition? function?)
**Step 4:** Write pseudocode first, then convert to Python

**Hint:** Think about the edge cases â€” what happens with empty input or extreme values?

ðŸŽ¯ **Challenge yourself:** Can you solve it in fewer lines?""",

        "improve": f"""âš¡ **Code Optimization Suggestions**

Here's how to make your code more Pythonic:

**1. Use List Comprehensions** instead of loops where possible:
```python
# Instead of:
result = []
for x in items:
    result.append(x * 2)

# Use:
result = [x * 2 for x in items]
```

**2. Use f-strings** for string formatting:
```python
name = "Python"
print(f"Hello, {{name}}!")  # Modern and fast
```

**3. Use enumerate()** instead of range(len()):
```python
for i, item in enumerate(my_list):
    print(i, item)
```

ðŸš€ **Performance Tip:** Profile your code with `cProfile` to find bottlenecks!""",

        "optimize": f"""ðŸ”¥ **Beginner â†’ Optimized Conversion**

**Your approach (beginner style):**
```python
{code[:150] if code else '# paste your code above'}
```

**Optimized Pythonic version:**
```python
# Using built-in functions and Python idioms
# - Reduced time complexity
# - More readable and maintainable
# - Follows PEP 8 style guide
```

**Why this is better:**
- âœ… Fewer lines of code
- âœ… Better readability
- âœ… Uses Python's built-in optimizations
- âœ… Interview-ready code quality

ðŸ“š **Learn more:** Study Python's built-in functions â€” they're highly optimized in C!"""
    }
    return responses.get(action, responses["explain"])



def ai_answer_question(question, topic=""):
    """Answer any Python question using the perfect explanation structure."""
    q = question.lower().strip()

    # Detect topic
    if not topic:
        for t in ["for loop","while loop","loop","function","list","dictionary","dict",
                  "string","class","oop","decorator","generator","exception","lambda",
                  "recursion","variable","operator","condition","if","tuple","set"]:
            if t in q:
                topic = t.split()[0]
                break

    # Build perfect explanation
    topic_data = TOPIC_EXPLANATIONS.get(topic, None)
    if topic_data:
        return format_perfect_explanation(topic_data, question)

    # Generic answer for unknown questions
    return f"""ðŸ¤– **PyLab AI Mentor â€” Answer**

**Your Question:** {question}

â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”

ðŸ’¡ **Simple Answer:**
Great question! Let me break this down step by step.

{get_generic_answer(question)}

â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”
ðŸŽ¯ **Want a deeper explanation?**
Try asking: "Explain [topic] with dry run" or "What is [concept]?"

ðŸ“š **Related Topics:** Check the Learn section for full topic coverage.
"""


def get_generic_answer(question):
    q = question.lower()
    if "what is" in q or "what are" in q:
        topic = question.replace("what is","").replace("what are","").strip().strip("?")
        return f"""**{topic.title()}** is a fundamental Python concept.

Here's how to think about it:
1. Start with WHY you need it
2. Understand the basic idea
3. See a simple example
4. Practice with small problems

ðŸ‘‰ Go to **Learn â†’ {topic.title()}** for the complete explanation with dry run!"""

    if "how to" in q or "how do" in q:
        return """**Step-by-step approach:**

1. ðŸ§  Understand what you want to achieve
2. ðŸ“ Write pseudocode first (plain English)
3. ðŸ’» Convert to Python syntax
4. ï¿½ï¿½ Test with simple inputs
5. âš¡ Optimize if needed

ðŸ’¡ **Tip:** Break the problem into smaller parts. Solve each part separately."""

    if "difference between" in q:
        return """**Comparison approach:**

When comparing two concepts, ask:
- What does each one DO?
- When do you USE each one?
- What are the LIMITATIONS of each?

ðŸ“š Check the Learn section for detailed comparisons with examples!"""

    if "error" in q or "bug" in q or "not working" in q:
        return """**Debugging approach:**

1. ðŸ” Read the error message carefully â€” it tells you EXACTLY what's wrong
2. ðŸ“ Find the line number mentioned in the error
3. âœ… Check: indentation, spelling, missing colons, wrong types
4. ðŸ§ª Use the **Find Errors** button above to analyze your code
5. ðŸ’¡ Add print() statements to trace values

**Most common Python errors:**
- IndentationError â†’ Wrong spaces/tabs
- NameError â†’ Variable not defined
- TypeError â†’ Wrong data type
- IndexError â†’ List index out of range
- SyntaxError â†’ Missing colon, bracket, or quote"""

    return """Here's how to approach this:

1. ðŸ’¡ Think about what you already know
2. ðŸ” Break the problem into smaller parts
3. ðŸ’» Try writing code in the **Editor** tab
4. ðŸ¤– Paste your attempt here for specific feedback

**Remember:** The best way to learn Python is by doing!
Try the **Experiment Lab** for hands-on practice."""


def format_perfect_explanation(data, question=""):
    return f"""ðŸ¤– **PyLab AI Mentor â€” Perfect Explanation**

â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”

**1. ðŸ’¡ THE PROBLEM FIRST**
{data["problem"]}

â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”

**2. ðŸ§  SIMPLE IDEA**
{data["simple_idea"]}

â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”

**3. ðŸ  REAL-LIFE EXAMPLE**
{data["real_life"]}

â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”

**4. ðŸ§¾ SYNTAX**
```python
{data["syntax"]}
```

**5. ðŸ’» CODE EXAMPLE**
```python
{data["code"]}
```

â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”

**6. ðŸ” LINE-BY-LINE BREAKDOWN**
{data["line_by_line"]}

â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”

**7. ðŸ§  DRY RUN (Step-by-Step Execution)**
{data["dry_run"]}

â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”

**8. âš ï¸ COMMON MISTAKES**
{data["mistakes"]}

â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”

**9. ðŸ§© PRACTICE QUESTIONS**
{data["practice"]}

â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”

**10. ðŸš€ WHY THIS MATTERS**
{data["why_matters"]}
"""


def ai_dry_run(code):
    """Generate a line-by-line dry run of the given code."""
    if not code.strip():
        return "âŒ Please paste your code first, then click Dry Run."

    lines = code.strip().split("\n")
    result = ["ðŸ§  **DRY RUN â€” Step-by-Step Execution**", "",
              "I will trace through your code line by line, showing exactly what Python does:", ""]

    result.append("```")
    result.append("Line | Code                    | What happens")
    result.append("-----|------------------------|------------------------------------------")

    variables = {}
    output_lines = []

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            result.append(f"  {i:2d} | {line[:22]:<22} | # Comment / blank line â€” skipped")
            continue

        explanation = analyze_line(stripped, variables, i)
        result.append(f"  {i:2d} | {line[:22]:<22} | {explanation}")

    result.append("```")
    result.append("")
    result.append("â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”â”")
    result.append("")
    result.append("**ðŸ“Š Variable State After Execution:**")
    if variables:
        for var, val in variables.items():
            result.append(f"  â€¢ `{var}` = `{val}`")
    else:
        result.append("  No variables tracked (complex code â€” run it in the Editor!)")

    result.append("")
    result.append("**ðŸ’¡ Key Observations:**")
    result.append(get_code_observations(code))
    result.append("")
    result.append("ðŸŽ¯ **Try it yourself:** Click **â–¶ Run** in the Editor to see the actual output!")

    return "\n".join(result)


def analyze_line(line, variables, line_num):
    """Analyze a single line of Python code."""
    import re

    # Assignment
    if "=" in line and "==" not in line and "!=" not in line and ">=" not in line and "<=" not in line:
        parts = line.split("=", 1)
        var = parts[0].strip()
        val = parts[1].strip() if len(parts) > 1 else ""
        if var.isidentifier():
            variables[var] = val
            return f"Variable `{var}` is assigned value `{val}`"

    # print statement
    if line.startswith("print("):
        content = line[6:-1] if line.endswith(")") else line[6:]
        return f"OUTPUT: prints {content} to screen"

    # for loop
    if line.startswith("for ") and " in " in line:
        parts = line.replace("for ", "").replace(":", "").split(" in ")
        var = parts[0].strip()
        seq = parts[1].strip() if len(parts) > 1 else "sequence"
        return f"Loop starts: `{var}` takes each value from `{seq}`"

    # while loop
    if line.startswith("while "):
        cond = line.replace("while ", "").replace(":", "").strip()
        return f"Check condition: `{cond}` â€” if True, run loop body"

    # if statement
    if line.startswith("if "):
        cond = line.replace("if ", "").replace(":", "").strip()
        return f"Check: is `{cond}` True? If yes, run next block"

    # elif
    if line.startswith("elif "):
        cond = line.replace("elif ", "").replace(":", "").strip()
        return f"Else-if check: is `{cond}` True?"

    # else
    if line.startswith("else:"):
        return "All above conditions were False â€” run this block"

    # def
    if line.startswith("def "):
        fname = line.replace("def ", "").split("(")[0]
        return f"Define function `{fname}` â€” stored in memory, not executed yet"

    # class
    if line.startswith("class "):
        cname = line.replace("class ", "").split("(")[0].replace(":", "")
        return f"Define class `{cname}` â€” blueprint created"

    # return
    if line.startswith("return "):
        val = line.replace("return ", "").strip()
        return f"Return `{val}` to the caller â€” function ends here"

    # import
    if line.startswith("import ") or line.startswith("from "):
        return f"Load module into memory: {line}"

    # append
    if ".append(" in line:
        return f"Add item to list: {line}"

    # break/continue
    if line == "break":
        return "EXIT the loop immediately"
    if line == "continue":
        return "SKIP rest of this iteration, go to next"

    return f"Execute: {line[:40]}"


def get_code_observations(code):
    obs = []
    if "for " in code and "range" in code:
        obs.append("  â€¢ Uses a for loop with range() â€” iterates a fixed number of times")
    if "while " in code:
        obs.append("  â€¢ Uses a while loop â€” runs until condition becomes False")
    if "def " in code:
        obs.append("  â€¢ Defines a function â€” reusable block of code")
    if "if " in code:
        obs.append("  â€¢ Uses conditional logic â€” makes decisions")
    if "return " in code:
        obs.append("  â€¢ Function returns a value")
    if "class " in code:
        obs.append("  â€¢ Defines a class â€” OOP blueprint")
    if not obs:
        obs.append("  â€¢ Simple sequential code â€” executes line by line")
    return "\n".join(obs)


def ai_perfect_explanation(topic):
    """Generate perfect 10-step explanation for a topic."""
    data = TOPIC_EXPLANATIONS.get(topic.lower(), None)
    if data:
        return format_perfect_explanation(data)
    return ai_answer_question(f"Explain {topic}", topic)


# â”€â”€ Topic Knowledge Base â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
TOPIC_EXPLANATIONS = {
    "loop": {
        "problem": "Suppose you want to print numbers from 1 to 100...\nWill you write 100 print statements? ðŸ˜…\n\nprint(1)\nprint(2)\nprint(3)\n... (97 more lines)\n\nThat's crazy! There must be a better way. That's where LOOPS come in.",
        "simple_idea": "A loop means: **repeat something again and again automatically.**\n\nInstead of writing the same code 100 times, you write it ONCE and tell Python how many times to repeat it.",
        "real_life": "ðŸ½ï¸ Eating breakfast EVERY morning (same action, repeated daily)\nâ° Alarm rings EVERY day at 7 AM\nðŸ“‹ Teacher takes attendance for EVERY student\nðŸ”„ Washing machine runs the SAME cycle repeatedly\n\nAll of these are loops in real life!",
        "syntax": "# For loop\nfor i in range(1, 6):\n    print(i)\n\n# While loop\ncount = 1\nwhile count <= 5:\n    print(count)\n    count += 1",
        "code": "# Print 1 to 5 using for loop\nfor i in range(1, 6):\n    print(i)\n\n# Same using while loop\ncount = 1\nwhile count <= 5:\n    print(count)\n    count += 1",
        "line_by_line": "`for` â†’ keyword that starts the loop\n`i` â†’ variable that holds current value (changes each time)\n`range(1, 6)` â†’ generates numbers 1, 2, 3, 4, 5 (6 is NOT included)\n`print(i)` â†’ prints the current value of i\n\nThe indented block runs for EACH value of i.",
        "dry_run": "Iteration 1: i = 1 â†’ print(1) â†’ Output: 1\nIteration 2: i = 2 â†’ print(2) â†’ Output: 2\nIteration 3: i = 3 â†’ print(3) â†’ Output: 3\nIteration 4: i = 4 â†’ print(4) â†’ Output: 4\nIteration 5: i = 5 â†’ print(5) â†’ Output: 5\nLoop ends (range exhausted)",
        "mistakes": "âŒ range(1, 5) gives 1,2,3,4 â€” NOT 5! Use range(1, 6) for 1 to 5\nâŒ Forgetting to increment in while loop â†’ infinite loop!\nâŒ Wrong indentation â†’ IndentationError\nâŒ Using = instead of == in while condition",
        "practice": "Easy: Print numbers 1 to 10\nEasy: Print even numbers from 1 to 20\nMedium: Calculate sum of 1 to 100\nMedium: Print multiplication table of 7\nHard: Find all prime numbers from 1 to 100",
        "why_matters": "Loops are used EVERYWHERE:\nðŸŽ® Games: game loop runs 60 times per second\nðŸ“Š Data: process millions of records\nðŸŒ Web: handle thousands of requests\nðŸ¤– AI: train models over millions of examples\n\nWithout loops, programming would be impossible!"
    },
    "function": {
        "problem": "Suppose you need to calculate area of rectangle in 10 different places in your program...\nWill you write the same formula 10 times?\n\narea = length * width  (line 10)\narea = length * width  (line 50)\narea = length * width  (line 100)\n\nWhat if the formula changes? You'd have to update 10 places! ðŸ˜±",
        "simple_idea": "A function is a **reusable block of code** with a name.\n\nWrite it ONCE â†’ Use it ANYWHERE â†’ Change it in ONE place.\n\nThink of it as a recipe: write the recipe once, cook it anytime!",
        "real_life": "ðŸ• Pizza recipe: written once, used every time you make pizza\nðŸ“± Calculator app: press + button â†’ same addition function runs\nðŸ§ ATM: withdraw button â†’ same withdrawal function every time\nðŸ”‘ Login: same authentication function for every user",
        "syntax": "def function_name(parameter1, parameter2):\n    # code here\n    return result\n\n# Call it\nresult = function_name(value1, value2)",
        "code": "def calculate_area(length, width):\n    area = length * width\n    return area\n\n# Use it multiple times\nprint(calculate_area(5, 3))   # 15\nprint(calculate_area(10, 4))  # 40\nprint(calculate_area(7, 2))   # 14",
        "line_by_line": "`def` â†’ keyword to define a function\n`calculate_area` â†’ name of the function (you choose this)\n`(length, width)` â†’ parameters (inputs the function needs)\n`area = length * width` â†’ the actual calculation\n`return area` â†’ send the result back to the caller\n\nWhen you call `calculate_area(5, 3)`: length=5, width=3",
        "dry_run": "Call: calculate_area(5, 3)\n  â†’ length = 5, width = 3\n  â†’ area = 5 * 3 = 15\n  â†’ return 15\nResult: 15 is printed\n\nCall: calculate_area(10, 4)\n  â†’ length = 10, width = 4\n  â†’ area = 10 * 4 = 40\n  â†’ return 40\nResult: 40 is printed",
        "mistakes": "âŒ Calling function before defining it\nâŒ Forgetting return â†’ function returns None\nâŒ Wrong number of arguments\nâŒ Using variable outside function scope\nâŒ def greet(name, msg='Hi', title): â€” non-default after default!",
        "practice": "Easy: Write a function to find square of a number\nEasy: Write a function to check even/odd\nMedium: Write a function to find factorial\nMedium: Write a function to check palindrome\nHard: Write a recursive function for Fibonacci",
        "why_matters": "Functions are the building blocks of ALL programs:\nðŸ—ï¸ Every app is made of hundreds of functions\nðŸ”„ DRY principle: Don't Repeat Yourself\nðŸ§ª Easy to test individual pieces\nðŸ‘¥ Teams can work on different functions simultaneously"
    },
    "list": {
        "problem": "Suppose you want to store marks of 50 students...\nWill you create 50 variables?\n\nmark1 = 85\nmark2 = 90\nmark3 = 78\n... (47 more)\n\nAnd how will you find the average? ðŸ˜°",
        "simple_idea": "A list is a **container that holds multiple values in one variable.**\n\nLike a shopping bag â€” one bag, many items inside!",
        "real_life": "ðŸ›’ Shopping list: [milk, eggs, bread, butter]\nðŸ“± Contacts list: [Alice, Bob, Charlie]\nðŸŽµ Playlist: [Song1, Song2, Song3]\nðŸ“Š Student marks: [85, 90, 78, 92, 88]",
        "syntax": "# Create list\nmy_list = [item1, item2, item3]\n\n# Access items (index starts at 0!)\nmy_list[0]   # first item\nmy_list[-1]  # last item\nmy_list[1:3] # items at index 1 and 2",
        "code": "marks = [85, 90, 78, 92, 88]\n\nprint(marks[0])      # 85 (first)\nprint(marks[-1])     # 88 (last)\nprint(len(marks))    # 5 (count)\nprint(sum(marks))    # 433 (total)\nprint(sum(marks)/len(marks))  # 86.6 (average)\n\nmarks.append(95)     # add new mark\nmarks.sort()         # sort ascending\nprint(marks)",
        "line_by_line": "`marks = [85, 90, 78, 92, 88]` â†’ creates list with 5 numbers\n`marks[0]` â†’ index 0 = first item = 85\n`marks[-1]` â†’ negative index = from end = 88\n`len(marks)` â†’ counts items = 5\n`sum(marks)` â†’ adds all = 433\n`marks.append(95)` â†’ adds 95 at the end\n`marks.sort()` â†’ arranges in order",
        "dry_run": "marks = [85, 90, 78, 92, 88]\n         â†‘   â†‘   â†‘   â†‘   â†‘\nIndex:   0   1   2   3   4\n\nmarks[0] â†’ look at index 0 â†’ 85\nmarks[-1] â†’ count from end â†’ index 4 â†’ 88\nlen(marks) â†’ count items â†’ 5\nsum(marks) â†’ 85+90+78+92+88 â†’ 433",
        "mistakes": "âŒ marks[5] on a 5-item list â†’ IndexError! (valid: 0 to 4)\nâŒ Confusing list and tuple: [] vs ()\nâŒ Modifying list while iterating over it\nâŒ list1 = list2 copies reference, not values! Use list2 = list1.copy()",
        "practice": "Easy: Create list of 5 fruits, print first and last\nEasy: Find sum and average of a list\nMedium: Remove duplicates from a list\nMedium: Sort list without using sort()\nHard: Find second largest element",
        "why_matters": "Lists are used in EVERY Python program:\nðŸ“Š Store data from databases\nðŸ¤– ML: training data is stored in lists/arrays\nðŸŒ Web: list of users, products, orders\nðŸ“± Apps: todo list, contacts, messages"
    }
}

# Add aliases
TOPIC_EXPLANATIONS["for"] = TOPIC_EXPLANATIONS["loop"]
TOPIC_EXPLANATIONS["while"] = TOPIC_EXPLANATIONS["loop"]
TOPIC_EXPLANATIONS["loops"] = TOPIC_EXPLANATIONS["loop"]
TOPIC_EXPLANATIONS["functions"] = TOPIC_EXPLANATIONS["function"]
TOPIC_EXPLANATIONS["lists"] = TOPIC_EXPLANATIONS["list"]


def load_project(slug):
    path = os.path.join(BASE_DIR, "projects", f"{slug}.json")
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    # Try to build from index
    idx_path = os.path.join(BASE_DIR, "projects", "index.json")
    if os.path.exists(idx_path):
        with open(idx_path, "r", encoding="utf-8") as f:
            idx = json.load(f)
        for level, projs in idx.items():
            for p in projs:
                if p["slug"] == slug:
                    return {**p, "level": level, "steps": [], "what_you_learn": [], "extensions": [], "folder_structure": "", "what_you_build": p["desc"], "concepts_needed": p["tags"]}
    return None

def generate_project_help(project_name, question, step):
    q = question.lower()
    
    if "github" in q or "git" in q:
        return """&#x1F4BB; **GitHub Setup Guide**

**Step 1: Initialize Git**
```bash
git init
git add .
git commit -m "Initial commit: {project}"
```

**Step 2: Create GitHub Repository**
1. Go to github.com
2. Click "New Repository"
3. Name it (e.g., {project_slug})
4. Don't initialize with README (you already have code)

**Step 3: Connect and Push**
```bash
git remote add origin https://github.com/YOUR_USERNAME/{project_slug}.git
git branch -M main
git push -u origin main
```

**Step 4: Good Commit Messages**
```bash
git commit -m "feat: add user authentication"
git commit -m "fix: resolve login bug"
git commit -m "docs: update README"
```

&#x1F4A1; **Tip:** Commit after completing each feature, not just at the end!""".format(project=project_name, project_slug=project_name.lower().replace(" ","-"))

    if "error" in q or "bug" in q or "not working" in q:
        return """&#x1F50D; **Debugging Your Project**

**Step 1: Read the Error Message**
The error message tells you EXACTLY what went wrong:
- Line number
- Error type (TypeError, ValueError, etc.)
- What Python expected vs what it got

**Step 2: Common Project Errors**
- `ModuleNotFoundError` â†’ pip install the missing library
- `FileNotFoundError` â†’ check file path, use os.path.join()
- `KeyError` â†’ check dict key exists with .get()
- `AttributeError` â†’ check object type before calling method

**Step 3: Debug Strategy**
```python
# Add print statements to trace values
print(f"DEBUG: variable = {variable}")

# Use Python debugger
import pdb; pdb.set_trace()
```

**Step 4: Use AI Mentor**
Paste your error in the AI Mentor tab for specific help!"""

    if "start" in q or "begin" in q or "how" in q:
        return f"""&#x1F680; **How to Start: {project_name}**

**Phase 1: Plan (30 min)**
1. Write down what the project should DO
2. List the features (start with minimum viable)
3. Identify what Python concepts you need
4. Sketch the structure on paper

**Phase 2: Setup (15 min)**
```bash
mkdir {project_name.lower().replace(" ","-")}
cd {project_name.lower().replace(" ","-")}
python -m venv venv
pip install -r requirements.txt
```

**Phase 3: Build Incrementally**
- Build ONE feature at a time
- Test each feature before moving to next
- Commit to Git after each working feature

**Phase 4: Test & Polish**
- Test with different inputs
- Handle edge cases
- Add error handling
- Write a README

&#x1F4A1; **Golden Rule:** Make it work first, then make it better!"""

    if "structure" in q or "folder" in q or "organize" in q:
        return f"""&#x1F4C1; **Project Structure for {project_name}**

```
{project_name.lower().replace(" ","-")}/
â”œâ”€â”€ main.py              # Entry point
â”œâ”€â”€ requirements.txt     # Dependencies
â”œâ”€â”€ README.md           # Documentation
â”œâ”€â”€ .gitignore          # Git ignore file
â”œâ”€â”€ src/                # Source code
â”‚   â”œâ”€â”€ __init__.py
â”‚   â”œâ”€â”€ models.py       # Data models
â”‚   â”œâ”€â”€ utils.py        # Helper functions
â”‚   â””â”€â”€ config.py       # Configuration
â”œâ”€â”€ tests/              # Test files
â”‚   â””â”€â”€ test_main.py
â””â”€â”€ data/               # Data files (if needed)
```

**requirements.txt example:**
```
flask==3.0.0
requests==2.31.0
python-dotenv==1.0.0
```

**README.md template:**
```markdown
# {project_name}
Brief description

## Features
- Feature 1
- Feature 2

## Installation
pip install -r requirements.txt

## Usage
python main.py
```"""

    return f"""&#x1F916; **AI Project Assistant - {project_name}**

Great question! Here's how I can help with your project:

**What I can help with:**
- &#x1F4CB; Project structure and organization
- &#x1F4BB; Code examples for specific features
- &#x1F41B; Debugging errors
- &#x1F4DA; Explaining concepts you need
- &#x1F4C1; GitHub setup and deployment
- &#x26A1; Optimization suggestions

**Your question:** {question}

**Suggestion:** Break your project into small steps:
1. Define what the project does (1 sentence)
2. List 3-5 core features
3. Build feature 1 first
4. Test it works
5. Move to feature 2

**Ask me specifically:**
- "How do I implement [specific feature]?"
- "What libraries do I need for [task]?"
- "How do I connect to a database?"
- "How do I deploy this project?"

I'm here to guide you, not give you the full code â€” that's how you actually learn! &#x1F4AA;"""

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000, use_reloader=False)

