import math
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
import requests

# Optional mysql import
try:
  import mysql.connector

  HAS_MYSQL = True
except ImportError:
  HAS_MYSQL = False

# ==========================================
# CONFIGURATION & CONSTANTS
# ==========================================
NTFY_TOPIC = os.environ.get('NTFY_TOPIC', 'your_ntfy_topic_here')

# Public Data & Mirror Endpoints to bypass regional 451 blocks
BINANCE_DATA_ENDPOINTS = [
    'https://data-api.binance.vision/api/v3/klines',  # Official Public Data Archive API (No Auth/Location Restrictions)
    'https://fapi.binance.com/fapi/v1/klines',  # Futures Market Public Data
    'https://api1.binance.com/api/v3/klines',  # Alternate Mirror 1
    'https://api3.binance.com/api/v3/klines',  # Alternate Mirror 2
]

BINANCE_FEE_RATE = 0.0005  # 0.05% Taker Fee
DEFAULT_RISK_USD = 1.0  # Default Risk for Win Rate calculation if missing

# ==========================================
# DATABASE CONNECTOR (MySQL with SQLite Fallback)
# ==========================================


def get_db_connection():
  """Establishes connection to MySQL or falls back to local SQLite."""
  db_host = os.environ.get(
      'DB_HOST', 'mysql-3a3d5779-project-b71a.b.aivencloud.com'
  )
  db_port = int(os.environ.get('DB_PORT', '23464'))
  db_user = os.environ.get('DB_USER', 'avnadmin')
  db_pass = os.environ.get('DB_PASS', '')
  db_name = os.environ.get('DB_NAME', 'defaultdb')

  if HAS_MYSQL and db_pass:
    try:
      conn = mysql.connector.connect(
          host=db_host,
          port=db_port,
          user=db_user,
          password=db_pass,
          database=db_name,
          ssl_disabled=False,
          connection_timeout=10,
      )
      return conn, 'mysql'
    except Exception as e:
      print(f'[WARN] MySQL SSL Connection failed ({e}). Trying Non-SSL...')
      try:
        conn = mysql.connector.connect(
            host=db_host,
            port=db_port,
            user=db_user,
            password=db_pass,
            database=db_name,
            ssl_disabled=True,
            connection_timeout=10,
        )
        return conn, 'mysql'
      except Exception as e2:
        print(f'[WARN] MySQL Non-SSL failed ({e2}). Falling back to SQLite...')

  # SQLite Fallback
  db_path = 'trading_system.db'
  conn = sqlite3.connect(db_path)
  conn.row_factory = sqlite3.Row
  return conn, 'sqlite'


# ==========================================
# BINANCE KLINE FETCHING (1m Incremental with Data API Fallbacks)
# ==========================================


def fetch_all_klines_since(symbol, start_ms):
  """Fetch all 1m klines from start_ms up to current time.

  Cycles through non-blocked public endpoints to bypass 451 HTTP errors.
  """
  klines = []
  curr_start = start_ms
  now_ms = int(time.time() * 1000)

  headers = {
      'User-Agent': (
          'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
      )
  }

  while curr_start < now_ms:
    params = {
        'symbol': symbol,
        'interval': '1m',
        'startTime': curr_start,
        'limit': 1000,
    }

    data = None

    # Try endpoints sequentially until one returns 200 OK
    for endpoint in BINANCE_DATA_ENDPOINTS:
      try:
        res = requests.get(
            endpoint, params=params, headers=headers, timeout=10
        )
        if res.status_code == 200:
          data = res.json()
          break
        elif res.status_code == 400 and 'fapi' in endpoint:
          # Skip if symbol is invalid for Futures API
          continue
      except Exception:
        continue

    if not data or not isinstance(data, list):
      print(
          f'[WARN] No response or invalid data for {symbol} at timestamp'
          f' {curr_start}'
      )
      break

    klines.extend(data)
    last_kline_time = data[-1][0]

    if last_kline_time <= curr_start:
      break

    curr_start = last_kline_time + 1
    time.sleep(0.05)  # Rate limit protection

  return klines


