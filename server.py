import base64
from datetime import datetime, timezone
import io
import os
import ssl
from flask import Flask, jsonify, render_template, request
import mysql.connector
import pandas as pd
import requests
import os
from flask import Flask, jsonify, render_template, request
from flask_httpauth import HTTPBasicAuth
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
auth = HTTPBasicAuth()

# Credentials Configuration
APP_USER = os.getenv("APP_USER", "hd")
APP_PASS = os.getenv("APP_PASS", "88123")

users = {
    APP_USER: generate_password_hash(APP_PASS)
}

@auth.verify_password
def verify_password(username, password):
    if username in users and check_password_hash(users.get(username), password):
        return username
    return None
# =========================================================
# 🔑 DB CREDENTIALS & CONNECTION SETTINGS
# =========================================================
DB_HOST = os.getenv("DB_HOST", "mysql-3a3d5779-project-b71a.b.aivencloud.com")
DB_USER = os.getenv("DB_USER", "avnadmin")
DB_PASS = os.getenv("DB_PASS", "")  # GitHub Secret or Local Env
DB_NAME = os.getenv("DB_NAME", "defaultdb")
DB_PORT = int(os.getenv("DB_PORT", "23464"))


def get_db_connection():
  try:
    conn = mysql.connector.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASS,
        database=DB_NAME,
        ssl_disabled=False,
        connect_timeout=20,
    )
    return conn
  except Exception as err:
    print(f"❌ MySQL Connection Error: {err}")
    return None


# =========================================================
# 📊 BINANCE API HELPERS
# =========================================================
def fetch_binance_klines(
    symbol, interval='1m', limit=1000, start_time=None, end_time=None
):
  symbol = symbol.replace('/', '').upper()
  if not symbol.endswith('USDT'):
    symbol += 'USDT'

  url = 'https://fapi.binance.com/fapi/v1/klines'
  params = {'symbol': symbol, 'interval': interval, 'limit': limit}
  if start_time:
    params['startTime'] = int(start_time)
  if end_time:
    params['endTime'] = int(end_time)

  try:
    res = requests.get(url, params=params, timeout=10)
    data = res.json()
    if not isinstance(data, list):
      return None

    df = pd.DataFrame(
        data,
        columns=[
            'open_time',
            'open',
            'high',
            'low',
            'close',
            'volume',
            'close_time',
            'quote_volume',
            'trades',
            'taker_buy_base',
            'taker_buy_quote',
            'ignore',
        ],
    )
    cols = ['open', 'high', 'low', 'close', 'volume']
    df[cols] = df[cols].astype(float)
    df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
    return df
  except Exception as e:
    print(f'⚠️ Binance Kline Error for {symbol}: {e}')
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


from flask import Flask, render_template, jsonify
from datetime import datetime

