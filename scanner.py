import os
import time
import numpy as np
import pandas as pd
import requests
import ssl
import sqlite3
from pap import save_all_signals_in_db

# Conditional MySQL Connector (Remote / GitHub Secrets)
try:
    import mysql.connector
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False

# Import Trader Engine for Seamless Automated Integration
try:
    from master_trader_engine import process_trade_logic
    TRADER_ENGINE_AVAILABLE = True
except ImportError:
    TRADER_ENGINE_AVAILABLE = False

# =========================================================
# 📋 TOP 75 HIGH-LIQUIDITY USDT PAIRS
# =========================================================
PAIRS = [
    # --- Major / Layer 1 & 2 ---
    'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT', 'ADAUSDT', 'AVAXUSDT',
    'LINKUSDT', 'NEARUSDT', 'APTUSDT', 'DOTUSDT', 'LTCUSDT', 'SUIUSDT', 'TRXUSDT',
    'XLMUSDT', 'BCHUSDT', 'ETCUSDT', 'FILUSDT', 'ATOMUSDT', 'ICPUSDT', 'HBARUSDT',
    'STXUSDT', 'SEIUSDT', 'TIAUSDT', 'FTMUSDT', 'INJUSDT', 'EGLDUSDT',
    'THETAUSDT', 'ROSEUSDT', 'ALGOUSDT', 'FLOWUSDT', 'NEOUSDT', 'EOSUSDT', 'IOTAUSDT',
    'XTZUSDT', 'ZILUSDT', 'KSMUSDT', 'POLUSDT', 'ARBUSDT', 'OPUSDT', 'STRKUSDT',
    'ZKUSDT', 'MANTAUSDT', 'DYMUSDT', 'ALTUSDT', 'SAGAUSDT', 'BBUSDT',

    # --- AI & Big Data ---
    'TAOUSDT', 'FETUSDT', 'RENDERUSDT', 'ARKMUSDT', 'WLDUSDT', 'GRTUSDT', 'JASMYUSDT',
    'IOUSDT', 'AKTUSDT',

    # --- Memes (High Liquidity) ---
    'DOGEUSDT', 'SHIBUSDT', 'PEPEUSDT', 'FLOKIUSDT', 'BONKUSDT', 'WIFUSDT',
    'POPCATUSDT', 'MEWUSDT', 'BOMEUSDT', 'NEIROUSDT', 'TURBOUSDT', '1000SATSUSDT',
    'MEMEUSDT', 'ORDIUSDT',

    # --- DeFi, RWA & Infrastructure ---
    'UNIUSDT', 'AAVEUSDT', 'MKRUSDT', 'LDOUSDT', 'PENDLEUSDT', 'ENAUSDT', 'ONDOUSDT',
    'OMUSDT', 'CRVUSDT', 'COMPUSDT', 'DYDXUSDT', 'ENSUSDT', '1INCHUSDT', 'SNXUSDT',
    'RUNEUSDT', 'JUPUSDT', 'PYTHUSDT', 'WUSDT', 'AEROUSDT', 'AEVOUSDT',

    # --- Gaming, Metaverse & NFT ---
    'GALAUSDT', 'SANDUSDT', 'MANAUSDT', 'AXSUSDT', 'IMXUSDT', 'PIXELUSDT',
    'PORTALUSDT', 'BEAMUSDT', 'ILVUSDT', 'BLURUSDT',

    # --- Ecosystems & High Momentum ---
    'TONUSDT', 'NOTUSDT', 'DOGSUSDT', 'KASUSDT', 'EIGENUSDT', 'RAYUSDT'
]

PAIRS = list(dict.fromkeys(PAIRS))

# =========================================================
# ⚙️ CONFIGURATION & PUBLIC ENDPOINTS
# =========================================================
BINANCE_SPOT_URL = 'https://data-api.binance.vision/api/v3/klines'
BINANCE_BOOK_TICKER_URL = 'https://data-api.binance.vision/api/v3/ticker/bookTicker'
BINANCE_DEPTH_URL = 'https://data-api.binance.vision/api/v3/depth'
BINANCE_FUTURES_FUNDING_URL = 'https://fapi.binance.com/fapi/v1/premiumIndex'

MAX_ALLOWED_SPREAD_PCT = 0.035
USER_CAPITAL_USDT = 100.0
MARGIN_ALLOC_PCT = 0.13
MAX_ACCOUNT_RISK_PCT = 0.01

# =========================================================
# 🔌 PAPER TRADING DATABASE ENGINE & SAVER
# =========================================================
# =========================================================
# 🔌 PAPER TRADING DATABASE ENGINE & INITIALIZER
# =========================================================


# =========================================================
# 🔌 REAL TRADING DATABASE CONNECTOR & ACTIVE CHECK
# =========================================================
def get_real_db_connection():
  db_host = os.environ.get(
      'DB_HOST', 'mysql-3a3d5779-project-b71a.b.aivencloud.com'
  )
  db_user = os.environ.get('DB_USER', 'avnadmin')
  db_pass = os.environ.get('DB_PASS', os.environ.get('DB_PASSWORD', ''))
  db_name = os.environ.get('DB_NAME', 'defaultdb')
  db_port = int(os.environ.get('DB_PORT', '23464'))

  if MYSQL_AVAILABLE and db_pass:
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
          connect_timeout=15,
      )
      return conn, 'MYSQL'
    except Exception:
      pass

  conn = sqlite3.connect('trading_system.db')
  return conn, 'SQLITE'


