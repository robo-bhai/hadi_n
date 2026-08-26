import os
import time
import math
import sqlite3
import requests
import pandas as pd
import ssl

# MySQL Connector for Remote DB / GitHub Secrets
try:
    import mysql.connector
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False

# =========================================================
# ⚙️ API ENDPOINTS (Clean Data API Endpoints)
# =========================================================
BINANCE_SPOT_URL = 'https://data-api.binance.vision/api/v3/klines'
BINANCE_BOOK_TICKER_URL = 'https://data-api.binance.vision/api/v3/ticker/bookTicker'
BINANCE_FUTURES_DEPTH_URL = 'https://data-api.binance.vision/api/v3/depth'

BINANCE_FUTURES_FUNDING_URL = 'https://fapi.binance.com/fapi/v1/premiumIndex'
BINANCE_FUTURES_OI_URL = 'https://fapi.binance.com/fapi/v1/openInterest'

# =========================================================
# 📲 PUSHBULLET NOTIFICATION ENGINE
# =========================================================
# =========================================================
# 📲 NTFY NOTIFICATION ENGINE (STRICT GITHUB SECRETS MODE)
# =========================================================
# =========================================================
# 📲 NTFY NOTIFICATION ENGINES (SPLIT TOPICS)
# =========================================================

# =========================================================
# 📲 HARDCODED NTFY NOTIFICATION ENGINES
# =========================================================

import base64
import requests

def send_pushbullet_notification(title, body):
    """
    Sends Rejections, Warnings, Skips, and Errors to HARDCODED Topic.
    """
    topic = "trhdjdj_jxauuwg6_xczs"
    url = f"https://ntfy.sh/{topic}"

    # Base64 encoding supports full Unicode & Emojis without header failures
    title_b64 = base64.b64encode(title.encode('utf-8')).decode('utf-8')

    headers = {
        "X-Title": f"=?utf-8?b?{title_b64}?=",
        "Priority": "high",
        "Tags": "warning,no_entry",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    }

    try:
        res = requests.post(url, data=body.encode("utf-8"), headers=headers, timeout=10)
        if res.status_code == 200:
            print(f"🚀 Alert sent to topic ({topic}): {title}")
        else:
            print(f"❌ Failed to send alert: Status {res.status_code} - {res.text}")
    except Exception as e:
        print(f"❌ ntfy API Request Error: {e}")


def send_ex_trade_signal(trade_title, trade_body, card_png_bytes=None):
    """
    Sends EXECUTED SIGNALS + Image Card to HARDCODED EX_TRADE Topic.
    """
    topic = "lskejej_hdhehje"
    url = f"https://ntfy.sh/{topic}"

    # UTF-8 Encoding for Header Safety with Emojis
    title_b64 = base64.b64encode(trade_title.encode('utf-8')).decode('utf-8')
    encoded_title = f"=?utf-8?b?{title_b64}?="

    try:
        if card_png_bytes:
            # Body text base64 encoded for X-Message header safety
            body_b64 = base64.b64encode(trade_body.encode('utf-8')).decode('utf-8')
            
            headers = {
                "X-Title": encoded_title,
                "X-Message": f"=?utf-8?b?{body_b64}?=",
                "Priority": "high",
                "Tags": "chart_with_upwards_trend,signal_strength",
                "Filename": "signal_card.png",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
            }
            res = requests.put(url, data=card_png_bytes, headers=headers, timeout=12)
        else:
            headers = {
                "X-Title": encoded_title,
                "Priority": "high",
                "Tags": "chart_with_upwards_trend,signal_strength",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
            }
            res = requests.post(url, data=trade_body.encode("utf-8"), headers=headers, timeout=10)

        if res.status_code == 200:
            print(f"🚀 EXECUTED SIGNAL sent to topic ({topic})")
        else:
            print(f"❌ Failed to send Signal: Status {res.status_code} - {res.text}")
    except Exception as e:
        print(f"❌ Signal Notification Error: {e}")