@app.route("/")
@app.route("/portfolio")
@auth.login_required
def tab_portfolio():
    conn = None
    try:
        # Multi-engine connector supports (MySQL / SQLite)
        db_res = get_db_connection()
        if not db_res:
            return "Database Connection Failed. Check server logs.", 500
        
        # Handle tuple return (conn, db_type) or direct connection object
        conn = db_res[0] if isinstance(db_res, tuple) else db_res
        
        # Determine dictionary cursor capability dynamically based on connector
        if hasattr(conn, 'cursor'):
            try:
                cursor = conn.cursor(dictionary=True)
            except TypeError:
                # SQLite fallback
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
        else:
            return "Invalid Database Cursor configuration.", 500

        # 1. Fetch Portfolio Stated Balance
        cursor.execute("SELECT * FROM portfolio WHERE id = 1")
        port_row = cursor.fetchone()
        port = dict(port_row) if port_row else {
            "total_capital": 100.0,
            "available_capital": 100.0,
            "frozen_margin": 0.0,
        }

        # 2. Fetch Active Trades
        cursor.execute("SELECT * FROM trades WHERE status = 'ACTIVE'")
        active_rows = cursor.fetchall() or []
        active_trades = [dict(r) for r in active_rows]

        # 3. Fetch Closed Trades
        cursor.execute("SELECT * FROM trades WHERE status != 'ACTIVE' ORDER BY id ASC")
        closed_rows = cursor.fetchall() or []
        closed_trades = [dict(r) for r in closed_rows]

        # Active Trades Floating Calculations
        total_floating_pnl = 0.0
        active_margin = 0.0
        total_active_pos_val = 0.0

        for t in active_trades:
            symbol = t.get("symbol", "BTCUSDT")
            live_p = fetch_live_price(symbol)
            
            entry = float(t.get("entry_price") or 0.0)
            pos_val = float(t.get("pos_value") or 0.0)
            margin = float(t.get("margin_frozen") or 0.0)
            direction = str(t.get("direction", "")).upper()

            # Mark price fallback to entry if live price fetch fails
            if live_p is None or live_p <= 0:
                live_p = entry

            active_margin += margin
            total_active_pos_val += pos_val

            if direction in ["LONG", "BUY"]:
                float_pnl = pos_val * ((live_p - entry) / entry) if entry > 0 else 0.0
            else:
                float_pnl = pos_val * ((entry - live_p) / entry) if entry > 0 else 0.0

            total_floating_pnl += float_pnl

        # Closed Trades Statistical Audit
        total_closed_count = len(closed_trades)
        winning_trades = []
        losing_trades = []
        pnls_history = []

        for t in closed_trades:
            pnl = float(t.get("pnl") or 0.0)
            pnls_history.append(pnl)
            if pnl > 0:
                winning_trades.append(pnl)
            elif pnl < 0:
                losing_trades.append(abs(pnl))

        wins_count = len(winning_trades)
        losses_count = len(losing_trades)
        total_gross_profit = sum(winning_trades)
        total_gross_loss = sum(losing_trades)
        net_realized_pnl = total_gross_profit - total_gross_loss

        win_rate = ((wins_count / total_closed_count) * 100) if total_closed_count > 0 else 0.0

        if total_gross_loss > 0:
            profit_factor = total_gross_profit / total_gross_loss
        else:
            profit_factor = total_gross_profit if total_gross_profit > 0 else 1.0

        avg_win = (total_gross_profit / wins_count) if wins_count > 0 else 0.0
        avg_loss = (total_gross_loss / losses_count) if losses_count > 0 else 0.0
        payoff_ratio = (avg_win / avg_loss) if avg_loss > 0 else avg_win

        loss_rate = 1.0 - (win_rate / 100.0)
        expectancy = ((win_rate / 100.0) * avg_win) - (loss_rate * avg_loss)

        sharpe_ratio = 0.0
        max_drawdown_pct = 0.0

        if total_closed_count > 1 and len(pnls_history) > 1:
            mean_ret = sum(pnls_history) / len(pnls_history)
            variance = sum((x - mean_ret) ** 2 for x in pnls_history) / len(pnls_history)
            std_dev = variance ** 0.5

            if std_dev > 0:
                sharpe_ratio = (mean_ret / std_dev) * (total_closed_count ** 0.5)

            cum_pnl = 0.0
            peak = 0.0
            max_dd = 0.0
            for p in pnls_history:
                cum_pnl += p
                if cum_pnl > peak:
                    peak = cum_pnl
                dd = peak - cum_pnl
                if dd > max_dd:
                    max_dd = dd

            base_cap = float(port.get("total_capital") or 100.0)
            max_drawdown_pct = (max_dd / base_cap * 100) if base_cap > 0 else 0.0

        # Account Balance Totals
        avail_cap = float(port.get("available_capital") or 0.0)
        base_starting_capital = float(port.get("total_capital") or 100.0)

        # Precise Real-time Equity Audit
        total_account_equity = avail_cap + active_margin + net_realized_pnl + total_floating_pnl

        all_time_roi = (
            ((total_account_equity - base_starting_capital) / base_starting_capital) * 100
            if base_starting_capital > 0
            else 0.0
        )

        effective_leverage = (
            (total_active_pos_val / total_account_equity)
            if total_account_equity > 0
            else 0.0
        )
        
        margin_utilization_pct = (
            (active_margin / total_account_equity * 100)
            if total_account_equity > 0
            else 0.0
        )

        if margin_utilization_pct > 60:
            risk_level = "HIGH EXPOSURE"
        elif margin_utilization_pct > 25:
            risk_level = "BALANCED"
        else:
            risk_level = "CONSERVATIVE"

        # Complete Audit Payload synchronized with Jinja HTML Template Tags
        audit = {
            "base_starting_capital": round(base_starting_capital, 2),
            "available_capital": round(avail_cap, 2),
            "active_margin_frozen": round(active_margin, 2),
            "total_account_equity": round(total_account_equity, 2),
            "unrealized_floating_pnl": round(total_floating_pnl, 2),
            "realized_net_pnl": round(net_realized_pnl, 2),
            "gross_profit": round(total_gross_profit, 2),
            "gross_loss": round(total_gross_loss, 2),
            "all_time_roi_pct": round(all_time_roi, 2),
            "total_trades_audited": total_closed_count + len(active_trades),
            "closed_trades_count": total_closed_count,
            "active_trades_count": len(active_trades),
            "win_rate_pct": round(win_rate, 2),
            "profit_factor": round(profit_factor, 2),
            "payoff_ratio": round(payoff_ratio, 2),
            "expectancy_per_trade": round(expectancy, 2),
            "avg_win_usdt": round(avg_win, 2),
            "avg_loss_usdt": round(avg_loss, 2),
            "sharpe_ratio": round(sharpe_ratio, 2),
            "max_drawdown_pct": round(max_drawdown_pct, 2),
            "effective_leverage": round(effective_leverage, 2),
            "margin_utilization_pct": round(margin_utilization_pct, 1),
            "risk_level": risk_level,
        }

        return render_template("portfolio.html", audit=audit)

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": "Internal Error", "details": str(e)}), 500

    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass



from flask import Flask, render_template, jsonify
import sqlite3
import traceback

@app.route('/active')
@auth.login_required
def tab_active_trades():
    conn = None
    try:
        # Multi-engine database connection handling (MySQL / SQLite)
        db_res = get_db_connection()
        if not db_res:
            return 'Database Connection Failed.', 500

        # Unpack connection and handle dictionary cursors dynamically
        conn = db_res[0] if isinstance(db_res, tuple) else db_res

        if hasattr(conn, 'cursor'):
            try:
                cursor = conn.cursor(dictionary=True)
            except TypeError:
                # SQLite row_factory fallback
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
        else:
            return "Invalid Database Cursor configuration.", 500

        cursor.execute("SELECT * FROM trades WHERE status = 'ACTIVE' ORDER BY id DESC")
        active_rows = cursor.fetchall() or []
        trades = [dict(r) for r in active_rows]

        parsed_trades = []
        total_floating_pnl = 0.0
        total_margin_used = 0.0
        long_count = 0
        short_count = 0

        for t in trades:
            symbol = t.get('symbol', 'BTCUSDT')
            live_p = fetch_live_price(symbol)
            
            entry = float(t.get('entry_price') or 0.0)
            sl = float(t.get('sl_price') or 0.0)
            tp1 = float(t.get('tp1_price') or 0.0)
            margin = float(t.get('margin_frozen') or 0.0)
            pos_val = float(t.get('pos_value') or 0.0)

            # Fallback to entry price if API fails
            if live_p is None or live_p <= 0:
                live_p = entry

            total_margin_used += margin
            direction = str(t.get('direction', 'LONG')).upper()

            if direction in ['LONG', 'BUY']:
                long_count += 1
                pnl_usdt = pos_val * ((live_p - entry) / entry) if entry > 0 else 0.0
                
                # Long TP & SL Progress Percentage
                if live_p >= entry and tp1 > entry:
                    tp_progress = min(100.0, max(0.0, ((live_p - entry) / (tp1 - entry)) * 100))
                    sl_progress = 0.0
                elif live_p < entry and entry > sl:
                    sl_progress = min(100.0, max(0.0, ((entry - live_p) / (entry - sl)) * 100))
                    tp_progress = 0.0
                else:
                    tp_progress = sl_progress = 0.0
            else:
                short_count += 1
                pnl_usdt = pos_val * ((entry - live_p) / entry) if entry > 0 else 0.0
                
                # Short TP & SL Progress Percentage
                if live_p <= entry and entry > tp1:
                    tp_progress = min(100.0, max(0.0, ((entry - live_p) / (entry - tp1)) * 100))
                    sl_progress = 0.0
                elif live_p > entry and sl > entry:
                    sl_progress = min(100.0, max(0.0, ((live_p - entry) / (sl - entry)) * 100))
                    tp_progress = 0.0
                else:
                    tp_progress = sl_progress = 0.0

            pnl_pct = (pnl_usdt / margin * 100) if margin > 0 else 0.0
            total_floating_pnl += pnl_usdt

            parsed_trades.append({
                'info': t,
                'live_price': round(live_p, 5),
                'pnl_usdt': round(pnl_usdt, 2),
                'pnl_pct': round(pnl_pct, 2),
                'tp_progress': round(tp_progress, 1),
                'sl_progress': round(sl_progress, 1)
            })

        summary = {
            'total_active': len(parsed_trades),
            'total_floating_pnl': round(total_floating_pnl, 2),
            'total_margin_used': round(total_margin_used, 2),
            'long_count': long_count,
            'short_count': short_count
        }

        return render_template('active_trades.html', trades=parsed_trades, summary=summary)

    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': 'Internal Error', 'details': str(e)}), 500

    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass



#+_+_+_+$+(())())())()
from flask import Flask, render_template, jsonify
import sqlite3
import traceback
from datetime import datetime, timezone

@app.route("/closed")
@auth.login_required
def tab_closed_trades():
    conn = None
    try:
        # Multi-engine database connection handling (MySQL / SQLite)
        db_res = get_db_connection()
        if not db_res:
            return "Database Connection Failed.", 500

        # Unpack connection and handle dictionary cursors dynamically
        conn = db_res[0] if isinstance(db_res, tuple) else db_res

        if hasattr(conn, 'cursor'):
            try:
                cursor = conn.cursor(dictionary=True)
            except TypeError:
                # SQLite row_factory fallback
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
        else:
            return "Invalid Database Cursor configuration.", 500

        # Fetch all closed/archived trades
        cursor.execute("SELECT * FROM trades WHERE status != 'ACTIVE' ORDER BY id DESC")
        closed_rows = cursor.fetchall() or []
        trades = [dict(r) for r in closed_rows]

        parsed_trades = []
        total_realized_pnl = 0.0
        wins_count = 0
        losses_count = 0

        for t in trades:
            pnl_val = float(t.get("pnl") or 0.0)
            margin = float(t.get("margin_frozen") or 0.0)
            
            roi_pct = (pnl_val / margin * 100) if margin > 0 else 0.0
            total_realized_pnl += pnl_val

            if pnl_val > 0:
                wins_count += 1
            elif pnl_val < 0:
                losses_count += 1

            parsed_trades.append({
                "info": t,
                "pnl": round(pnl_val, 2),
                "roi_pct": round(roi_pct, 2),
                "status": t.get("status", "CLOSED"),
            })

        summary = {
            "total_closed": len(parsed_trades),
            "total_realized_pnl": round(total_realized_pnl, 2),
            "wins_count": wins_count,
            "losses_count": losses_count,
            "win_rate_pct": round((wins_count / len(parsed_trades) * 100), 2) if parsed_trades else 0.0
        }

        return render_template("closed_trades.html", trades=parsed_trades, summary=summary)

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": "Internal Error", "details": str(e)}), 500

    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass


import time
import sqlite3
import traceback
from datetime import datetime, timezone
from flask import Flask, render_template, jsonify

