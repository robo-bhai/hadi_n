import os
import sqlite3
import ssl
from datetime import datetime
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
import requests

# ReportLab Imports
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

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
EVENT_ALERT_TOPIC = os.getenv('LIVE_MON_PAPER', '').strip()


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
# 🛠️ DATABASE UTILITIES & NOTIFICATION HELPERS
# =========================================================
def update_sl_in_db(trade_id, new_sl):
  """Updates Stop Loss price in DB for a given trade."""
  conn, db_type = get_db_connection()
  cursor = conn.cursor()
  ph = '%s' if db_type == 'MYSQL' else '?'

  query = f'UPDATE trades SET sl_price = {ph} WHERE id = {ph}'
  cursor.execute(query, (float(new_sl), int(trade_id)))
  conn.commit()
  conn.close()


from email.header import Header


def send_ntfy_notification(
    title, message_body, tags=None, topic=EVENT_ALERT_TOPIC
):
  """Sends push notification via NTFY with RFC 2047 encoded Title."""
  if not topic:
    return

  url = f'https://ntfy.sh/{topic}'

  # Encode Title to RFC 2047 format for Unicode header support
  encoded_title = Header(title, 'utf-8').encode()

  headers = {'Title': encoded_title}
  if tags:
    headers['Tags'] = ','.join(tags)

  try:
    requests.post(url, data=message_body.encode('utf-8'), headers=headers)
  except Exception as e:
    print(f'⚠️ NTFY Notification error: {e}')


# =========================================================
# 🛡️ TRAILING & BREAKEVEN LOGIC INTEGRATION
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
# 📈 GENERATE PROFESSIONAL CANDLESTICK CHART WITH INDICATORS
# =========================================================
def generate_trade_chart(
    symbol, df, entry_p, sl_p, tp1_p, tp2_p, live_p, output_filename
):
  if df is None or df.empty:
    return None

  chart_df = df.tail(120).copy() if len(df) > 120 else df.copy()

  chart_df['datetime'] = pd.to_datetime(chart_df['time'], unit='ms')
  chart_df['ema9'] = chart_df['close'].ewm(span=9, adjust=False).mean()
  chart_df['sma20'] = chart_df['close'].rolling(window=20).mean()

  plt.style.use('dark_background')
  fig, ax = plt.subplots(figsize=(8.5, 3.8), dpi=200)
  fig.patch.set_facecolor('#111827')
  ax.set_facecolor('#1F2937')

  width = 0.0004
  up = chart_df[chart_df['close'] >= chart_df['open']]
  down = chart_df[chart_df['close'] < chart_df['open']]

  ax.vlines(
      up['datetime'],
      up['low'],
      up['high'],
      color='#10B981',
      linewidth=0.8,
      alpha=0.9,
  )
  ax.bar(
      up['datetime'],
      up['close'] - up['open'],
      width,
      bottom=up['open'],
      color='#10B981',
      alpha=0.9,
  )

  ax.vlines(
      down['datetime'],
      down['low'],
      down['high'],
      color='#EF4444',
      linewidth=0.8,
      alpha=0.9,
  )
  ax.bar(
      down['datetime'],
      down['open'] - down['close'],
      width,
      bottom=down['close'],
      color='#EF4444',
      alpha=0.9,
  )

  ax.plot(
      chart_df['datetime'],
      chart_df['ema9'],
      color='#F59E0B',
      linewidth=1.0,
      label='EMA 9',
  )
  ax.plot(
      chart_df['datetime'],
      chart_df['sma20'],
      color='#3B82F6',
      linewidth=1.0,
      label='SMA 20',
  )

  ax.axhline(
      entry_p,
      color='#3B82F6',
      linestyle='--',
      linewidth=1.2,
      label=f'ENTRY (${entry_p:.4f})',
  )
  ax.axhline(
      sl_p,
      color='#EF4444',
      linestyle=':',
      linewidth=1.2,
      label=f'SL (${sl_p:.4f})',
  )
  ax.axhline(
      tp1_p,
      color='#10B981',
      linestyle='-.',
      linewidth=1.1,
      label=f'TP1 (${tp1_p:.4f})',
  )
  ax.axhline(
      tp2_p,
      color='#059669',
      linestyle='-.',
      linewidth=1.1,
      label=f'TP2 (${tp2_p:.4f})',
  )

  if live_p:
    ax.axhline(
        live_p,
        color='#EC4899',
        linestyle='-',
        linewidth=1.3,
        label=f'LIVE (${live_p:.4f})',
    )

  ax.set_title(
      f'EXPERT MARKET ANALYSIS: {symbol}',
      fontsize=11,
      fontweight='bold',
      color='#F9FAFB',
      pad=10,
  )
  ax.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
  ax.grid(True, color='#374151', linestyle=':', alpha=0.5)
  ax.legend(
      loc='upper left',
      fontsize=7,
      facecolor='#1F2937',
      edgecolor='#4B5563',
      labelcolor='#F3F4F6',
  )

  plt.xticks(fontsize=7, color='#D1D5DB')
  plt.yticks(fontsize=7, color='#D1D5DB')
  plt.tight_layout()

  plt.savefig(
      output_filename,
      dpi=200,
      bbox_inches='tight',
      facecolor=fig.get_facecolor(),
  )
  plt.close()
  return output_filename