# =========================================================
# 🔌 DATABASE CONNECTION ENGINE (MYSQL + SQLITE FALLBACK)
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
    Ensures required tables (portfolio, trades) exist in MySQL/SQLite.
    Handles dynamic column migrations for existing MySQL production databases.
    """
    conn, db_type = get_db_connection()
    cursor = conn.cursor()

    ph = "%s" if db_type == "MYSQL" else "?"

    # Create Portfolio & Trades Tables
    if db_type == "MYSQL":
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS portfolio (
            id INT PRIMARY KEY,
            total_capital DOUBLE,
            available_capital DOUBLE,
            frozen_margin DOUBLE
        )
        """)
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

        # 🛠️ Safe Migration: Existing MySQL Table Par Columns Add Karna
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
                pass  # Column pehle se majood hone par error skip karega
    else:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS portfolio (
            id INTEGER PRIMARY KEY,
            total_capital REAL,
            available_capital REAL,
            frozen_margin REAL
        )
        """)
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

        # 🛠️ Safe Migration: SQLite Fallback DB Ke Liye
        sqlite_columns = [
            ("exit_reason", "TEXT"),
            ("close_price", "REAL"),
            ("pnl", "REAL"),
            ("updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ]
        for col_name, col_type in sqlite_columns:
            try:
                cursor.execute(
                    f"ALTER TABLE trades ADD COLUMN {col_name} {col_type}"
                )
            except Exception:
                pass

    # Check Portfolio Record 1
    cursor.execute(f"SELECT COUNT(*) FROM portfolio WHERE id = {ph}", (1,))
    if cursor.fetchone()[0] == 0:
        cursor.execute(
            f"INSERT INTO portfolio (id, total_capital, available_capital, frozen_margin) VALUES ({ph}, 100.0, 100.0, 0.0)",
            (1,),
        )

    conn.commit()
    conn.close()


# Initialize DB structure on load
init_db()



# =========================================================
# 📊 DATABASE QUERIES & PORTFOLIO STATE
# =========================================================

from datetime import datetime

def check_dynamic_cooldown(symbol):
    """
    Checks if symbol is in dynamic cooldown based on last trade outcome.
    - SL Hit / Loss: 24 Hours Cooldown
    - TP Hit / Profit: 4 Hours Cooldown
    """
    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    ph = "%s" if db_type == "MYSQL" else "?"

    # Get the latest closed trade for this symbol
    query = f"""
        SELECT status, exit_reason, updated_at 
        FROM trades 
        WHERE symbol = {ph} AND status != {ph}
        ORDER BY updated_at DESC LIMIT 1
    """
    cursor.execute(query, (symbol, 'ACTIVE'))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return False, ""

    status = str(row[0] or "").upper()
    exit_reason = str(row[1] or "").upper()
    last_time = row[2]

    # Handle string timestamp from SQLite fallback
    if isinstance(last_time, str):
        try:
            last_time = datetime.strptime(last_time, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            last_time = datetime.strptime(last_time.split('.')[0], "%Y-%m-%d %H:%M:%S")

    time_diff = datetime.now() - last_time
    hours_passed = time_diff.total_seconds() / 3600.0

    # 1. Stop Loss Cooldown (24 Hours)
    if "SL" in status or "SL" in exit_reason or "STOP" in status or "LOSS" in exit_reason:
        if hours_passed < 24.0:
            remaining = 24.0 - hours_passed
            return True, f"24H SL Cooldown Active! Last trade hit SL {hours_passed:.1f}h ago. Wait {remaining:.1f}h more."

    # 2. Take Profit / Normal Close Cooldown (4 Hours)
    else:
        if hours_passed < 4.0:
            remaining = 4.0 - hours_passed
            return True, f"4H TP Cooldown Active! Last trade closed successfully {hours_passed:.1f}h ago. Wait {remaining:.1f}h more."

    return False, ""






def load_portfolio():
    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    ph = "%s" if db_type == "MYSQL" else "?"
    cursor.execute(f"SELECT total_capital, available_capital, frozen_margin FROM portfolio WHERE id = {ph}", (1,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {"total": float(row[0]), "available": float(row[1]), "frozen": float(row[2])}
    return {"total": 100.0, "available": 100.0, "frozen": 0.0}

def get_active_trades_count():
    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    ph = "%s" if db_type == "MYSQL" else "?"
    cursor.execute(f"SELECT COUNT(*) FROM trades WHERE status = {ph}", ('ACTIVE',))
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_active_symbols():
    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    ph = "%s" if db_type == "MYSQL" else "?"
    cursor.execute(f"SELECT symbol FROM trades WHERE status = {ph}", ('ACTIVE',))
    rows = cursor.fetchall()
    conn.close()
    return [r[0] for r in rows]

def is_coin_trade_active(symbol):
    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    ph = "%s" if db_type == "MYSQL" else "?"
    cursor.execute(f"SELECT COUNT(*) FROM trades WHERE symbol = {ph} AND status = {ph}", (symbol, 'ACTIVE'))
    count = cursor.fetchone()[0]
    conn.close()
    return count > 0

def save_trade_to_db(trade_data):
    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    ph = "%s" if db_type == "MYSQL" else "?"

    insert_query = f"""
    INSERT INTO trades (symbol, direction, entry_price, sl_price, tp1_price, tp2_price, margin_frozen, pos_value, coin_qty, leverage, status)
    VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, 'ACTIVE')
    """
    cursor.execute(insert_query, (
        trade_data['symbol'], trade_data['direction'], trade_data['entry_price'],
        trade_data['sl_price'], trade_data['tp1_price'], trade_data['tp2_price'],
        trade_data['margin_frozen'], trade_data['pos_value'], trade_data['coin_qty'], trade_data['leverage']
    ))

    new_available = trade_data['available_cap'] - trade_data['margin_frozen']
    new_frozen = trade_data['frozen_cap'] + trade_data['margin_frozen']

    update_query = f"""
    UPDATE portfolio 
    SET available_capital = {ph}, frozen_margin = {ph}
    WHERE id = {ph}
    """
    cursor.execute(update_query, (new_available, new_frozen, 1))

    conn.commit()
    conn.close()
    print(f"\n💾 [{db_type} DATABASE] Trade Saved! ${trade_data['margin_frozen']:.2f} Margin Frozen. Available Capital: ${new_available:.2f}")

# =========================================================
# 📈 TECHNICAL INDICATORS & DATA FETCHERS
# =========================================================
import numpy as np
import pandas as pd
import requests

# ------------------------------------------------------------------------------
# 1. TECHNICAL INDICATORS (TradingView / Quant-Grade Precision)
# ------------------------------------------------------------------------------

def calculate_rsi(series, period=14):
    """Wilder's Smoothing RSI (Matches Binance & TradingView native indicators)"""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    
    # Wilder's Exponential Moving Average (alpha = 1 / period)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    
    avg_loss = avg_loss.replace(0, 1e-9)
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calculate_atr(df, period=14):
    """Wilder's Smoothing ATR (RMA) with Zero Copy Overhead"""
    high = df['high']
    low = df['low']
    close_prev = df['close'].shift(1)
    
    tr1 = high - low
    tr2 = (high - close_prev).abs()
    tr3 = (low - close_prev).abs()
    
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    # TradingView style RMA smoothing
    atr = tr.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    return atr

