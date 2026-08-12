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
# ⚙️ API ENDPOINTS & CONFIG (BINANCE VISION INTEGRATED)
# =========================================================
BINANCE_SPOT_URL = 'https://data-api.binance.vision/api/v3/klines'
BINANCE_BOOK_TICKER_URL = 'https://data-api.binance.vision/api/v3/ticker/bookTicker'
BINANCE_DEPTH_URL = 'https://data-api.binance.vision/api/v3/depth'
BINANCE_FUTURES_FUNDING_URL = 'https://fapi.binance.com/fapi/v1/premiumIndex'

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
# 📊 ACCURATE BINANCE VISION LIVE PRICE FETCH
# =========================================================
def fetch_live_price(symbol):
    if not symbol:
        return None
    
    clean_symbol = str(symbol).strip().upper()
    
    # 1. Fetch via Binance Vision Book Ticker Endpoint
    try:
        url = f"{BINANCE_BOOK_TICKER_URL}?symbol={clean_symbol}"
        res = requests.get(url, timeout=4)
        if res.status_code == 200:
            data = res.json()
            bid = float(data.get('bidPrice', 0))
            ask = float(data.get('askPrice', 0))
            if bid > 0 and ask > 0:
                return (bid + ask) / 2.0
            elif bid > 0:
                return bid
            elif ask > 0:
                return ask
    except Exception as e:
        print(f"⚠️ Book Ticker fetch failed for {clean_symbol}: {e}")

    # 2. Fallback via Binance Futures Funding Endpoint
    try:
        url = f"{BINANCE_FUTURES_FUNDING_URL}?symbol={clean_symbol}"
        res = requests.get(url, timeout=4)
        if res.status_code == 200:
            val = float(res.json().get('markPrice', 0))
            if val > 0:
                return val
    except Exception as e:
        print(f"⚠️ Futures Funding fetch failed for {clean_symbol}: {e}")

    print(f"❌ ERROR: Live price not found for {clean_symbol}")
    return None

# =========================================================
# 🕯️ DOWNLOAD 1m CANDLES FROM TRADE START TIME TO NOW
# =========================================================
def fetch_full_trade_klines(symbol, start_time_ms):
    clean_symbol = str(symbol).strip().upper()
    all_candles = []
    current_start = start_time_ms
    now_ms = int(datetime.now().timestamp() * 1000)

    while current_start < now_ms:
        url = f"{BINANCE_SPOT_URL}?symbol={clean_symbol}&interval=1m&startTime={current_start}&limit=1000"
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
        except Exception as e:
            print(f"⚠️ Error fetching klines for {clean_symbol}: {e}")
            break

    if not all_candles:
        return None

    # DataFrame creation for candles
    df = pd.DataFrame(all_candles, columns=['time', 'open', 'high', 'low', 'close', '_', '_', '_', '_', '_', '_', '_'])
    for col in ['time', 'open', 'high', 'low', 'close']:
        df[col] = df[col].astype(float)
    
    # Chronological Sorting (Ensure 100% Sequence Order)
    df = df.sort_values(by='time', ascending=True).reset_index(drop=True)
    return df

