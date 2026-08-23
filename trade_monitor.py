from datetime import datetime
import os
import sqlite3
import ssl
import pandas as pd
import requests

# Remote MySQL Support Check
try:
  import mysql.connector

  MYSQL_AVAILABLE = True
except ImportError:
  MYSQL_AVAILABLE = False

# =========================================================
# ⚙️ API ENDPOINTS & CONFIG
# =========================================================
BINANCE_SPOT_URL = 'https://data-api.binance.vision/api/v3/klines'
BINANCE_BOOK_TICKER_URL = (
    'https://data-api.binance.vision/api/v3/ticker/bookTicker'
)
BINANCE_FUTURES_FUNDING_URL = 'https://fapi.binance.com/fapi/v1/premiumIndex'

BINANCE_FEE_RATE = 0.00075
EVENT_ALERT_TOPIC = 'events_hit_hdhdhe'


# =========================================================
# 🔌 RESPONSIVE MULTI-ENGINE DATABASE CONNECTOR & MIGRATION
# =========================================================
def get_db_connection():
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
          connect_timeout=30,
      )
      return conn, 'MYSQL'
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
      return conn, 'MYSQL'
    except Exception as e:
      print(f'⚠️ Remote MySQL Error: {e}. Falling back to SQLite...')

  conn = sqlite3.connect('trading_system.db')
  return conn, 'SQLITE'


def auto_migrate_db():
  """Checks and automatically creates 'last_checked_ms' column if missing."""
  conn, db_type = get_db_connection()
  cursor = conn.cursor()

  try:
    if db_type == 'MYSQL':
      cursor.execute("""
                SELECT COUNT(*) 
                FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_SCHEMA = DATABASE() 
                  AND TABLE_NAME = 'trades' 
                  AND COLUMN_NAME = 'last_checked_ms'
            """)
      column_exists = cursor.fetchone()[0] > 0
    else:
      cursor.execute('PRAGMA table_info(trades)')
      columns = [row[1] for row in cursor.fetchall()]
      column_exists = 'last_checked_ms' in columns

    if not column_exists:
      print("🛠️ Column 'last_checked_ms' missing. Adding automatically...")
      col_type = 'BIGINT DEFAULT 0' if db_type == 'MYSQL' else 'INTEGER DEFAULT 0'
      cursor.execute(f'ALTER TABLE trades ADD COLUMN last_checked_ms {col_type}')
      conn.commit()
      print("✅ Column 'last_checked_ms' created successfully.")
  except Exception as e:
    print(f'⚠️ Migration check error: {e}')
  finally:
    conn.close()


# =========================================================
# 💾 DATABASE HELPER FUNCTIONS
# =========================================================
def update_sl_in_db(trade_id, new_sl):
  conn, db_type = get_db_connection()
  cursor = conn.cursor()
  ph = '%s' if db_type == 'MYSQL' else '?'

  cursor.execute(
      f'UPDATE trades SET sl_price = {ph} WHERE id = {ph}',
      (new_sl, trade_id),
  )
  conn.commit()
  conn.close()