# =========================================================
# 🔄 PROCESS ACTIVE TRADES (INTEGRATED WITH TRAILING LOGIC)
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

  for trade_tuple in active_trades:
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
    ) = trade_tuple
    print(f'\n📌 Evaluating Trade #{t_id} | {symbol} [{direction}]')

    # Convert tuple to dictionary format for trailing logic
    trade_dict = {
        'id': t_id,
        'symbol': symbol,
        'direction': direction,
        'entry_price': entry_p,
        'sl_price': sl_p,
        'pos_value': pos_val,
    }

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

      # 🛡️ Trailing Check for current candle close
      sl_p = check_trailing_and_breakeven(trade_dict, c_close)

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

      q_trade = f'UPDATE trades SET status = {ph}, pnl = {ph} WHERE id = {ph}'
      cursor.execute(q_trade, (str(status), float(net_pnl), int(t_id)))

      frozen_margin = max(0.0, frozen_margin - margin)
      avail_cap += margin + net_pnl
      total_cap += net_pnl

      q_port = (
          f'UPDATE portfolio SET total_capital = {ph}, available_capital ='
          f' {ph}, frozen_margin = {ph} WHERE id = {ph}'
      )
      cursor.execute(
          q_port,
          (float(total_cap), float(avail_cap), float(frozen_margin), 1),
      )

      conn.commit()

      print(
          f'   🔔 EVENT TRIGGERED: Trade #{t_id} [{symbol}] CLOSED via {status}'
          f' | Net PnL: ${net_pnl:+.2f}'
      )

  conn.close()
  print('=' * 60 + '\n')