# =========================================================
# 🔄 PROCESS ACTIVE TRADES (SEQUENTIAL CANDLE EVALUATION)
# =========================================================
def process_active_trades():
    print("\n" + "="*60)
    print("🔍 ACTIVE TRADES CANDLE CHECKING & MONITORING INITIALIZED")
    print("="*60)

    conn, db_type = get_db_connection()
    cursor = conn.cursor()
    ph = "%s" if db_type == "MYSQL" else "?"

    cursor.execute(f"SELECT total_capital, available_capital, frozen_margin FROM portfolio WHERE id = {ph}", (1,))
    port_row = cursor.fetchone()
    if not port_row:
        print("⚠️ Portfolio record #1 not found. Aborting trade processing.")
        conn.close()
        return
    total_cap, avail_cap, frozen_margin = port_row

    cursor.execute(f"SELECT id, timestamp, symbol, direction, entry_price, sl_price, tp1_price, tp2_price, margin_frozen, pos_value FROM trades WHERE status = {ph}", ('ACTIVE',))
    active_trades = cursor.fetchall()

    if not active_trades:
        print("ℹ️ No active trades currently present in the database.")

    for trade in active_trades:
        t_id, t_time_str, symbol, direction, entry_p, sl_p, tp1_p, tp2_p, margin, pos_val = trade
        print(f"\n📌 Processing Trade ID #{t_id} | {symbol} [{direction}]")
        print(f"   - Entry: ${entry_p:.6f} | SL: ${sl_p:.6f} | TP1: ${tp1_p:.6f} | TP2: ${tp2_p:.6f}")
        print(f"   - Margin: ${margin:.2f} USDT | Pos Value: ${pos_val:.2f} USDT")

        try:
            dt_obj = datetime.strptime(str(t_time_str), "%Y-%m-%d %H:%M:%S")
            start_ms = int(dt_obj.timestamp() * 1000)
        except Exception as e:
            print(f"❌ Timestamp Parsing Error for Trade #{t_id}: {e}")
            continue

        print(f"   ⏳ Fetching 1m candles starting from: {t_time_str}...")
        df = fetch_full_trade_klines(symbol, start_ms)
        if df is None or df.empty:
            print(f"⚠️ No kline data retrieved for {symbol}. Skipping evaluation.")
            continue

        print(f"   📊 Downloaded {len(df)} candles. Evaluating sequentially candle-by-candle...")

        status = 'ACTIVE'
        gross_pnl = 0.0

        # Sequential Evaluation Candle-by-Candle
        for idx, row in df.iterrows():
            c_time_ms = row['time']
            c_dt = datetime.fromtimestamp(c_time_ms / 1000.0).strftime('%Y-%m-%d %H:%M:%S')
            c_open, c_high, c_low, c_close = row['open'], row['high'], row['low'], row['close']
            time_elapsed_seconds = (c_time_ms - start_ms) / 1000.0

            print(f"   🕯️ Candle #{idx+1} [{c_dt}] -> O:{c_open} | H:{c_high} | L:{c_low} | C:{c_close}")

            if direction == "LONG":
                # Check intra-candle movement based on candle direction
                if c_close >= c_open:
                    # Bullish Candle: Low comes first, then High
                    if c_low <= sl_p:
                        status = 'CLOSED_SL'
                        gross_pnl = -pos_val * ((entry_p - sl_p) / entry_p)
                        print(f"      🚨 SL HIT on Bullish Candle Low (${c_low} <= ${sl_p})")
                        break
                    elif c_high >= tp2_p:
                        status = 'CLOSED_TP2'
                        gross_pnl = pos_val * ((tp2_p - entry_p) / entry_p)
                        print(f"      🎯 TP2 HIT on Bullish Candle High (${c_high} >= ${tp2_p})")
                        break
                    elif c_high >= tp1_p:
                        status = 'CLOSED_TP1'
                        gross_pnl = pos_val * ((tp1_p - entry_p) / entry_p)
                        print(f"      🎯 TP1 HIT on Bullish Candle High (${c_high} >= ${tp1_p})")
                        break
                else:
                    # Bearish Candle: High comes first, then Low
                    if c_high >= tp2_p:
                        status = 'CLOSED_TP2'
                        gross_pnl = pos_val * ((tp2_p - entry_p) / entry_p)
                        print(f"      🎯 TP2 HIT on Bearish Candle High (${c_high} >= ${tp2_p})")
                        break
                    elif c_high >= tp1_p:
                        status = 'CLOSED_TP1'
                        gross_pnl = pos_val * ((tp1_p - entry_p) / entry_p)
                        print(f"      🎯 TP1 HIT on Bearish Candle High (${c_high} >= ${tp1_p})")
                        break
                    elif c_low <= sl_p:
                        status = 'CLOSED_SL'
                        gross_pnl = -pos_val * ((entry_p - sl_p) / entry_p)
                        print(f"      🚨 SL HIT on Bearish Candle Low (${c_low} <= ${sl_p})")
                        break

                # 24 Hours Exit Rule
                if time_elapsed_seconds >= 86400:
                    candle_gross_pnl = pos_val * ((c_close - entry_p) / entry_p)
                    entry_fee = pos_val * BINANCE_FEE_RATE
                    exit_val = max(0, pos_val + candle_gross_pnl)
                    exit_fee = exit_val * BINANCE_FEE_RATE
                    net_pnl_check = candle_gross_pnl - (entry_fee + exit_fee)
                    net_pct = (net_pnl_check / margin) * 100 if margin > 0 else 0.0

                    if net_pct > 0.5:
                        status = 'CLOSED_24H_PROFIT'
                        gross_pnl = candle_gross_pnl
                        print(f"      ⏱️ 24H EXIT RULE TRIGGERED! Profit Net %: {net_pct:.2f}%")
                        break

            else:  # SHORT Direction
                if c_close <= c_open:
                    # Bearish Candle: High comes first, then Low
                    if c_high >= sl_p:
                        status = 'CLOSED_SL'
                        gross_pnl = -pos_val * ((sl_p - entry_p) / entry_p)
                        print(f"      🚨 SL HIT on Bearish Candle High (${c_high} >= ${sl_p})")
                        break
                    elif c_low <= tp2_p:
                        status = 'CLOSED_TP2'
                        gross_pnl = pos_val * ((entry_p - tp2_p) / entry_p)
                        print(f"      🎯 TP2 HIT on Bearish Candle Low (${c_low} <= ${tp2_p})")
                        break
                    elif c_low <= tp1_p:
                        status = 'CLOSED_TP1'
                        gross_pnl = pos_val * ((entry_p - tp1_p) / entry_p)
                        print(f"      🎯 TP1 HIT on Bearish Candle Low (${c_low} <= ${tp1_p})")
                        break
                else:
                    # Bullish Candle: Low comes first, then High
                    if c_low <= tp2_p:
                        status = 'CLOSED_TP2'
                        gross_pnl = pos_val * ((entry_p - tp2_p) / entry_p)
                        print(f"      🎯 TP2 HIT on Bullish Candle Low (${c_low} <= ${tp2_p})")
                        break
                    elif c_low <= tp1_p:
                        status = 'CLOSED_TP1'
                        gross_pnl = pos_val * ((entry_p - tp1_p) / entry_p)
                        print(f"      🎯 TP1 HIT on Bullish Candle Low (${c_low} <= ${tp1_p})")
                        break
                    elif c_high >= sl_p:
                        status = 'CLOSED_SL'
                        gross_pnl = -pos_val * ((sl_p - entry_p) / entry_p)
                        print(f"      🚨 SL HIT on Bullish Candle High (${c_high} >= ${sl_p})")
                        break

                # 24 Hours Exit Rule
                if time_elapsed_seconds >= 86400:
                    candle_gross_pnl = pos_val * ((entry_p - c_close) / entry_p)
                    entry_fee = pos_val * BINANCE_FEE_RATE
                    exit_val = max(0, pos_val + candle_gross_pnl)
                    exit_fee = exit_val * BINANCE_FEE_RATE
                    net_pnl_check = candle_gross_pnl - (entry_fee + exit_fee)
                    net_pct = (net_pnl_check / margin) * 100 if margin > 0 else 0.0

                    if net_pct > 0.5:
                        status = 'CLOSED_24H_PROFIT'
                        gross_pnl = candle_gross_pnl
                        print(f"      ⏱️ 24H EXIT RULE TRIGGERED! Profit Net %: {net_pct:.2f}%")
                        break

        # If trade closed in sequence, update DB & portfolio & send Full Pushbullet Alert
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

            print(f"   ✅ DB UPDATED: Trade #{t_id} status changed to {status}. Net PnL: ${net_pnl:+.2f}")

            # Fetch Updated Portfolio Statistics
            cursor.execute("SELECT status, pnl FROM trades")
            all_trades = cursor.fetchall()
            
            closed_count = 0
            win_count = 0
            total_realized_pnl = 0.0

            for t_st, t_pnl in all_trades:
                pnl_val = t_pnl if t_pnl is not None else 0.0
                if t_st in ['CLOSED_TP1', 'CLOSED_TP2', 'CLOSED_SL', 'CLOSED_MANUAL', 'CLOSED_24H_PROFIT']:
                    closed_count += 1
                    total_realized_pnl += pnl_val
                    if pnl_val > 0:
                        win_count += 1

            win_rate = (win_count / closed_count * 100) if closed_count > 0 else 0.0
            initial_capital = max(1.0, total_cap - total_realized_pnl)
            total_roi = (total_realized_pnl / initial_capital) * 100

            # Fetch All Remaining Active Trades
            cursor.execute("SELECT id, symbol, direction, entry_price, sl_price, tp1_price, tp2_price, margin_frozen, pos_value, leverage, status FROM trades WHERE status = 'ACTIVE' ORDER BY id DESC")
            remaining_active_trades = cursor.fetchall()

            def fmt_p(p):
                return f"{p:.6f}".rstrip('0').rstrip('.') if p and p < 1 else f"{p:.2f}" if p else "0.00"

            event_title = f"🔔 TRADE CLOSED: {symbol} [{status}]"
            
            event_body = "🚨 CLOSED TRADE DETAILS\n"
            event_body += "========================================\n"
            event_body += f"🪙 Symbol: {symbol} [{direction}]\n"
            event_body += f"📌 Exit Status: {status}\n"
            event_body += f"📥 Entry Price: ${fmt_p(entry_p)}\n"
            event_body += f"💵 Trade Margin: ${margin:.2f} USDT\n"
            event_body += f"⚡ Position Value: ${pos_val:.2f} USDT\n"
            event_body += f"💵 Gross PnL: ${gross_pnl:+.2f} USDT\n"
            event_body += f"💸 Net PnL (Fees Incl): ${net_pnl:+.2f} USDT\n"
            event_body += "========================================\n\n"

            event_body += "💰 UPDATED PORTFOLIO STATS\n"
            event_body += "========================================\n"
            event_body += f"💵 Total Capital    : ${total_cap:.2f} USDT\n"
            event_body += f"🟢 Available Balance : ${avail_cap:.2f} USDT\n"
            event_body += f"🔒 Freezed Balance   : ${frozen_margin:.2f} USDT\n"
            event_body += f"🎯 Overall Win Rate  : {win_rate:.1f}%\n"
            event_body += f"📈 Total ROI         : {total_roi:+.2f}%\n"
            event_body += "========================================\n\n"

            if not remaining_active_trades:
                event_body += "😴 Currently no remaining active trades."
            else:
                event_body += f"🟢 RUNNING POSITIONS ({len(remaining_active_trades)})\n"
                event_body += "----------------------------------------\n"
                for r in remaining_active_trades:
                    act_id, act_symbol, act_dir, act_entry, act_sl, act_tp1, act_tp2, act_margin, act_pos, act_lev, act_status = r
                    fetched_live = fetch_live_price(act_symbol)
                    live_p = fetched_live if fetched_live is not None else act_entry

                    if act_dir == 'LONG':
                        float_pnl = act_pos * ((live_p - act_entry) / act_entry)
                    else:
                        float_pnl = act_pos * ((act_entry - live_p) / act_entry)

                    float_pnl_pct = (float_pnl / act_margin) * 100 if act_margin > 0 else 0.0

                    event_body += f"🪙 {act_symbol} [{act_dir}]\n"
                    event_body += f"💵 Trade Margin  : ${act_margin:.2f} USDT\n"
                    event_body += f"⚡ Leverage      : {act_lev}x (Pos: ${act_pos:.2f})\n"
                    event_body += f"📥 Entry Point   : ${fmt_p(act_entry)}\n"
                    event_body += f"📊 Live Price    : ${fmt_p(live_p)}\n"
                    event_body += f"🛑 SL Price      : ${fmt_p(act_sl)}\n"
                    event_body += f"🎯 TP1 Price     : ${fmt_p(act_tp1)}\n"
                    event_body += f"🚀 TP2 Price     : ${fmt_p(act_tp2)}\n"
                    event_body += f"📌 Current Status : 🟢 RUNNING\n"
                    event_body += f"💰 Floating PnL  : ${float_pnl:+.2f} ({float_pnl_pct:+.2f}%)\n"
                    event_body += "----------------------------------------\n"

            print(f"   🚀 Sending Pushbullet event alert for Trade #{t_id} with full portfolio & active trades...")
            send_pushbullet_notification(event_title, event_body)
        else:
            print(f"   🟢 Trade #{t_id} [{symbol}] remains ACTIVE after evaluation.")

    conn.close()
    print("="*60 + "\n")

