import os
import sqlite3
import ssl
from datetime import datetime
import pandas as pd
import requests

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
BINANCE_BOOK_TICKER_URL = (
    'https://data-api.binance.vision/api/v3/ticker/bookTicker'
)
BINANCE_DEPTH_URL = 'https://data-api.binance.vision/api/v3/depth'
BINANCE_FUTURES_FUNDING_URL = 'https://fapi.binance.com/fapi/v1/premiumIndex'

BINANCE_FEE_RATE = 0.00075


# =========================================================
# 🔌 HARDCODED AIVEN DB CONNECTOR
# =========================================================
def get_db_connection():
  """Hardcoded Aiven MySQL Connector with PASS_DB_2 Secret integration.

  Fallback to SQLite if MySQL connection fails or password missing.
  """
  db_host = 'mysql-paper-trading-nomistorage3-d0bf.d.aivencloud.com'
  db_user = 'avnadmin'
  db_name = 'defaultdb'
  db_port = 13722

  db_pass = os.environ.get('PASS_DB_2', '').strip()

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

  # Fallback SQLite
  conn = sqlite3.connect('trading_system.db')
  return conn, 'SQLITE'


# =========================================================
# 📲 NOTIFICATION ENGINE (NTFY.SH INTEGRATION - RICH UI & LATIN-1 SAFE)
# =========================================================
def send_ntfy_notification(
    title, body, tags='chart_with_upwards_trend,bar_chart'
):
  """Sends professional, rich Markdown-formatted notifications via ntfy.sh using

  LIVE_MON_PAPER GitHub secret as the Topic Name.
  Header titles are kept in clean ASCII to avoid latin-1 encoding errors.
  """
  topic_name = os.getenv('LIVE_MON_PAPER', '').strip()
  if not topic_name:
    print(
        '⚠️ LIVE_MON_PAPER secret/environment variable set nahi hai. Alert skip'
        ' ho raha hai.'
    )
    return

  url = f'https://ntfy.sh/{topic_name}'

  # Clean non-ASCII characters from title to prevent Header latin-1 encoding error
  clean_title = title.encode('ascii', 'ignore').decode('ascii').strip()

  headers = {
      'Title': clean_title if clean_title else 'Portfolio Update',
      'Priority': 'high',
      'Tags': tags,
      'Markdown': 'yes',  # Enables Responsive Markdown Formatting
  }

  try:
    # Body fully supports UTF-8 Unicode / Emojis
    res = requests.post(
        url, data=body.encode('utf-8'), headers=headers, timeout=10
    )
    if res.status_code == 200:
      print(f'🚀 ntfy alert successfully sent to topic: {topic_name}')
    else:
      print(f'❌ ntfy failed: {res.status_code} - {res.text}')
  except Exception as e:
    print(f'❌ ntfy Request Error: {e}')


