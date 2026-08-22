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
def generate_and_send_report():
  # Auto Check / Migration for missing column
  auto_migrate_db()

  # Process Trades
  process_active_trades()

  conn, db_type = get_db_connection()
  cursor = conn.cursor()

  cursor.execute(
      'SELECT total_capital, available_capital, frozen_margin FROM portfolio'
      ' WHERE id = 1'
  )
  port_row = cursor.fetchone() or (100.0, 100.0, 0.0)
  base_total_capital, avail_capital, frozen_margin = port_row

  cursor.execute(
      'SELECT id, symbol, direction, entry_price, sl_price, tp1_price,'
      ' tp2_price, margin_frozen, pos_value, leverage, status FROM trades WHERE'
      " status = 'ACTIVE' ORDER BY id DESC"
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
    ) = r

    fetched_live = fetch_live_price(symbol)
    live_p = fetched_live if fetched_live is not None else entry_p

    if direction == 'LONG':
      float_pnl = pos_val * ((live_p - entry_p) / entry_p)
    else:
      float_pnl = pos_val * ((entry_p - live_p) / entry_p)

    float_pnl_pct = (float_pnl / margin) * 100 if margin > 0 else 0.0
    total_floating_pnl += float_pnl

    active_positions_details.append({
        'symbol': symbol,
        'direction': direction,
        'margin': margin,
        'leverage': lev,
        'pos_val': pos_val,
        'entry_p': entry_p,
        'live_p': live_p,
        'float_pnl': float_pnl,
        'float_pnl_pct': float_pnl_pct,
    })

  live_total_balance = base_total_capital + total_floating_pnl

  cursor.execute("SELECT status, pnl FROM trades WHERE status != 'ACTIVE'")
  closed_trades = cursor.fetchall()

  closed_count = len(closed_trades)
  closed_realized_pnl = sum(
      (t[1] if t[1] is not None else 0.0) for t in closed_trades
  )

  # --- Advanced Analytics (ROI, Win Ratio, Profit Factor) ---
  winning_pnl = sum(t[1] for t in closed_trades if t[1] and t[1] > 0)
  losing_pnl = abs(sum(t[1] for t in closed_trades if t[1] and t[1] < 0))
  win_count = sum(1 for t in closed_trades if t[1] and t[1] > 0)

  win_ratio = (win_count / closed_count * 100) if closed_count > 0 else 0.0

  # Profit Factor (Co-Factor)
  if losing_pnl > 0:
    profit_factor = winning_pnl / losing_pnl
    pf_str = f'{profit_factor:.2f}'
  else:
    pf_str = f'{winning_pnl:.2f}' if winning_pnl > 0 else '0.00'

  # All Time ROI (Calculated against Starting Capital or Base Capital)
  initial_capital = (
      base_total_capital - closed_realized_pnl
  )  # Est. initial capital
  all_time_roi = (
      (closed_realized_pnl / initial_capital * 100)
      if initial_capital > 0
      else 0.0
  )

  conn.close()

  pnl_sign = '+' if total_floating_pnl >= 0 else ''

  # =========================================================
  # 📩 NOTIFICATION 1: PORTFOLIO & STATS SUMMARY
  # =========================================================
  msg1 = '📊 PORTFOLIO BREAKDOWN\n'
  msg1 += '───────────────────────────\n'
  msg1 += f'💎 Total Balance : ${live_total_balance:.2f} USDT (Live)\n'
  msg1 += f'💵 Base Capital  : ${base_total_capital:.2f} USDT\n'
  msg1 += f'🟢 Available Bal : ${avail_capital:.2f} USDT\n'
  msg1 += f'🔒 Freezed Bal   : ${frozen_margin:.2f} USDT\n'
  msg1 += f'📈 Floating PnL  : {pnl_sign}${total_floating_pnl:.2f} USDT\n'
  msg1 += '───────────────────────────\n\n'

  msg1 += f'🔴 CLOSED TRADES STATS ({closed_count})\n'
  msg1 += '───────────────────────────\n'
  msg1 += f'💰 Realized PnL  : ${closed_realized_pnl:+.2f} USDT\n'
  msg1 += f'🎯 All Time ROI  : {all_time_roi:+.2f}%\n'
  msg1 += f'🏆 Win Ratio     : {win_ratio:.1f}% ({win_count}/{closed_count})\n'
  msg1 += f'⚖️ Profit Factor : {pf_str}\n'
  msg1 += '───────────────────────────'

  send_ntfy_notification(
      '📊 Portfolio Metrics & Stats',
      msg1,
      tags=['chart_with_upwards_trend', 'moneybag'],
  )

  # =========================================================
  # 📩 NOTIFICATION 2: ACTIVE TRADES ONLY
  # =========================================================
  msg2 = f'⚡ ACTIVE TRADES ({len(active_positions_details)})\n'
  msg2 += '═══════════════════════════\n'

  if not active_positions_details:
    msg2 += '😴 No active positions currently open.\n'
  else:
    for pos in active_positions_details:
      direction_icon = '🟢' if pos['direction'] == 'LONG' else '🔴'
      pnl_icon = '🟢' if pos['float_pnl'] >= 0 else '🔻'

      msg2 += (
          f"{direction_icon} {pos['symbol']} | {pos['direction']}"
          f" {pos['leverage']}x\n"
      )
      msg2 += f"• Margin    : ${pos['margin']:.2f} USDT\n"
      msg2 += f"• Entry     : ${fmt_p(pos['entry_p'])}\n"
      msg2 += f"• Mark Price: ${fmt_p(pos['live_p'])}\n"
      msg2 += (
          f"• Live PnL  : {pnl_icon} ${pos['float_pnl']:+.2f}"
          f" ({pos['float_pnl_pct']:+.2f}%)\n"
      )
      msg2 += '-------------------------------------------\n'

  send_ntfy_notification(
      f'⚡ Active Positions ({len(active_positions_details)})',
      msg2,
      tags=['zap', 'briefcase'],
  )


if __name__ == '__main__':
  generate_and_send_report()
