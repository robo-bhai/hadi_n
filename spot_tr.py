import os
import requests
import pandas as pd
import numpy as np
import psycopg2

# ==========================================================
# CONFIGURATION & GITHUB SECRETS
# ==========================================================
DB_HOST = "pg-39432034-project-b71a.aivencloud.com"
DB_PORT = "23464"
DB_NAME = "defaultdb"
DB_USER = "avnadmin"
DB_PASSWORD = os.getenv("DB_SPOT_PASSWORD")  # Reads from GitHub Secrets / Env Var

NTFY_TOPIC_URL = "https://ntfy.sh/spot_tr_99_23"

# Position & Risk Rules
INITIAL_BALANCE = 300.0
MAX_ACTIVE_TRADES = 5
BASE_TRADE_AMOUNT = 30.0  # $30 Initial Allocation
RE_ENTRY_ADD_AMOUNT = 5.0 # +$5 if strong signal repeats (Max $35)
MAX_TRADE_AMOUNT = 35.0

def send_ntfy_notification(title, message, tags="chart_with_upwards_trend"):
    """ntfy.sh topic 'spot_tr_99_23' par instant alert push karta hai."""
    try:
        requests.post(
            NTFY_TOPIC_URL,
            data=message.encode('utf-8'),
            headers={
                "Title": title,
                "Tags": tags,
                "Priority": "high"
            },
            timeout=10
        )
        print(f"[+] Push notification sent: {title}")
    except Exception as e:
        print(f"[!] Notification Error: {e}")

def get_db_connection():
    if not DB_PASSWORD:
        print("[!] DB_PASSWORD environment variable / secret missing.")
        return None
    try:
        return psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            dbname=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD,
            sslmode="require"
        )
    except Exception as e:
        print(f"[!] DB Connection Error: {e}")
        return None