@app.route('/sl-analysis')
@auth.login_required
def tab_sl_analysis():
    conn = None
    try:
        # Multi-engine database connection handling (MySQL / SQLite)
        db_res = get_db_connection()
        if not db_res:
            return 'Database Connection Failed.', 500

        # Unpack connection and handle dictionary cursors dynamically
        conn = db_res[0] if isinstance(db_res, tuple) else db_res

        if hasattr(conn, 'cursor'):
            try:
                cursor = conn.cursor(dictionary=True)
            except TypeError:
                # SQLite row_factory fallback
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
        else:
            return "Invalid Database Cursor configuration.", 500

        # Query all Stop-Loss hit or net negative PnL trades
        cursor.execute(
            "SELECT * FROM trades WHERE status LIKE '%SL%' OR pnl < 0 ORDER BY id DESC"
        )
        sl_rows = cursor.fetchall() or []
        sl_trades = [dict(r) for r in sl_rows]

        analyzed_list = []
        current_time_ms = int(time.time() * 1000)

        for t in sl_trades:
            entry_time = t.get('timestamp')

            # Datetime string parsing and fallback handling
            if isinstance(entry_time, str):
                try:
                    entry_time = datetime.strptime(entry_time, '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    entry_time = datetime.now(timezone.utc)

            if isinstance(entry_time, datetime):
                if entry_time.tzinfo is None:
                    start_ms = int(entry_time.replace(tzinfo=timezone.utc).timestamp() * 1000)
                else:
                    start_ms = int(entry_time.timestamp() * 1000)
            else:
                start_ms = current_time_ms - (3600 * 1000)  # Fallback to 1 hour back

            symbol = t.get('symbol', 'BTCUSDT')

            # Fetch 1-minute historical candles from entry time to current context
            df = fetch_binance_klines(
                symbol=symbol,
                interval='1m',
                limit=1000,
                start_time=start_ms,
                end_time=current_time_ms,
            )

            # Perform post-mortem diagnostic analysis
            analysis = analyze_sl_trade(t, df)

            analyzed_list.append({
                'trade': t,
                'analysis': analysis,
                'candles_audited': len(df) if (df is not None and hasattr(df, '__len__')) else 0,
            })

        summary = {
            'total_sl_trades': len(analyzed_list),
            'total_pnl_loss': round(sum(float(x['trade'].get('pnl') or 0.0) for x in analyzed_list if float(x['trade'].get('pnl') or 0.0) < 0), 2)
        }

        return render_template('sl_analysis.html', trades=analyzed_list, summary=summary)

    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': 'Analysis Engine Error', 'details': str(e)}), 500

    finally:
        if conn:
            try:
                conn.close()
            except Exception:
                pass



import traceback
from flask import request, jsonify

@app.route("/api/kline")
@auth.login_required
def api_kline():
    try:
        # Request Parameters and Input Sanitization
        symbol = request.args.get("symbol", "BTCUSDT").strip()
        tf = request.args.get("tf", "1m").strip()
        
        try:
            limit = int(request.args.get("limit", 150))
            limit = max(1, min(limit, 1000))  # Clamp within safe limits (1-1000)
        except ValueError:
            limit = 150

        # Fetch market candles dataframe
        df = fetch_binance_klines(symbol, interval=tf, limit=limit)

        if df is None or df.empty:
            response = jsonify({
                "status": "error",
                "message": f"Failed to fetch kline data for {symbol} ({tf})"
            })
            response.status_code = 400
            response.headers.add("Access-Control-Allow-Origin", "*")
            return response

        # Format time-series data vectors
        result = {
            "status": "success",
            "symbol": symbol.upper(),
            "timeframe": tf,
            "count": len(df),
            "times": df["open_time"].dt.strftime("%Y-%m-%d %H:%M").tolist(),
            "open": df["open"].tolist(),
            "high": df["high"].tolist(),
            "low": df["low"].tolist(),
            "close": df["close"].tolist(),
            "volume": df["volume"].tolist() if "volume" in df.columns else []
        }

        response = jsonify(result)
        response.headers.add("Access-Control-Allow-Origin", "*")
        return response, 200

    except Exception as e:
        traceback.print_exc()
        response = jsonify({
            "status": "error",
            "message": "Internal Kline API Error",
            "details": str(e)
        })
        response.status_code = 500
        response.headers.add("Access-Control-Allow-Origin", "*")
        return response



if __name__ == "__main__":
  app.run(host="0.0.0.0", port=5000, debug=True)