def is_trade_active_in_real_db(symbol):
  """Real Trading DB mein Active Trade check karta hai."""
  try:
    conn, mode = get_real_db_connection()
    if not conn:
      return False
    cursor = conn.cursor()
    ph = '%s' if mode == 'MYSQL' else '?'

    # Table 'trades' (Real DB) mein check
    query = (
        f"SELECT COUNT(*) FROM trades WHERE symbol = {ph} AND status = 'ACTIVE'"
    )
    cursor.execute(query, (symbol,))
    row = cursor.fetchone()
    conn.close()
    return (row[0] > 0) if row else False
  except Exception as e:
    print(f'⚠️ Error checking Real DB for {symbol}: {e}')
    return False


def check_dual_db_status(symbol):
  """Returns: (is_paper_active, is_real_active)"""
  paper_active = is_trade_running_in_db(symbol)  # Paper DB Check
  real_active = is_trade_active_in_real_db(symbol)  # Real DB Check
  return paper_active, real_active


def get_paper_trade_db_connection():
    db_host = "mysql-paper-trading-nomistorage3-d0bf.d.aivencloud.com"
    db_user = "avnadmin"
    db_name = "defaultdb"
    db_port = 13722
    db_pass = os.environ.get("PASS_DB_2", "").strip()

    if MYSQL_AVAILABLE and db_pass:
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
                connect_timeout=30,
            )
            return conn, "MYSQL"
        except Exception:
            pass

        try:
            conn = mysql.connector.connect(
                host=db_host,
                user=db_user,
                password=db_pass,
                database=db_name,
                port=db_port,
                ssl_disabled=False,
                ssl_verify_cert=False,
                connect_timeout=30,
            )
            return conn, "MYSQL"
        except Exception as e:
            print(
                f"⚠️ Paper MySQL Connection Error: {e}. Falling back to SQLite..."
            )

    conn = sqlite3.connect("paper_trading_system.db")
    return conn, "SQLITE"


def init_paper_db():
    """Script startup par hi paper_trades table create karne ki guarantee deta hai."""
    conn, mode = get_paper_trade_db_connection()
    if not conn:
        return
    try:
        cursor = conn.cursor()
        create_tbl = (
            """
        CREATE TABLE IF NOT EXISTS paper_trades (
            id INT AUTO_INCREMENT PRIMARY KEY,
            symbol VARCHAR(20) NOT NULL,
            direction VARCHAR(10) NOT NULL,
            entry_price DECIMAL(18,8),
            stop_loss DECIMAL(18,8),
            target_1 DECIMAL(18,8),
            target_2 DECIMAL(18,8),
            score INT,
            leverage INT,
            margin_usdt DECIMAL(10,2),
            status VARCHAR(20) DEFAULT 'ACTIVE',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
            if mode == "MYSQL"
            else """
        CREATE TABLE IF NOT EXISTS paper_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            direction TEXT NOT NULL,
            entry_price REAL,
            stop_loss REAL,
            target_1 REAL,
            target_2 REAL,
            score INTEGER,
            leverage INTEGER,
            margin_usdt REAL,
            status TEXT DEFAULT 'ACTIVE',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
        )
        cursor.execute(create_tbl)
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"⚠️ Error initializing Paper DB table: {e}")
        if conn:
            conn.close()


# Database table ko import/execution ke waqt auto-create karna
init_paper_db()


def is_trade_running_in_db(symbol):
    try:
        conn, mode = get_paper_trade_db_connection()
        if not conn:
            return False
        cursor = conn.cursor()

        # Extra safety check: agar table abhi bhi create na hui ho
        init_paper_db()

        ph = "%s" if mode == "MYSQL" else "?"
        query = f"SELECT COUNT(*) FROM paper_trades WHERE symbol = {ph} AND status = {ph}"
        cursor.execute(query, (symbol, "ACTIVE"))

        row = cursor.fetchone()
        conn.close()

        return (row[0] > 0) if row else False
    except Exception as e:
        print(f"⚠️ Error checking DB for {symbol}: {e}")
        return False



def is_trade_running_in_db(symbol):
    try:
        conn, mode = get_paper_trade_db_connection()
        if not conn:
            return False
        cursor = conn.cursor()
        ph = "%s" if mode == "MYSQL" else "?"
        
        query = f"SELECT COUNT(*) FROM paper_trades WHERE symbol = {ph} AND status = {ph}"
        cursor.execute(query, (symbol, 'ACTIVE'))
        
        row = cursor.fetchone()
        conn.close()
        
        return (row[0] > 0) if row else False
    except Exception as e:
        print(f"⚠️ Error checking DB for {symbol}: {e}")
        return False


