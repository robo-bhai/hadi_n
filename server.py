import os
import io
import base64
import time
import ssl
import requests
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')  # Non-GUI backend
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from flask import Flask, render_template, jsonify

app = Flask(__name__)

# =========================================================
# 🔑 CREDENTIALS FROM ENVIRONMENT (GITHUB SECRETS)
# =========================================================
DB_HOST = os.getenv("DB_HOST", "mysql-3a3d5779-project-b71a.b.aivencloud.com")
DB_USER = os.getenv("DB_USER", "avnadmin")
DB_PASS = os.getenv("DB_PASS", "")  # Read from GitHub Secret DB_PASS
DB_NAME = os.getenv("DB_NAME", "defaultdb")
DB_PORT = int(os.getenv("DB_PORT", "23464"))

# =========================================================
# 🔌 MYSQL CONNECTION
# =========================================================
def get_db_connection():
    try:
        import mysql.connector
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        conn = mysql.connector.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASS,
            database=DB_NAME,
            ssl_context=ssl_ctx,
            connect_timeout=20
        )
        return conn
    except Exception as e:
        print(f"⚠️ Primary SSL Connection Failed: {e}")
        try:
            import mysql.connector
            conn = mysql.connector.connect(
                host=DB_HOST,
                port=DB_PORT,
                user=DB_USER,
                password=DB_PASS,
                database=DB_NAME,
                ssl_disabled=False,
                ssl_verify_cert=False,
                connect_timeout=20
            )
            return conn
        except Exception as err:
            print(f"❌ MySQL Connection Error: {err}")
            return None

# =========================================================
# 📊 TECHNICAL INDICATORS & MARKET FETCHERS
# =========================================================
def fetch_klines(symbol, interval="4h", limit=80):
    url = f"https://data-api.binance.vision/api/v3/klines?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        res = requests.get(url, timeout=6)
        if res.status_code == 200:
            df = pd.DataFrame(res.json(), columns=['time', 'open', 'high', 'low', 'close', 'volume', '_', '_', '_', '_', '_', '_'])
            df['time'] = pd.to_datetime(df['time'], unit='ms')
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = df[col].astype(float)
            return df
    except Exception as e:
        print(f"❌ Error fetching KLines for {symbol}: {e}")
    return None

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

