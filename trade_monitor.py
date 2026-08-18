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

# Trade Closing & Break-Even Alerts Target Topic
EVENT_ALERT_TOPIC = 'events_hit_hdhdhe'


# =========================================================
# 🔌 RESPONSIVE MULTI-ENGINE DATABASE CONNECTOR
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


# =========================================================
# 💾 DATABASE HELPER FUNCTIONS
# =========================================================
def update_sl_in_db(trade_id, new_sl):
  """Updates Stop-Loss price in the MySQL / SQLite database."""
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
# 🛡️ TRAILING & BREAK-EVEN MONITORING ENGINE
# =========================================================
# =========================================================
# 🛡️ DYNAMIC USDT-BASED BREAK-EVEN / TRAILING ENGINE
# =========================================================
# =========================================================
# 🛡️ DYNAMIC USDT-BASED BREAK-EVEN / TRAILING ENGINE
# =========================================================
def check_trailing_and_breakeven(trade, current_price):
  """Multi-Level USDT Lock Logic:

  1. Profit >= +0.15 USDT -> SL locked at +0.05 USDT
  2. Profit >= +0.30 USDT -> SL locked at +0.15 USDT
  3. Profit >= +1.00 USDT -> SL locked at +0.50 USDT
  """
  entry = trade['entry_price']
  sl = trade['sl_price']
  direction = trade['direction'].upper()
  t_id = trade['id']
  symbol = trade.get('symbol', '')
  pos_val = trade.get('pos_value', 0.0)

  if pos_val <= 0 or entry <= 0:
    return sl

  updated = False
  new_sl = sl
  locked_profit = 0.0

  if direction in ['LONG', 'BUY']:
    current_pnl_usdt = pos_val * ((current_price - entry) / entry)

    # Multi-level targets check (Highest level first)
    if current_pnl_usdt >= 1.00:
      target_sl = entry * (1 + (0.50 / pos_val))
      locked_profit = 0.50
    elif current_pnl_usdt >= 0.30:
      target_sl = entry * (1 + (0.15 / pos_val))
      locked_profit = 0.15
    elif current_pnl_usdt >= 0.15:
      target_sl = entry * (1 + (0.05 / pos_val))
      locked_profit = 0.05
    else:
      target_sl = sl

    # SL move strictly upwards
    if target_sl > sl:
      new_sl = target_sl
      update_sl_in_db(t_id, new_sl)
      trade['sl_price'] = new_sl
      updated = True
      print(
          f'🛡️ [PROFIT LOCKED] Trade #{t_id} [{symbol}] SL updated to'
          f' ${new_sl:.5f} (Locked +${locked_profit:.2f} USDT)'
      )

  elif direction in ['SHORT', 'SELL']:
    current_pnl_usdt = pos_val * ((entry - current_price) / entry)

    # Multi-level targets check for SHORT
    if current_pnl_usdt >= 1.00:
      target_sl = entry * (1 - (0.50 / pos_val))
      locked_profit = 0.50
    elif current_pnl_usdt >= 0.30:
      target_sl = entry * (1 - (0.15 / pos_val))
      locked_profit = 0.15
    elif current_pnl_usdt >= 0.15:
      target_sl = entry * (1 - (0.05 / pos_val))
      locked_profit = 0.05
    else:
      target_sl = sl

    # SL move strictly downwards for SHORT
    if sl == 0 or target_sl < sl:
      new_sl = target_sl
      update_sl_in_db(t_id, new_sl)
      trade['sl_price'] = new_sl
      updated = True
      print(
          f'🛡️ [PROFIT LOCKED] Trade #{t_id} [{symbol}] SL updated to'
          f' ${new_sl:.5f} (Locked +${locked_profit:.2f} USDT)'
      )

  if updated:
    msg = f'🛡️ PROFIT LOCKED (+${locked_profit:.2f} USDT) FOR TRADE #{t_id}\n'
    msg += '───────────────────────────\n'
    msg += f'📌 Symbol    : {symbol} [{direction}]\n'
    msg += f'📍 Entry     : ${entry:.5f}\n'
    msg += f'🛡️ Locked SL : ${new_sl:.5f}\n'
    msg += f'💵 Peak PnL  : +${current_pnl_usdt:.2f} USDT\n'
    msg += '───────────────────────────'

    send_ntfy_notification(
        title=f'🛡️ Profit Locked (+${locked_profit:.2f} USDT): {symbol}',
        message_body=msg,
        tags=['shield', 'moneybag'],
        topic=EVENT_ALERT_TOPIC,
    )

  return new_sl