def save_signal_to_paper_trade_db(trade):
    conn, mode = get_paper_trade_db_connection()
    if not conn:
        print(f"❌ [PAPER DB] Connection failed for {trade['symbol']}")
        return False

    symbol = trade['symbol']
    direction = trade['bias']

    try:
        cursor = conn.cursor(dictionary=True) if mode == "MYSQL" else conn.cursor()

        create_tbl = """
        CREATE TABLE IF NOT EXISTS paper_trades (
            id INT AUTO_INCREMENT PRIMARY KEY,
            symbol VARCHAR(20) NOT NULL,
            direction VARCHAR(10) NOT NULL,
            entry_price DECIMAL(18,8),
            stop_loss DECIMAL(18,8),
            target_1 DECIMAL(18,8),
            target_2 DECIMAL(18,8),
            score INT,
            leverage INT,
            margin_usdt DECIMAL(10,2),
            status VARCHAR(20) DEFAULT 'ACTIVE',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """ if mode == "MYSQL" else """
        CREATE TABLE IF NOT EXISTS paper_trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            direction TEXT NOT NULL,
            entry_price REAL,
            stop_loss REAL,
            target_1 REAL,
            target_2 REAL,
            score INTEGER,
            leverage INTEGER,
            margin_usdt REAL,
            status TEXT DEFAULT 'ACTIVE',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
        cursor.execute(create_tbl)

        chk_query = (
            "SELECT id FROM paper_trades WHERE symbol = %s AND status = 'ACTIVE'"
            if mode == "MYSQL"
            else "SELECT id FROM paper_trades WHERE symbol = ? AND status = 'ACTIVE'"
        )
        cursor.execute(chk_query, (symbol,))
        if cursor.fetchone():
            print(f"⚠️ [PAPER DB] {symbol} is already ACTIVE in Paper DB.")
            conn.close()
            return False

        insert_query = """
        INSERT INTO paper_trades 
        (symbol, direction, entry_price, stop_loss, target_1, target_2, score, leverage, margin_usdt, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'ACTIVE')
        """ if mode == "MYSQL" else """
        INSERT INTO paper_trades 
        (symbol, direction, entry_price, stop_loss, target_1, target_2, score, leverage, margin_usdt, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE')
        """

        vals = (
            symbol, direction, trade['entry'], trade['sl'], trade['tp1'],
            trade['tp2'], trade['score'], trade['leverage'], trade['margin_usdt']
        )
        cursor.execute(insert_query, vals)
        conn.commit()
        conn.close()
        print(f"✅ [PAPER DB] Saved new signal for {symbol} ({direction})")
        return True

    except Exception as e:
        print(f"❌ [PAPER DB] Error saving record: {e}")
        if conn:
            conn.close()
        return False


def check_db_trade_guard(symbol, direction=""):
    conn, mode = get_paper_trade_db_connection()
    if not conn:
        print(f"⚠️ DB Guard Warning: Database connection unavailable. Skipping DB check for {symbol}.")
        return False, ""

    try:
        cursor = conn.cursor(dictionary=True) if mode == "MYSQL" else conn.cursor()

        # 1. Active trade check (paper_trades table)
        query_active = """
            SELECT id, direction, entry_price FROM paper_trades 
            WHERE symbol = %s AND status = 'ACTIVE'
        """ if mode == "MYSQL" else """
            SELECT id, direction, entry_price FROM paper_trades 
            WHERE symbol = ? AND status = 'ACTIVE'
        """
        
        cursor.execute(query_active, (symbol,))
        active_trade = cursor.fetchone()

        if active_trade:
            active_dir = active_trade['direction'] if isinstance(active_trade, dict) else active_trade[1]
            cursor.close()
            conn.close()
            reason = f"Active trade already exists on {symbol} (Direction: {active_dir})."
            return True, reason

        # 2. 24-Hour Stop-Loss Cooldown Check
        query_sl = """
            SELECT id, exit_reason, updated_at FROM paper_trades 
            WHERE symbol = %s 
              AND status = 'CLOSED' 
              AND (exit_reason LIKE '%SL%' OR exit_reason LIKE '%STOP_LOSS%')
              AND updated_at >= NOW() - INTERVAL 24 HOUR
            ORDER BY updated_at DESC LIMIT 1
        """ if mode == "MYSQL" else """
            SELECT id, exit_reason, updated_at FROM paper_trades 
            WHERE symbol = ? 
              AND status = 'CLOSED' 
              AND (exit_reason LIKE '%SL%' OR exit_reason LIKE '%STOP_LOSS%')
              AND updated_at >= datetime('now', '-24 hours')
            ORDER BY updated_at DESC LIMIT 1
        """
        
        try:
            cursor.execute(query_sl, (symbol,))
            sl_trade = cursor.fetchone()
            if sl_trade:
                cursor.close()
                conn.close()
                reason = f"Trade on {symbol} hit Stop Loss in the last 24 hours."
                return True, reason
        except Exception as sl_err:
            # Table schema mein exit_reason/updated_at na hone par silent fallback
            pass

        cursor.close()
        conn.close()
        return False, ""

    except Exception as e:
        print(f"❌ DB Guard Query Error for {symbol}: {e}")
        if conn:
            try:
                conn.close()
            except Exception:
                pass
        return False, ""



# =========================================================
# 📲 NOTIFICATIONS & INDICATORS
# =========================================================
def send_pushbullet_notification(title, body):
    """
    Sends ntfy.sh notification using the NTFY_FOR_SCANNER environment variable / secret.
    Retries up to 3 times on failure.
    """
    topic = os.environ.get("NTFY_FOR_SCANNER")
    if not topic:
        print("⚠️ NTFY_FOR_SCANNER environment variable / secret is not set.")
        return False

    url = f"https://ntfy.sh/{topic}"

    clean_title = title.encode("ascii", "ignore").decode("ascii").strip()
    if not clean_title:
        clean_title = "QUANT ENGINE ALERT"

    headers = {
        "Title": clean_title,
        "Priority": "high",
        "Tags": "chart_with_upwards_trend,warning",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    }

    for attempt in range(1, 4):
        try:
            response = requests.post(
                url, data=body.encode("utf-8"), headers=headers, timeout=15
            )
            if response.status_code == 200:
                print(f"🚀 Notification sent successfully for: {clean_title}")
                return True
        except Exception as e:
            print(f"⚠️ Ntfy Attempt {attempt} Error: {e}")
        time.sleep(1)

    print("❌ Notification failed after 3 attempts.")
    return False




def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    loss = loss.replace(0, 0.00001)
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calculate_atr(df, period=14):
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift()).abs()
    low_close = (df['low'] - df['close'].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()

def calculate_adx(df, period=14):
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
        return float(adx.iloc[-1]) if not adx.empty and not pd.isna(adx.iloc[-1]) else 0.0
    except Exception:
        return 0.0


# =========================================================
# 📊 BINANCE MARKET & QUANT FETCHERS
# =========================================================
def fetch_taker_buy_delta(symbol):
    try:
        url = f'https://fapi.binance.com/futures/data/takerlongshortRatio?symbol={symbol}&period=15m&limit=1'
        res = requests.get(url, timeout=3)
        if res.status_code == 200:
            data = res.json()
            if data:
                return float(data[0]['buySellRatio'])
    except Exception:
        pass
    return 1.0

def fetch_oi_change_delta(symbol):
    try:
        url = f'https://fapi.binance.com/futures/data/openInterestHist?symbol={symbol}&period=15m&limit=2'
        res = requests.get(url, timeout=3)
        if res.status_code == 200:
            data = res.json()
            if len(data) >= 2:
                prev_oi = float(data[0]['sumOpenInterestValue'])
                curr_oi = float(data[1]['sumOpenInterestValue'])
                if prev_oi > 0:
                    return ((curr_oi - prev_oi) / prev_oi) * 100
    except Exception:
        pass
    return 0.0

def analyze_dynamic_structure(df_4h):
    if df_4h is None or len(df_4h) < 30:
        return None

    closes = df_4h['close'].values
    opens = df_4h['open'].values
    body_highs = np.maximum(closes, opens)
    body_lows = np.minimum(closes, opens)

    pivot_highs, pivot_lows = [], []
    for i in range(2, len(df_4h) - 2):
        if body_highs[i] > body_highs[i - 1] and body_highs[i] > body_highs[i - 2] and body_highs[i] > body_highs[i + 1] and body_highs[i] > body_highs[i + 2]:
            pivot_highs.append(body_highs[i])
        if body_lows[i] < body_lows[i - 1] and body_lows[i] < body_lows[i - 2] and body_lows[i] < body_lows[i + 1] and body_lows[i] < body_lows[i + 2]:
            pivot_lows.append(body_lows[i])

    current_price = closes[-1]
    valid_res = [h for h in pivot_highs if h > current_price]
    valid_sup = [l for l in pivot_lows if l < current_price]

    dynamic_res = min(valid_res) if valid_res else df_4h['high'].tail(20).max()
    dynamic_sup = max(valid_sup) if valid_sup else df_4h['low'].tail(20).min()

    dist_to_res_pct = ((dynamic_res - current_price) / current_price) * 100
    dist_to_sup_pct = ((current_price - dynamic_sup) / current_price) * 100

    return {
        'support': dynamic_sup,
        'resistance': dynamic_res,
        'dist_res_pct': dist_to_res_pct,
        'dist_sup_pct': dist_to_sup_pct,
        'is_breakout': current_price >= dynamic_res,
        'is_breakdown': current_price <= dynamic_sup,
    }

def calculate_price_velocity(df_1m):
    if df_1m is None or len(df_1m) < 3:
        return 0.0
    current_close = df_1m['close'].iloc[-1]
    prev_close = df_1m['close'].iloc[-3]
    return ((current_close - prev_close) / prev_close) * 100

def check_volume_velocity(df_1m):
    if df_1m is None or len(df_1m) < 20:
        return False, 1.0
    latest_vol = df_1m['volume'].iloc[-1]
    avg_vol = df_1m['volume'].rolling(20).mean().iloc[-1]
    if avg_vol > 0 and (latest_vol >= avg_vol * 3.0):
        return True, latest_vol / avg_vol
    return False, (latest_vol / avg_vol) if avg_vol > 0 else 1.0

def check_liquidity_and_spread(symbol):
    try:
        url = f'{BINANCE_BOOK_TICKER_URL}?symbol={symbol}'
        res = requests.get(url, timeout=3)
        if res.status_code == 200:
            data = res.json()
            bid = float(data['bidPrice'])
            ask = float(data['askPrice'])
            if bid > 0:
                spread_pct = ((ask - bid) / bid) * 100
                return spread_pct <= MAX_ALLOWED_SPREAD_PCT, spread_pct
    except Exception:
        pass
    return False, 999.0

def fetch_orderbook_imbalance(symbol, depth=20):
    try:
        url = f'{BINANCE_DEPTH_URL}?symbol={symbol}&limit={depth}'
        res = requests.get(url, timeout=3)
        if res.status_code == 200:
            data = res.json()
            total_bid_vol = sum([float(b[1]) for b in data.get('bids', [])])
            total_ask_vol = sum([float(a[1]) for a in data.get('asks', [])])
            if total_ask_vol > 0:
                return total_bid_vol / total_ask_vol, total_bid_vol, total_ask_vol
    except Exception:
        pass
    return 1.0, 0.0, 0.0

def fetch_klines(symbol, interval='4h', limit=100):
    url = f'{BINANCE_SPOT_URL}?symbol={symbol}&interval={interval}&limit={limit}'
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
        url = f'{BINANCE_FUTURES_FUNDING_URL}?symbol={symbol}'
        res = requests.get(url, timeout=4)
        if res.status_code == 200:
            return float(res.json().get('lastFundingRate', 0.0)) * 100
    except Exception:
        pass
    return 0.0

def get_btc_macro_regime():
    df_daily = fetch_klines('BTCUSDT', interval='1d', limit=60)
    if df_daily is None:
        return 'NEUTRAL', 0.0

    df_daily['EMA_20'] = df_daily['close'].ewm(span=20, adjust=False).mean()
    df_daily['EMA_50'] = df_daily['close'].ewm(span=50, adjust=False).mean()
    latest = df_daily.iloc[-1]
    price, ema20, ema50 = latest['close'], latest['EMA_20'], latest['EMA_50']

    if price > ema20 and ema20 > ema50:
        return 'BULLISH', price
    elif price < ema20 and ema20 < ema50:
        return 'BEARISH', price
    return 'CHOPPY', price

# =========================================================
# 🏛️ LEGENDARY QUANT SETUP ANALYZER
# =========================================================
def analyze_legendary_setup(symbol, btc_regime):
    is_liquid, current_spread = check_liquidity_and_spread(symbol)
    if not is_liquid:
        return {'symbol': symbol, 'status': 'REJECTED_SLIPPAGE_RISK', 'reason': f'High Bid/Ask Spread ({current_spread:.4f}%)'}

    df_1d = fetch_klines(symbol, interval='1d', limit=60)
    df_4h = fetch_klines(symbol, interval='4h', limit=60)
    df_1m = fetch_klines(symbol, interval='1m', limit=30)

    if df_1d is None or df_4h is None:
        return None

    chart_struct = analyze_dynamic_structure(df_4h)
    if not chart_struct:
        return None

    df_4h['ATR'] = calculate_atr(df_4h, 14)
    atr_val = df_4h['ATR'].iloc[-1]
    atr_pct = (atr_val / df_4h['close'].iloc[-1]) * 100

    if atr_pct > 5.0 and symbol not in ['BTCUSDT', 'ETHUSDT']:
        return {'symbol': symbol, 'status': 'REJECTED_SLIPPAGE_RISK', 'reason': f'Extreme Volatility / Wick Risk (ATR: {atr_pct:.2f}%)'}

    adx_4h = calculate_adx(df_4h, 14)
    adx_1d = calculate_adx(df_1d, 14)

    if adx_4h < 20.0 and adx_1d < 18.0 and symbol not in ['BTCUSDT', 'ETHUSDT']:
        return {'symbol': symbol, 'status': 'REJECTED_SIDEWAYS', 'reason': f'No Strong Trend / Sideways Market (4H ADX: {adx_4h:.1f}, 1D ADX: {adx_1d:.1f})'}

    df_1d['EMA_20'] = df_1d['close'].ewm(span=20, adjust=False).mean()
    df_4h['EMA_20'] = df_4h['close'].ewm(span=20, adjust=False).mean()
    df_4h['RSI'] = calculate_rsi(df_4h['close'], 14)
    df_4h['Vol_SMA'] = df_4h['volume'].rolling(20).mean()

    if df_1m is not None and len(df_1m) >= 10:
        df_1m['EMA_3'] = df_1m['close'].ewm(span=3, adjust=False).mean()
        df_1m['EMA_8'] = df_1m['close'].ewm(span=8, adjust=False).mean()
        fast_ema_bullish = df_1m['EMA_3'].iloc[-1] > df_1m['EMA_8'].iloc[-1]
        fast_ema_bearish = df_1m['EMA_3'].iloc[-1] < df_1m['EMA_8'].iloc[-1]
    else:
        fast_ema_bullish = fast_ema_bearish = False

    curr_1d, curr_4h = df_1d.iloc[-1], df_4h.iloc[-1]
    live_price, rsi_4h = curr_4h['close'], curr_4h['RSI']
    vol_spike = curr_4h['volume'] > (curr_4h['Vol_SMA'] * 1.25)

    roc_1m = calculate_price_velocity(df_1m)
    vol_spurt, vol_ratio = check_volume_velocity(df_1m)

    ob_ratio, bid_vol, ask_vol = fetch_orderbook_imbalance(symbol, depth=20)
    funding_rate = fetch_funding_rate(symbol)
    taker_ratio = fetch_taker_buy_delta(symbol)
    oi_delta = fetch_oi_change_delta(symbol)

    score = 50
    confluences = [f'Low Slippage Guard Passed (Spread: {current_spread:.3f}%)']

    is_mtf_bullish = curr_1d['close'] > curr_1d['EMA_20'] and curr_4h['close'] > curr_4h['EMA_20']
    is_mtf_bearish = curr_1d['close'] < curr_1d['EMA_20'] and curr_4h['close'] < curr_4h['EMA_20']

    if is_mtf_bullish:
        score += 15
        confluences.append('Bullish MTF Alignment (1D+4H)')
    elif is_mtf_bearish:
        score -= 15
        confluences.append('Bearish MTF Alignment (1D+4H)')

    if rsi_4h <= 35:
        score += 20
        confluences.append(f'4H RSI Oversold ({rsi_4h:.1f})')
    elif rsi_4h >= 65:
        score -= 20
        confluences.append(f'4H RSI Overbought ({rsi_4h:.1f})')

    if vol_spike:
        score += 10 if score >= 50 else -10
        confluences.append('Institutional Volume Spike')

    if taker_ratio >= 1.25:
        score += 10
        confluences.append(f'Aggressive CVD Taker Buying ({taker_ratio:.2f}x)')
    elif taker_ratio <= 0.80:
        score -= 10
        confluences.append(f'Aggressive CVD Taker Selling ({taker_ratio:.2f}x)')

    if ob_ratio >= 1.3:
        score += 10
        confluences.append(f'Bullish OB Imbalance ({ob_ratio:.2f}x)')
    elif ob_ratio <= 0.7:
        score -= 10
        confluences.append(f'Bearish OB Imbalance ({ob_ratio:.2f}x)')

    if funding_rate < -0.01:
        score += 15
        confluences.append(f'Short Squeeze Scent (Funding: {funding_rate:.4f}%)')
        if oi_delta >= 2.5:
            score += 10
            confluences.append(f'🔥 Institutional Money Flow (15m OI Surge: +{oi_delta:.2f}%)')
    elif funding_rate > 0.03:
        score -= 15
        confluences.append(f'Long Flush Scent (Funding: {funding_rate:.4f}%)')
        if oi_delta >= 2.5:
            score -= 10
            confluences.append(f'⚠️ Aggressive Long Leverage Spike (OI: +{oi_delta:.2f}%)')

    if roc_1m >= 1.0 and vol_spurt and fast_ema_bullish:
        score += 15
        confluences.append(f'⚡ Instant Pump Impulse: +{roc_1m:.2f}% (Vol Surge: {vol_ratio:.1f}x)')
    elif roc_1m <= -1.0 and vol_spurt and fast_ema_bearish:
        score -= 15
        confluences.append(f'⚡ Instant Dump Impulse: {roc_1m:.2f}% (Vol Surge: {vol_ratio:.1f}x)')

    if adx_4h >= 30.0:
        score += 10 if score >= 50 else -10
        confluences.append(f'💪 Strong Trend Momentum (4H ADX: {adx_4h:.1f})')

    if score >= 60:
        if chart_struct['is_breakout']:
            score += 15
            confluences.append('🔥 Dynamic Resistance Breakout Confirmed!')
        elif chart_struct['dist_res_pct'] < 0.3:
            score -= 25
            confluences.append('⚠️ Long Blocked: Price Hitting Direct Resistance')
        else:
            confluences.append(f"Chart Room to Rise: {chart_struct['dist_res_pct']:.2f}% to Res")

    elif score <= 40:
        if chart_struct['is_breakdown']:
            score -= 15
            confluences.append('💥 Dynamic Support Breakdown Confirmed!')
        elif chart_struct['dist_sup_pct'] < 0.3:
            score += 25
            confluences.append('⚠️ Short Blocked: Price Sitting Direct on Support')
        else:
            confluences.append(f"Chart Room to Fall: {chart_struct['dist_sup_pct']:.2f}% to Sup")

    signal, bias = 'NEUTRAL 🟡', 'NO TRADE'

    if score >= 58:
        if is_mtf_bearish:
            signal, bias = '⚠️ BLOCKED LONG (Bearish MTF Trend)', 'HIGH RISK'
        elif btc_regime == 'BEARISH' and symbol != 'BTCUSDT':
            signal, bias = '⚠️ BLOCKED LONG (BTC Bearish Risk)', 'HIGH RISK'
        else:
            signal, bias = '🔥 LEGENDARY LONG', 'LONG'

    elif score <= 42:
        if is_mtf_bullish:
            signal, bias = '⚠️ BLOCKED SHORT (Bullish MTF Trend)', 'HIGH RISK'
        elif btc_regime == 'BULLISH' and symbol != 'BTCUSDT':
            signal, bias = '⚠️ BLOCKED SHORT (BTC Bullish Risk)', 'HIGH RISK'
        else:
            signal, bias = '💥 LEGENDARY SHORT', 'SHORT'

    atr_buffer = atr_val * 1.5
    entry = live_price

    if bias == 'LONG':
        sl = entry - atr_buffer
        sl_pct = (entry - sl) / entry
        tp1 = entry * (1 + (sl_pct * 1.5))
        tp2 = entry * (1 + (sl_pct * 2.0))
    elif bias == 'SHORT':
        sl = entry + atr_buffer
        sl_pct = (sl - entry) / entry
        tp1 = entry * (1 - (sl_pct * 1.5))
        tp2 = entry * (1 - (sl_pct * 2.0))
    else:
        sl = sl_pct = tp1 = tp2 = 0.0

    if sl_pct > 0:
        risk_amount_usdt = USER_CAPITAL_USDT * MAX_ACCOUNT_RISK_PCT
        margin_used_usdt = USER_CAPITAL_USDT * MARGIN_ALLOC_PCT
        position_size_usdt = risk_amount_usdt / sl_pct
        calc_leverage = position_size_usdt / margin_used_usdt
        recommended_leverage = int(np.clip(np.round(calc_leverage), 1, 3))
    else:
        risk_amount_usdt = margin_used_usdt = position_size_usdt = 0
        recommended_leverage = 1

    # 🔹 Coin Quantity Calculate Karein (Return se pehle)
    coin_quantity = position_size_usdt / entry if entry > 0 else 0.0

    # 🔹 Single Final Return
    return {
        'status': 'PASSED', 'symbol': symbol, 'price': live_price, 'score': score,
        'signal': signal, 'bias': bias, 'funding': funding_rate, 'taker_ratio': taker_ratio,
        'oi_delta': oi_delta, 'rsi_4h': rsi_4h, 'adx_4h': adx_4h,
        'support': chart_struct['support'], 'resistance': chart_struct['resistance'],
        'ob_ratio': ob_ratio, 'confluences': confluences, 'entry': entry, 'sl': sl,
        'sl_pct': sl_pct * 100, 'tp1': tp1, 'tp2': tp2, 'margin_usdt': margin_used_usdt,
        'risk_usdt': risk_amount_usdt, 'pos_size_usdt': position_size_usdt,
        'coin_qty': round(coin_quantity, 6),  # 👈 Single clean return block
        'leverage': recommended_leverage
    }


# =========================================================
# 🚀 MAIN SCANNER RUNNER & AUTOMATED TRADER BRIDGE
# =========================================================
# =========================================================
# 🚀 MAIN SCANNER RUNNER & AUTOMATED TRADER BRIDGE
# =========================================================
def run_legendary_engine():
    print('=' * 80)
    print('   🏛️ LEGENDARY ENGINE v3.5 (QUANT CVD + OI SQUEEZE + DIRECT DB BRIDGE) 🏛️')
    print('=' * 80)

    print('\n⏳ Fetching BTC Macro Market Guard...')
    btc_regime, btc_price = get_btc_macro_regime()
    print(f'🌐 BTC Market Regime: [{btc_regime}] @ ${btc_price:.2f} USDT\n')

    print(f'🔍 Scanning {len(PAIRS)} Pairs for High Order-Book Depth, Low Slippage & Trend Strength...')
    print('-' * 80)

    results, rejected = [], []
    for pair in PAIRS:
        res = analyze_legendary_setup(pair, btc_regime)
        if res:
            if res.get('status') == 'PASSED':
                results.append(res)
            else:
                rejected.append(res)
        time.sleep(0.04)

    results.sort(key=lambda x: x['score'], reverse=True)

    high_conviction = [r for r in results if r['bias'] in ['LONG', 'SHORT']]
    blocked_trades = [r for r in results if 'BLOCKED' in r['signal']]
    neutral_trades = [r for r in results if r['bias'] not in ['LONG', 'SHORT'] and 'BLOCKED' not in r['signal']]

    def fmt_p(price):
        return f'{price:.6f}'.rstrip('0').rstrip('.') if price < 1 else f'{price:.2f}'

    print('\n' + '=' * 80)
    print('🎯 HIGH-CONVICTION SAFE TRADES (EXECUTION CARDS FOR $100 CAPITAL)')
    print('=' * 80)
    if high_conviction:
        for item in high_conviction:
            print(f"\n🪙 PAIR: {item['symbol']} | Signal: {item['signal']} | Score: {item['score']}/100")
            print(f"   ├─ Leverage: {item['leverage']}x | Margin: ${item['margin_usdt']:.2f} USDT | Risk: ${item['risk_usdt']:.2f} USDT (1%)")
            print(f"   ├─ Position Size: ${item['pos_size_usdt']:.2f} USDT Notional | Qty: {item.get('coin_qty', 0.0)}")
            print(f"   ├─ Entry Price : ${fmt_p(item['entry'])}")
            print(f"   ├─ Stop Loss   : ${fmt_p(item['sl'])} (-{item['sl_pct']:.2f}%)")
            print(f"   ├─ Target 1    : ${fmt_p(item['tp1'])} (R:R 1:1.5)")
            print(f"   ├─ Target 2    : ${fmt_p(item['tp2'])} (R:R 1:2.0)")
            print(f"   └─ Confluences : {', '.join(item['confluences'])}\n")
    else:
        print('   (Koi high-probability safe trade spot nahi hui. Capital preserve karein!)\n')

    # =================================================================
    # 🎯 DIRECT DB SIGNAL PASSING (NO CONDITIONS AT ALL)
    # =================================================================
    if high_conviction:
        print('=' * 80)
        print(f"📥 Passing {len(high_conviction)} generated signal(s) directly to DB...")
        print('=' * 80)
        for item in high_conviction:
            # Har signal jaise hi high_conviction mein aayega, foran bina kisi condition ke pass ho jayega
            save_all_signals_in_db(item)
    else:
        print("ℹ️ No high conviction signals generated in this run to pass to DB.")

    # =================================================================
    # 🛡️ SUMMARY & LOGGING REPORTS
    # =================================================================
    if blocked_trades:
        print("\n" + "=" * 80)
        print("🛡️ BTC / MTF GUARD BLOCKED TRADES")
        print("=" * 80)
        for item in blocked_trades:
            print(f"⚠️ {item['symbol']:<10} | Signal: {item['signal']} | Score: {item['score']}/100")
            print(f"   └─ Reason: Macro Trend ({btc_regime} / MTF Structure) trade direction ke opposite hai.\n")

    if rejected:
        print("=" * 80)
        print(f"🛡️ REJECTED COINS ({len(rejected)} Pairs filtered due to High Spread / Volatility / Sideways Risk)")
        print("=" * 80)
        for r in rejected[:15]:
            print(f"❌ {r['symbol']:<10} | Reason: {r['reason']}")
        if len(rejected) > 15:
            print(f"   ... and {len(rejected) - 15} more coins rejected for safe trading.")
        print("\n")

    print("=" * 80)
    print("🟡 LOW CONVICTION / NEUTRAL WATCHLIST SUMMARY")
    print("=" * 80)
    summary_list = [f"{i['symbol']}:{i['score']}" for i in neutral_trades]
    print("   " + (", ".join(summary_list) if summary_list else "None"))
    print("\n" + "=" * 80 + "\n")

    return {
        "status": "success",
        "processed_signals": len(high_conviction)
    }


    # =================================================================
    # 🎯 SIGNAL PROCESSING & PAPER DB NOTIFICATION BUILDER
    # =================================================================
    # =================================================================
    # 🎯 SIGNAL PROCESSING & PAPER DB NOTIFICATION BUILDER
    # =================================================================
    # =================================================================
    # 🎯 SIGNAL PROCESSING & DUAL DB ROUTING BUILDER
    # =================================================================
    if pushbullet_signals:
        new_signals_count = 0

        for item in pushbullet_signals:
            symbol = item["symbol"]
            direction = item["bias"]
            score = item["score"]

            # Dual DB Status Check
            paper_active = is_trade_running_in_db(symbol)
            
            # Helper logic: Check if active on Real DB Guard
            is_real_blocked, real_block_reason = check_db_trade_guard(symbol, direction)
            is_real_active = is_real_blocked and ("Active trade already exists" in real_block_reason)

            # -------------------------------------------------------------
            # 1. PAPER TRADING DB ROUTING
            # -------------------------------------------------------------
            if not paper_active:
                paper_saved = save_signal_to_paper_trade_db(item)

                if paper_saved:
                    new_signals_count += 1

                    # Notification Title
                    single_alert_title = (
                        f"🚨 {symbol} - {item['signal']} (Score: {item['score']})"
                    )

                    # Notification Body Formatting
                    card_body = f"🌐 BTC Regime: {btc_regime} (${fmt_p(btc_price)})\n"
                    card_body += "========================================\n"
                    card_body += f"🪙 PAIR: {symbol}\n"
                    card_body += f"📊 Signal: {item['signal']} | Score: {item['score']}/100\n"
                    card_body += f"⚙️ Execution: Leverage {item['leverage']}x | Margin: ${item['margin_usdt']:.2f} USDT\n"
                    card_body += f"💵 Pos Size: ${item['pos_size_usdt']:.2f} USDT | Max Risk: ${item['risk_usdt']:.2f} USDT (1%)\n"
                    card_body += f"📥 Entry Price : ${fmt_p(item['entry'])}\n"
                    card_body += f"🛑 Stop Loss   : ${fmt_p(item['sl'])} (-{item['sl_pct']:.2f}%)\n"
                    card_body += f"🎯 Target 1    : ${fmt_p(item['tp1'])} (R:R 1:1.5)\n"
                    card_body += f"🎯 Target 2    : ${fmt_p(item['tp2'])} (R:R 1:2.0)\n\n"
                    card_body += "📈 QUANT STATS:\n"
                    card_body += f"   • 4H RSI: {item['rsi_4h']:.1f} | 4H ADX: {item['adx_4h']:.1f}\n"
                    card_body += f"   • CVD Taker Buy Ratio: {item['taker_ratio']:.2f}x | 15m OI Delta: {item['oi_delta']:+.2f}%\n"
                    card_body += f"   • Orderbook Ratio: {item['ob_ratio']:.2f}x | Funding Rate: {item['funding']:.4f}%\n"
                    card_body += f"   • Key Levels: Sup ${fmt_p(item['support'])} | Res ${fmt_p(item['resistance'])}\n\n"
                    card_body += "💡 CONFLUENCES & REASONS:\n"
                    for conf in item["confluences"]:
                        card_body += f"   ✓ {conf}\n"

                    send_pushbullet_notification(single_alert_title, card_body)
                    time.sleep(1)  # API rate-limit delay
            else:
                print(f"⏭️ [PAPER DB] Skipping {symbol}: Active trade already exists in Paper DB.")

            # -------------------------------------------------------------
            # 2. REAL TRADER ENGINE ROUTING
            # -------------------------------------------------------------
            if TRADER_ENGINE_AVAILABLE:
                if not is_real_active:
                    if is_real_blocked:
                        print(f"🛡️ [REAL DB GUARD] Skipping Engine for {symbol}: {real_block_reason}")
                        alert_title = f"🛡️ TRADE GUARD BLOCKED: {symbol}"
                        alert_body = (
                            f"⚠️ Engine execution bypassed for {symbol}.\n"
                            f"📌 Reason: {real_block_reason}\n"
                            f"📊 Signal Bias: {direction} | Score: {score}/100\n"
                            f"⏰ Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
                        )
                        send_pushbullet_notification(alert_title, alert_body)
                    else:
                        print(f"🚀 [REAL ENGINE] Trade not active on Real DB. Executing Trader Engine for [{symbol}]...")
                        process_trade_logic(symbol)
                else:
                    print(f"🛡️ [REAL DB] Skipping Engine for {symbol}: Active trade already running on Real DB.")

        if new_signals_count == 0:
            print("ℹ️ All signals were already active in Paper DB. Notification skipped.")
    else:
        print("ℹ️ No high conviction signal found reaching score threshold. Skipping Pushbullet notification.")

    # =================================================================
    # 🛡️ SUMMARY & LOGGING REPORTS
    # =================================================================
    if blocked_trades:
        print("=" * 80)
        print("🛡️ BTC / MTF GUARD BLOCKED TRADES")
        print("=" * 80)
        for item in blocked_trades:
            print(f"⚠️ {item['symbol']:<10} | Signal: {item['signal']} | Score: {item['score']}/100")
            print(f"   └─ Reason: Macro Trend ({btc_regime} / MTF Structure) trade direction ke opposite hai.\n")

    if rejected:
        print("=" * 80)
        print(f"🛡️ REJECTED COINS ({len(rejected)} Pairs filtered due to High Spread / Volatility / Sideways Risk)")
        print("=" * 80)
        for r in rejected[:15]:
            print(f"❌ {r['symbol']:<10} | Reason: {r['reason']}")
        if len(rejected) > 15:
            print(f"   ... and {len(rejected) - 15} more coins rejected for safe trading.")
        print("\n")

    print("=" * 80)
    print("🟡 LOW CONVICTION / NEUTRAL WATCHLIST SUMMARY")
    print("=" * 80)
    summary_list = [f"{i['symbol']}:{i['score']}" for i in neutral_trades]
    print("   " + (", ".join(summary_list) if summary_list else "None"))
    print("\n" + "=" * 80 + "\n")



    # =========================================================
    # 🔗 AUTOMATED TRADER ENGINE INTEGRATION TRIGGER
    # =========================================================
    if TRADER_ENGINE_AVAILABLE and pushbullet_signals:
        print(f"\n🤖 [AUTOMATION BRIDGE] Found {len(pushbullet_signals)} high conviction signal(s). Checking DB Guard...")
        
        executed_trades = []
        for trade in pushbullet_signals:
            symbol = trade['symbol']
            score = trade['score']
            direction = trade['bias']
            
            is_blocked, block_reason = check_db_trade_guard(symbol, direction)

            if is_blocked:
                print(f"🛡️ [DB GUARD BLOCKED] Skipping Engine for {symbol}: {block_reason}")
                
                alert_title = f"🛡️ TRADE GUARD BLOCKED: {symbol}"
                alert_body = (
                    f"⚠️ Engine execution bypassed for {symbol}.\n"
                    f"📌 Reason: {block_reason}\n"
                    f"📊 Signal Bias: {direction} | Score: {score}/100\n"
                    f"⏰ Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
                )
                send_pushbullet_notification(alert_title, alert_body)
                continue

            print(f"🚀 Triggering Trader Engine for [{symbol}] (Score: {score})...")
            result = process_trade_logic(symbol)
            executed_trades.append({"symbol": symbol, "score": score, "result": result})
            
        return {
            "status": "success",
            "executed_count": len(executed_trades),
            "trades": executed_trades
        }

    elif TRADER_ENGINE_AVAILABLE:
        print("\n🤖 [AUTOMATION BRIDGE] No valid trade passed threshold to execute in Trader Engine.")
        return {
            "status": "skipped",
            "reason": "No high-conviction signals passed threshold."
        }

    else:
        print("\n⚠️ [AUTOMATION BRIDGE] Trader Engine unavailable or disabled.")
        return {
            "status": "disabled",
            "reason": "Trader Engine module not imported."
        }


if __name__ == '__main__':
    run_legendary_engine()