# =========================================================
# 🛡️ DYNAMIC USDT-BASED BREAK-EVEN / TRAILING ENGINE
# =========================================================
def check_trailing_and_breakeven(trade, current_price):
  entry = trade.get('entry_price', 0.0)
  sl = trade.get('sl_price', 0.0)
  direction = str(trade.get('direction', '')).upper()
  t_id = trade.get('id')
  symbol = trade.get('symbol', '')
  pos_val = trade.get('pos_value', 0.0)

  if pos_val <= 0 or entry <= 0:
    return sl

  total_fee_usdt = pos_val * (BINANCE_FEE_RATE * 2)
  is_long = direction in ['LONG', 'BUY']
  is_short = direction in ['SHORT', 'SELL']

  if not (is_long or is_short):
    return sl

  # Calculate Current PnL in USDT
  current_pnl_usdt = (
      pos_val * ((current_price - entry) / entry)
      if is_long
      else pos_val * ((entry - current_price) / entry)
  )

  # Define Profit Tiers: (Peak_Unrealized_PNL_Threshold, Net_Lock_Amount)
  # Tier 1: $1.00+ Peak -> Lock $0.60 NET
  # Tier 2: $0.60+ Peak -> Lock $0.35 NET
  # Tier 3: $0.40+ Peak -> Lock $0.15 NET
  # Tier 4: $0.28+ Peak -> Lock $0.05 NET (Early Break-Even + Fee Cover)
  tiers = [(1.00, 0.60), (0.60, 0.35), (0.40, 0.15), (0.28, 0.05)]

  target_sl = sl
  locked_profit = 0.0

  # Evaluate Tiers (Highest floor threshold triggers first)
  for threshold, lock_amount in tiers:
    if current_pnl_usdt >= threshold:
      target_gross = lock_amount + total_fee_usdt
      target_sl = (
          entry * (1 + (target_gross / pos_val))
          if is_long
          else entry * (1 - (target_gross / pos_val))
      )
      locked_profit = lock_amount
      break

  # Check if SL needs updating
  is_sl_improved = (is_long and target_sl > sl) or (
      is_short and (sl == 0 or target_sl < sl)
  )

  if is_sl_improved:
    new_sl = target_sl
    update_sl_in_db(t_id, new_sl)
    trade['sl_price'] = new_sl

    print(
        f'🛡️ [PROFIT LOCKED] Trade #{t_id} [{symbol}] SL updated to'
        f' ${new_sl:.5f} (Locked +${locked_profit:.2f} NET USDT)'
    )

    msg = (
        f'🛡️ PROFIT LOCKED (+${locked_profit:.2f} NET) FOR TRADE #{t_id}\n'
        '───────────────────────────\n'
        f'📌 Symbol       : {symbol} [{direction}]\n'
        f'📍 Entry Price : ${entry:.5f}\n'
        f'🎯 New SL Price: ${new_sl:.5f}\n'
        f'💵 Peak PnL     : +${current_pnl_usdt:.2f} USDT\n'
        '───────────────────────────'
    )

    send_ntfy_notification(
        title=f'🛡️ New SL Set (${new_sl:.5f}): {symbol}',
        message_body=msg,
        tags=['shield', 'moneybag'],
        topic=EVENT_ALERT_TOPIC,
    )
    return new_sl

  return sl




# =========================================================
# 📲 NTFY NOTIFICATION ENGINE
# =========================================================
def get_ntfy_topic():
  topic = os.getenv('LIVE_MON_TOP', '').strip()
  return topic if topic else 'my_trading_monitor_channel_88'


def send_ntfy_notification(
    title,
    message_body,
    tags=['chart_with_upwards_trend', 'moneybag'],
    topic=None,
):
  target_topic = topic if topic else get_ntfy_topic()
  ntfy_url = f'https://ntfy.sh/{target_topic}'

  clean_title = title.encode('ascii', 'ignore').decode('ascii').strip()
  if not clean_title:
    clean_title = 'LIVE PORTFOLIO REPORT'

  headers = {
      'Title': clean_title,
      'Priority': 'high' if topic == EVENT_ALERT_TOPIC else 'default',
      'Tags': ','.join(tags),
  }

  try:
    res = requests.post(
        ntfy_url, data=message_body.encode('utf-8'), headers=headers, timeout=10
    )
    if res.status_code == 200:
      print(f'🚀 Ntfy notification sent to topic: {target_topic}')
  except Exception as e:
    print(f'❌ Ntfy Request Exception: {e}')


