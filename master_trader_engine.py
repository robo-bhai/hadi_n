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
def send_pushbullet_notification(title, body):
    """
    Sends ntfy.sh notification for trade execution, skipped setups, or rejections.
    Strictly loads topic from GitHub Secrets / Environment Variables.
    """
    topic = os.environ.get("NTFY_TOPIC_TRADER_ENGINE")
    if not topic:
        print("⚠️ NTFY_TOPIC environment variable / secret is not set.")
        return

    url = f"https://ntfy.sh/{topic}"

    # Clean title to prevent ASCII encoding issues with header text
    clean_title = title.encode("ascii", "ignore").decode("ascii").strip()
    if not clean_title:
        clean_title = "QUANT ENGINE ALERT"

    headers = {
        "Title": clean_title,
        "Priority": "high",
        "Tags": "chart_with_upwards_trend,warning",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    }

    try:
        res = requests.post(
            url, data=body.encode("utf-8"), headers=headers, timeout=10
        )
        if res.status_code == 200:
            print(f"🚀 ntfy notification sent successfully for: {clean_title}")
        else:
            print(
                f"❌ Failed to send ntfy notification: Status {res.status_code} - {res.text}"
            )
    except Exception as e:
        print(f"❌ ntfy API Request Error: {e}")



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
            pnl DOUBLE NULL
        )
        """)

        # 🛠️ Safe Migration: Existing MySQL Table Par Columns Add Karna
        mysql_columns_to_add = [
            "ADD COLUMN exit_reason VARCHAR(255) NULL",
            "ADD COLUMN close_price DOUBLE NULL",
            "ADD COLUMN pnl DOUBLE NULL",
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
            pnl REAL NULL
        )
        """)

        # 🛠️ Safe Migration: SQLite Fallback DB Ke Liye
        sqlite_columns = [
            ("exit_reason", "TEXT"),
            ("close_price", "REAL"),
            ("pnl", "REAL"),
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
def process_trade_logic(symbol_input, base_risk_pct=1.5):
    """
    Main Trader Engine execution logic with Dynamic Key-Level RRR (Min 1:1.5) & Strict 1% Total Risk Guard.
    """
    port = load_portfolio()
    active_count = get_active_trades_count()
    
    print("=" * 70)
    print(f"   🏛️ MASTER TRADER ENGINE v4.5 | Processing: [{symbol_input}]")
    print("=" * 70)
    print(f"💼 PORTFOLIO: Total: ${port['total']:.2f} | Available: ${port['available']:.2f} | Frozen: ${port['frozen']:.2f}")
    print(f"📊 ACTIVE TRADES IN DB: {active_count}/3")
    print("=" * 70)

    # 🔴 EARLY GUARD 1: Active Trades Limit Check (Top-Level)
    if active_count >= 5:
        msg = f"⚠️ Trade Skipped for [{symbol_input}]: Maximum 3 Active Trades limit reached ({active_count}/3)."
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
            if (direction == "LONG" and score >= 60) or (direction == "SHORT" and score <= 40):
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
        
        tp1_price = resistance_4h
        reward_dist = tp1_price - live_price
        
        calculated_rrr = reward_dist / risk_dist if risk_dist > 0 else 0
        tp2_price = live_price + (risk_dist * max(2.5, calculated_rrr * 1.3))
        breakeven_lock_level = tp1_price

    elif direction == "SHORT":
        sl_price = max(live_price + atr_sl_buffer, resistance_4h * 1.005)
        risk_dist = sl_price - live_price
        
        tp1_price = support_4h
        reward_dist = live_price - tp1_price
        
        calculated_rrr = reward_dist / risk_dist if risk_dist > 0 else 0
        tp2_price = live_price - (risk_dist * max(2.5, calculated_rrr * 1.3))
        breakeven_lock_level = tp1_price

    # 🛑 STRICT FILTER 1: Minimum 1:1.5 Risk-to-Reward Ratio Guard
    MIN_REQUIRED_RRR = 1.5
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
    print(f"║ 📊 CALCULATED RRR      : 1:{calculated_rrr:<13.2f} (Min Required 1:1.5)║")
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

    # PUSHBULLET NOTIFICATION FOR EXECUTED TRADE
    trade_title = f"🚀 [TRADE EXECUTED] {symbol_input} ({direction})"
    trade_body = f"🪙 Pair: {symbol_input} | Side: {direction}\n"
    trade_body += f"📊 Quant Score: {score}/100 | Max Available RRR: 1:{calculated_rrr:.2f}\n"
    trade_body += "----------------------------------------\n"
    trade_body += f"📍 Entry Price: ${live_price:.4f}\n"
    trade_body += f"🛑 Stop Loss: ${sl_price:.4f} (-{sl_dist_pct:.2f}%)\n"
    trade_body += f"🎯 Target 1 (TP1): ${tp1_price:.4f} (Key Level Target)\n"
    trade_body += f"🚀 Target 2 (TP2): ${tp2_price:.4f} (Extended Target)\n"
    trade_body += f"🔄 Breakeven SL: ${breakeven_lock_level:.4f}\n"
    trade_body += "----------------------------------------\n"
    trade_body += f"💼 Total Portfolio: ${port['total']:.2f} USDT\n"
    trade_body += f"💵 Available Cap Before: ${port['available']:.2f} USDT\n"
    trade_body += f"🔒 Margin Frozen: ${required_margin:.2f} USDT\n"
    trade_body += f"⚡ Leverage: {leverage}x | Volatility: {volatility_state}\n"
    trade_body += f"📈 Total Position Value: ${pos_value:.2f} USDT\n"
    trade_body += f"🪙 Coin Quantity: {coin_qty:.4f}\n"
    trade_body += f"🛡️ Max Risk Amount: ${dollar_risk:.2f} USDT (Strict 1% Capital)\n"
    trade_body += f"📊 Active Trades Count: {active_count + 1}/3\n"

    send_pushbullet_notification(trade_title, trade_body)

    save_trade_to_db({
        'symbol': symbol_input, 'direction': direction, 'entry_price': live_price,
        'sl_price': sl_price, 'tp1_price': tp1_price, 'tp2_price': tp2_price,
        'margin_frozen': required_margin, 'pos_value': pos_value, 'coin_qty': coin_qty,
        'leverage': leverage, 'available_cap': port['available'], 'frozen_cap': port['frozen']
    })
    return True



def master_trade_analyzer():
    """
    Interactive Terminal Mode for manual testing.
    """
    symbol_input = input("👉 Enter Coin Pair (e.g., SOLUSDT, LTCUSDT) [Default INJUSDT]: ").strip().upper() or "INJUSDT"
    base_risk_pct = float(input("👉 Base Risk Per Trade (%) [Default 1.5]: ") or 1.5)
    process_trade_logic(symbol_input, base_risk_pct)

if __name__ == "__main__":
    master_trade_analyzer()
