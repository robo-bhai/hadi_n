import base64
from datetime import datetime, timezone
import io
import os
import ssl
from flask import Flask, jsonify, render_template, request
import mysql.connector
import pandas as pd
import requests

app = Flask(__name__)

# =========================================================
# 🔑 EXACT DB CREDENTIALS & CONNECTION SETTINGS
# =========================================================
DB_HOST = os.getenv("DB_HOST", "mysql-3a3d5779-project-b71a.b.aivencloud.com")
DB_USER = os.getenv("DB_USER", "avnadmin")
DB_PASS = os.getenv("DB_PASS", "")  # Read from GitHub Secret DB_PASS
DB_NAME = os.getenv("DB_NAME", "defaultdb")
DB_PORT = int(os.getenv("DB_PORT", "23464"))


def get_db_connection():
  print("⏳ Connecting to Aiven MySQL Database...")
  try:
    conn = mysql.connector.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASS,
        database=DB_NAME,
        ssl_disabled=False,  # Aiven ke liye SSL zaroori hai
        connect_timeout=20,
    )
    print("✅ Connected Successfully!")
    return conn
  except Exception as err:
    print(f"❌ MySQL Connection Error: {err}")
    return None


# =========================================================
# 📊 BINANCE API HELPERS
# =========================================================
def fetch_binance_klines(symbol, interval="1m", limit=300, start_time=None):
  symbol = symbol.replace("/", "").upper()
  if not symbol.endswith("USDT"):
    symbol += "USDT"

  url = "https://fapi.binance.com/fapi/v1/klines"
  params = {"symbol": symbol, "interval": interval, "limit": limit}
  if start_time:
    params["startTime"] = int(start_time)

  try:
    res = requests.get(url, params=params, timeout=8)
    data = res.json()
    if not isinstance(data, list):
      return None

    df = pd.DataFrame(
        data,
        columns=[
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "close_time",
            "quote_volume",
            "trades",
            "taker_buy_base",
            "taker_buy_quote",
            "ignore",
        ],
    )
    cols = ["open", "high", "low", "close", "volume"]
    df[cols] = df[cols].astype(float)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    return df
  except Exception as e:
    print(f"⚠️ Binance Kline Error for {symbol}: {e}")
    return None


def fetch_live_price(symbol):
  symbol = symbol.replace("/", "").upper()
  if not symbol.endswith("USDT"):
    symbol += "USDT"

  url = "https://fapi.binance.com/fapi/v1/ticker/price"
  try:
    res = requests.get(url, params={"symbol": symbol}, timeout=5)
    data = res.json()
    return float(data.get("price", 0.0))
  except Exception:
    return 0.0


# =========================================================
# 🧠 SL DIAGNOSTIC POST-MORTEM ENGINE
# =========================================================
def analyze_sl_trade(trade, df):
  direction = str(trade.get("direction", "LONG")).upper()
  entry = float(trade.get("entry_price", 0.0))
  sl = float(trade.get("sl_price", 0.0))

  total_candles = len(df) if df is not None else 0
  if total_candles < 2:
    return {
        "max_favorable": 0.0,
        "max_adverse": 0.0,
        "vol_spike": 1.0,
        "reasons": ["Insufficient kline data."],
        "win_solutions": [
            "Ensure candles exist in Binance API for this duration."
        ],
    }

  delta = df["close"].diff()
  gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
  loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
  rs = gain / loss
  df["rsi"] = 100 - (100 / (1 + rs))

  tr = (
      pd.concat(
          [
              df["high"] - df["low"],
              (df["high"] - df["close"].shift()).abs(),
              (df["low"] - df["close"].shift()).abs(),
          ],
          axis=1,
      )
      .max(axis=1)
      .rolling(window=14)
      .mean()
  )
  df["atr"] = tr

  max_high = df["high"].max()
  min_low = df["low"].min()
  avg_vol = df["volume"].mean()
  max_vol = df["volume"].max()

  if direction in ["LONG", "BUY"]:
    max_favorable = ((max_high - entry) / entry) * 100 if entry > 0 else 0
    max_adverse = ((entry - min_low) / entry) * 100 if entry > 0 else 0
  else:
    max_favorable = ((entry - min_low) / entry) * 100 if entry > 0 else 0
    max_adverse = ((max_high - entry) / entry) * 100 if entry > 0 else 0

  reasons = []
  win_solutions = []

  atr_val = df["atr"].dropna().iloc[0] if not df["atr"].dropna().empty else 0
  sl_dist = abs(entry - sl)

  if atr_val > 0 and sl_dist < (atr_val * 1.2):
    reasons.append(
        "⚠️ **Tight SL**: Stop Loss distance was within normal ATR noise range."
    )
  if max_vol > (avg_vol * 3.5):
    reasons.append(
        "⚡ **Liquidity Sweep**: Sudden high volume spike hit SL before"
        " movement."
    )
  if max_favorable >= 0.3:
    reasons.append(
        f"🔄 **Reversal / Greed**: Trade was up +{max_favorable:.2f}% before"
        " reversing to SL."
    )

  if not reasons:
    reasons.append(
        "📊 Higher Timeframe market trend or momentum hit the Stop Loss."
    )

  if max_favorable >= 0.3:
    win_tp = entry * (
        1 + (max_favorable * 0.85 / 100)
        if direction in ["LONG", "BUY"]
        else 1 - (max_favorable * 0.85 / 100)
    )
    win_solutions.append(
        f"🎯 Set Micro-TP Target at +{max_favorable*0.8:.2f}% (Price:"
        f" ${win_tp:.5f})."
    )
    win_solutions.append(
        "🛡️ Enable Auto Break-Even (BE) when trade reaches +0.35% profit."
    )
  else:
    win_solutions.append(
        "⛔ Filter out using 15m/1h Higher Timeframe EMA Trend Alignment."
    )

  return {
      "max_favorable": max_favorable,
      "max_adverse": max_adverse,
      "vol_spike": max_vol / avg_vol if avg_vol > 0 else 1.0,
      "reasons": reasons,
      "win_solutions": win_solutions,
  }


