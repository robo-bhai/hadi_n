import os
import ssl
import sqlite3
import requests
import pandas as pd
from datetime import datetime

# Remote MySQL Support Check
try:
    import mysql.connector
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False

# =========================================================
# ⚙️ API ENDPOINTS & CONFIG
# =========================================================
BINANCE_SPOT_URL = "https://api.binance.com/api/v3/klines"
BINANCE_TICKER_URL = "https://api.binance.com/api/v3/ticker/price"
BINANCE_FEE_RATE = 0.00075 

# =========================================================
# 🔌 RESPONSIVE MULTI-ENGINE DATABASE CONNECTOR
# =========================================================
def get_db_connection():
    """
    Responsive DB Engine: Remote MySQL (Aiven/Secrets) se connect karega.
    Agar fail ho ya credentials na ho toh Local SQLite par fallback kar jayega.
    """
    db_host = os.environ.get("DB_HOST", "mysql-3a3d5779-project-b71a.b.aivencloud.com")
    db_user = os.environ.get("DB_USER", "avnadmin")
    db_pass = os.environ.get("DB_PASS", os.environ.get("DB_PASSWORD", ""))
    db_name = os.environ.get("DB_NAME", "defaultdb")
    db_port = int(os.environ.get("DB_PORT", "23464"))

    if MYSQL_AVAILABLE and db_pass:
        # Attempt 1: Native SSL Context (Termux / Actions / Ubuntu)
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
            print(f"⚠️ Remote MySQL Error: {e}. Falling back to SQLite...")

    # Fallback to Local SQLite DB
    conn = sqlite3.connect("trading_system.db")
    return conn, "SQLITE"

# =========================================================
# 📲 NOTIFICATION ENGINE (PUSHBULLET)
# =========================================================
def send_pushbullet_notification(title, body):
    api_token = os.getenv('PUSHBULLET_TOKEN')
    if not api_token:
        print("⚠️ PUSHBULLET_TOKEN secret set nahi hai. Alert skip ho raha hai.")
        return

    url = 'https://api.pushbullet.com/v2/pushes'
    headers = {'Access-Token': api_token, 'Content-Type': 'application/json'}
    payload = {'type': 'note', 'title': title, 'body': body}
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=5)
        if res.status_code == 200:
            print("🚀 Pushbullet alert trigger ho gaya!")
        else:
            print(f"❌ Pushbullet failed: {res.status_code} - {res.text}")
    except Exception as e:
        print(f"❌ Pushbullet Request Error: {e}")

# =========================================================
# 📊 BINANCE MARKET DATA FETCHERS
# =========================================================
def fetch_live_price(symbol):
    try:
        res = requests.get(f"{BINANCE_TICKER_URL}?symbol={symbol}", timeout=4)
        if res.status_code == 200:
            return float(res.json()['price'])
    except Exception:
        pass
    return None

def fetch_full_trade_klines(symbol, start_time_ms):
    all_candles = []
    current_start = start_time_ms
    now_ms = int(datetime.now().timestamp() * 1000)

    while current_start < now_ms:
        url = f"{BINANCE_SPOT_URL}?symbol={symbol}&interval=1m&startTime={current_start}&limit=1000"
        try:
            res = requests.get(url, timeout=5)
            if res.status_code == 200:
                data = res.json()
                if not data:
                    break
                all_candles.extend(data)
                last_candle_time = data[-1][0]
                if last_candle_time <= current_start:
                    break
                current_start = last_candle_time + 60000
            else:
                break
        except Exception:
            break

    if not all_candles:
        return None

    df = pd.DataFrame(all_candles, columns=['time', 'open', 'high', 'low', 'close', '_', '_', '_', '_', '_', '_', '_'])
    for col in ['time', 'high', 'low', 'close']:
        df[col] = df[col].astype(float)
    return df