# =========================================================
# 📄 EXPERT PDF REPORT GENERATOR
# =========================================================
def build_expert_pdf_report(pdf_filename='Expert_Trading_Report.pdf'):
  conn, db_type = get_db_connection()
  cursor = conn.cursor()

  cursor.execute(
      'SELECT total_capital, available_capital, frozen_margin FROM portfolio'
      ' WHERE id = 1'
  )
  port_row = cursor.fetchone() or (100.0, 100.0, 0.0)
  total_capital, avail_capital, frozen_margin = port_row

  cursor.execute(
      'SELECT id, timestamp, symbol, direction, entry_price, sl_price,'
      ' tp1_price, tp2_price, margin_frozen, pos_value, leverage, status, pnl'
      ' FROM trades ORDER BY id DESC'
  )
  all_trades = cursor.fetchall()
  conn.close()

  closed_trades = []
  active_trades = []
  total_realized_pnl = 0.0
  win_count = 0

  for r in all_trades:
    status = r[11]
    pnl_val = r[12] if r[12] is not None else 0.0

    if status == 'ACTIVE':
      active_trades.append(r)
    else:
      closed_trades.append(r)
      total_realized_pnl += pnl_val
      if pnl_val > 0:
        win_count += 1

  closed_count = len(closed_trades)
  win_rate = (win_count / closed_count * 100) if closed_count > 0 else 0.0
  initial_capital = max(1.0, total_capital - total_realized_pnl)
  total_roi = (total_realized_pnl / initial_capital) * 100

  def fmt_p(p):
    return (
        f'{p:.6f}'.rstrip('0').rstrip('.')
        if p and p < 1
        else f'{p:.2f}' if p else '0.00'
    )

  doc = SimpleDocTemplate(
      pdf_filename,
      pagesize=A4,
      leftMargin=25,
      rightMargin=25,
      topMargin=25,
      bottomMargin=25,
  )
  story = []
  styles = getSampleStyleSheet()

  title_style = ParagraphStyle(
      'DocTitle',
      parent=styles['Normal'],
      fontName='Helvetica-Bold',
      fontSize=20,
      textColor=colors.HexColor('#1E293B'),
      spaceAfter=2,
  )
  subtitle_style = ParagraphStyle(
      'DocSubTitle',
      parent=styles['Normal'],
      fontName='Helvetica',
      fontSize=9,
      textColor=colors.HexColor('#64748B'),
      spaceAfter=12,
  )
  sec_heading = ParagraphStyle(
      'SecHeading',
      parent=styles['Normal'],
      fontName='Helvetica-Bold',
      fontSize=12,
      textColor=colors.HexColor('#0F172A'),
      spaceBefore=10,
      spaceAfter=8,
  )
  cell_text = ParagraphStyle(
      'CellText',
      parent=styles['Normal'],
      fontName='Helvetica',
      fontSize=8,
      textColor=colors.HexColor('#334155'),
      alignment=0,
  )
  cell_bold = ParagraphStyle(
      'CellBold',
      parent=styles['Normal'],
      fontName='Helvetica-Bold',
      fontSize=8,
      textColor=colors.HexColor('#0F172A'),
      alignment=0,
  )

  now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')
  story.append(
      Paragraph('⚡ QUANTITATIVE TRADING EXPERT REPORT', title_style)
  )
  story.append(
      Paragraph(
          f'Generated: {now_str} | System Identity: HADI88 QUANT-PLATFORM',
          subtitle_style,
      )
  )
  story.append(
      HRFlowable(
          width='100%',
          thickness=1.5,
          color=colors.HexColor('#2563EB'),
          spaceAfter=12,
      )
  )

  story.append(Paragraph('📊 EXECUTIVE PORTFOLIO SUMMARY', sec_heading))

  summary_data = [
      [
          Paragraph('Metric Description', cell_bold),
          Paragraph('Value (USDT)', cell_bold),
          Paragraph('Metric Description', cell_bold),
          Paragraph('Value / Rate', cell_bold),
      ],
      [
          Paragraph('Total Portfolio Capital', cell_text),
          Paragraph(f'${total_capital:.2f}', cell_bold),
          Paragraph('Closed Trade Count', cell_text),
          Paragraph(f'{closed_count}', cell_text),
      ],
      [
          Paragraph('Available Liquid Balance', cell_text),
          Paragraph(f'${avail_capital:.2f}', cell_bold),
          Paragraph('Overall Win Rate', cell_text),
          Paragraph(f'{win_rate:.1f}%', cell_bold),
      ],
      [
          Paragraph('Frozen Position Margin', cell_text),
          Paragraph(f'${frozen_margin:.2f}', cell_text),
          Paragraph('Cumulative Portfolio ROI', cell_text),
          Paragraph(
              f'<font color="{("#16A34A" if total_roi >= 0 else "#DC2626")}"><b>{total_roi:+.2f}%</b></font>',
              cell_text,
          ),
      ],
  ]

  summary_table = Table(summary_data, colWidths=[140, 130, 140, 130])
  summary_table.setStyle(
      TableStyle([
          ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#F1F5F9')),
          ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
          ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
          ('TOPPADDING', (0, 0), (-1, -1), 5),
          ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
      ])
  )
  story.append(summary_table)
  story.append(Spacer(1, 12))

  story.append(
      Paragraph(
          f'⚡ ACTIVE TRADING POSITIONS ({len(active_trades)})', sec_heading
      )
  )

  if not active_trades:
    story.append(
        Paragraph('<i>No active positions found in database.</i>', cell_text)
    )
  else:
    active_headers = [
        'ID',
        'Symbol',
        'Dir',
        'Leverage',
        'Entry Price',
        'Live Price',
        'Stop Loss',
        'Target 1',
        'Target 2',
        'Margin',
        'Float PnL',
    ]
    active_grid = [[Paragraph(h, cell_bold) for h in active_headers]]

    for r in active_trades:
      (
          t_id,
          t_time,
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
          pnl_val,
      ) = r
      live_p = fetch_live_price(symbol) or entry_p

      if direction == 'LONG':
        float_pnl = pos_val * ((live_p - entry_p) / entry_p)
      else:
        float_pnl = pos_val * ((entry_p - live_p) / entry_p)

      float_pnl_pct = (float_pnl / margin) * 100 if margin > 0 else 0.0
      p_color = '#16A34A' if float_pnl >= 0 else '#DC2626'

      row = [
          Paragraph(f'#{t_id}', cell_text),
          Paragraph(f'<b>{symbol}</b>', cell_text),
          Paragraph(f'{direction}', cell_text),
          Paragraph(f'{lev}x', cell_text),
          Paragraph(f'${fmt_p(entry_p)}', cell_text),
          Paragraph(f'${fmt_p(live_p)}', cell_text),
          Paragraph(f'${fmt_p(sl_p)}', cell_text),
          Paragraph(f'${fmt_p(tp1_p)}', cell_text),
          Paragraph(f'${fmt_p(tp2_p)}', cell_text),
          Paragraph(f'${margin:.1f}', cell_text),
          Paragraph(
              f'<font color="{p_color}"><b>${float_pnl:+.2f}<br/>({float_pnl_pct:+.1f}%)</b></font>',
              cell_text,
          ),
      ]
      active_grid.append(row)

    active_table = Table(
        active_grid,
        colWidths=[25, 55, 35, 42, 52, 52, 52, 52, 52, 45, 78],
    )
    active_table.setStyle(
        TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#E2E8F0')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#94A3B8')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ])
    )
    story.append(active_table)

  story.append(Spacer(1, 14))

  story.append(
      Paragraph('📈 LIVE TECHNICAL MARKET ANALYSIS CHARTS', sec_heading)
  )

  if active_trades:
    for index, r in enumerate(active_trades[:4]):
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
          lev,
          status,
          pnl_val,
      ) = r
      try:
        dt_obj = datetime.strptime(str(t_time_str), '%Y-%m-%d %H:%M:%S')
        start_ms = int(dt_obj.timestamp() * 1000)
      except Exception:
        start_ms = int(datetime.now().timestamp() * 1000) - (86400 * 1000)

      df_klines = fetch_full_trade_klines(symbol, start_ms)
      live_p = fetch_live_price(symbol) or entry_p

      chart_file = f'chart_trade_{t_id}.png'
      generated_file = generate_trade_chart(
          symbol,
          df_klines,
          entry_p,
          sl_p,
          tp1_p,
          tp2_p,
          live_p,
          output_filename=chart_file,
      )

      if generated_file and os.path.exists(generated_file):
        story.append(Image(generated_file, width=7.2 * inch, height=3.2 * inch))
        story.append(Spacer(1, 10))

  story.append(Spacer(1, 10))

  story.append(Paragraph('📑 RECENT CLOSED TRADES HISTORY', sec_heading))

  if not closed_trades:
    story.append(
        Paragraph('<i>No closed trades recorded in system.</i>', cell_text)
    )
  else:
    closed_headers = [
        'ID',
        'Closed Time',
        'Symbol',
        'Direction',
        'Entry Price',
        'Exit Reason / Status',
        'Margin',
        'Net Realized PnL',
    ]
    closed_grid = [[Paragraph(h, cell_bold) for h in closed_headers]]

    for r in closed_trades[:15]:
      (
          t_id,
          t_time,
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
          net_pnl,
      ) = r
      pnl_val = net_pnl if net_pnl is not None else 0.0
      p_color = '#16A34A' if pnl_val > 0 else '#DC2626'

      row = [
          Paragraph(f'#{t_id}', cell_text),
          Paragraph(f'{str(t_time)[:16]}', cell_text),
          Paragraph(f'<b>{symbol}</b>', cell_text),
          Paragraph(f'{direction}', cell_text),
          Paragraph(f'${fmt_p(entry_p)}', cell_text),
          Paragraph(f'<code>{status}</code>', cell_text),
          Paragraph(f'${margin:.1f}', cell_text),
          Paragraph(
              f'<font color="{p_color}"><b>${pnl_val:+.2f} USDT</b></font>',
              cell_text,
          ),
      ]
      closed_grid.append(row)

    closed_table = Table(
        closed_grid, colWidths=[25, 85, 60, 50, 65, 110, 50, 95]
    )
    closed_table.setStyle(
        TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#F8FAFC')),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ])
    )
    story.append(closed_table)

  doc.build(story)
  print(f'✅ Professional PDF Report successfully generated: {pdf_filename}')
  return pdf_filename


