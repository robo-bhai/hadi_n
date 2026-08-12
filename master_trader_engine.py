import os
import time
import math
import sqlite3
import requests
import pandas as pd

# MySQL Connector for Remote DB / GitHub Secrets
try:
    import mysql.connector
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False

# =========================================================
# ⚙️ API ENDPOINTS
# =========================================================
BINANCE_SPOT_URL = "https://api.binance.com/api/v3/klines"
BINANCE_FUTURES_FUNDING_URL = "https://fapi.binance.com/fapi/v1/premiumIndex"
BINANCE_FUTURES_DEPTH_URL = "https://fapi.binance.com/fapi/v1/depth"
BINANCE_FUTURES_OI_URL = "https://fapi.binance.com/fapi/v1/openInterest"

# =========================================================
# 🔌 DATABASE CONNECTION ENGINE (MYSQL + SQLITE FALLBACK)
# =========================================================
def get_db_connection():
    """
    Connects to MySQL if GitHub Secrets / Env Variables exist.
    Falls back to Local SQLite database seamlessly if MySQL is unavailable.
    """
    db_host = os.environ.get("DB_HOST")
    db_user = os.environ.get("DB_USER")
    db_pass = os.environ.get("DB_PASSWORD")
    db_name = os.environ.get("DB_NAME")
    db_port = os.environ.get("DB_PORT", "3306")

    # Try MySQL if Credentials exist in GitHub Secrets / Env Variables
    if MYSQL_AVAILABLE and db_host and db_user and db_pass and db_name:
        try:
            conn = mysql.connector.connect(
                host=db_host,
                user=db_user,
                password=db_pass,
                database=db_name,
                port=int(db_port),
                connect_timeout=10
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
    """
    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    
    ph = "%s" if db_type == "MYSQL" else "?"

    # Create Portfolio Table
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
            status VARCHAR(20)
        )
        """)
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
            status TEXT
        )
        """)

    # Check Portfolio Record 1
    cursor.execute(f"SELECT COUNT(*) FROM portfolio WHERE id = {ph}", (1,))
    if cursor.fetchone()[0] == 0:
        cursor.execute(f"INSERT INTO portfolio (id, total_capital, available_capital, frozen_margin) VALUES ({ph}, 100.0, 100.0, 0.0)", (1,))

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
def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    loss = loss.replace(0, 0.00001)
    return 100 - (100 / (1 + (gain / loss)))

def calculate_atr(df, period=14):
    df = df.copy()
    high_low = df['high'] - df['low']
    high_cp = (df['high'] - df['close'].shift(1)).abs()
    low_cp = (df['low'] - df['close'].shift(1)).abs()
    df['tr'] = pd.concat([high_low, high_cp, low_cp], axis=1).max(axis=1)
    df['atr'] = df['tr'].rolling(window=period).mean()
    return df['atr']

def calculate_adx(df, period=14):
    try:
        df = df.copy()
        df['up'] = df['high'] - df['high'].shift(1)
        df['down'] = df['low'].shift(1) - df['low']
        df['+dm'] = ((df['up'] > df['down']) & (df['up'] > 0)) * df['up']
        df['-dm'] = ((df['down'] > df['up']) & (df['down'] > 0)) * df['down']
        df['atr'] = calculate_atr(df, period)
        df['+di'] = 100 * (df['+dm'].ewm(alpha=1/period).mean() / df['atr'])
        df['-di'] = 100 * (df['-dm'].ewm(alpha=1/period).mean() / df['atr'])
        di_sum = (df['+di'] + df['-di']).replace(0, 0.00001)
        dx = 100 * (df['+di'] - df['-di']).abs() / di_sum
        return dx.ewm(alpha=1/period).mean().iloc[-1]
    except Exception:
        return 0.0

def fetch_klines(symbol, interval="4h", limit=100):
    url = f"{BINANCE_SPOT_URL}?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        res = requests.get(url, timeout=5)
        if res.status_code != 200:
            return None
        df = pd.DataFrame(res.json(), columns=['time', 'open', 'high', 'low', 'close', 'volume', '_', '_', '_', '_', '_', '_'])
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = df[col].astype(float)
        return df
    except Exception:
        return None

def fetch_funding_rate(symbol):
    try:
        url = f"{BINANCE_FUTURES_FUNDING_URL}?symbol={symbol}"
        res = requests.get(url, timeout=4)
        if res.status_code == 200:
            return float(res.json().get('lastFundingRate', 0.0)) * 100
    except Exception:
        pass
    return 0.0

def fetch_orderbook_imbalance(symbol):
    try:
        url = f"{BINANCE_FUTURES_DEPTH_URL}?symbol={symbol}&limit=20"
        res = requests.get(url, timeout=4)
        if res.status_code == 200:
            data = res.json()
            bids_vol = sum([float(item[1]) for item in data.get('bids', [])])
            asks_vol = sum([float(item[1]) for item in data.get('asks', [])])
            ratio = bids_vol / asks_vol if asks_vol > 0 else 1.0
            return ratio, bids_vol, asks_vol
    except Exception:
        pass
    return 1.0, 0.0, 0.0

def fetch_open_interest(symbol):
    try:
        url = f"{BINANCE_FUTURES_OI_URL}?symbol={symbol}"
        res = requests.get(url, timeout=4)
        if res.status_code == 200:
            return float(res.json().get('openInterest', 0.0))
    except Exception:
        pass
    return 0.0

CORRELATION_GROUPS = {
    'LAYER_1': ['SOLUSDT', 'SUIUSDT', 'AVAXUSDT', 'NEARUSDT', 'APTUSDT', 'DOTUSDT', 'LTCUSDT'],
    'MEMES': ['DOGEUSDT', 'SHIBUSDT', 'PEPEUSDT', 'BONKUSDT', 'FLOKIUSDT', 'WIFUSDT'],
    'DEFI': ['INJUSDT', 'LINKUSDT', 'UNIUSDT', 'LDOUSDT', 'AAVEUSDT']
}

def check_correlation_exposure(symbol_input):
    active_symbols = get_active_symbols()
    target_group = None
    
    for group, coins in CORRELATION_GROUPS.items():
        if symbol_input in coins:
            target_group = group
            break

    if target_group:
        for act in active_symbols:
            if act in CORRELATION_GROUPS[target_group]:
                return True, f"High Correlation Exposure! Already running [{act}] from {target_group} category."
    return False, ""

def get_btc_regime():
    df_daily = fetch_klines("BTCUSDT", interval="1d", limit=60)
    if df_daily is None:
        return "NEUTRAL", 0.0
    df_daily['EMA_20'] = df_daily['close'].ewm(span=20, adjust=False).mean()
    df_daily['EMA_50'] = df_daily['close'].ewm(span=50, adjust=False).mean()
    latest = df_daily.iloc[-1]
    if latest['close'] > latest['EMA_20'] and latest['EMA_20'] > latest['EMA_50']:
        return "BULLISH", latest['close']
    elif latest['close'] < latest['EMA_20'] and latest['EMA_20'] < latest['EMA_50']:
        return "BEARISH", latest['close']
    return "CHOPPY", latest['close']

def check_micro_momentum(df, direction):
    df = df.copy()
    df['EMA_3'] = df['close'].ewm(span=3, adjust=False).mean()
    df['EMA_8'] = df['close'].ewm(span=8, adjust=False).mean()
    df['ROC'] = df['close'].pct_change(periods=3) * 100

    latest = df.iloc[-1]
    prev = df.iloc[-2]

    if direction == "LONG":
        ema_bullish = latest['EMA_3'] > latest['EMA_8'] or prev['EMA_3'] <= prev['EMA_8']
        roc_positive = latest['ROC'] > 0
        return ema_bullish and roc_positive
    elif direction == "SHORT":
        ema_bearish = latest['EMA_3'] < latest['EMA_8'] or prev['EMA_3'] >= prev['EMA_8']
        roc_negative = latest['ROC'] < 0
        return ema_bearish and roc_negative

    return False

# =========================================================
# 🏛️ CORE TRADE EXECUTION LOGIC
# =========================================================
def process_trade_logic(symbol_input, base_risk_pct=1.5):
    """
    Main Trader Engine execution logic. Operates identically for Scanner & CLI.
    """
    port = load_portfolio()
    active_count = get_active_trades_count()
    
    print("=" * 70)
    print(f"   🏛️ MASTER TRADER ENGINE v4.5 | Processing: [{symbol_input}]")
    print("=" * 70)
    print(f"💼 PORTFOLIO: Total: ${port['total']:.2f} | Available: ${port['available']:.2f} | Frozen: ${port['frozen']:.2f}")
    print(f"📊 ACTIVE TRADES IN DB: {active_count}/3")
    print("=" * 70)

    if port['available'] < 5.0:
        print("❌ Low Available Capital! Trades close hone ka wait karein.")
        return False

    if is_coin_trade_active(symbol_input):
        print(f"\n❌ TRADE REJECTED: An ACTIVE trade for [{symbol_input}] is ALREADY RUNNING!\n")
        return False

    corr_risk, corr_msg = check_correlation_exposure(symbol_input)
    if corr_risk:
        print(f"\n⚠️ CORRELATION BLOCKED: {corr_msg}\n")
        return False

    print(f"\n⏳ Fetching Live Market Data, Orderbook Depth & OI for [{symbol_input}]...")
    
    btc_regime, btc_price = get_btc_regime()
    df_1d = fetch_klines(symbol_input, interval="1d", limit=60)
    df_4h = fetch_klines(symbol_input, interval="4h", limit=60)
    df_15m = fetch_klines(symbol_input, interval="15m", limit=60)
    df_5m = fetch_klines(symbol_input, interval="5m", limit=60)

    if df_1d is None or df_4h is None or df_15m is None or df_5m is None:
        print(f"❌ Error: Invalid symbol or Binance API error for {symbol_input}")
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

    if score >= 65:
        if btc_regime == "BEARISH" and symbol_input != "BTCUSDT":
            trade_possible = False
            status_msg = "⚠️ NO TRADE: Macro BTC Trend is BEARISH"
        else:
            direction = "LONG"
    elif score <= 35:
        if btc_regime == "BULLISH" and symbol_input != "BTCUSDT":
            trade_possible = False
            status_msg = "⚠️ NO TRADE: Macro BTC Trend is BULLISH"
        else:
            direction = "SHORT"
    else:
        trade_possible = False
        status_msg = "💤 NO TRADE: Score in Chop Zone (36-64)"

    if trade_possible:
        micro_15m = check_micro_momentum(df_15m, direction)
        micro_5m = check_micro_momentum(df_5m, direction)

        if not (micro_15m or micro_5m):
            trade_possible = False
            status_msg = f"⏳ NO TRADE: Waiting for Micro-Timeframe Reversal (15M/5M EMA 3/8 & ROC)"

    print("\n" + "=" * 70)
    print(f"📊 LIVE QUANT REPORT: [{symbol_input}] | Score: {score}/100")
    print(f"💰 Price: ${live_price:.4f} | Funding: {funding_rate:.4f}% | RSI: {rsi_4h:.2f} | ADX: {adx_4h:.2f}")
    print(f"🌊 Volatility: {volatility_state} | OrderBook Ratio: {ob_ratio:.2f}x | Open Interest: {open_interest:,.0f}")
    print("=" * 70)

    if not trade_possible:
        print(f"\n🚫 TRADE STATUS: {status_msg}\n")
        return False

    # Dynamic Margin Allocation
    avail_cap = port['available']
    
    if score >= 85 or score <= 15:
        margin_pct = 0.12  # 12% Max Margin
    elif score >= 75 or score <= 25:
        margin_pct = 0.10  # 10% Margin
    else:
        margin_pct = 0.08  # 8% Base Margin
        
    required_margin = avail_cap * margin_pct
    atr_sl_buffer = atr_val * 1.5

    if direction == "LONG":
        sl_price = min(live_price - atr_sl_buffer, support_4h * 0.995)
        sl_dist_pct = ((live_price - sl_price) / live_price) * 100
        tp1_price = live_price * (1 + (sl_dist_pct * 2.0 / 100.0))
        tp2_price = live_price * (1 + (sl_dist_pct * 3.5 / 100.0))
        breakeven_lock_level = tp1_price
    else:
        sl_price = max(live_price + atr_sl_buffer, resistance_4h * 1.005)
        sl_dist_pct = ((sl_price - live_price) / live_price) * 100
        tp1_price = live_price * (1 - (sl_dist_pct * 2.0 / 100.0))
        tp2_price = live_price * (1 - (sl_dist_pct * 3.5 / 100.0))
        breakeven_lock_level = tp1_price

    pos_value = required_margin * leverage
    coin_qty = pos_value / live_price
    dollar_risk = required_margin * (sl_dist_pct / 100.0) * leverage

    print("\n" + "╔" + "═" * 68 + "╗")
    print(f"║ 🎯 INSTITUTIONAL EXECUTION CARD v4.5 | PAIR: {symbol_input:<10} [{direction}]║")
    print("╠" + "═" * 68 + "╣")
    print(f"║ 📍 ENTRY POINT         : ${live_price:<15.4f}                        ║")
    print(f"║ 🛑 STOP LOSS (SL)      : ${sl_price:<15.4f} (-{sl_dist_pct:.2f}% Risk 1:1.5)     ║")
    print(f"║ 🔄 BREAKEVEN SL TRIGGER: ${breakeven_lock_level:<15.4f} (Locked at TP1 Hit)  ║")
    print(f"║ 🎯 TARGET 1 (TP1)      : ${tp1_price:<15.4f} (Position R:R 1:2.0)     ║")
    print(f"║ 🚀 TARGET 2 (TP2)      : ${tp2_price:<15.4f} (Position R:R 1:3.5)     ║")
    print("╠" + "═" * 68 + "╣")
    print(f"║ 💵 POSITION VALUE      : ${pos_value:<15.2f}                        ║")
    print(f"║ 🪙 COIN QUANTITY       : {coin_qty:<16.4f}                        ║")
    print(f"║ ⚡ LEVERAGE            : {leverage:<2}x (Dynamic Volatility Mode)         ║")
    print(f"║ 🔒 MARGIN FROZEN       : ${required_margin:<15.2f} (-{margin_pct*100:.0f}% Available Cap)  ║")
    print(f"║ 🛡️ RISK AMOUNT         : ${dollar_risk:<15.2f}                            ║")
    print("╚" + "═" * 68 + "╝")

    if active_count >= 3:
        print("\n💡 TIP: Maximum 3 Active Trades limit reached (3/3 active). Trade displayed but NOT saved to DB.\n")
        return False

    save_trade_to_db({
        'symbol': symbol_input, 'direction': direction, 'entry_price': live_price,
        'sl_price': sl_price, 'tp1_price': tp1_price, 'tp2_price': tp2_price,
        'margin_frozen': required_margin, 'pos_value': pos_value, 'coin_qty': coin_qty,
        'leverage': leverage, 'available_cap': avail_cap, 'frozen_cap': port['frozen']
    })
    return True

def run_engine_for_coin(symbol_input, base_risk_pct=1.5):
    """
    Automated Bridge Function called by Scanner script seamlessly.
    """
    return process_trade_logic(symbol_input, base_risk_pct)

def master_trade_analyzer():
    """
    Interactive Terminal Mode for manual testing.
    """
    symbol_input = input("👉 Enter Coin Pair (e.g., SOLUSDT, LTCUSDT) [Default INJUSDT]: ").strip().upper() or "INJUSDT"
    base_risk_pct = float(input("👉 Base Risk Per Trade (%) [Default 1.5]: ") or 1.5)
    process_trade_logic(symbol_input, base_risk_pct)

if __name__ == "__main__":
    master_trade_analyzer()