def calculate_adx(df, period=14):
    """Full Directional Movement Index (ADX) with Precision Smoothings"""
    try:
        df_calc = df.copy()
        high = df_calc['high']
        low = df_calc['low']
        
        up_move = high - high.shift(1)
        down_move = low.shift(1) - low
        
        plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
        
        atr = calculate_atr(df_calc, period).replace(0, 1e-9)
        
        plus_di = 100 * (pd.Series(plus_dm, index=df_calc.index).ewm(alpha=1/period, adjust=False).mean() / atr)
        minus_di = 100 * (pd.Series(minus_dm, index=df_calc.index).ewm(alpha=1/period, adjust=False).mean() / atr)
        
        di_sum = (plus_di + minus_di).replace(0, 1e-9)
        dx = 100 * (plus_di - minus_di).abs() / di_sum
        
        adx = dx.ewm(alpha=1/period, adjust=False).mean()
        return float(adx.iloc[-1]) if not adx.empty else 0.0
    except Exception:
        return 0.0

# ------------------------------------------------------------------------------
# 2. MARKET DATA FETCHERS (Speed & Reliability Optimized)
# ------------------------------------------------------------------------------

def fetch_klines(symbol, interval="4h", limit=100):
    url = f"{BINANCE_SPOT_URL}?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        res = requests.get(url, timeout=5)
        if res.status_code != 200:
            return None
        data = res.json()
        if not data or not isinstance(data, list):
            return None
            
        df = pd.DataFrame(data, columns=['time', 'open', 'high', 'low', 'close', 'volume', '_', '_', '_', '_', '_', '_'])
        cols = ['open', 'high', 'low', 'close', 'volume']
        df[cols] = df[cols].astype(float)
        return df
    except Exception:
        return None

def fetch_funding_rate(symbol):
    try:
        url = f"{BINANCE_FUTURES_FUNDING_URL}?symbol={symbol}"
        res = requests.get(url, timeout=4)
        if res.status_code == 200:
            val = res.json().get('lastFundingRate')
            return float(val) * 100 if val is not None else 0.0
    except Exception:
        pass
    return 0.0

def fetch_orderbook_imbalance(symbol):
    try:
        url = f"{BINANCE_FUTURES_DEPTH_URL}?symbol={symbol}&limit=20"
        res = requests.get(url, timeout=4)
        if res.status_code == 200:
            data = res.json()
            bids = data.get('bids', [])
            asks = data.get('asks', [])
            
            bids_vol = sum(float(item[1]) for item in bids)
            asks_vol = sum(float(item[1]) for item in asks)
            
            ratio = bids_vol / asks_vol if asks_vol > 0 else 1.0
            return float(ratio), float(bids_vol), float(asks_vol)
    except Exception:
        pass
    return 1.0, 0.0, 0.0

def fetch_open_interest(symbol):
    try:
        url = f"{BINANCE_FUTURES_OI_URL}?symbol={symbol}"
        res = requests.get(url, timeout=4)
        if res.status_code == 200:
            val = res.json().get('openInterest')
            return float(val) if val is not None else 0.0
    except Exception:
        pass
    return 0.0

from datetime import datetime, timedelta

def check_daily_drawdown_limit(max_daily_loss_pct=1.5, max_sl_count=2):
    """
    Checks if Daily Drawdown Limit (1.5% Equity) or Max SL Count (2 SLs) hit in last 24h.
    Returns: (is_halted, reason_msg)
    """
    port = load_portfolio()
    total_capital = port['total']
    max_allowed_daily_loss = total_capital * (max_daily_loss_pct / 100.0)

    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    ph = "%s" if db_type == "MYSQL" else "?"

    # Get all closed trades from the last 24 hours
    if db_type == "MYSQL":
        query = f"""
            SELECT status, exit_reason, pnl, updated_at 
            FROM trades 
            WHERE status != {ph} AND updated_at >= NOW() - INTERVAL 24 HOUR
            ORDER BY updated_at DESC
        """
    else:  # SQLite Fallback
        query = f"""
            SELECT status, exit_reason, pnl, updated_at 
            FROM trades 
            WHERE status != {ph} AND updated_at >= datetime('now', '-1 day')
            ORDER BY updated_at DESC
        """

    cursor.execute(query, ('ACTIVE',))
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return False, ""

    sl_count = 0
    total_daily_loss = 0.0

    for row in rows:
        status = str(row[0] or "").upper()
        exit_reason = str(row[1] or "").upper()
        pnl = float(row[2] or 0.0)

        # 1. SL Count Logic
        if "SL" in status or "SL" in exit_reason or "STOP" in status:
            sl_count += 1

        # 2. Daily Loss Tracking
        if pnl < 0:
            total_daily_loss += abs(pnl)

    # 🛑 GUARD 1: Max SL Hit Guard (2 SLs Limit)
    if sl_count >= max_sl_count:
        return True, f"Daily Circuit Breaker! {sl_count} Stop-Losses hit in last 24h. Bot HALTED for today."

    # 🛑 GUARD 2: Max Daily Drawdown Guard (1.5% Capital Loss)
    if total_daily_loss >= max_allowed_daily_loss:
        return True, f"Daily Risk Limit Hit! Realized Loss: ${total_daily_loss:.2f} (>= 1.5% of ${total_capital:.2f}). Bot HALTED for today."

    return False, ""