def send_trade_event_notification(
    trade_id,
    symbol,
    direction,
    close_reason,
    margin,
    exit_amount,
    net_pnl,
    entry_p=0.0,
    exit_p=0.0,
    pos_val=0.0,
):
  pnl_icon = '🟢' if net_pnl >= 0 else '🔻'
  pnl_sign = '+' if net_pnl >= 0 else ''
  roi_pct = (net_pnl / margin * 100) if margin > 0 else 0.0

  reason_map = {
      'CLOSED_SL': '🚫 STOP LOSS HIT',
      'CLOSED_TP1': '🎯 TAKE PROFIT 1 HIT',
      'CLOSED_TP2': '🚀 TAKE PROFIT 2 HIT',
      'CLOSED_24H_PROFIT': '⏳ 24H TIME EXPIRY (PROFIT)',
  }
  formatted_reason = reason_map.get(close_reason, close_reason)
  total_fee_usdt = pos_val * (BINANCE_FEE_RATE * 2) if pos_val > 0 else 0.0

  msg = f'⚡ TRADE CLOSED BREAKDOWN #{trade_id}\n'
  msg += '═══════════════════════════\n'
  msg += f'📌 Symbol       : {symbol} [{direction}]\n'
  msg += f'📝 Close Reason : {formatted_reason}\n'
  msg += '───────────────────────────\n'

  if entry_p > 0 and exit_p > 0:
    msg += f'📍 Entry Price : ${entry_p:.5f}\n'
    msg += f'🚪 Exit Price  : ${exit_p:.5f}\n'
    msg += '───────────────────────────\n'

  msg += f'💰 Start Margin : ${margin:.2f} USDT\n'
  msg += f'🏦 Payout Value : ${exit_amount:.2f} USDT\n'
  if total_fee_usdt > 0:
    msg += f'🧾 Est. Fees   : -${total_fee_usdt:.3f} USDT\n'

  msg += '───────────────────────────\n'
  msg += (
      f'📊 Net PnL      : {pnl_icon} {pnl_sign}${net_pnl:.2f} USDT'
      f' ({pnl_sign}{roi_pct:.2f}% ROI)\n'
  )
  msg += '═══════════════════════════\n'
  msg += f'🕒 Closed At    : {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'

  title = f'{pnl_icon} Trade Closed: {symbol} ({pnl_sign}${net_pnl:.2f} USDT)'
  tags = (
      ['warning', 'checkered_flag']
      if net_pnl < 0
      else ['rocket', 'moneybag', 'trophy']
  )

  send_ntfy_notification(
      title=title, message_body=msg, tags=tags, topic=EVENT_ALERT_TOPIC
  )


# =========================================================
# 📊 BINANCE LIVE PRICE FETCH
# =========================================================
def fetch_live_price(symbol):
  if not symbol:
    return None

  clean_symbol = str(symbol).strip().upper()

  try:
    url = f'{BINANCE_BOOK_TICKER_URL}?symbol={clean_symbol}'
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
  except Exception:
    pass

  try:
    url = f'{BINANCE_FUTURES_FUNDING_URL}?symbol={clean_symbol}'
    res = requests.get(url, timeout=4)
    if res.status_code == 200:
      val = float(res.json().get('markPrice', 0))
      if val > 0:
        return val
  except Exception:
    pass

  return None


# =========================================================
# 🕯️ INCREMENTAL KLINES DOWNLOADER (NEW OPTIMIZED LOGIC)
# =========================================================
def fetch_incremental_klines(symbol, start_time_ms):
  """Fetches only NEW candles starting from start_time_ms to reduce API latency."""
  clean_symbol = str(symbol).strip().upper()
  all_candles = []
  current_start = start_time_ms
  now_ms = int(datetime.now().timestamp() * 1000)

  # Fetch only required missing chunks
  while current_start < now_ms:
    url = f'{BINANCE_SPOT_URL}?symbol={clean_symbol}&interval=1m&startTime={current_start}&limit=1000'
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
      print(f'⚠️ Error fetching klines for {clean_symbol}: {e}')
      break

  if not all_candles:
    return None

  df = pd.DataFrame(
      all_candles,
      columns=[
          'time',
          'open',
          'high',
          'low',
          'close',
          '_',
          '_',
          '_',
          '_',
          '_',
          '_',
          '_',
      ],
  )
  for col in ['time', 'open', 'high', 'low', 'close']:
    df[col] = df[col].astype(float)

  df = df.sort_values(by='time', ascending=True).reset_index(drop=True)
  return df


