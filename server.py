import os
import ssl
import base64
import sqlite3
import requests
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from werkzeug.security import generate_password_hash, check_password_hash

# Try importing mysql.connector cleanly
try:
    import mysql.connector
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "hadi88_super_secret_key_2026")


# =========================================================
# 🗄️ DATABASE MANAGEMENT (INTEGRATED & ISOLATED)
# =========================================================

def get_db_connection():
    """
    Connects to MySQL if GitHub Secrets / Env Variables exist with SSL Support.
    Falls back to Local SQLite database seamlessly if MySQL is unavailable.
    """
    db_host = os.environ.get("DB_HOST", "mysql-3a3d5779-project-b71a.b.aivencloud.com")
    db_user = os.environ.get("DB_USER", "avnadmin")
    db_pass = os.environ.get("DB_PASS", os.environ.get("DB_PASSWORD", ""))
    db_name = os.environ.get("DB_NAME", "defaultdb")
    db_port = int(os.environ.get("DB_PORT", "23464"))

    if MYSQL_AVAILABLE and db_host and db_user and db_pass and db_name:
        # Attempt 1: Native SSL Context
        try:
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE

            conn = mysql.connector.connect(
                host=db_host,
                user=db_user,
                password=db_pass,
                database=db_name,
                port=db_port,
                ssl_context=ssl_ctx,
                connect_timeout=30
            )
            return conn, "MYSQL"
        except Exception:
            pass

        # Attempt 2: Standard SSL Fallback
        try:
            conn = mysql.connector.connect(
                host=db_host,
                user=db_user,
                password=db_pass,
                database=db_name,
                port=db_port,
                ssl_disabled=False,
                ssl_verify_cert=False,
                connect_timeout=30
            )
            return conn, "MYSQL"
        except Exception as e:
            print(f"⚠️ MySQL Connection Error: {e}. Falling back to SQLite...")

    # Fallback to Local SQLite DB
    conn = sqlite3.connect("trading_system.db")
    return conn, "SQLITE"