# =========================================================
# 📲 NTFY NOTIFICATION ENGINE
# =========================================================
def get_ntfy_topic():
  """Environment variables (GitHub Secrets) se LIVE_MON_TOP topic fetch karta hai."""
  topic = os.getenv('LIVE_MON_TOP', '').strip()
  if not topic:
    print(
        '⚠️ LIVE_MON_TOP topic secret set nahi hai. Default fallback topic use'
        ' hoga.'
    )
    return 'my_trading_monitor_channel_88'
  return topic


def send_ntfy_notification(
    title,
    message_body,
    tags=['chart_with_upwards_trend', 'moneybag'],
    topic=None,
):
  """Ntfy server ko clean Markdown/Text format mein notification bhejta hai."""
  target_topic = topic if topic else get_ntfy_topic()
  ntfy_url = f'https://ntfy.sh/{target_topic}'

  # Clean Unicode emojis from Title Header
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
      print(f'🚀 Ntfy notification successfully sent to topic: {target_topic}')
    else:
      print(f'❌ Ntfy push failed [{res.status_code}]: {res.text}')
  except Exception as e:
    print(f'❌ Ntfy Request Exception: {e}')


def send_trade_event_notification(
    trade_id, symbol, direction, close_reason, margin, exit_amount, net_pnl
):
  """Trade hit (SL, TP, 24H) hone par short responsive breakdown notification bhejta hai."""
  pnl_icon = '🟢' if net_pnl >= 0 else '🔻'
  pnl_sign = '+' if net_pnl >= 0 else ''

  reason_text_map = {
      'CLOSED_SL': '🚫 STOP LOSS HIT',
      'CLOSED_TP1': '🎯 TAKE PROFIT 1 HIT',
      'CLOSED_TP2': '🎯 TAKE PROFIT 2 HIT',
      'CLOSED_24H_PROFIT': '⏳ 24H TIME PROFIT HIT',
  }
  formatted_reason = reason_text_map.get(close_reason, close_reason)

  msg = f'🚨 TRADE CLOSED BREAKDOWN #{trade_id}\n'
  msg += '───────────────────────────\n'
  msg += f'📌 Symbol       : {symbol} [{direction}]\n'
  msg += f'📝 Close Reason : {formatted_reason}\n'
  msg += f'💰 Start Margin : ${margin:.2f} USDT\n'
  msg += f'🚪 Exit Amount  : ${exit_amount:.2f} USDT\n'
  msg += f'📊 Net PnL      : {pnl_icon} {pnl_sign}${net_pnl:.2f} USDT\n'
  msg += '───────────────────────────'

  title = f'🔔 Trade Closed: {symbol} ({formatted_reason})'
  tags = ['warning', 'checkered_flag'] if net_pnl < 0 else ['rocket', 'moneybag']

  send_ntfy_notification(
      title=title,
      message_body=msg,
      tags=tags,
      topic=EVENT_ALERT_TOPIC,  # Use 'events_hit_hdhdhe' topic
  )


# =========================================================
# 📊 ACCURATE BINANCE VISION LIVE PRICE FETCH
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
  except Exception as e:
    print(f'⚠️ Book Ticker fetch failed for {clean_symbol}: {e}')

  try:
    url = f'{BINANCE_FUTURES_FUNDING_URL}?symbol={clean_symbol}'
    res = requests.get(url, timeout=4)
    if res.status_code == 200:
      val = float(res.json().get('markPrice', 0))
      if val > 0:
        return val
  except Exception as e:
    print(f'⚠️ Futures Funding fetch failed for {clean_symbol}: {e}')

  print(f'❌ ERROR: Live price not found for {clean_symbol}')
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
    url = (
        f'{BINANCE_SPOT_URL}?symbol={clean_symbol}&interval=1m&startTime={current_start}&limit=1000'
    )
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
# 🛡️ AUTO BREAK-EVEN (BE) ENGINE (NEW ADDITION)
# =========================================================