# =========================================================
# 🔄 PROCESS ACTIVE TRADES WITH DB TIMESTAMP TRACKING
# =========================================================
def process_active_trades():
  print('\n' + '=' * 60)
  print('🔍 CHECKING ACTIVE TRADES IN BACKGROUND')
  print('=' * 60)

  conn, db_type = get_db_connection()
  cursor = conn.cursor()
  ph = '%s' if db_type == 'MYSQL' else '?'

  cursor.execute(
      f'SELECT total_capital, available_capital, frozen_margin FROM portfolio'
      f' WHERE id = {ph}',
      (1,),
  )
  port_row = cursor.fetchone()
  if not port_row:
    print('⚠️ Portfolio record #1 not found. Aborting.')
    conn.close()
    return
  total_cap, avail_cap, frozen_margin = port_row

  cursor.execute(
      f'SELECT id, timestamp, symbol, direction, entry_price, sl_price,'
      f' tp1_price, tp2_price, margin_frozen, pos_value, last_checked_ms FROM'
      f' trades WHERE status = {ph}',
      ('ACTIVE',),
  )
  active_trades = cursor.fetchall()

  if not active_trades:
    print('ℹ️ No active trades currently present in database.')

  for trade in active_trades:
    (
        t_id,
        t_time_str,
        symbol,
        direction,
        entry_p,
        sl_p,
        tp1_p,
        tp2_p,
        margin,
        pos_val,
        last_checked_ms,
    ) = trade
    print(f'\n📌 Evaluating Trade #{t_id} | {symbol} [{direction}]')

    try:
      dt_obj = datetime.strptime(str(t_time_str), '%Y-%m-%d %H:%M:%S')
      start_ms = int(dt_obj.timestamp() * 1000)
    except Exception as e:
      print(f'❌ Timestamp Parsing Error for Trade #{t_id}: {e}')
      continue

    # Determine fetch point: Use last_checked_ms if present, otherwise trade start_ms
    fetch_from_ms = (
        last_checked_ms if (last_checked_ms and last_checked_ms > 0) else start_ms
    )

    df = fetch_incremental_klines(symbol, fetch_from_ms)
    if df is None or df.empty:
      print(f'⚠️ No new kline data retrieved for {symbol}.')
      continue

    status = 'ACTIVE'
    gross_pnl = 0.0
    exit_p = 0.0
    latest_processed_ms = fetch_from_ms

    trade_dict = {
        'id': t_id,
        'symbol': symbol,
        'direction': direction,
        'entry_price': entry_p,
        'sl_price': sl_p,
        'pos_value': pos_val,
    }

    for idx, row in df.iterrows():
      c_time_ms = int(row['time'])
      latest_processed_ms = c_time_ms
      c_open, c_high, c_low, c_close = (
          row['open'],
          row['high'],
          row['low'],
          row['close'],
      )
      time_elapsed_seconds = (c_time_ms - start_ms) / 1000.0

      check_p = c_high if direction == 'LONG' else c_low
      sl_p = check_trailing_and_breakeven(trade_dict, check_p)

      if direction == 'LONG':
        if c_close >= c_open:
          if c_low <= sl_p:
            status = 'CLOSED_SL'
            exit_p = sl_p
            gross_pnl = -pos_val * ((entry_p - sl_p) / entry_p)
            break
          elif c_high >= tp2_p:
            status = 'CLOSED_TP2'
            exit_p = tp2_p
            gross_pnl = pos_val * ((tp2_p - entry_p) / entry_p)
            break
          elif c_high >= tp1_p:
            status = 'CLOSED_TP1'
            exit_p = tp1_p
            gross_pnl = pos_val * ((tp1_p - entry_p) / entry_p)
            break
        else:
          if c_high >= tp2_p:
            status = 'CLOSED_TP2'
            exit_p = tp2_p
            gross_pnl = pos_val * ((tp2_p - entry_p) / entry_p)
            break
          elif c_high >= tp1_p:
            status = 'CLOSED_TP1'
            exit_p = tp1_p
            gross_pnl = pos_val * ((tp1_p - entry_p) / entry_p)
            break
          elif c_low <= sl_p:
            status = 'CLOSED_SL'
            exit_p = sl_p
            gross_pnl = -pos_val * ((entry_p - sl_p) / entry_p)
            break

        if time_elapsed_seconds >= 86400:
          candle_gross_pnl = pos_val * ((c_close - entry_p) / entry_p)
          entry_fee = pos_val * BINANCE_FEE_RATE
          exit_val = max(0, pos_val + candle_gross_pnl)
          exit_fee = exit_val * BINANCE_FEE_RATE
          net_pnl_check = candle_gross_pnl - (entry_fee + exit_fee)
          net_pct = (net_pnl_check / margin) * 100 if margin > 0 else 0.0

          if net_pct > 0.5:
            status = 'CLOSED_24H_PROFIT'
            exit_p = c_close
            gross_pnl = candle_gross_pnl
            break

      else:  # SHORT
        if c_close <= c_open:
          if c_high >= sl_p:
            status = 'CLOSED_SL'
            exit_p = sl_p
            gross_pnl = -pos_val * ((sl_p - entry_p) / entry_p)
            break
          elif c_low <= tp2_p:
            status = 'CLOSED_TP2'
            exit_p = tp2_p
            gross_pnl = pos_val * ((entry_p - tp2_p) / entry_p)
            break
          elif c_low <= tp1_p:
            status = 'CLOSED_TP1'
            exit_p = tp1_p
            gross_pnl = pos_val * ((entry_p - tp1_p) / entry_p)
            break
        else:
          if c_low <= tp2_p:
            status = 'CLOSED_TP2'
            exit_p = tp2_p
            gross_pnl = pos_val * ((entry_p - tp2_p) / entry_p)
            break
          elif c_low <= tp1_p:
            status = 'CLOSED_TP1'
            exit_p = tp1_p
            gross_pnl = pos_val * ((entry_p - tp1_p) / entry_p)
            break
          elif c_high >= sl_p:
            status = 'CLOSED_SL'
            exit_p = sl_p
            gross_pnl = -pos_val * ((sl_p - entry_p) / entry_p)
            break

        if time_elapsed_seconds >= 86400:
          candle_gross_pnl = pos_val * ((entry_p - c_close) / entry_p)
          entry_fee = pos_val * BINANCE_FEE_RATE
          exit_val = max(0, pos_val + candle_gross_pnl)
          exit_fee = exit_val * BINANCE_FEE_RATE
          net_pnl_check = candle_gross_pnl - (entry_fee + exit_fee)
          net_pct = (net_pnl_check / margin) * 100 if margin > 0 else 0.0

          if net_pct > 0.5:
            status = 'CLOSED_24H_PROFIT'
            exit_p = c_close
            gross_pnl = candle_gross_pnl
            break

    # Save last checked candle timestamp to DB
    cursor.execute(
        f'UPDATE trades SET last_checked_ms = {ph} WHERE id = {ph}',
        (latest_processed_ms, t_id),
    )
    conn.commit()

    if status != 'ACTIVE':
      entry_fee = pos_val * BINANCE_FEE_RATE
      exit_value = max(0, pos_val + gross_pnl)
      exit_fee = exit_value * BINANCE_FEE_RATE
      net_pnl = gross_pnl - (entry_fee + exit_fee)
      exit_amount = margin + net_pnl

      cursor.execute(
          f'UPDATE trades SET status = {ph}, pnl = {ph} WHERE id = {ph}',
          (status, net_pnl, t_id),
      )
      frozen_margin = max(0.0, frozen_margin - margin)
      avail_cap += margin + net_pnl
      total_cap += net_pnl

      cursor.execute(
          f'UPDATE portfolio SET total_capital = {ph}, available_capital ='
          f' {ph}, frozen_margin = {ph} WHERE id = 1',
          (total_cap, avail_cap, frozen_margin),
      )
      conn.commit()

      print(
          f'   🔔 TRADE CLOSED: Trade #{t_id} [{symbol}] via {status} | Net'
          f' PnL: ${net_pnl:+.2f}'
      )

      send_trade_event_notification(
          trade_id=t_id,
          symbol=symbol,
          direction=direction,
          close_reason=status,
          margin=margin,
          exit_amount=exit_amount,
          net_pnl=net_pnl,
          entry_p=entry_p,
          exit_p=exit_p,
          pos_val=pos_val,
      )

  conn.close()