# =========================================================
# 🎨 CHART PLOTTER
# =========================================================
def generate_trade_chart(df, trade):
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 7), gridspec_kw={'height_ratios': [3, 1]}, sharex=True)
    fig.patch.set_facecolor('#0f172a')
    ax1.set_facecolor('#1e293b')
    ax2.set_facecolor('#1e293b')

    for idx, row in df.iterrows():
        color = '#22c55e' if row['close'] >= row['open'] else '#ef4444'
        ax1.plot([row['time'], row['time']], [row['low'], row['high']], color=color, linewidth=1.2)
        height = abs(row['close'] - row['open'])
        bottom = min(row['open'], row['close'])
        ax1.bar(row['time'], height if height > 0 else 0.0001, bottom=bottom, color=color, width=0.08, align='center')

    recent_20 = df.tail(20)
    sup_level = recent_20['low'].min()
    res_level = recent_20['high'].max()

    ax1.axhline(res_level, color='#a855f7', linestyle='--', linewidth=1.5, label=f'Resistance: ${res_level:.4f}')
    ax1.axhline(sup_level, color='#06b6d4', linestyle='--', linewidth=1.5, label=f'Support: ${sup_level:.4f}')

    entry = float(trade['entry_price'])
    sl = float(trade['sl_price'])
    tp1 = float(trade['tp1_price'])
    tp2 = float(trade['tp2_price'])

    ax1.axhline(entry, color='#3b82f6', linestyle='-', linewidth=2, label=f'Entry: ${entry:.4f}')
    ax1.axhline(sl, color='#f43f5e', linestyle='-.', linewidth=2, label=f'SL: ${sl:.4f}')
    ax1.axhline(tp1, color='#10b981', linestyle=':', linewidth=2, label=f'TP1: ${tp1:.4f}')
    ax1.axhline(tp2, color='#059669', linestyle=':', linewidth=2, label=f'TP2: ${tp2:.4f}')

    last_time = df['time'].iloc[-1]
    ax1.annotate(f"ENTRY ({trade['direction']})", xy=(last_time, entry), 
                 xytext=(last_time, entry * 1.02 if trade['direction'] == 'LONG' else entry * 0.98),
                 arrowprops=dict(facecolor='#3b82f6', edgecolor='#3b82f6', shrink=0.05, width=2, headwidth=8),
                 fontsize=10, fontweight='bold', color='#ffffff', ha='center',
                 bbox=dict(boxstyle="round,pad=0.3", fc="#1e3a8a", ec="#3b82f6", lw=1))

    ax1.set_title(f"PRO ANALYST CHART: {trade['symbol']} ({trade['direction']}) | Leverage: {trade['leverage']}x", fontsize=14, fontweight='bold', color='#f8fafc', pad=12)
    ax1.grid(True, color='#334155', linestyle=':', alpha=0.6)
    ax1.legend(loc='upper left', facecolor='#0f172a', edgecolor='#334155', labelcolor='#f8fafc', fontsize=9)
    ax1.tick_params(colors='#94a3b8')

    colors_vol = ['#22c55e' if c >= o else '#ef4444' for c, o in zip(df['close'], df['open'])]
    ax2.bar(df['time'], df['volume'], color=colors_vol, width=0.08, alpha=0.7)
    ax2.set_ylabel('Volume', color='#94a3b8', fontsize=10)
    ax2.grid(True, color='#334155', linestyle=':', alpha=0.6)
    ax2.tick_params(colors='#94a3b8')
    ax2.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))

    plt.xticks(rotation=20)
    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format='png', dpi=130, facecolor=fig.get_facecolor(), edgecolor='none')
    buf.seek(0)
    img_b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
    plt.close(fig)
    return img_b64

# =========================================================
# 🌐 ROUTES
# =========================================================
@app.route('/')
def index():
    return render_template('live_sql.html')

@app.route('/api/active_trades')
def api_active_trades():
    conn = get_db_connection()
    if not conn:
        return jsonify({"status": "error", "message": "Database Connection Failed"}), 500

    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM trades WHERE status = 'ACTIVE'")
    trades = cursor.fetchall()

    cursor.execute("SELECT total_capital, available_capital, frozen_margin FROM portfolio WHERE id = 1")
    portfolio = cursor.fetchone()
    conn.close()

    parsed_trades = []
    for trade in trades:
        symbol = trade['symbol']
        df = fetch_klines(symbol, interval="4h", limit=80)

        if df is not None:
            live_price = float(df['close'].iloc[-1])
            df['RSI'] = calculate_rsi(df['close'])
            df['ATR'] = calculate_atr(df)

            entry = float(trade['entry_price'])
            qty = float(trade['coin_qty'])
            margin = float(trade['margin_frozen'])

            pnl_usdt = (live_price - entry) * qty if trade['direction'] == 'LONG' else (entry - live_price) * qty
            pnl_pct = (pnl_usdt / margin) * 100 if margin > 0 else 0.0

            chart_b64 = generate_trade_chart(df, trade)

            parsed_trades.append({
                "trade_info": trade,
                "live_price": live_price,
                "pnl_usdt": round(pnl_usdt, 2),
                "pnl_pct": round(pnl_pct, 2),
                "rsi": round(float(df['RSI'].iloc[-1]), 2),
                "atr": round(float(df['ATR'].iloc[-1]), 4),
                "volume": round(float(df['volume'].iloc[-1]), 2),
                "chart": chart_b64
            })

    return jsonify({
        "status": "success",
        "portfolio": portfolio,
        "trades": parsed_trades
    })

if __name__ == '__main__':
    port = int(os.getenv("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