# =========================================================
# 🔄 PROCESS ACTIVE TRADES
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
    print('⚠️ Portfolio record #1 not found. Aborting trade processing.')
    conn.close()
    return
  total_cap, avail_cap, frozen_margin = port_row

  cursor.execute(
      f'SELECT id, timestamp, symbol, direction, entry_price, sl_price,'
      ' tp1_price, tp2_price, margin_frozen, pos_value FROM trades WHERE status'
      f' = {ph}',
      ('ACTIVE',),
  )
  active_trades = cursor.fetchall()

  if not active_trades:
    print('ℹ️ No active trades currently present in the database.')

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
    ) = trade
    print(f'\n📌 Evaluating Trade #{t_id} | {symbol} [{direction}]')

    try:
      dt_obj = datetime.strptime(str(t_time_str), '%Y-%m-%d %H:%M:%S')
      start_ms = int(dt_obj.timestamp() * 1000)
    except Exception as e:
      print(f'❌ Timestamp Parsing Error for Trade #{t_id}: {e}')
      continue

    df = fetch_full_trade_klines(symbol, start_ms)
    if df is None or df.empty:
      print(f'⚠️ No kline data retrieved for {symbol}. Skipping evaluation.')
      continue

    status = 'ACTIVE'
    gross_pnl = 0.0

    trade_dict = {
        'id': t_id,
        'symbol': symbol,
        'direction': direction,
        'entry_price': entry_p,
        'sl_price': sl_p,
        'pos_value': pos_val,
    }

    for idx, row in df.iterrows():
      c_time_ms = row['time']
      c_open, c_high, c_low, c_close = (
          row['open'],
          row['high'],
          row['low'],
          row['close'],
      )
      time_elapsed_seconds = (c_time_ms - start_ms) / 1000.0

      # 🛡️ Dynamic Break-Even Check (Candle High for LONG, Candle Low for SHORT)
      check_p = c_high if direction == 'LONG' else c_low
      sl_p = check_trailing_and_breakeven(trade_dict, check_p)

      if direction == 'LONG':
        if c_close >= c_open:
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
        else:
          if c_high >= tp2_p:
            status = 'CLOSED_TP2'
            gross_pnl = pos_val * ((tp2_p - entry_p) / entry_p)
            break
          elif c_high >= tp1_p:
            status = 'CLOSED_TP1'
            gross_pnl = pos_val * ((tp1_p - entry_p) / entry_p)
            break
          elif c_low <= sl_p:
            status = 'CLOSED_SL'
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
            gross_pnl = candle_gross_pnl
            break

      else:  # SHORT Direction
        if c_close <= c_open:
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
        else:
          if c_low <= tp2_p:
            status = 'CLOSED_TP2'
            gross_pnl = pos_val * ((entry_p - tp2_p) / entry_p)
            break
          elif c_low <= tp1_p:
            status = 'CLOSED_TP1'
            gross_pnl = pos_val * ((entry_p - tp1_p) / entry_p)
            break
          elif c_high >= sl_p:
            status = 'CLOSED_SL'
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
            gross_pnl = candle_gross_pnl
            break

    # DB updates & Event Notification trigger if trade status changed
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
          'UPDATE portfolio SET total_capital = %s, available_capital = %s,'
          ' frozen_margin = %s WHERE id = 1'
          if db_type == 'MYSQL'
          else 'UPDATE portfolio SET total_capital = ?, available_capital = ?,'
          ' frozen_margin = ? WHERE id = 1',
          (total_cap, avail_cap, frozen_margin),
      )
      conn.commit()

      print(
          f'   🔔 TRADE CLOSED: Trade #{t_id} [{symbol}] via {status} | Net'
          f' PnL: ${net_pnl:+.2f}'
      )

      # Send Event Breakdown Notification to topic 'events_hit_hdhdhe'
      send_trade_event_notification(
          trade_id=t_id,
          symbol=symbol,
          direction=direction,
          close_reason=status,
          margin=margin,
          exit_amount=exit_amount,
          net_pnl=net_pnl,
      )

  conn.close()