# ------------------------------------------------------------------------------
# 3. PORTFOLIO & MACRO EXPOSURE ENGINE
# ------------------------------------------------------------------------------

CORRELATION_GROUPS = {
    'LAYER_1': ['SOLUSDT', 'SUIUSDT', 'AVAXUSDT', 'NEARUSDT', 'APTUSDT', 'DOTUSDT', 'LTCUSDT'],
    'MEMES': ['DOGEUSDT', 'SHIBUSDT', 'PEPEUSDT', 'BONKUSDT', 'FLOKIUSDT', 'WIFUSDT'],
    'DEFI': ['INJUSDT', 'LINKUSDT', 'UNIUSDT', 'LDOUSDT', 'AAVEUSDT']
}

def check_correlation_exposure(symbol_input):
    active_symbols = get_active_symbols()
    symbol_clean = str(symbol_input).upper().strip()
    target_group = None
    
    for group, coins in CORRELATION_GROUPS.items():
        if symbol_clean in coins:
            target_group = group
            break

    if target_group:
        active_set = set(str(s).upper().strip() for s in active_symbols)
        for act in active_set:
            if act in CORRELATION_GROUPS[target_group] and act != symbol_clean:
                return True, f"High Correlation Exposure! Already running [{act}] from {target_group} category."
    return False, ""

def get_btc_regime():
    df_daily = fetch_klines("BTCUSDT", interval="1d", limit=60)
    if df_daily is None or len(df_daily) < 50:
        return "NEUTRAL", 0.0
        
    ema_20 = df_daily['close'].ewm(span=20, adjust=False).mean()
    ema_50 = df_daily['close'].ewm(span=50, adjust=False).mean()
    
    latest_close = float(df_daily['close'].iloc[-1])
    latest_ema20 = float(ema_20.iloc[-1])
    latest_ema50 = float(ema_50.iloc[-1])
    
    if latest_close > latest_ema20 and latest_ema20 > latest_ema50:
        return "BULLISH", latest_close
    elif latest_close < latest_ema20 and latest_ema20 < latest_ema50:
        return "BEARISH", latest_close
    return "CHOPPY", latest_close

def check_micro_momentum(df, direction):
    # Data glitch ya kam candles hone par True return karein taakay valid trade block na ho
    if df is None or len(df) < 5:
        return True
        
    df_m = df.copy()
    ema_3 = df_m['close'].ewm(span=3, adjust=False).mean()
    ema_8 = df_m['close'].ewm(span=8, adjust=False).mean()

    latest_ema3 = ema_3.iloc[-1]
    latest_ema8 = ema_8.iloc[-1]

    # Optimized Expert Logic: Lagging ROC ko remove kar ke fast EMA alignment use ki hai
    if direction == "LONG":
        return latest_ema3 >= latest_ema8
    elif direction == "SHORT":
        return latest_ema3 <= latest_ema8

    return False



# =========================================================
# 🏛️ CORE TRADE EXECUTION LOGIC
# =========================================================

import io
from PIL import Image, ImageDraw, ImageFont

def generate_signal_card(symbol, direction, leverage, live_price, sl_price, tp1_price, tp2_price, margin, pos_value, net_tp1, net_tp2, rrr):
    """
    Generates a professional dark-themed trading signal card as bytes.
    """
    # Canvas Dimensions & Colors
    width, height = 800, 500
    bg_color = (15, 23, 42)      # Slate Dark 900
    card_bg = (30, 41, 59)       # Slate Dark 800
    text_white = (248, 250, 252)
    text_gray = (148, 163, 184)
    green = (34, 197, 94)        # Long Accent
    red = (239, 68, 68)          # Short Accent

    accent_color = green if direction == "LONG" else red

    img = Image.new("RGB", (width, height), bg_color)
    draw = ImageDraw.Draw(img)

    # Outer Border & Card Header
    draw.rectangle([20, 20, width - 20, height - 20], fill=card_bg, outline=accent_color, width=2)
    draw.rectangle([20, 20, width - 20, 90], fill=accent_color)

    # Load Default Fonts
    font_title = ImageFont.load_default()
    font_body = ImageFont.load_default()

    # Header Text
    header_text = f"QUANT SIGNAL: {direction} #{symbol} ({leverage}x Cross)"
    draw.text((40, 42), header_text, fill=(255, 255, 255), font=font_title)

    # Signal Data Sections
    lines = [
        f"ENTRY PRICE : ${live_price:.4f}",
        f"STOP LOSS   : ${sl_price:.4f}",
        f"TARGET 1    : ${tp1_price:.4f} (Net Profit: +${net_tp1:.2f})",
        f"TARGET 2    : ${tp2_price:.4f} (Net Profit: +${net_tp2:.2f})",
        "---------------------------------------------------",
        f"MARGIN USED : ${margin:.2f} USDT",
        f"POS VALUE   : ${pos_value:.2f} USDT",
        f"RISK/REWARD : 1:{rrr:.2f}"
    ]

    y_offset = 120
    for line in lines:
        color = text_white if ":" in line else text_gray
        draw.text((50, y_offset), line, fill=color, font=font_body)
        y_offset += 40

    # Save to Bytes Buffer
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format='PNG')
    return img_byte_arr.getvalue()


