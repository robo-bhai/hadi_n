import os
import base64
import sqlite3
import requests
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash

# Dynamic Database Import (Uses your existing get_db_connection setup)
from master_trader_engine import get_db_connection, init_db

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "hadi88_super_secret_key_2026")

# Dynamic DB Auto-Initialization on start without disturbing existing schemas
init_db()

# =========================================================
# 🔐 AUTHENTICATION & USER MANAGEMENT
# =========================================================

@app.route("/")
def home():
    """
    Root route redirecting authenticated users to dashboard and guest users to login.
    """
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        ntfy_topic = request.form.get("ntfy_topic", "").strip()

        if not username or not password:
            return render_template("signup.html", error="Username and Password required!")

        hashed_pass = generate_password_hash(password)
        conn, db_type = get_db_connection()
        cursor = conn.cursor()
        ph = "%s" if db_type == "MYSQL" else "?"

        try:
            cursor.execute(
                f"INSERT INTO users (username, password_hash, ntfy_topic) VALUES ({ph}, {ph}, {ph})",
                (username, hashed_pass, ntfy_topic)
            )
            conn.commit()
            conn.close()
            return redirect(url_for("login"))
        except Exception as e:
            conn.close()
            return render_template("signup.html", error="Username already exists!")

    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        conn, db_type = get_db_connection()
        cursor = conn.cursor()
        ph = "%s" if db_type == "MYSQL" else "?"

        cursor.execute(f"SELECT id, password_hash, ntfy_topic FROM users WHERE username = {ph}", (username,))
        row = cursor.fetchone()
        conn.close()

        if row and check_password_hash(row[1], password):
            session["user_id"] = row[0]
            session["username"] = username
            session["ntfy_topic"] = row[2]
            return redirect(url_for("dashboard"))
        
        return render_template("login.html", error="Invalid Username or Password!")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/profile", methods=["GET", "POST"])
def profile():
    if "user_id" not in session:
        return redirect(url_for("login"))

    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    ph = "%s" if db_type == "MYSQL" else "?"

    if request.method == "POST":
        new_ntfy = request.form.get("ntfy_topic", "").strip()
        cursor.execute(f"UPDATE users SET ntfy_topic = {ph} WHERE id = {ph}", (new_ntfy, session["user_id"]))
        conn.commit()
        session["ntfy_topic"] = new_ntfy

    cursor.execute(f"SELECT username, ntfy_topic FROM users WHERE id = {ph}", (session["user_id"],))
    user_info = cursor.fetchone()
    conn.close()

    return render_template("profile.html", username=user_info[0], ntfy_topic=user_info[1])

# =========================================================
# 📊 USER DASHBOARD & LIVE API
# =========================================================

@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))

    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    
    # Fully responsive query for both MySQL & SQLite
    cursor.execute("""
        SELECT id, symbol, direction, entry_price, sl_price, tp1_price, tp2_price, card_base64, created_at 
        FROM user_signals 
        ORDER BY id DESC LIMIT 20
    """)

    signals = cursor.fetchall()
    conn.close()

    return render_template("dashboard.html", signals=signals, username=session.get("username"))


@app.route("/api/signals/latest", methods=["GET"])
def get_latest_signals():
    """
    Returns recent signals as JSON for live AJAX dashboard polling.
    """
    if "user_id" not in session:
        return jsonify({"status": "unauthorized"}), 401

    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, symbol, direction, entry_price, sl_price, tp1_price, tp2_price, card_base64, created_at 
        FROM user_signals 
        ORDER BY id DESC LIMIT 20
    """)
    rows = cursor.fetchall()
    conn.close()

    signals_list = []
    for r in rows:
        signals_list.append({
            "id": r[0],
            "symbol": r[1],
            "direction": r[2],
            "entry_price": r[3],
            "sl_price": r[4],
            "tp1_price": r[5],
            "tp2_price": r[6],
            "card_base64": r[7],
            "created_at": str(r[8])
        })

    return jsonify({"status": "success", "signals": signals_list}), 200

# =========================================================
# 📢 SIGNAL BROADCAST ENDPOINT (TRADER ENGINE CALLS THIS)
# =========================================================

@app.route("/api/signals/broadcast", methods=["POST"])
def broadcast_signal():
    """
    Trader engine receives signal, saves to database, and broadcasts to user NTFY topics.
    """
    data = request.json or {}
    symbol = data.get("symbol")
    direction = data.get("direction")
    entry_price = data.get("entry_price")
    sl_price = data.get("sl_price")
    tp1_price = data.get("tp1_price")
    tp2_price = data.get("tp2_price")
    card_b64 = data.get("card_base64", "")
    trade_body = data.get("trade_body", "")

    if not symbol or not direction:
        return jsonify({"status": "error", "message": "Invalid signal payload"}), 400

    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    ph = "%s" if db_type == "MYSQL" else "?"

    # 1. Save Signal to Signals Table for Web Dashboard View
    cursor.execute(f"""
        INSERT INTO user_signals (symbol, direction, entry_price, sl_price, tp1_price, tp2_price, card_base64)
        VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})
    """, (symbol, direction, entry_price, sl_price, tp1_price, tp2_price, card_b64))
    conn.commit()

    # 2. Fetch all User-Configured NTFY Topics
    cursor.execute("SELECT ntfy_topic FROM users WHERE ntfy_topic IS NOT NULL AND ntfy_topic != ''")
    user_topics = [row[0] for row in cursor.fetchall()]
    conn.close()

    # 3. Broadcast Signal Image & Card to all Registered User Topics
    card_bytes = base64.b64decode(card_b64) if card_b64 else None
    title = f"{'🟢' if direction == 'LONG' else '🔴'} SIGNAL: {symbol} ({direction})"
    title_b64 = base64.b64encode(title.encode('utf-8')).decode('utf-8')
    encoded_title = f"=?utf-8?b?{title_b64}?="

    for topic in set(user_topics):
        url = f"https://ntfy.sh/{topic}"
        try:
            if card_bytes:
                body_b64 = base64.b64encode(trade_body.encode('utf-8')).decode('utf-8')
                headers = {
                    "X-Title": encoded_title,
                    "X-Message": f"=?utf-8?b?{body_b64}?=",
                    "Priority": "high",
                    "Tags": "chart_with_upwards_trend,signal_strength",
                    "Filename": f"signal_{symbol}.png",
                    "User-Agent": "Mozilla/5.0"
                }
                requests.put(url, data=card_bytes, headers=headers, timeout=10)
            else:
                headers = {
                    "X-Title": encoded_title,
                    "Priority": "high",
                    "Tags": "chart_with_upwards_trend",
                    "User-Agent": "Mozilla/5.0"
                }
                requests.post(url, data=trade_body.encode("utf-8"), headers=headers, timeout=10)
        except Exception as e:
            print(f"❌ Failed to dispatch NTFY to topic {topic}: {e}")

    return jsonify({"status": "success", "broadcasted_topics_count": len(user_topics)}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