# =========================================================
# 📋 GENERATE & SEND REPORT
# =========================================================

from datetime import datetime
import time
import requests


def generate_and_send_report():
  auto_migrate_db()
  process_active_trades()

  conn, db_type = get_db_connection()
  cursor = conn.cursor()

  cursor.execute(
      'SELECT total_capital, available_capital, frozen_margin FROM portfolio'
      ' WHERE id = 1'
  )
  port_row = cursor.fetchone() or (100.0, 100.0, 0.0)
  base_total_capital, avail_capital, frozen_margin = port_row

  cursor.execute('SELECT MIN(timestamp) FROM trades')
  first_trade_row = cursor.fetchone()

  duration_str = '0d 0h 0m'
  if first_trade_row and first_trade_row[0]:
    try:
      first_ts_str = str(first_trade_row[0])
      first_dt = datetime.strptime(first_ts_str, '%Y-%m-%d %H:%M:%S')
      now_dt = datetime.now()

      diff_seconds = int((now_dt - first_dt).total_seconds())
      if diff_seconds > 0:
        months = diff_seconds // (30 * 86400)
        rem_sec = diff_seconds % (30 * 86400)
        days = rem_sec // 86400
        rem_sec %= 86400
        hours = rem_sec // 3600
        rem_sec %= 3600
        minutes = rem_sec // 60

        parts = []
        if months > 0:
          parts.append(f'{months}mo')
        if days > 0 or months > 0:
          parts.append(f'{days}d')
        if hours > 0 or days > 0 or months > 0:
          parts.append(f'{hours}h')
        parts.append(f'{minutes}m')
        duration_str = ' '.join(parts)
    except Exception as e:
      print(f'⚠️ Duration parsing error: {e}')

  cursor.execute(
      'SELECT id, symbol, direction, entry_price, sl_price, tp1_price,'
      ' tp2_price, margin_frozen, pos_value, leverage, status, timestamp FROM'
      " trades WHERE status = 'ACTIVE' ORDER BY id DESC"
  )
  running_trades = cursor.fetchall()

  total_floating_pnl = 0.0
  active_positions_details = []

  def fmt_p(p):
    return (
        f'{p:.6f}'.rstrip('0').rstrip('.')
        if p and p < 1
        else f'{p:.2f}'
        if p
        else '0.00'
    )

  now_dt = datetime.now()

  for r in running_trades:
    (
        t_id,
        symbol,
        direction,
        entry_p,
        sl_p,
        tp1_p,
        tp2_p,
        margin,
        pos_val,
        lev,
        status,
        trade_ts,
    ) = r

    fetched_live = fetch_live_price(symbol)
    live_p = fetched_live if fetched_live is not None else entry_p

    if direction == 'LONG':
      float_pnl = pos_val * ((live_p - entry_p) / entry_p)
    else:
      float_pnl = pos_val * ((entry_p - live_p) / entry_p)

    float_pnl_pct = (float_pnl / margin) * 100 if margin > 0 else 0.0
    total_floating_pnl += float_pnl

    trade_life_str = '0m'
    period_high = max(entry_p, live_p)
    period_low = min(entry_p, live_p)

    if trade_ts:
      try:
        t_dt = datetime.strptime(str(trade_ts), '%Y-%m-%d %H:%M:%S')
        start_ms = int(t_dt.timestamp() * 1000)

        df_period = fetch_incremental_klines(symbol, start_ms)
        if df_period is not None and not df_period.empty:
          period_high = float(df_period['high'].max())
          period_low = float(df_period['low'].min())

        t_diff = int((now_dt - t_dt).total_seconds())
        if t_diff > 0:
          t_days = t_diff // 86400
          t_rem = t_diff % 86400
          t_hours = t_rem // 3600
          t_mins = (t_rem % 3600) // 60

          t_parts = []
          if t_days > 0:
            t_parts.append(f'{t_days}d')
          if t_hours > 0 or t_days > 0:
            t_parts.append(f'{t_hours}h')
          t_parts.append(f'{t_mins}m')
          trade_life_str = ' '.join(t_parts)
      except Exception as e:
        print(f'⚠️ High/Low extraction error for {symbol}: {e}')

    sl_drawdown_pct = 0.0
    tp_progress_pct = 0.0

    if direction == 'LONG':
      if sl_p and entry_p > sl_p:
        max_down = entry_p - period_low
        total_sl_dist = entry_p - sl_p
        sl_drawdown_pct = max(0.0, (max_down / total_sl_dist) * 100)

      if tp1_p and tp1_p > entry_p:
        max_up = period_high - entry_p
        total_tp_dist = tp1_p - entry_p
        tp_progress_pct = max(0.0, (max_up / total_tp_dist) * 100)

    else:
      if sl_p and sl_p > entry_p:
        max_up = period_high - entry_p
        total_sl_dist = sl_p - entry_p
        sl_drawdown_pct = max(0.0, (max_up / total_sl_dist) * 100)

      if tp1_p and entry_p > tp1_p:
        max_down = entry_p - period_low
        total_tp_dist = entry_p - tp1_p
        tp_progress_pct = max(0.0, (max_down / total_tp_dist) * 100)

    active_positions_details.append({
        'symbol': symbol,
        'direction': direction,
        'margin': margin,
        'leverage': lev,
        'pos_val': pos_val,
        'entry_p': entry_p,
        'sl_p': sl_p,
        'tp1_p': tp1_p,
        'live_p': live_p,
        'float_pnl': float_pnl,
        'float_pnl_pct': float_pnl_pct,
        'trade_life': trade_life_str,
        'period_high': period_high,
        'period_low': period_low,
        'sl_drawdown_pct': sl_drawdown_pct,
        'tp_progress_pct': tp_progress_pct,
    })

  live_total_balance = base_total_capital + total_floating_pnl

  cursor.execute("SELECT status, pnl FROM trades WHERE status != 'ACTIVE'")
  closed_trades = cursor.fetchall()

  closed_count = len(closed_trades)
  closed_realized_pnl = sum(
      (t[1] if t[1] is not None else 0.0) for t in closed_trades
  )

  winning_trades_pnl = [t[1] for t in closed_trades if t[1] and t[1] > 0]
  losing_trades_pnl = [t[1] for t in closed_trades if t[1] and t[1] < 0]

  winning_pnl = sum(winning_trades_pnl)
  losing_pnl = abs(sum(losing_trades_pnl))

  win_count = len(winning_trades_pnl)
  loss_count = len(losing_trades_pnl)

  win_ratio = (win_count / closed_count * 100) if closed_count > 0 else 0.0
  avg_win_trade = (winning_pnl / win_count) if win_count > 0 else 0.0
  avg_loss_trade = (losing_pnl / loss_count) if loss_count > 0 else 0.0

  if losing_pnl > 0:
    profit_factor = winning_pnl / losing_pnl
    pf_str = f'{profit_factor:.2f}'
  else:
    pf_str = f'{winning_pnl:.2f}' if winning_pnl > 0 else '0.00'

  initial_capital = base_total_capital - closed_realized_pnl
  all_time_roi = (
      (closed_realized_pnl / initial_capital * 100)
      if initial_capital > 0
      else 0.0
  )

  cap_utilization = (
      (frozen_margin / base_total_capital * 100)
      if base_total_capital > 0
      else 0.0
  )

  conn.close()

  pnl_sign = '+' if total_floating_pnl >= 0 else ''

  # 📩 STEP 1: ACTIVE TRADES NOTIFICATIONS (SPLIT BY 2 TRADES PER MESSAGE)
  total_active = len(active_positions_details)

  if total_active == 0:
    msg1 = '⚡ ACTIVE POSITIONS RISK AUDIT (0)\n'
    msg1 += '═══════════════════════════════════\n'
    msg1 += '😴 No active positions currently open.\n'
    send_ntfy_notification(
        '⚡ Active Positions (0)', msg1, tags=['zap', 'briefcase']
    )
  else:
    chunk_size = 2
    chunks = [
        active_positions_details[i : i + chunk_size]
        for i in range(0, total_active, chunk_size)
    ]
    total_parts = len(chunks)

    for idx, chunk in enumerate(chunks, 1):
      msg = f'⚡ ACTIVE POSITIONS AUDIT [{idx}/{total_parts}]\n'
      msg += '═══════════════════════════════════\n'

      for pos in chunk:
        direction_icon = '🟢' if pos['direction'] == 'LONG' else '🔴'
        pnl_icon = '🟢' if pos['float_pnl'] >= 0 else '🔻'

        # Clean SL Line without extra spaces
        sl_line = f'`🚒 SL          : ${fmt_p(pos["sl_p"])} (max down: {pos["sl_drawdown_pct"]:.1f}%)`'

        msg += (
            f"{direction_icon} {pos['symbol']} | {pos['direction']}"
            f" {pos['leverage']}x\n"
        )
        msg += f"• Time         : ⏱️ {pos['trade_life']}\n"
        msg += f"• Capital      : 🏧 ${pos['margin']:.2f} USDT\n"
        msg += f"• EP           : 🎰 ${fmt_p(pos['entry_p'])}\n"
        msg += f'{sl_line}\n'
        msg += (
            f"• TP           : 💵 ${fmt_p(pos['tp1_p'])} (max up:"
            f" {pos['tp_progress_pct']:.1f}%)\n"
        )
        msg += f"• Mark Price   : ${fmt_p(pos['live_p'])}\n"
        msg += f"• Max Up/Down  : 🔺${fmt_p(pos['period_high'])} | 🔻${fmt_p(pos['period_low'])}\n"
        msg += (
            f"• Live PnL     : {pnl_icon} ${pos['float_pnl']:+.2f}"
            f" ({pos['float_pnl_pct']:+.2f}%)\n"
        )
        msg += '-----------------------------------\n'

      send_ntfy_notification(
          f'⚡ Active Positions ({idx}/{total_parts})',
          msg,
          tags=['zap', 'briefcase'],
      )
      time.sleep(1.5)

  # 📩 STEP 2: PORTFOLIO AUDIT REPORT
  msg2 = '🏛️ PORTFOLIO EXECUTIVE AUDIT REPORT\n'
  msg2 += '═══════════════════════════════════\n'
  msg2 += f'⏱️ System Age     : {duration_str}\n'
  msg2 += (
      f'📅 Audit Time     : {datetime.now().strftime("%Y-%m-%d %H:%M UTC")}\n'
  )
  msg2 += '───────────────────────────────────\n\n'

  msg2 += '💵 ACCOUNT CAPITAL BALANCE\n'
  msg2 += '───────────────────────────────────\n'
  msg2 += f'💎 Total Equity   : ${live_total_balance:.2f} USDT\n'
  msg2 += f'🏦 Base Capital   : ${base_total_capital:.2f} USDT\n'
  msg2 += f'🟢 Available Cash : ${avail_capital:.2f} USDT\n'
  msg2 += f'🔒 Margin Frozen  : ${frozen_margin:.2f} USDT\n'
  msg2 += f'⚡ Margin Usage   : {cap_utilization:.1f}%\n'
  msg2 += f'📈 Floating PnL   : {pnl_sign}${total_floating_pnl:.2f} USDT\n'
  msg2 += '───────────────────────────────────\n\n'

  msg2 += f'📊 PERFORMANCE & RISK METRICS ({closed_count})\n'
  msg2 += '───────────────────────────────────\n'
  msg2 += f'💰 Net Realized PnL : ${closed_realized_pnl:+.2f} USDT\n'
  msg2 += f'🎯 Cumulative ROI  : {all_time_roi:+.2f}%\n'
  msg2 += (
      f'🏆 System Win Rate  : {win_ratio:.1f}%'
      f' ({win_count}W/{loss_count}L)\n'
  )
  msg2 += f'⚖️ Profit Factor    : {pf_str}\n'
  msg2 += f'🟢 Avg Win Trade    : +${avg_win_trade:.2f} USDT\n'
  msg2 += f'🔴 Avg Loss Trade   : -${avg_loss_trade:.2f} USDT\n'
  msg2 += '═══════════════════════════════════'

  send_ntfy_notification(
      '📊 Portfolio Audit Report',
      msg2,
      tags=['chart_with_upwards_trend', 'briefcase'],
  )





if __name__ == '__main__':
  generate_and_send_report()