def process_trade_logic(symbol_input, base_risk_pct=1.5):
    """
    Main Trader Engine execution logic with Scalp-Optimized Dynamic Key-Level RRR (Min 1:0.3) & Strict 1% Total Risk Guard.
    """
    port = load_portfolio()
    active_count = get_active_trades_count()
    
    print("=" * 70)
    print(f"   🏛️ MASTER TRADER ENGINE v4.5 | Processing: [{symbol_input}]")
    print("=" * 70)
    print(f"💼 PORTFOLIO: Total: ${port['total']:.2f} | Available: ${port['available']:.2f} | Frozen: ${port['frozen']:.2f}")
    print(f"📊 ACTIVE TRADES IN DB: {active_count}/5")
    print("=" * 70)
    # 🔴 GLOBAL EARLY GUARD 0: Daily Risk Circuit Breaker (2 SLs / 1.5% Loss Limit)
    is_halted, halt_reason = check_daily_drawdown_limit(max_daily_loss_pct=1.5, max_sl_count=5)
    if is_halted:
        msg = f"🛑 EMERGENCY STOP: {halt_reason}"
        print(f"\n{msg}\n")
        send_pushbullet_notification(f"🛑 [DAILY CIRCUIT BREAKER] {symbol_input}", msg)
        return False

    # 🔴 EARLY GUARD 1: Active Trades Limit Check (Top-Level)
    if active_count >= 5:
        msg = f"⚠️ Trade Skipped for [{symbol_input}]: Maximum 5 Active Trades limit reached ({active_count}/5)."
        print(f"\n{msg}\n")
        send_pushbullet_notification(f"⚠️ [MAX LIMIT REACHED] {symbol_input}", msg)
        return False

    # 🔴 EARLY GUARD 2: Low Available Capital
    if port['available'] < 5.0:
        msg = f"❌ Low Available Capital (${port['available']:.2f} USDT). Cannot place trade."
        print(msg)
        send_pushbullet_notification(f"🚫 [TRADE REJECTED] {symbol_input}", msg)
        return False

    # 🔴 EARLY GUARD 3: Duplicate Active Pair Check
    if is_coin_trade_active(symbol_input):
        msg = f"❌ TRADE REJECTED: An ACTIVE trade for [{symbol_input}] is ALREADY RUNNING!"
        print(f"\n{msg}\n")
        send_pushbullet_notification(f"🚫 [TRADE REJECTED] {symbol_input}", msg)
        return False

    # 🔴 EARLY GUARD 3.5: Dynamic Cooldown Check (SL = 24H | TP = 4H)
    is_blocked, cooldown_msg = check_dynamic_cooldown(symbol_input)
    if is_blocked:
        msg = f"🚫 TRADE REJECTED: [{symbol_input}] - {cooldown_msg}"
        print(f"\n{msg}\n")
        send_pushbullet_notification(f"🚫 [DYNAMIC COOLDOWN] {symbol_input}", msg)
        return False

    # 🔴 EARLY GUARD 4: Sector/Category Correlation Exposure Check
    corr_risk, corr_msg = check_correlation_exposure(symbol_input)
    if corr_risk:
        msg = f"⚠️ CORRELATION BLOCKED: {corr_msg}"
        print(f"\n{msg}\n")
        send_pushbullet_notification(f"🚫 [TRADE REJECTED] {symbol_input}", msg)
        return False

    print(f"\n⏳ Fetching Live Market Data, Orderbook Depth & OI for [{symbol_input}]...")
    
    btc_regime, btc_price = get_btc_regime()
    df_1d = fetch_klines(symbol_input, interval="1d", limit=60)
    df_4h = fetch_klines(symbol_input, interval="4h", limit=60)
    df_15m = fetch_klines(symbol_input, interval="15m", limit=60)
    df_5m = fetch_klines(symbol_input, interval="5m", limit=60)

    if df_1d is None or df_4h is None or df_15m is None or df_5m is None:
        msg = f"❌ Error: Invalid symbol or Binance API fetch error for {symbol_input}"
        print(msg)
        send_pushbullet_notification(f"⚠️ [API ERROR] {symbol_input}", msg)
        return False

    df_1d['EMA_20'] = df_1d['close'].ewm(span=20, adjust=False).mean()
    df_4h['EMA_20'] = df_4h['close'].ewm(span=20, adjust=False).mean()
    df_4h['RSI'] = calculate_rsi(df_4h['close'], 14)
    df_4h['Vol_SMA'] = df_4h['volume'].rolling(20).mean()
    df_4h['ATR'] = calculate_atr(df_4h, 14)

    curr_1d, curr_4h, curr_15m = df_1d.iloc[-1], df_4h.iloc[-1], df_15m.iloc[-1]
    live_price = curr_15m['close']
    rsi_4h = curr_4h['RSI']
    adx_4h = calculate_adx(df_4h, 14)
    atr_val = curr_4h['ATR']
    funding_rate = fetch_funding_rate(symbol_input)
    ob_ratio, bids_vol, asks_vol = fetch_orderbook_imbalance(symbol_input)
    open_interest = fetch_open_interest(symbol_input)
    vol_spike = curr_4h['volume'] > (curr_4h['Vol_SMA'] * 1.25)

    recent_20_4h = df_4h.tail(20)
    support_4h = recent_20_4h['low'].min()
    resistance_4h = recent_20_4h['high'].max()

    atr_pct = (atr_val / live_price) * 100
    if atr_pct > 3.5:  
        volatility_state, leverage = "HIGH ⚡", 1
    elif atr_pct < 1.2:  
        volatility_state, leverage = "LOW 🧊", 3
    else:
        volatility_state, leverage = "NORMAL 🟢", 2

    # =========================================================
    # 🎯 FULLY SYNCED QUANT SCORING ENGINE
    # =========================================================
    score = 50
    reasons = []

    # 1. Trend Alignment (MTF EMA)
    if curr_1d['close'] > curr_1d['EMA_20'] and curr_4h['close'] > curr_4h['EMA_20']:
        score += 15
        reasons.append("Bullish MTF Alignment (+15)")
    elif curr_1d['close'] < curr_1d['EMA_20'] and curr_4h['close'] < curr_4h['EMA_20'] and rsi_4h > 35:
        score -= 15
        reasons.append("Bearish MTF Alignment (-15)")

    # 2. Strong Trend Boost (ADX Filter)
    if adx_4h >= 30.0:
        score += 10
        reasons.append(f"Strong Trend ADX ({adx_4h:.1f}) (+10)")

    # 3. RSI Logic (Trend-Aware)
    if rsi_4h <= 35:
        score += 20
        reasons.append(f"4H RSI Oversold ({rsi_4h:.1f}) (+20)")
    elif rsi_4h >= 75:
        score -= 20
        reasons.append(f"4H RSI Overbought ({rsi_4h:.1f}) (-20)")
    elif 55 <= rsi_4h < 75 and adx_4h >= 25.0:
        score += 10
        reasons.append(f"Bullish RSI Momentum Zone ({rsi_4h:.1f}) (+10)")

    # 4. Volume Spike
    if vol_spike:
        score += 10 if score >= 50 else -10
        reasons.append("Volume Spike (+10)")

    # 5. Order Book Depth Imbalance
    if ob_ratio >= 1.20:
        score += 10
        reasons.append(f"Orderbook Bid Support ({ob_ratio:.2f}x) (+10)")
    elif ob_ratio <= 0.80:
        score -= 10
        reasons.append(f"Orderbook Ask Pressure ({ob_ratio:.2f}x) (-10)")

    # 6. Short Squeeze & Funding Rate
    if funding_rate < -0.01:
        score += 15
        reasons.append(f"Short Squeeze Potential ({funding_rate:.4f}%) (+15)")
    elif funding_rate > 0.03:
        score -= 15
        reasons.append(f"Long Flush Scent ({funding_rate:.4f}%) (-15)")

    trade_possible = True
    direction = "NONE"

    if score >= 58:
        if btc_regime == "BEARISH" and symbol_input != "BTCUSDT":
            trade_possible = False
            status_msg = "⚠️ NO TRADE: Macro BTC Trend is BEARISH"
        else:
            direction = "LONG"
    elif score <= 42:
        if btc_regime == "BULLISH" and symbol_input != "BTCUSDT":
            trade_possible = False
            status_msg = "⚠️ NO TRADE: Macro BTC Trend is BULLISH"
        else:
            direction = "SHORT"
    else:
        trade_possible = False
        status_msg = "💤 NO TRADE: Score in Chop Zone (42-57)"

    if trade_possible:
        micro_15m = check_micro_momentum(df_15m, direction)
        micro_5m = check_micro_momentum(df_5m, direction)

        if not (micro_15m or micro_5m):
            # 💡 High Quant Score Bypass Guard
            if (direction == "LONG" and score >= 70) or (direction == "SHORT" and score <= 30):
                print(f"⚡ High Score ({score}): Overriding Micro-Delay for Instant Execution!")
            else:
                trade_possible = False
                status_msg = f"⏳ NO TRADE: Waiting for Micro-Timeframe Alignment"

    print("\n" + "=" * 70)
    print(f"📊 LIVE QUANT REPORT: [{symbol_input}] | Score: {score}/100")
    print(f"💰 Price: ${live_price:.4f} | Funding: {funding_rate:.4f}% | RSI: {rsi_4h:.2f} | ADX: {adx_4h:.2f}")
    print(f"🌊 Volatility: {volatility_state} | OrderBook Ratio: {ob_ratio:.2f}x | Open Interest: {open_interest:,.0f}")
    print("=" * 70)

    if not trade_possible:
        print(f"\n🚫 TRADE STATUS: {status_msg}\n")
        
        no_trade_body = f"🪙 Pair: {symbol_input}\n"
        no_trade_body += f"📊 Quant Score: {score}/100\n"
        no_trade_body += f"💰 Current Price: ${live_price:.4f}\n"
        no_trade_body += f"🌐 BTC Regime: {btc_regime}\n"
        no_trade_body += f"📈 RSI (4H): {rsi_4h:.1f} | ADX: {adx_4h:.1f}\n"
        no_trade_body += f"🛑 Status / Reason: {status_msg}\n\n"
        if reasons:
            no_trade_body += "💡 Confluences Evaluated:\n"
            for r in reasons:
                no_trade_body += f"   • {r}\n"
                
        send_pushbullet_notification(f"💤 [NO TRADE] {symbol_input} (Score: {score})", no_trade_body)
        return False

    # =========================================================
    # 🎯 DYNAMIC KEY-LEVEL RRR & STRICT 1% RISK ALLOCATION ENGINE
    # =========================================================
    total_account_capital = port['total']
    max_allowed_dollar_risk = total_account_capital * 0.01  # Exact 1% Total Equity Risk ($1.00 USDT)
    atr_sl_buffer = atr_val * 1.5

    if direction == "LONG":
        sl_price = min(live_price - atr_sl_buffer, support_4h * 0.995)
        risk_dist = live_price - sl_price
        
        # Expanded Scalp Target for Optimized RRR (1.5x ATR)
        tp1_price = live_price + (atr_val * 1.5)
        tp2_price = resistance_4h
        
        reward_dist = tp1_price - live_price
        calculated_rrr = reward_dist / risk_dist if risk_dist > 0 else 0
        breakeven_lock_level = tp1_price

    elif direction == "SHORT":
        sl_price = max(live_price + atr_sl_buffer, resistance_4h * 1.005)
        risk_dist = sl_price - live_price
        
        # Expanded Scalp Target for Optimized RRR (1.5x ATR)
        tp1_price = live_price - (atr_val * 1.5)
        tp2_price = support_4h
        
        reward_dist = live_price - tp1_price
        calculated_rrr = reward_dist / risk_dist if risk_dist > 0 else 0
        breakeven_lock_level = tp1_price

    # 🛑 SCALP-OPTIMIZED FILTER 1: Minimum Risk-to-Reward Ratio Guard (Min 1:0.3)
    MIN_REQUIRED_RRR = 0.2
    if calculated_rrr < MIN_REQUIRED_RRR:
        msg = f"🚫 TRADE REJECTED: Low Risk-to-Reward Ratio (1:{calculated_rrr:.2f}). Minimum 1:{MIN_REQUIRED_RRR} Required!"
        print(f"\n{msg}\n")
        send_pushbullet_notification(f"🚫 [LOW RRR REJECTED] {symbol_input}", msg)
        return False

    # 🛑 STRICT FILTER 2: Total Capital 1% Risk Based Position Sizing
    sl_dist_pct = (risk_dist / live_price) * 100
    if sl_dist_pct <= 0:
        msg = f"❌ TRADE REJECTED: Invalid SL distance percentage ({sl_dist_pct:.2f}%)."
        print(f"\n{msg}\n")
        return False

    pos_value = max_allowed_dollar_risk / (sl_dist_pct / 100.0)
    required_margin = pos_value / leverage
    coin_qty = pos_value / live_price
    dollar_risk = max_allowed_dollar_risk

    # Capital Check
    if required_margin > port['available']:
        msg = f"❌ TRADE REJECTED: Required Margin (${required_margin:.2f}) exceeds Available Capital (${port['available']:.2f})."
        print(f"\n{msg}\n")
        send_pushbullet_notification(f"🚫 [INSUFFICIENT MARGIN] {symbol_input}", msg)
        return False

    margin_pct = required_margin / port['available']

    print("\n" + "╔" + "═" * 68 + "╗")
    print(f"║ 🎯 INSTITUTIONAL EXECUTION CARD v4.5 | PAIR: {symbol_input:<10} [{direction}]║")
    print("╠" + "═" * 68 + "╣")
    print(f"║ 📍 ENTRY POINT         : ${live_price:<15.4f}                        ║")
    print(f"║ 🛑 STOP LOSS (SL)      : ${sl_price:<15.4f} (-{sl_dist_pct:.2f}%)               ║")
    print(f"║ 📊 CALCULATED RRR      : 1:{calculated_rrr:<13.2f} (Min Required 1:{MIN_REQUIRED_RRR})║")
    print(f"║ 🔄 BREAKEVEN SL TRIGGER: ${breakeven_lock_level:<15.4f} (Locked at TP1 Hit)  ║")
    print(f"║ 🎯 TARGET 1 (TP1)      : ${tp1_price:<15.4f} (Key Level Target)     ║")
    print(f"║ 🚀 TARGET 2 (TP2)      : ${tp2_price:<15.4f} (Extended Target)      ║")
    print("╠" + "═" * 68 + "╣")
    print(f"║ 💵 POSITION VALUE      : ${pos_value:<15.2f}                        ║")
    print(f"║ 🪙 COIN QUANTITY       : {coin_qty:<16.4f}                        ║")
    print(f"║ ⚡ LEVERAGE            : {leverage:<2}x (Dynamic Volatility Mode)         ║")
    print(f"║ 🔒 MARGIN FROZEN       : ${required_margin:<15.2f} (-{margin_pct*100:.0f}% Available Cap)  ║")
    print(f"║ 🛡️ MAX RISK AMOUNT     : ${dollar_risk:<15.2f} (Strict 1% Total Equity)║")
    print("╚" + "═" * 68 + "╝")

    # =========================================================
    # 📲 PROFESSIONAL SIGNAL FORMATTER & IMAGE CARD GENERATOR
    # =========================================================
    direction_emoji = "🟢 LONG" if direction == "LONG" else "🔴 SHORT"
    trade_title = f"{direction_emoji} | {symbol_input} | {leverage}x Cross"
    
    # Timestamps & Expiry
    now_utc = datetime.utcnow()
    timestamp_str = now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")
    expire_time_str = (now_utc + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S UTC (24 Hours)")

    # 💰 Fee & Net Profit Calculations (0.10% Total Fee)
    ROUND_TRIP_FEE_PCT = 0.0010
    estimated_fee_usdt = pos_value * ROUND_TRIP_FEE_PCT

    if direction == "LONG":
        gross_tp1 = (tp1_price - live_price) * coin_qty
        gross_tp2 = (tp2_price - live_price) * coin_qty
    else:
        gross_tp1 = (live_price - tp1_price) * coin_qty
        gross_tp2 = (live_price - tp2_price) * coin_qty

    net_profit_tp1 = max(0.0, gross_tp1 - estimated_fee_usdt)
    net_profit_tp2 = max(0.0, gross_tp2 - estimated_fee_usdt)

    # 📝 Responsive Text Body
    trade_body = f"🏛️ QUANT TRADING SIGNAL 🏛️\n"
    trade_body += f"━━━━━━━━━━━━━━━━━━━━━━\n"
    trade_body += f"📌 Pair: #{symbol_input}\n"
    trade_body += f"📈 Direction: {direction} ({leverage}x Cross)\n"
    trade_body += f"⏱️ Timestamp: {timestamp_str}\n"
    trade_body += f"━━━━━━━━━━━━━━━━━━━━━━\n"
    trade_body += f"📍 Entry Price : ${live_price:.4f}\n"
    trade_body += f"📊 Live Price  : ${live_price:.4f}\n"
    trade_body += f"🛑 Stop Loss   : ${sl_price:.4f} (-{sl_dist_pct:.2f}%)\n"
    trade_body += f"🎯 Target 1    : ${tp1_price:.4f}\n"
    trade_body += f"🚀 Target 2    : ${tp2_price:.4f}\n"
    trade_body += f"━━━━━━━━━━━━━━━━━━━━━━\n"
    trade_body += f"🔒 Margin Used : ${required_margin:.2f} USDT\n"
    trade_body += f"💼 Position Size: ${pos_value:.2f} USDT ({coin_qty:.4f} {symbol_input.replace('USDT','')})\n"
    trade_body += f"💵 Est Net TP1 : +${net_profit_tp1:.2f} USDT (Fee: -${estimated_fee_usdt:.2f})\n"
    trade_body += f"💵 Est Net TP2 : +${net_profit_tp2:.2f} USDT\n"
    trade_body += f"━━━━━━━━━━━━━━━━━━━━━━\n"
    trade_body += f"⏳ Expires In  : {expire_time_str}\n"
    trade_body += f"⚖️ Risk/Reward : 1:{calculated_rrr:.2f}\n"
    trade_body += f"🛡️ Max Risk    : ${dollar_risk:.2f} USDT (1% Capital)\n"
    trade_body += f"━━━━━━━━━━━━━━━━━━━━━━"

    # =========================================================
    # 🎯 TRADE EXECUTION & DB SAVE BLOCK
    # =========================================================

    # 🖼️ Send Image Card + Message strictly to HARDCODED Topic ('lskejej_hdhehje')
    try:
        card_png_bytes = generate_signal_card(
            symbol=symbol_input, direction=direction, leverage=leverage,
            live_price=live_price, sl_price=sl_price, tp1_price=tp1_price,
            tp2_price=tp2_price, margin=required_margin, pos_value=pos_value,
            net_tp1=net_profit_tp1, net_tp2=net_profit_tp2, rrr=calculated_rrr
        )
        send_ex_trade_signal(trade_title, trade_body, card_png_bytes)
    except Exception as e:
        print(f"⚠️ Image attachment error: {e}. Falling back to text-only signal.")
        send_ex_trade_signal(trade_title, trade_body, None)

    # 💾 Save Executed Trade to DB
    save_trade_to_db({
        'symbol': symbol_input, 'direction': direction, 'entry_price': live_price,
        'sl_price': sl_price, 'tp1_price': tp1_price, 'tp2_price': tp2_price,
        'margin_frozen': required_margin, 'pos_value': pos_value, 'coin_qty': coin_qty,
        'leverage': leverage, 'available_cap': port['available'], 'frozen_cap': port['frozen']
    })
    return True




#((((((-&&&-----+'__&&&&'))))))



def master_trade_analyzer():
    """
    Interactive Terminal Mode for manual testing.
    """
    symbol_input = input("👉 Enter Coin Pair (e.g., SOLUSDT, LTCUSDT) [Default INJUSDT]: ").strip().upper() or "INJUSDT"
    base_risk_pct = float(input("👉 Base Risk Per Trade (%) [Default 1.5]: ") or 1.5)
    process_trade_logic(symbol_input, base_risk_pct)

if __name__ == "__main__":
    master_trade_analyzer()