def init_db():
    """Database tables aur schema auto-create karta hai."""
    create_query = """
    CREATE TABLE IF NOT EXISTS trades (
        id SERIAL PRIMARY KEY,
        symbol VARCHAR(20) NOT NULL,
        gain_percent NUMERIC(5, 2),
        entry_price NUMERIC(12, 4),
        allocated_amount NUMERIC(8, 2),
        rsi NUMERIC(5, 2),
        vol_spike NUMERIC(5, 2),
        taker_buy_pct NUMERIC(5, 2),
        tp1 NUMERIC(12, 4),
        tp2 NUMERIC(12, 4),
        stop_loss NUMERIC(12, 4),
        status VARCHAR(20) DEFAULT 'ACTIVE',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute(create_query)
            conn.commit()
            cur.close()
            conn.close()
            print("[+] DB Schema verification complete.")
        except Exception as e:
            print(f"[!] Init DB Error: {e}")

def track_and_update_saved_trades():
    """Active trades ki execution check karta hai aur TP/SL hit par alert karta hai."""
    conn = get_db_connection()
    if not conn:
        return

    try:
        cur = conn.cursor()
        cur.execute("SELECT id, symbol, entry_price, allocated_amount, tp1, tp2, stop_loss, status, created_at FROM trades WHERE status IN ('ACTIVE', 'TP1_HIT');")
        active_trades = cur.fetchall()

        for trade in active_trades:
            trade_id, symbol, entry_price, amount, tp1, tp2, stop_loss, status, created_at = trade
            
            # Fetch Live Binance Price
            url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
            curr_price = float(requests.get(url, timeout=5).json()['price'])
            
            new_status = status
            alert_title = ""
            alert_msg = ""

            if curr_price <= float(stop_loss):
                new_status = "SL_HIT"
                pnl_loss = round(float(amount) * ((curr_price - float(entry_price)) / float(entry_price)), 2)
                alert_title = f"🚨 STOP LOSS HIT: {symbol}"
                alert_msg = f"Symbol: {symbol}\nEntry: ${entry_price}\nExit Price: ${curr_price}\nEstimated PnL: ${pnl_loss}\nPosition Size: ${amount}\nCreated: {created_at}"

            elif curr_price >= float(tp2):
                new_status = "TP2_HIT"
                pnl_win = round(float(amount) * ((curr_price - float(entry_price)) / float(entry_price)), 2)
                alert_title = f"🎯 TARGET 2 HIT (+12%): {symbol}"
                alert_msg = f"Symbol: {symbol}\nEntry: ${entry_price}\nExit Price: ${curr_price}\nProfit: +${pnl_win}\nPosition Size: ${amount}"

            elif curr_price >= float(tp1) and status == 'ACTIVE':
                new_status = "TP1_HIT"
                pnl_win = round(float(amount) * ((curr_price - float(entry_price)) / float(entry_price)), 2)
                alert_title = f"✅ TARGET 1 HIT (+6%): {symbol}"
                alert_msg = f"Symbol: {symbol}\nEntry: ${entry_price}\nTarget Price: ${curr_price}\nPartial Profit: +${pnl_win}"

            if new_status != status:
                cur.execute("UPDATE trades SET status = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s;", (new_status, trade_id))
                conn.commit()
                send_ntfy_notification(alert_title, alert_msg, tags="heavy_dollar_sign" if "TP" in new_status else "warning")

        cur.close()
        conn.close()
    except Exception as e:
        print(f"[!] Tracking Error: {e}")

def count_active_trades():
    conn = get_db_connection()
    if not conn:
        return 0
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM trades WHERE status IN ('ACTIVE', 'TP1_HIT');")
    count = cur.fetchone()[0]
    cur.close()
    conn.close()
    return count

def check_existing_active_trade(symbol):
    conn = get_db_connection()
    if not conn:
        return None
    cur = conn.cursor()
    cur.execute("SELECT id, allocated_amount FROM trades WHERE symbol = %s AND status IN ('ACTIVE', 'TP1_HIT');", (symbol,))
    record = cur.fetchone()
    cur.close()
    conn.close()
    return record

def save_or_upgrade_trade(signal):
    conn = get_db_connection()
    if not conn:
        return
    
    cur = conn.cursor()
    existing = check_existing_active_trade(signal['Symbol'])
    
    if existing:
        trade_id, current_amount = existing
        new_amount = min(float(current_amount) + RE_ENTRY_ADD_AMOUNT, MAX_TRADE_AMOUNT)
        if new_amount > float(current_amount):
            cur.execute("UPDATE trades SET allocated_amount = %s, updated_at = CURRENT_TIMESTAMP WHERE id = %s;", (new_amount, trade_id))
            conn.commit()
            send_ntfy_notification(
                f"📈 SIGNAL RE-ENTRY ADDITION: {signal['Symbol']}",
                f"Strong signal repeated.\nPosition increased from ${current_amount} to ${new_amount}.\nCurrent Price: ${signal['Price_Val']}"
            )
    else:
        active_count = count_active_trades()
        if active_count >= MAX_ACTIVE_TRADES:
            print(f"[!] Skipping {signal['Symbol']}: Active Trade limit reached ({MAX_ACTIVE_TRADES}/{MAX_ACTIVE_TRADES}).")
            return

        insert_query = """
        INSERT INTO trades (
            symbol, gain_percent, entry_price, allocated_amount, rsi, vol_spike, 
            taker_buy_pct, tp1, tp2, stop_loss, status
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'ACTIVE');
        """
        cur.execute(insert_query, (
            signal['Symbol'], signal['Gain_Val'], signal['Price_Val'], BASE_TRADE_AMOUNT,
            signal['RSI'], signal['VolSpike_Val'], signal['TakerBuy_Val'],
            signal['TP1'], signal['TP2'], signal['SL']
        ))
        conn.commit()
        send_ntfy_notification(
            f"🚀 NEW SIGNAL TRIGGERED: {signal['Symbol']}",
            f"Entry Price: ${signal['Price_Val']}\nAllocated Capital: ${BASE_TRADE_AMOUNT}\nTP1: ${signal['TP1']} | TP2: ${signal['TP2']}\nStop Loss: ${signal['SL']}"
        )
    cur.close()
    conn.close()

def get_top_gainers(limit=20):
    url = "https://api.binance.com/api/v3/ticker/24hr"
    try:
        data = requests.get(url, timeout=10).json()
        usdt_pairs = [
            item for item in data 
            if item['symbol'].endswith('USDT') 
            and not item['symbol'].endswith(('UPUSDT', 'DOWNUSDT', 'BEARUSDT', 'BULLUSDT'))
            and float(item['quoteVolume']) > 1_000_000
        ]
        return sorted(usdt_pairs, key=lambda x: float(x['priceChangePercent']), reverse=True)[:limit]
    except Exception as e:
        print(f"Error fetching tickers: {e}")
        return []

def get_klines(symbol, interval='1h', limit=100):
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    data = requests.get(url, timeout=10).json()
    df = pd.DataFrame(data, columns=['open_time', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'quote_volume', 'trades', 'taker_base_vol', 'taker_quote_vol', 'ignore'])
    numeric_cols = ['open', 'high', 'low', 'close', 'volume', 'quote_volume', 'taker_base_vol']
    df[numeric_cols] = df[numeric_cols].apply(pd.to_numeric)
    return df

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calculate_ema(series, span):
    return series.ewm(span=span, adjust=False).mean()

def analyze_coin(symbol, gain_pct):
    df = get_klines(symbol, interval='1h', limit=100)
    if df.empty:
        return None
    
    df['RSI'] = calculate_rsi(df['close'], period=14)
    df['EMA_20'] = calculate_ema(df['close'], span=20)
    df['EMA_50'] = calculate_ema(df['close'], span=50)
    df['Volume_MA'] = df['volume'].rolling(window=20).mean()
    
    last_row = df.iloc[-1]
    prev_rows = df.iloc[-20:-1]
    
    price = float(last_row['close'])
    rsi = float(last_row['RSI']) if pd.notna(last_row['RSI']) else 0.0
    ema20 = float(last_row['EMA_20'])
    ema50 = float(last_row['EMA_50'])
    
    vol_spike_ratio = float(last_row['volume'] / last_row['Volume_MA']) if last_row['Volume_MA'] > 0 else 1.0
    taker_buy_percent = float((last_row['taker_base_vol'] / last_row['volume']) * 100) if last_row['volume'] > 0 else 50.0
    
    recent_high = float(prev_rows['high'].max())
    is_breakout = price > recent_high

    if not (vol_spike_ratio >= 1.5 and taker_buy_percent >= 52.0 and is_breakout and rsi <= 75.0 and ema20 > ema50):
        return None

    return {
        "Symbol": symbol,
        "Gain_Val": round(float(gain_pct), 2),
        "Price_Val": round(price, 4),
        "RSI": round(rsi, 1),
        "VolSpike_Val": round(vol_spike_ratio, 1),
        "TakerBuy_Val": round(taker_buy_percent, 1),
        "TP1": round(price * 1.06, 4),
        "TP2": round(price * 1.12, 4),
        "SL": round(ema20, 4)
    }

def main():
    init_db()
    
    # 1. Active Trades Check & Update
    track_and_update_saved_trades()
    
    # 2. Market Scanning for New/Upgraded Signals
    gainers = get_top_gainers(20)
    for ticker in gainers:
        res = analyze_coin(ticker['symbol'], ticker['priceChangePercent'])
        if res:
            save_or_upgrade_trade(res)

if __name__ == "__main__":
    main()