def init_db():
    """
    Ensures required tables exist using users_v2 to preserve existing table data.
    """
    conn, db_type = get_db_connection()
    cursor = conn.cursor()

    ph = "%s" if db_type == "MYSQL" else "?"

    # =========================================================
    # 🐬 MYSQL SCHEMA DEFINITIONS
    # =========================================================
    if db_type == "MYSQL":
        # 1. Portfolio Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS portfolio (
            id INT PRIMARY KEY,
            total_capital DOUBLE,
            available_capital DOUBLE,
            frozen_margin DOUBLE
        )
        """)

        # 2. Trades Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INT AUTO_INCREMENT PRIMARY KEY,
            symbol VARCHAR(20),
            direction VARCHAR(10),
            entry_price DOUBLE,
            sl_price DOUBLE,
            tp1_price DOUBLE,
            tp2_price DOUBLE,
            margin_frozen DOUBLE,
            pos_value DOUBLE,
            coin_qty DOUBLE,
            leverage INT,
            status VARCHAR(20),
            exit_reason VARCHAR(255) NULL,
            close_price DOUBLE NULL,
            pnl DOUBLE NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        )
        """)

        # 3. New Isolated Users Table (Preserves original 'users' table)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users_v2 (
            id INT AUTO_INCREMENT PRIMARY KEY,
            username VARCHAR(100) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            ntfy_topic VARCHAR(100) NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # 4. User Signals Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_signals (
            id INT AUTO_INCREMENT PRIMARY KEY,
            symbol VARCHAR(20),
            direction VARCHAR(10),
            entry_price DOUBLE,
            sl_price DOUBLE,
            tp1_price DOUBLE,
            tp2_price DOUBLE,
            card_base64 LONGTEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # 🛠️ Safe Migrations for MySQL Trades
        mysql_columns_to_add = [
            "ADD COLUMN exit_reason VARCHAR(255) NULL",
            "ADD COLUMN close_price DOUBLE NULL",
            "ADD COLUMN pnl DOUBLE NULL",
            "ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP",
        ]

        for col_statement in mysql_columns_to_add:
            try:
                cursor.execute(f"ALTER TABLE trades {col_statement}")
            except Exception:
                pass

    # =========================================================
    # 🗄️ SQLITE SCHEMA DEFINITIONS (FALLBACK)
    # =========================================================
    else:
        # 1. Portfolio Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS portfolio (
            id INTEGER PRIMARY KEY,
            total_capital REAL,
            available_capital REAL,
            frozen_margin REAL
        )
        """)

        # 2. Trades Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            direction TEXT,
            entry_price REAL,
            sl_price REAL,
            tp1_price REAL,
            tp2_price REAL,
            margin_frozen REAL,
            pos_value REAL,
            coin_qty REAL,
            leverage INTEGER,
            status TEXT,
            exit_reason TEXT NULL,
            close_price REAL NULL,
            pnl REAL NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # 3. New Isolated Users Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users_v2 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            ntfy_topic TEXT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # 4. User Signals Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT,
            direction TEXT,
            entry_price REAL,
            sl_price REAL,
            tp1_price REAL,
            tp2_price REAL,
            card_base64 TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)

        # 🛠️ Safe Migrations for SQLite
        sqlite_columns = [
            ("exit_reason", "TEXT"),
            ("close_price", "REAL"),
            ("pnl", "REAL"),
            ("updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ]
        for col_name, col_type in sqlite_columns:
            try:
                cursor.execute(f"ALTER TABLE trades ADD COLUMN {col_name} {col_type}")
            except Exception:
                pass

    # =========================================================
    # 💰 PORTFOLIO INITIAL SEED RECORD
    # =========================================================
    cursor.execute(f"SELECT COUNT(*) FROM portfolio WHERE id = {ph}", (1,))
    if cursor.fetchone()[0] == 0:
        cursor.execute(
            f"INSERT INTO portfolio (id, total_capital, available_capital, frozen_margin) VALUES ({ph}, 100.0, 100.0, 0.0)",
            (1,),
        )

    conn.commit()
    conn.close()


# Auto Initialize DB schemas on server boot
init_db()


# =========================================================
# 👤 AUTHENTICATION & USER MANAGEMENT
# =========================================================

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
                f"INSERT INTO users_v2 (username, password_hash, ntfy_topic) VALUES ({ph}, {ph}, {ph})",
                (username, hashed_pass, ntfy_topic)
            )
            conn.commit()
            conn.close()
            return redirect(url_for("login"))
        except Exception as e:
            conn.close()
            print(f"Signup Error Details: {e}")
            return render_template("signup.html", error=f"Signup failed: {str(e)}")

    return render_template("signup.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()

        conn, db_type = get_db_connection()
        cursor = conn.cursor()
        ph = "%s" if db_type == "MYSQL" else "?"

        cursor.execute(f"SELECT id, password_hash, ntfy_topic FROM users_v2 WHERE username = {ph}", (username,))
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
        cursor.execute(f"UPDATE users_v2 SET ntfy_topic = {ph} WHERE id = {ph}", (new_ntfy, session["user_id"]))
        conn.commit()
        session["ntfy_topic"] = new_ntfy

    cursor.execute(f"SELECT username, ntfy_topic FROM users_v2 WHERE id = {ph}", (session["user_id"],))
    user_info = cursor.fetchone()
    conn.close()

    return render_template("profile.html", username=user_info[0], ntfy_topic=user_info[1])


# =========================================================
# 📊 USER DASHBOARD
# =========================================================

@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))

    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, symbol, direction, entry_price, sl_price, tp1_price, tp2_price, card_base64, created_at FROM user_signals ORDER BY id DESC LIMIT 20")
    signals = cursor.fetchall()
    conn.close()

    return render_template("dashboard.html", signals=signals, username=session.get("username"))


# =========================================================
# 🚀 SIGNAL BROADCAST ENDPOINT (TRADER ENGINE CALLS THIS)
# =========================================================

@app.route("/api/signals/broadcast", methods=["POST"])
def broadcast_signal():
    """
    Trader engine signal receive karke DB mein save karta hai aur sabhi Users ke NTFY topics par push kar deta hai.
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

    # 2. Fetch all User-Configured NTFY Topics from users_v2
    cursor.execute("SELECT ntfy_topic FROM users_v2 WHERE ntfy_topic IS NOT NULL AND ntfy_topic != ''")
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
    app.run(host="0.0.0.0", port=5000, debug=True)