# =========================================================
# 📊 ACCURATE BINANCE VISION LIVE PRICE FETCH
# =========================================================
def fetch_live_price(symbol):
  if not symbol:
    return None

  clean_symbol = str(symbol).strip().upper()

  # 1. Fetch via Binance Vision Book Ticker Endpoint
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

  # 2. Fallback via Binance Futures Funding Endpoint
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
# 🔄 PROCESS ACTIVE TRADES (QUIET BACKGROUND CANDLE EVALUATION)
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
      ' tp1_price, tp2_price, margin_frozen, pos_value FROM trades WHERE'
      f' status = {ph}',
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

    print(f'   📊 Quietly processing {len(df)} candles from {t_time_str}...')

    status = 'ACTIVE'
    gross_pnl = 0.0

    for idx, row in df.iterrows():
      c_time_ms = row['time']
      c_open, c_high, c_low, c_close = (
          row['open'],
          row['high'],
          row['low'],
          row['close'],
      )
      time_elapsed_seconds = (c_time_ms - start_ms) / 1000.0

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

    if status != 'ACTIVE':
      entry_fee = pos_val * BINANCE_FEE_RATE
      exit_value = max(0, pos_val + gross_pnl)
      exit_fee = exit_value * BINANCE_FEE_RATE
      net_pnl = gross_pnl - (entry_fee + exit_fee)

      cursor.execute(
          f'UPDATE trades SET status = {ph}, pnl = {ph} WHERE id = {ph}',
          (status, net_pnl, t_id),
      )
      frozen_margin = max(0.0, frozen_margin - margin)
      avail_cap += margin + net_pnl
      total_cap += net_pnl

      cursor.execute(
          'UPDATE portfolio SET total_capital = {ph}, available_capital ='
          ' {ph}, frozen_margin = {ph} WHERE id = 1',
          (total_cap, avail_cap, frozen_margin),
      )
      conn.commit()

      print(
          f'   🔔 EVENT TRIGGERED: Trade #{t_id} [{symbol}] CLOSED via {status}'
          f' | Net PnL: ${net_pnl:+.2f}'
      )

      cursor.execute('SELECT status, pnl FROM trades')
      all_trades = cursor.fetchall()

      closed_count = 0
      win_count = 0
      total_realized_pnl = 0.0

      for t_st, t_pnl in all_trades:
        pnl_val = t_pnl if t_pnl is not None else 0.0
        if t_st in [
            'CLOSED_TP1',
            'CLOSED_TP2',
            'CLOSED_SL',
            'CLOSED_MANUAL',
            'CLOSED_24H_PROFIT',
        ]:
          closed_count += 1
          total_realized_pnl += pnl_val
          if pnl_val > 0:
            win_count += 1

      win_rate = (win_count / closed_count * 100) if closed_count > 0 else 0.0
      initial_capital = max(1.0, total_cap - total_realized_pnl)
      total_roi = (total_realized_pnl / initial_capital) * 100

      cursor.execute(
          'SELECT id, symbol, direction, entry_price, sl_price, tp1_price,'
          ' tp2_price, margin_frozen, pos_value, leverage, status FROM trades'
          " WHERE status = 'ACTIVE' ORDER BY id DESC"
      )
      remaining_active_trades = cursor.fetchall()

      def fmt_p(p):
        return (
            f'{p:.6f}'.rstrip('0').rstrip('.')
            if p and p < 1
            else f'{p:.2f}' if p else '0.00'
        )

      event_title = f'TRADE CLOSED: {symbol} [{status}]'
      pnl_icon = '🎉' if net_pnl > 0 else '🛑'

      event_body = f'## {pnl_icon} TRADE CLOSED: `{symbol}`\n'
      event_body += '```\n'
      event_body += f'Reason     : {status}\n'
      event_body += f'Direction  : {direction}\n'
      event_body += f'Entry Price: ${fmt_p(entry_p)}\n'
      event_body += f'Margin     : ${margin:.2f} USDT\n'
      event_body += f'Gross PnL  : ${gross_pnl:+.2f} USDT\n'
      event_body += f'Net PnL    : ${net_pnl:+.2f} USDT\n'
      event_body += '```\n\n'

      event_body += '### 📊 UPDATED PORTFOLIO SUMMARY\n'
      event_body += f'* **Total Capital:** `${total_cap:.2f}` USDT\n'
      event_body += f'* **Available Bal:** `${avail_cap:.2f}` USDT\n'
      event_body += f'* **Frozen Margin:** `${frozen_margin:.2f}` USDT\n'
      event_body += (
          f'* **Win Rate / ROI:** `{win_rate:.1f}%` | **`{total_roi:+.2f}%`**\n\n'
      )

      if not remaining_active_trades:
        event_body += '> ℹ️ *Currently no remaining active trades.*'
      else:
        event_body += (
            f'---\n### 🟢 Active Positions ({len(remaining_active_trades)})\n'
        )
        for r in remaining_active_trades:
          (
              act_id,
              act_symbol,
              act_dir,
              act_entry,
              act_sl,
              act_tp1,
              act_tp2,
              act_margin,
              act_pos,
              act_lev,
              act_status,
          ) = r
          fetched_live = fetch_live_price(act_symbol)
          live_p = fetched_live if fetched_live is not None else act_entry

          if act_dir == 'LONG':
            float_pnl = act_pos * ((live_p - act_entry) / act_entry)
          else:
            float_pnl = act_pos * ((act_entry - live_p) / act_entry)

          float_pnl_pct = (
              (float_pnl / act_margin) * 100 if act_margin > 0 else 0.0
          )
          pnl_badge = '🟢' if float_pnl >= 0 else '🔴'

          event_body += f'{pnl_badge} **`{act_symbol}`** | `{act_dir}` `{act_lev}x`\n'
          event_body += f'> ▫️ **Margin:** `${act_margin:.2f}` USDT | **Pos:** `${act_pos:.2f}`\n'
          event_body += f'> ▫️ **Entry:** `${fmt_p(act_entry)}` ➔ **Live:** `${fmt_p(live_p)}`\n'
          event_body += f'> ▫️ **PnL:** **`{float_pnl:+.2f} USDT`** (`{float_pnl_pct:+.2f}%`)\n\n'

      print(
          '   🚀 ntfy alert sent with full portfolio & running positions'
          ' context.'
      )
      send_ntfy_notification(
          event_title,
          event_body,
          tags='bell,moneybag' if net_pnl > 0 else 'bell,warning',
      )
    else:
      print(f'   🟢 Trade #{t_id} [{symbol}] remains ACTIVE.')

  conn.close()
  print('=' * 60 + '\n')