# =========================================================
# 🔄 PROCESS ACTIVE TRADES & TIMELINE TRACKING
# =========================================================
def process_active_trades():
    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    ph = "%s" if db_type == "MYSQL" else "?"

    cursor.execute(f"SELECT total_capital, available_capital, frozen_margin FROM portfolio WHERE id = {ph}", (1,))
    port_row = cursor.fetchone()
    if not port_row:
        conn.close()
        return
    total_cap, avail_cap, frozen_margin = port_row

    cursor.execute(f"SELECT id, timestamp, symbol, direction, entry_price, sl_price, tp1_price, tp2_price, margin_frozen, pos_value FROM trades WHERE status = {ph}", ('ACTIVE',))
    active_trades = cursor.fetchall()

    for trade in active_trades:
        t_id, t_time_str, symbol, direction, entry_p, sl_p, tp1_p, tp2_p, margin, pos_val = trade
        try:
            dt_obj = datetime.strptime(str(t_time_str), "%Y-%m-%d %H:%M:%S")
            start_ms = int(dt_obj.timestamp() * 1000)
        except Exception:
            continue

        df = fetch_full_trade_klines(symbol, start_ms)
        if df is None or df.empty:
            continue

        status = 'ACTIVE'
        gross_pnl = 0.0

        for _, row in df.iterrows():
            c_time_ms = row['time']
            c_high, c_low, c_close = row['high'], row['low'], row['close']
            time_elapsed_seconds = (c_time_ms - start_ms) / 1000.0

            if direction == "LONG":
                if c_low <= sl_p:
                    status = 'CLOSED_SL'
                    gross_pnl = -pos_val * ((entry_p - sl_p) / entry_p)
                    break
                elif c_high >= tp2_p:
                    status = 'CLOSED_TP2'
                    gross_pnl = pos_val * ((tp2_p - entry_p) / entry_p)
                    break
                elif c_high >= tp1_p:
                    status = 'CLOSED_TP1'
                    gross_pnl = pos_val * ((tp1_p - entry_p) / entry_p)
                    break
                elif time_elapsed_seconds >= 86400:
                    candle_gross_pnl = pos_val * ((c_close - entry_p) / entry_p)
                    entry_fee = pos_val * BINANCE_FEE_RATE
                    exit_val = max(0, pos_val + candle_gross_pnl)
                    exit_fee = exit_val * BINANCE_FEE_RATE
                    net_pnl_check = candle_gross_pnl - (entry_fee + exit_fee)
                    net_pct = (net_pnl_check / margin) * 100 if margin > 0 else 0.0

                    if net_pct > 0.5:
                        status = 'CLOSED_24H_PROFIT'
                        gross_pnl = candle_gross_pnl
                        break
            else:  # SHORT Direction
                if c_high >= sl_p:
                    status = 'CLOSED_SL'
                    gross_pnl = -pos_val * ((sl_p - entry_p) / entry_p)
                    break
                elif c_low <= tp2_p:
                    status = 'CLOSED_TP2'
                    gross_pnl = pos_val * ((entry_p - tp2_p) / entry_p)
                    break
                elif c_low <= tp1_p:
                    status = 'CLOSED_TP1'
                    gross_pnl = pos_val * ((entry_p - tp1_p) / entry_p)
                    break
                elif time_elapsed_seconds >= 86400:
                    candle_gross_pnl = pos_val * ((entry_p - c_close) / entry_p)
                    entry_fee = pos_val * BINANCE_FEE_RATE
                    exit_val = max(0, pos_val + candle_gross_pnl)
                    exit_fee = exit_val * BINANCE_FEE_RATE
                    net_pnl_check = candle_gross_pnl - (entry_fee + exit_fee)
                    net_pct = (net_pnl_check / margin) * 100 if margin > 0 else 0.0

                    if net_pct > 0.5:
                        status = 'CLOSED_24H_PROFIT'
                        gross_pnl = candle_gross_pnl
                        break

        if status != 'ACTIVE':
            entry_fee = pos_val * BINANCE_FEE_RATE
            exit_value = max(0, pos_val + gross_pnl)
            exit_fee = exit_value * BINANCE_FEE_RATE
            net_pnl = gross_pnl - (entry_fee + exit_fee)

            cursor.execute(f"UPDATE trades SET status = {ph}, pnl = {ph} WHERE id = {ph}", (status, net_pnl, t_id))
            frozen_margin = max(0.0, frozen_margin - margin)
            avail_cap += (margin + net_pnl)
            total_cap += net_pnl

            cursor.execute(f"UPDATE portfolio SET total_capital = {ph}, available_capital = {ph}, frozen_margin = {ph} WHERE id = 1",
                           (total_cap, avail_cap, frozen_margin))

    conn.commit()
    conn.close()