# =========================================================
# 📋 GENERATE & PRINT DETAILED CONSOLE REPORT
# =========================================================
def generate_and_send_report():
    process_active_trades()

    conn, db_type = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT total_capital, available_capital, frozen_margin FROM portfolio WHERE id = 1")
    port_row = cursor.fetchone() or (100.0, 100.0, 0.0)
    total_capital, avail_capital, frozen_margin = port_row

    cursor.execute("SELECT status, pnl FROM trades")
    all_trades = cursor.fetchall()
    
    closed_count = 0
    win_count = 0
    total_realized_pnl = 0.0

    for status, pnl in all_trades:
        pnl_val = pnl if pnl is not None else 0.0
        if status in ['CLOSED_TP1', 'CLOSED_TP2', 'CLOSED_SL', 'CLOSED_MANUAL', 'CLOSED_24H_PROFIT']:
            closed_count += 1
            total_realized_pnl += pnl_val
            if pnl_val > 0:
                win_count += 1

    win_rate = (win_count / closed_count * 100) if closed_count > 0 else 0.0
    initial_capital = max(1.0, total_capital - total_realized_pnl)
    total_roi = (total_realized_pnl / initial_capital) * 100

    cursor.execute("SELECT id, symbol, direction, entry_price, sl_price, tp1_price, tp2_price, margin_frozen, pos_value, leverage, status FROM trades WHERE status = 'ACTIVE' ORDER BY id DESC")
    running_trades = cursor.fetchall()
    conn.close()

    def fmt_p(p):
        return f"{p:.6f}".rstrip('0').rstrip('.') if p and p < 1 else f"{p:.2f}" if p else "0.00"

    report_title = f"⚡ LIVE PORTFOLIO & RUNNING TRADES ({len(running_trades)})"
    
    report_body = "💰 PORTFOLIO STATS\n"
    report_body += "========================================\n"
    report_body += f"💵 Total Capital    : ${total_capital:.2f} USDT\n"
    report_body += f"🟢 Available Balance : ${avail_capital:.2f} USDT\n"
    report_body += f"🔒 Freezed Balance   : ${frozen_margin:.2f} USDT\n"
    report_body += f"🎯 Overall Win Rate  : {win_rate:.1f}%\n"
    report_body += f"📈 Total ROI         : {total_roi:+.2f}%\n"
    report_body += "========================================\n\n"

    if not running_trades:
        report_body += "😴 Currently no running trades."
    else:
        report_body += "🟢 RUNNING POSITIONS\n"
        report_body += "----------------------------------------\n"
        for r in running_trades:
            t_id, symbol, direction, entry_p, sl_p, tp1_p, tp2_p, margin, pos_val, lev, status = r
            
            # Direct Live Fetch via Binance Vision Ticker
            fetched_live = fetch_live_price(symbol)
            live_p = fetched_live if fetched_live is not None else entry_p

            if direction == 'LONG':
                float_pnl = pos_val * ((live_p - entry_p) / entry_p)
            else:
                float_pnl = pos_val * ((entry_p - live_p) / entry_p)

            float_pnl_pct = (float_pnl / margin) * 100 if margin > 0 else 0.0

            report_body += f"🪙 {symbol} [{direction}]\n"
            report_body += f"💵 Trade Margin  : ${margin:.2f} USDT\n"
            report_body += f"⚡ Leverage      : {lev}x (Pos: ${pos_val:.2f})\n"
            report_body += f"📥 Entry Point   : ${fmt_p(entry_p)}\n"
            report_body += f"📊 Live Price    : ${fmt_p(live_p)}\n"
            report_body += f"🛑 SL Price      : ${fmt_p(sl_p)}\n"
            report_body += f"🎯 TP1 Price     : ${fmt_p(tp1_p)}\n"
            report_body += f"🚀 TP2 Price     : ${fmt_p(tp2_p)}\n"
            report_body += f"📌 Current Status : 🟢 RUNNING\n"
            report_body += f"💰 Floating PnL  : ${float_pnl:+.2f} ({float_pnl_pct:+.2f}%)\n"
            report_body += "----------------------------------------\n"

    # Full details printed directly to Console
    print("\n" + "="*60)
    print(report_title)
    print("="*60)
    print(report_body)
    print("="*60)

if __name__ == "__main__":
    generate_and_send_report()