# =========================================================
# 📋 RICH UI REPORT GENERATOR & NTFY SENDER
# =========================================================
def generate_and_send_report():
  process_active_trades()

  conn, db_type = get_db_connection()
  cursor = conn.cursor()

  cursor.execute(
      'SELECT total_capital, available_capital, frozen_margin FROM portfolio'
      ' WHERE id = 1'
  )
  port_row = cursor.fetchone() or (100.0, 100.0, 0.0)
  total_capital, avail_capital, frozen_margin = port_row

  cursor.execute('SELECT status, pnl, symbol, direction FROM trades')
  all_trades = cursor.fetchall()

  closed_trades_list = []
  closed_count = 0
  win_count = 0
  total_realized_pnl = 0.0

  for status, pnl, sym, r_dir in all_trades:
    pnl_val = pnl if pnl is not None else 0.0
    if status in [
        'CLOSED_TP1',
        'CLOSED_TP2',
        'CLOSED_SL',
        'CLOSED_MANUAL',
        'CLOSED_24H_PROFIT',
    ]:
      closed_count += 1
      total_realized_pnl += pnl_val
      if pnl_val > 0:
        win_count += 1
      closed_trades_list.append((sym, r_dir, status, pnl_val))

  win_rate = (win_count / closed_count * 100) if closed_count > 0 else 0.0
  initial_capital = max(1.0, total_capital - total_realized_pnl)
  total_roi = (total_realized_pnl / initial_capital) * 100

  cursor.execute(
      'SELECT id, symbol, direction, entry_price, sl_price, tp1_price,'
      ' tp2_price, margin_frozen, pos_value, leverage, status FROM trades WHERE'
      " status = 'ACTIVE' ORDER BY id DESC"
  )
  running_trades = cursor.fetchall()
  conn.close()

  def fmt_p(p):
    return (
        f'{p:.6f}'.rstrip('0').rstrip('.')
        if p and p < 1
        else f'{p:.2f}' if p else '0.00'
    )

  # ---------------------------------------------------------
  # CALCULATE LIVE FLOATING PNL FOR ACTIVE POSITIONS
  # ---------------------------------------------------------
  total_live_floating_pnl = 0.0
  active_cards_body = ''

  if running_trades:
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
      total_live_floating_pnl += float_pnl

      pnl_badge = '🟢' if float_pnl >= 0 else '🔴'

      active_cards_body += (
          f'{pnl_badge} **`{symbol}`** | `{direction}` `{lev}x`\n'
      )
      active_cards_body += (
          f'> ▫️ **Margin:** `${margin:.2f}` USDT | **Pos:** `${pos_val:.2f}`\n'
      )
      active_cards_body += (
          f'> ▫️ **Entry:** `${fmt_p(entry_p)}` ➔ **Live:** `${fmt_p(live_p)}`\n'
      )
      active_cards_body += (
          f'> ▫️ **PnL:** **`{float_pnl:+.2f} USDT`** (`{float_pnl_pct:+.2f}%`)\n'
      )
      active_cards_body += (
          f'> ▫️ `SL: ${fmt_p(sl_p)}` | `TP1: ${fmt_p(tp1_p)}` | `TP2:'
          f' ${fmt_p(tp2_p)}`\n\n'
      )

  report_title = f'PORTFOLIO DASHBOARD ({len(running_trades)} ACTIVE)'

  # ---------------------------------------------------------
  # RICH MARKDOWN NOTIFICATION BODY
  # ---------------------------------------------------------
  report_body = '## 📊 PORTFOLIO DASHBOARD\n'
  report_body += '```\n'
  report_body += f'Total Capital : ${total_capital:.2f} USDT\n'
  report_body += f'Avail Balance : ${avail_capital:.2f} USDT\n'
  report_body += f'Frozen Margin : ${frozen_margin:.2f} USDT\n'
  report_body += f'Live Float PnL: ${total_live_floating_pnl:+.2f} USDT\n'
  report_body += f'Win Rate / ROI: {win_rate:.1f}% | {total_roi:+.2f}%\n'
  report_body += '```\n\n'

  # ACTIVE TRADES SECTION
  report_body += f'### ⚡ ACTIVE POSITIONS ({len(running_trades)})\n'
  if not running_trades:
    report_body += '> ℹ️ *No active running trades at the moment.*\n\n'
  else:
    report_body += active_cards_body

  # CLOSED TRADES SECTION
  report_body += f'### 📑 RECENT CLOSED TRADES ({len(closed_trades_list)})\n'
  if not closed_trades_list:
    report_body += '> ℹ️ *No closed trades history available.*\n'
  else:
    for c_sym, c_dir, c_status, c_pnl in closed_trades_list[-5:]:
      c_badge = '✅' if c_pnl > 0 else '❌'
      report_body += (
          f'* {c_badge} **`{c_sym}`** ({c_dir}) ➔ `{c_status}` | PnL:'
          f' **`${c_pnl:+.2f}`**\n'
      )

  print('\n' + '=' * 60)
  print(report_title)
  print('=' * 60)
  print(report_body)
  print('=' * 60)

  # Send Notification
  send_ntfy_notification(
      report_title, report_body, tags='chart_with_upwards_trend,moneybag'
  )


if __name__ == '__main__':
  generate_and_send_report()