# ==========================================
# MAIN ANALYSIS LOGIC
# ==========================================


def run_comprehensive_analysis():
  conn, db_type = get_db_connection()
  cursor = conn.cursor(dictionary=True) if db_type == 'mysql' else conn.cursor()

  print(f'=== Starting Full Trade Analysis (DB Mode: {db_type.upper()}) ===\n')

  try:
    cursor.execute('SELECT * FROM trades')
    trades = (
        cursor.fetchall()
        if db_type == 'mysql'
        else [dict(row) for row in cursor.fetchall()]
    )
  except Exception as e:
    print(f'[FATAL] Could not fetch trades from DB: {e}')
    conn.close()
    return

  if not trades:
    print('No trades found in database.')
    conn.close()
    return

  # Metrics Counters
  total_trades = len(trades)
  natural_tp_first = 0
  natural_sl_first = 0
  neither_hit_yet = 0

  safe_closed_saved_us = 0  # Safe close success (SL would have hit, but we closed in small profit/breakeven)
  safe_closed_missed_tp = 0  # Premature close (We closed early, but price later hit TP without hitting original SL)
  safe_closed_still_pending = (
      0  # Safe closed, but original SL or TP has not been hit yet
  )

  wins = 0
  losses = 0
  breakevens = 0

  trade_details_log = []

  for t in trades:
    t_id = t.get('id')
    symbol = t.get('symbol')
    direction = t.get('direction', 'LONG').upper()
    entry_p = float(t.get('entry_price', 0))
    orig_sl_p = float(t.get('sl_price', 0))
    tp_p = float(
        t.get('tp_price', entry_p * 1.02)
    )  # Fallback to +2% if TP missing
    db_status = t.get('status', 'OPEN')
    exit_p = float(t.get('exit_price', 0)) if t.get('exit_price') else None

    # Parse open time (Support string timestamp or epoch ms)
    open_time_val = t.get('created_at') or t.get('open_time')
    if isinstance(open_time_val, (int, float)):
      start_ms = int(open_time_val)
    elif isinstance(open_time_val, datetime):
      start_ms = int(open_time_val.timestamp() * 1000)
    elif isinstance(open_time_val, str):
      try:
        dt = datetime.fromisoformat(open_time_val.replace('Z', '+00:00'))
        start_ms = int(dt.timestamp() * 1000)
      except:
        start_ms = int(time.time() * 1000) - (86400 * 1000)  # 24h default
    else:
      start_ms = int(time.time() * 1000) - (86400 * 1000)

    # 1. Fetch Klines from Open Time to Present using Data APIs
    klines = fetch_all_klines_since(symbol, start_ms)

    first_hit = None  # 'TP', 'SL', or None
    first_hit_time = None

    # 2. Simulate Natural Outcome (Without Script's Intervention)
    for k in klines:
      k_time = k[0]
      c_high = float(k[2])
      c_low = float(k[3])

      if direction == 'LONG':
        # Check if Low hit SL or High hit TP
        hit_sl = c_low <= orig_sl_p
        hit_tp = c_high >= tp_p

        if hit_sl and hit_tp:
          # Same candle hit both -> Assume SL for safety
          first_hit = 'SL'
          first_hit_time = k_time
          break
        elif hit_sl:
          first_hit = 'SL'
          first_hit_time = k_time
          break
        elif hit_tp:
          first_hit = 'TP'
          first_hit_time = k_time
          break

      elif direction == 'SHORT':
        hit_sl = c_high >= orig_sl_p
        hit_tp = c_low <= tp_p

        if hit_sl and hit_tp:
          first_hit = 'SL'
          first_hit_time = k_time
          break
        elif hit_sl:
          first_hit = 'SL'
          first_hit_time = k_time
          break
        elif hit_tp:
          first_hit = 'TP'
          first_hit_time = k_time
          break

    # Categorize Natural Outcome
    if first_hit == 'TP':
      natural_tp_first += 1
    elif first_hit == 'SL':
      natural_sl_first += 1
    else:
      neither_hit_yet += 1

    # 3. Analyze Safe Close / Early Closure Impact
    is_safe_closed = 'SAFE' in db_status or 'MODIFIED' in db_status or (
        exit_p and exit_p > entry_p and exit_p < tp_p
    )

    if is_safe_closed:
      if first_hit == 'SL':
        safe_closed_saved_us += (
            1  # Saved us! We locked profit before original SL was hit.
        )
      elif first_hit == 'TP':
        safe_closed_missed_tp += 1  # We closed early, but it would have hit TP!
      else:
        safe_closed_still_pending += 1

    # 4. Actual Win/Loss Tally (Based on Database Final Status)
    if 'TP' in db_status or (exit_p and exit_p >= tp_p):
      wins += 1
    elif 'SL' in db_status and not is_safe_closed:
      losses += 1
    else:
      # Safe closed or small profit
      if exit_p:
        if exit_p > entry_p:
          wins += 1
        elif exit_p == entry_p:
          breakevens += 1
        else:
          losses += 1

    # Log individual trade breakdown
    trade_details_log.append(
        f'ID {t_id} [{symbol} {direction}]: DB Status={db_status} | Natural'
        f' Outcome={first_hit or "STILL_OPEN"}'
    )

  conn.close()

  # ==========================================
  # METRICS & STATS CALCULATION
  # ==========================================
  actual_closed_trades = wins + losses
  actual_win_rate = (
      (wins / actual_closed_trades * 100) if actual_closed_trades > 0 else 0.0
  )

  natural_decided = natural_tp_first + natural_sl_first
  natural_win_rate = (
      (natural_tp_first / natural_decided * 100) if natural_decided > 0 else 0.0
  )

  report_msg = (
      f'📊 **A-to-Z TRADE PERFORMANCE BREAKDOWN**\n'
      f'-----------------------------------------\n'
      f'🔹 **Total Trades Analyzed:** {total_trades}\n\n'
      f'📈 **1. Pure Market Outcome (Without Early SL/TP Modifications):**\n'
      f'  • Natural TP Hit First: {natural_tp_first}\n'
      f'  • Natural SL Hit First: {natural_sl_first}\n'
      f'  • Neither Hit Yet (Still In-Range): {neither_hit_yet}\n'
      f'  • **Raw Strategy Win Rate:** {natural_win_rate:.2f}%\n\n'
      f'🛡️ **2. Safe-Close & Trailing SL Analysis:**\n'
      f'  • **Saved from Loss (Good Call):** {safe_closed_saved_us} trades'
      ' (Safe close executed & market later hit original SL)\n'
      f'  • **Missed Full Profit (Early Close):** {safe_closed_missed_tp} trades'
      ' (Safe close executed, but market later reached TP)\n'
      f'  • **In-Progress:** {safe_closed_still_pending} trades\n\n'
      f'🏆 **3. Actual Account Outcome:**\n'
      f'  • Realized Wins: {wins}\n'
      f'  • Realized Losses: {losses}\n'
      f'  • Breakeven / Flat: {breakevens}\n'
      f'  • **Actual Strategy Win Rate:** {actual_win_rate:.2f}%\n'
  )

  print(report_msg)

  # Send Summary via Ntfy
  send_ntfy_notification(report_msg)


def send_ntfy_notification(message):
  """Sends formatted report to Ntfy."""
  if not NTFY_TOPIC:
    return
  try:
    url = f'https://ntfy.sh/{NTFY_TOPIC}'
    requests.post(
        url,
        data=message.encode('utf-8'),
        headers={'Title': 'Trade Strategy A-to-Z Analysis', 'Priority': '3'},
    )
    print('\n[INFO] Analysis report successfully sent to Ntfy!')
  except Exception as e:
    print(f'[ERROR] Failed to send Ntfy notification: {e}')


if __name__ == '__main__':
  run_comprehensive_analysis()