# =========================================================
# 🌐 ROUTES & VIEW CONTROLLERS
# =========================================================


@app.route("/")
@app.route("/portfolio")
def tab_portfolio():
  conn = get_db_connection()
  if not conn:
    return "Database Connection Failed. Check server logs."

  cursor = conn.cursor(dictionary=True)

  cursor.execute("SELECT * FROM portfolio WHERE id = 1")
  port = cursor.fetchone() or {
      "total_capital": 100.0,
      "available_capital": 100.0,
      "frozen_margin": 0.0,
  }

  cursor.execute("SELECT * FROM trades WHERE status = 'ACTIVE'")
  active_trades = cursor.fetchall()

  cursor.execute("SELECT * FROM trades WHERE status != 'ACTIVE'")
  closed_trades = cursor.fetchall()

  total_floating_pnl = 0.0
  active_margin = 0.0

  for t in active_trades:
    live_p = fetch_live_price(t["symbol"])
    entry = float(t["entry_price"])
    pos_val = float(t["pos_value"])
    margin = float(t["margin_frozen"])
    active_margin += margin

    if str(t["direction"]).upper() in ["LONG", "BUY"]:
      float_pnl = pos_val * ((live_p - entry) / entry) if entry > 0 else 0
    else:
      float_pnl = pos_val * ((entry - live_p) / entry) if entry > 0 else 0

    total_floating_pnl += float_pnl

  closed_realized_pnl = sum(float(t["pnl"] or 0.0) for t in closed_trades)
  loss_trades_capital = sum(
      abs(float(t["pnl"])) for t in closed_trades if float(t["pnl"] or 0.0) < 0
  )

  avail_cap = float(port["available_capital"])
  freezed_bal = float(port["frozen_margin"])

  # Stated Capital Calculation
  stated_capital = avail_cap + active_margin + loss_trades_capital
  total_overall_balance = float(port["total_capital"]) + total_floating_pnl
  live_roi = (
      ((total_overall_balance - stated_capital) / stated_capital) * 100
      if stated_capital > 0
      else 0.0
  )

  conn.close()

  data = {
      "stated_capital": round(stated_capital, 2),
      "available_capital": round(avail_cap, 2),
      "freezed_balance": round(freezed_bal, 2),
      "active_margin": round(active_margin, 2),
      "total_active": len(active_trades),
      "total_closed": len(closed_trades),
      "floating_pnl": round(total_floating_pnl, 2),
      "realized_pnl": round(closed_realized_pnl, 2),
      "live_roi": round(live_roi, 2),
      "total_overall_balance": round(total_overall_balance, 2),
  }
  return render_template("portfolio.html", p=data)