# =========================================================
# 📋 GENERATE & SEND CLEAN NTFY NOTIFICATION REPORT
# =========================================================
def generate_and_send_report():
  process_active_trades()

  conn, db_type = get_db_connection()
  cursor = conn.cursor()

  # 1. Fetch Base Portfolio State
  cursor.execute(
      'SELECT total_capital, available_capital, frozen_margin FROM portfolio'
      ' WHERE id = 1'
  )
  port_row = cursor.fetchone() or (100.0, 100.0, 0.0)
  base_total_capital, avail_capital, frozen_margin = port_row

  # 2. Fetch Active Trades & Calculate Live Floating PnL
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

  # Total Balance including Live PnL
  live_total_balance = base_total_capital + total_floating_pnl

  # 3. Fetch Closed Trades Metrics
  cursor.execute("SELECT status, pnl FROM trades WHERE status != 'ACTIVE'")
  closed_trades = cursor.fetchall()

  closed_count = len(closed_trades)
  closed_realized_pnl = sum(
      (t[1] if t[1] is not None else 0.0) for t in closed_trades
  )

  conn.close()

  # =========================================================
  # 📱 BUILD CLEAN & RESPONSIVE NTFY FORMATTED MESSAGE
  # =========================================================
  pnl_sign = '+' if total_floating_pnl >= 0 else ''

  msg = '📊 PORTFOLIO BREAKDOWN\n'
  msg += '───────────────────────────\n'
  msg += f'💎 Total Balance : ${live_total_balance:.2f} USDT (Live)\n'
  msg += f'💵 Base Capital  : ${base_total_capital:.2f} USDT\n'
  msg += f'🟢 Available Bal : ${avail_capital:.2f} USDT\n'
  msg += f'🔒 Freezed Bal   : ${frozen_margin:.2f} USDT\n'
  msg += f'📈 Floating PnL  : {pnl_sign}${total_floating_pnl:.2f} USDT\n'
  msg += '───────────────────────────\n\n'

  msg += f'🔴 CLOSED TRADES PnL ({closed_count})\n'
  msg += '───────────────────────────\n'
  msg += f'💰 Realized PnL  : ${closed_realized_pnl:+.2f} USDT\n'
  msg += '───────────────────────────\n\n'

  msg += f'⚡ ACTIVE TRADES ({len(active_positions_details)})\n'
  msg += '═══════════════════════════\n'

  if not active_positions_details:
    msg += '😴 No active positions currently open.\n'
  else:
    for pos in active_positions_details:
      direction_icon = '🟢' if pos['direction'] == 'LONG' else '🔴'
      pnl_icon = '🟢' if pos['float_pnl'] >= 0 else '🔻'

      msg += (
          f"{direction_icon} {pos['symbol']} | {pos['direction']}"
          f" {pos['leverage']}x\n"
      )
      msg += f"• Margin    : ${pos['margin']:.2f} USDT\n"
      msg += f"• Entry     : ${fmt_p(pos['entry_p'])}\n"
      msg += f"• Mark Price: ${fmt_p(pos['live_p'])}\n"
      msg += (
          f"• Live PnL  : {pnl_icon} ${pos['float_pnl']:+.2f}"
          f" ({pos['float_pnl_pct']:+.2f}%)\n"
      )
      msg += '-------------------------------------------\n'

  # Title & Triggering Send
  report_title = (
      '⚡ Live Portfolio Report'
      f' ({len(active_positions_details)} Active Trades)'
  )
  send_ntfy_notification(report_title, msg)


if __name__ == '__main__':
  generate_and_send_report()