# =========================================================
# 📲 NOTIFICATION ENGINE (SEND PDF VIA NTFY.SH ATTACHMENT)
# =========================================================
def send_pdf_report_via_ntfy(pdf_file_path):
  """Dispatches the generated PDF report as a direct file attachment via ntfy.sh."""
  topic_name = os.getenv('LIVE_MON_PAPER', '').strip()
  if not topic_name:
    print(
        '⚠️ LIVE_MON_PAPER secret/environment variable set nahi hai. Alert skip'
        ' ho raha hai.'
    )
    return

  url = f'https://ntfy.sh/{topic_name}'

  if not os.path.exists(pdf_file_path):
    print(f'❌ Cannot attach PDF: File {pdf_file_path} not found.')
    return

  try:
    with open(pdf_file_path, 'rb') as f:
      res = requests.put(
          url,
          data=f,
          headers={
              'Title': 'Trading Expert Portfolio Report (PDF)',
              'Filename': 'Expert_Trading_Report.pdf',
              'Tags': 'file_folder,chart_with_upwards_trend,bar_chart',
              'Priority': 'high',
          },
      )
    if res.status_code == 200:
      print(f'🚀 PDF Report successfully uploaded to ntfy topic: {topic_name}')
    else:
      print(f'❌ ntfy PDF upload failed: {res.status_code} - {res.text}')
  except Exception as e:
    print(f'❌ ntfy Upload Request Error: {e}')


# =========================================================
# 📋 GENERATE REPORT AND DISPATCH
# =========================================================
def generate_and_send_report():
  process_active_trades()
  pdf_file = build_expert_pdf_report('Expert_Trading_Report.pdf')
  send_pdf_report_via_ntfy(pdf_file)


if __name__ == '__main__':
  generate_and_send_report()