# =========================================================
# 📋 GENERATE & SEND FORMATTED PUSHBULLET REPORT
# =========================================================
def generate_and_send_report():
    process_active_trades()
    conn, db_type = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id, symbol, direction, entry_price, sl_price, tp1_price, tp2_price, margin_frozen, pos_value, leverage, status, pnl FROM trades ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        send_pushbullet_notification("📊 TRADE REPORT SUMMARY", "Database mein koi trades mojood nahi hain.")
        return

    def fmt_p(p):
        return f"{p:.6f}".rstrip('0').rstrip('.') if p and p < 1 else f"{p:.2f}" if p else "0.00"

    report_title = f"📊 QUANT TRADE MONITOR REPORT ({len(rows)} Trades)"
    report_body = f"🏛️ DB Engine: [{db_type}]\n"
    report_body += "========================================\n\n"

    for r in rows:
        t_id, symbol, direction, entry_p, sl_p, tp1_p, tp2_p, margin, pos_val, lev, status, pnl = r
        pnl = pnl if pnl is not None else 0.0
        live_p = fetch_live_price(symbol) or entry_p

        # Status formatting & icons
        if status == 'ACTIVE':
            status_icon = "🟢 RUNNING"
            if direction == 'LONG':
                float_pnl = pos_val * ((live_p - entry_p) / entry_p)
            else:
                float_pnl = pos_val * ((entry_p - live_p) / entry_p)
            pnl_str = f"Floating: ${float_pnl:+.2f}"
        elif 'CLOSED_TP' in status or status == 'CLOSED_24H_PROFIT':
            status_icon = "🎯 HIT TARGET (WIN)"
            pnl_str = f"Net PnL: ${pnl:+.2f}"
        elif status == 'CLOSED_SL':
            status_icon = "🛑 HIT STOPLOSS (LOSS)"
            pnl_str = f"Net PnL: ${pnl:+.2f}"
        else:
            status_icon = f"🔴 {status}"
            pnl_str = f"Net PnL: ${pnl:+.2f}"

        report_body += f"🪙 PAIR: {symbol} [{direction}]\n"
        report_body += f"📌 Current Status : {status_icon}\n"
        report_body += f"💵 Trade Margin  : ${margin:.2f} USDT\n"
        report_body += f"⚡ Leverage      : {lev}x (Pos: ${pos_val:.2f})\n"
        report_body += f"📥 Entry Point   : ${fmt_p(entry_p)}\n"
        report_body += f"📊 Live Price    : ${fmt_p(live_p)}\n"
        report_body += f"🛑 SL Price      : ${fmt_p(sl_p)}\n"
        report_body += f"🎯 TP1 Price     : ${fmt_p(tp1_p)}\n"
        report_body += f"🚀 TP2 Price     : ${fmt_p(tp2_p)}\n"
        report_body += f"💰 PnL Status    : {pnl_str}\n"
        report_body += "----------------------------------------\n"

    send_pushbullet_notification(report_title, report_body)

if __name__ == "__main__":
    generate_and_send_report()