@app.route("/active")
def tab_active_trades():
  conn = get_db_connection()
  if not conn:
    return "Database Connection Failed."

  cursor = conn.cursor(dictionary=True)
  cursor.execute("SELECT * FROM trades WHERE status = 'ACTIVE' ORDER BY id DESC")
  trades = cursor.fetchall()
  conn.close()

  parsed_trades = []
  for t in trades:
    live_p = fetch_live_price(t["symbol"])
    entry = float(t["entry_price"])
    sl = float(t["sl_price"])
    tp1 = float(t["tp1_price"])
    margin = float(t["margin_frozen"])
    pos_val = float(t["pos_value"])

    direction = str(t["direction"]).upper()
    if direction in ["LONG", "BUY"]:
      pnl_usdt = pos_val * ((live_p - entry) / entry) if entry > 0 else 0
      if live_p >= entry and tp1 > entry:
        tp_progress = min(100, max(0, ((live_p - entry) / (tp1 - entry)) * 100))
        sl_progress = 0
      elif live_p < entry and entry > sl:
        sl_progress = min(100, max(0, ((entry - live_p) / (entry - sl)) * 100))
        tp_progress = 0
      else:
        tp_progress = sl_progress = 0
    else:
      pnl_usdt = pos_val * ((entry - live_p) / entry) if entry > 0 else 0
      if live_p <= entry and entry > tp1:
        tp_progress = min(100, max(0, ((entry - live_p) / (entry - tp1)) * 100))
        sl_progress = 0
      elif live_p > entry and sl > entry:
        sl_progress = min(100, max(0, ((live_p - entry) / (sl - entry)) * 100))
        tp_progress = 0
      else:
        tp_progress = sl_progress = 0

    pnl_pct = (pnl_usdt / margin) * 100 if margin > 0 else 0.0

    parsed_trades.append({
        "info": t,
        "live_price": live_p,
        "pnl_usdt": round(pnl_usdt, 2),
        "pnl_pct": round(pnl_pct, 2),
        "tp_progress": round(tp_progress, 1),
        "sl_progress": round(sl_progress, 1),
    })

  return render_template("active_trades.html", trades=parsed_trades)


@app.route("/closed")
def tab_closed_trades():
  conn = get_db_connection()
  if not conn:
    return "Database Connection Failed."

  cursor = conn.cursor(dictionary=True)
  cursor.execute(
      "SELECT * FROM trades WHERE status != 'ACTIVE' ORDER BY id DESC"
  )
  trades = cursor.fetchall()
  conn.close()

  parsed_trades = []
  for t in trades:
    parsed_trades.append({
        "info": t,
        "pnl": round(float(t["pnl"] or 0.0), 2),
        "status": t["status"],
    })

  return render_template("closed_trades.html", trades=parsed_trades)


@app.route("/sl-analysis")
def tab_sl_analysis():
  conn = get_db_connection()
  if not conn:
    return "Database Connection Failed."

  cursor = conn.cursor(dictionary=True)
  cursor.execute(
      "SELECT * FROM trades WHERE status LIKE '%SL%' OR pnl < 0 ORDER BY id DESC"
  )
  sl_trades = cursor.fetchall()
  conn.close()

  analyzed_list = []
  for t in sl_trades:
    entry_time = t["timestamp"]
    if isinstance(entry_time, str):
      entry_time = datetime.strptime(entry_time, "%Y-%m-%d %H:%M:%S")

    start_ms = entry_time.replace(tzinfo=timezone.utc).timestamp() * 1000
    df = fetch_binance_klines(
        t["symbol"], interval="1m", limit=500, start_time=start_ms
    )
    analysis = analyze_sl_trade(t, df)

    analyzed_list.append({"trade": t, "analysis": analysis})

  return render_template("sl_analysis.html", trades=analyzed_list)


@app.route("/api/kline")
def api_kline():
  symbol = request.args.get("symbol", "BTCUSDT")
  tf = request.args.get("tf", "1m")
  df = fetch_binance_klines(symbol, interval=tf, limit=150)

  if df is None or df.empty:
    return jsonify({"error": "Failed to fetch kline data"}), 400

  result = {
      "times": df["open_time"].dt.strftime("%Y-%m-%d %H:%M").tolist(),
      "open": df["open"].tolist(),
      "high": df["high"].tolist(),
      "low": df["low"].tolist(),
      "close": df["close"].tolist(),
  }
  return jsonify(result)


if __name__ == "__main__":
  app.run(host="0.0.0.0", port=5000, debug=True)
