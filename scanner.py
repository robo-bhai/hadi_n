import os
import requests
import pandas as pd
import numpy as np
import time

# Top 75 High-Liquidity USDT Pairs (Futures / Major Spot)
PAIRS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "AVAXUSDT", 
    "LINKUSDT", "NEARUSDT", "APTUSDT", "DOTUSDT", "LTCUSDT", "SUIUSDT", "DOGEUSDT", 
    "SHIBUSDT", "PEPEUSDT", "FLOKIUSDT", "BONKUSDT", "WIFUSDT", "ARBUSDT", "OPUSDT", 
    "MATICUSDT", "FETUSDT", "RNDRUSDT","INJUSDT", "TIAUSDT", "SEIUSDT", "STXUSDT", 
    "FILUSDT", "ATOMUSDT", "ETCUSDT", "BCHUSDT", "UNIUSDT", "AAVEUSDT", "MKRUSDT", 
    "LDOUSDT", "RUNEUSDT", "GRTUSDT", "SNXUSDT", "ICPUSDT", "IMXUSDT", "GALAUSDT", 
    "SANDUSDT", "MANAUSDT", "AXSUSDT", "ROSEUSDT", "THETAUSDT", "EGLDUSDT", "FTMUSDT", 
    "ALGOUSDT", "FLOWUSDT", "KSMUSDT", "NEOUSDT", "EOSUSDT", "IOTAUSDT", "XTZUSDT", 
    "ZILUSDT", "CRVUSDT", "COMPUSDT", "DYDXUSDT", "ENSUSDT", "ORDIUSDT", "1INCHUSDT", 
    "PYTHUSDT", "JUPUSDT", "STRKUSDT", "ENAUSDT", "NOTUSDT", "PENDLEUSDT", "TONUSDT", 
    "WLDUSDT", "ARKMUSDT", "TRXUSDT", "XLMUSDT", "ORDIUSDT"
]

# Unique filter to avoid any duplicates
PAIRS = list(dict.fromkeys(PAIRS))

# Public Vision Endpoints (GitHub Actions / Cloud IP friendly - No US Geoblock)
BINANCE_SPOT_URL = "https://data-api.binance.vision/api/v3/klines"
BINANCE_BOOK_TICKER_URL = "https://data-api.binance.vision/api/v3/ticker/bookTicker"
BINANCE_DEPTH_URL = "https://data-api.binance.vision/api/v3/depth"
BINANCE_FUTURES_FUNDING_URL = "https://fapi.binance.com/fapi/v1/premiumIndex"

# Maximum allowed bid-ask spread % (0.035% = Tight Orderbook, Low Slippage Risk)
MAX_ALLOWED_SPREAD_PCT = 0.035

def send_pushbullet_notification(title, body):
    """Sends native Android lock-screen push notifications via Pushbullet API."""
    api_token = os.getenv("PUSHBULLET_TOKEN")
    if not api_token:
        print("⚠️ PUSHBULLET_TOKEN is not set in environment variables.")
        return

    url = "https://api.pushbullet.com/v2/pushes"
    headers = {
        "Access-Token": api_token,
        "Content-Type": "application/json"
    }
    payload = {
        "type": "note",
        "title": title,
        "body": body
    }
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=5)
        if res.status_code == 200:
            print("🚀 Pushbullet notification sent successfully!")
        else:
            print(f"❌ Failed to send Pushbullet notification: Status {res.status_code} - {res.text}")
    except Exception as e:
        print(f"❌ Pushbullet API Request Error: {e}")

def calculate_rsi(series, period=14):
    """Calculates RSI using pure pandas math."""
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    loss = loss.replace(0, 0.00001)
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calculate_atr(df, period=14):
    """Calculates Average True Range (ATR) for volatility filtering."""
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift()).abs()
    low_close = (df['low'] - df['close'].shift()).abs()
    
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    return atr

def calculate_adx(df, period=14):
    """Calculates ADX (Average Directional Index) to detect Sideways vs Strong Trend Markets."""
    try:
        df = df.copy()
        df['up'] = df['high'] - df['high'].shift(1)
        df['down'] = df['low'].shift(1) - df['low']
        
        df['+dm'] = ((df['up'] > df['down']) & (df['up'] > 0)) * df['up']
        df['-dm'] = ((df['down'] > df['up']) & (df['down'] > 0)) * df['down']
        
        df['atr'] = calculate_atr(df, period)
        
        df['+di'] = 100 * (df['+dm'].ewm(alpha=1/period).mean() / df['atr'])
        df['-di'] = 100 * (df['-dm'].ewm(alpha=1/period).mean() / df['atr'])
        
        di_sum = df['+di'] + df['-di']
        di_sum = di_sum.replace(0, 0.00001)
        
        dx = 100 * (df['+di'] - df['-di']).abs() / di_sum
        adx = dx.ewm(alpha=1/period).mean()
        return adx.iloc[-1]
    except Exception:
        return 0.0

def analyze_dynamic_structure(df_4h):
    """
    Reads live chart candles to detect real Price Action Support & Resistance.
    Calculates Pivot Points and Level Proximity.
    """
    if df_4h is None or len(df_4h) < 30:
        return None

    highs = df_4h['high'].values
    lows = df_4h['low'].values
    closes = df_4h['close'].values

    pivot_highs = []
    pivot_lows = []

    for i in range(2, len(df_4h) - 2):
        if highs[i] > highs[i-1] and highs[i] > highs[i-2] and highs[i] > highs[i+1] and highs[i] > highs[i+2]:
            pivot_highs.append(highs[i])
        if lows[i] < lows[i-1] and lows[i] < lows[i-2] and lows[i] < lows[i+1] and lows[i] < lows[i+2]:
            pivot_lows.append(lows[i])

    current_price = closes[-1]
    
    valid_res = [h for h in pivot_highs if h > current_price]
    valid_sup = [l for l in pivot_lows if l < current_price]

    dynamic_res = min(valid_res) if valid_res else df_4h['high'].tail(20).max()
    dynamic_sup = max(valid_sup) if valid_sup else df_4h['low'].tail(20).min()

    dist_to_res_pct = ((dynamic_res - current_price) / current_price) * 100
    dist_to_sup_pct = ((current_price - dynamic_sup) / current_price) * 100

    is_resistance_breakout = current_price >= dynamic_res
    is_support_breakdown = current_price <= dynamic_sup

    return {
        "support": dynamic_sup,
        "resistance": dynamic_res,
        "dist_res_pct": dist_to_res_pct,
        "dist_sup_pct": dist_to_sup_pct,
        "is_breakout": is_resistance_breakout,
        "is_breakdown": is_support_breakdown
    }

def calculate_price_velocity(df_1m):
    """Calculates 1-minute to 3-minute instant Price Rate of Change (ROC)."""
    if df_1m is None or len(df_1m) < 3:
        return 0.0
    current_close = df_1m['close'].iloc[-1]
    prev_close = df_1m['close'].iloc[-3]
    return ((current_close - prev_close) / prev_close) * 100

def check_volume_velocity(df_1m):
    """Checks for instant Volume Spurt compared to 20-period average."""
    if df_1m is None or len(df_1m) < 20:
        return False, 1.0
    latest_vol = df_1m['volume'].iloc[-1]
    avg_vol = df_1m['volume'].rolling(20).mean().iloc[-1]
    if avg_vol > 0 and (latest_vol >= avg_vol * 3.0):
        return True, latest_vol / avg_vol
    return False, (latest_vol / avg_vol) if avg_vol > 0 else 1.0

def check_liquidity_and_spread(symbol):
    """Checks Live Bid/Ask Spread to ensure SL order won't suffer heavy slippage."""
    try:
        url = f"{BINANCE_BOOK_TICKER_URL}?symbol={symbol}"
        res = requests.get(url, timeout=3)
        if res.status_code == 200:
            data = res.json()
            bid = float(data['bidPrice'])
            ask = float(data['askPrice'])
            if bid > 0:
                spread_pct = ((ask - bid) / bid) * 100
                return spread_pct <= MAX_ALLOWED_SPREAD_PCT, spread_pct
    except Exception:
        pass
    return False, 999.0

def fetch_orderbook_imbalance(symbol, depth=20):
    """Fetches Live Orderbook Depth and calculates Bid-Ask Imbalance Ratio."""
    try:
        url = f"{BINANCE_DEPTH_URL}?symbol={symbol}&limit={depth}"
        res = requests.get(url, timeout=3)
        if res.status_code == 200:
            data = res.json()
            total_bid_vol = sum([float(b[1]) for b in data.get('bids', [])])
            total_ask_vol = sum([float(a[1]) for a in data.get('asks', [])])
            if total_ask_vol > 0:
                imbalance_ratio = total_bid_vol / total_ask_vol
                return imbalance_ratio, total_bid_vol, total_ask_vol
    except Exception:
        pass
    return 1.0, 0.0, 0.0

def fetch_klines(symbol, interval="4h", limit=100):
    """Fetches Binance Public Kline Data."""
    url = f"{BINANCE_SPOT_URL}?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        res = requests.get(url, timeout=5)
        if res.status_code != 200:
            return None
        data = res.json()
        df = pd.DataFrame(data, columns=[
            'time', 'open', 'high', 'low', 'close', 'volume',
            '_', '_', '_', '_', '_', '_'
        ])
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = df[col].astype(float)
        return df
    except Exception:
        return None

def fetch_funding_rate(symbol):
    """Fetches Futures Funding Rate (Derivatives Squeeze Sentiment)."""
    try:
        url = f"{BINANCE_FUTURES_FUNDING_URL}?symbol={symbol}"
        res = requests.get(url, timeout=4)
        if res.status_code == 200:
            val = float(res.json().get('lastFundingRate', 0.0))
            return val * 100  # Percentage
    except Exception:
        pass
    return 0.0

def get_btc_macro_regime():
    """BTC Market Guard: Checks if BTC is Bullish, Bearish, or Choppy."""
    df_daily = fetch_klines("BTCUSDT", interval="1d", limit=60)
    if df_daily is None:
        return "NEUTRAL", 0.0

    df_daily['EMA_20'] = df_daily['close'].ewm(span=20, adjust=False).mean()
    df_daily['EMA_50'] = df_daily['close'].ewm(span=50, adjust=False).mean()
    
    latest = df_daily.iloc[-1]
    price = latest['close']
    ema20 = latest['EMA_20']
    ema50 = latest['EMA_50']

    if price > ema20 and ema20 > ema50:
        return "BULLISH", price
    elif price < ema20 and ema20 < ema50:
        return "BEARISH", price
    else:
        return "CHOPPY", price

def analyze_legendary_setup(symbol, btc_regime):
    # 1. Anti-Slippage Filter: Live Spread Verification
    is_liquid, current_spread = check_liquidity_and_spread(symbol)
    if not is_liquid:
        return {
            "symbol": symbol,
            "status": "REJECTED_SLIPPAGE_RISK",
            "reason": f"High Bid/Ask Spread ({current_spread:.4f}%)"
        }

    # Fetch Multi-Timeframe Data (1D, 4H & High-Frequency 1M)
    df_1d = fetch_klines(symbol, interval="1d", limit=60)
    df_4h = fetch_klines(symbol, interval="4h", limit=60)
    df_1m = fetch_klines(symbol, interval="1m", limit=30)

    if df_1d is None or df_4h is None:
        return None

    # Live Chart Dynamic Structure Readout
    chart_struct = analyze_dynamic_structure(df_4h)
    if not chart_struct:
        return None

    # Calculate ATR Volatility Squeeze
    df_4h['ATR'] = calculate_atr(df_4h, 14)
    atr_pct = (df_4h['ATR'].iloc[-1] / df_4h['close'].iloc[-1]) * 100
    
    # Dynamic Volatility Cutoff: Reject tokens moving too erratically
    if atr_pct > 5.0 and symbol not in ["BTCUSDT", "ETHUSDT"]:
        return {
            "symbol": symbol,
            "status": "REJECTED_SLIPPAGE_RISK",
            "reason": f"Extreme Volatility / Wick Risk (ATR: {atr_pct:.2f}%)"
        }

    # --- SIDEWAYS & CONSOLIDATION FILTER (ADX < 20 Filter) ---
    adx_4h = calculate_adx(df_4h, 14)
    if adx_4h < 20.0 and symbol not in ["BTCUSDT", "ETHUSDT"]:
        return {
            "symbol": symbol,
            "status": "REJECTED_SIDEWAYS",
            "reason": f"No Strong Trend / Sideways Market (ADX: {adx_4h:.1f} < 20.0)"
        }

    # Calculate Indicators for 1D
    df_1d['EMA_20'] = df_1d['close'].ewm(span=20, adjust=False).mean()
    df_1d['EMA_50'] = df_1d['close'].ewm(span=50, adjust=False).mean()
    df_1d['RSI'] = calculate_rsi(df_1d['close'], 14)

    # Calculate Indicators for 4H
    df_4h['EMA_20'] = df_4h['close'].ewm(span=20, adjust=False).mean()
    df_4h['EMA_50'] = df_4h['close'].ewm(span=50, adjust=False).mean()
    df_4h['RSI'] = calculate_rsi(df_4h['close'], 14)
    df_4h['Vol_SMA'] = df_4h['volume'].rolling(20).mean()

    # Fast Micro-Structure Indicators (1M Timeframe - Lag Elimination)
    if df_1m is not None and len(df_1m) >= 10:
        df_1m['EMA_3'] = df_1m['close'].ewm(span=3, adjust=False).mean()
        df_1m['EMA_8'] = df_1m['close'].ewm(span=8, adjust=False).mean()
        fast_ema_bullish = df_1m['EMA_3'].iloc[-1] > df_1m['EMA_8'].iloc[-1]
        fast_ema_bearish = df_1m['EMA_3'].iloc[-1] < df_1m['EMA_8'].iloc[-1]
    else:
        fast_ema_bullish = False
        fast_ema_bearish = False

    curr_1d = df_1d.iloc[-1]
    curr_4h = df_4h.iloc[-1]

    live_price = curr_4h['close']
    rsi_4h = curr_4h['RSI']
    vol_spike = curr_4h['volume'] > (curr_4h['Vol_SMA'] * 1.25)

    # Fast Real-Time Momentum Calculations
    roc_1m = calculate_price_velocity(df_1m)
    vol_spurt, vol_ratio = check_volume_velocity(df_1m)
    
    # Orderbook Imbalance Calculation
    ob_ratio, bid_vol, ask_vol = fetch_orderbook_imbalance(symbol, depth=20)

    # Derivatives Sentiment
    funding_rate = fetch_funding_rate(symbol)

    # Scoring Algorithm (Institutional Edge Score)
    score = 50
    confluences = [f"Low Slippage Guard Passed (Spread: {current_spread:.3f}%)"]

    # 1. Multi-Timeframe Alignment
    if curr_1d['close'] > curr_1d['EMA_20'] and curr_4h['close'] > curr_4h['EMA_20']:
        score += 15
        confluences.append("Bullish MTF Alignment (1D+4H)")
    elif curr_1d['close'] < curr_1d['EMA_20'] and curr_4h['close'] < curr_4h['EMA_20']:
        score -= 15
        confluences.append("Bearish MTF Alignment (1D+4H)")

    # 2. RSI Oversold/Overbought Squeeze
    if rsi_4h <= 35:
        score += 20
        confluences.append(f"4H RSI Oversold ({rsi_4h:.1f})")
    elif rsi_4h >= 65:
        score -= 20
        confluences.append(f"4H RSI Overbought ({rsi_4h:.1f})")

    # 3. Volume Spike
    if vol_spike:
        score += 10 if score >= 50 else -10
        confluences.append("Institutional Volume Spike")

    # 4. Orderbook Imbalance Depth Filter
    if ob_ratio >= 1.3:
        score += 10
        confluences.append(f"Bullish Orderbook Depth Imbalance (Bid/Ask: {ob_ratio:.2f}x)")
    elif ob_ratio <= 0.7:
        score -= 10
        confluences.append(f"Bearish Orderbook Depth Imbalance (Bid/Ask: {ob_ratio:.2f}x)")

    # 5. Derivatives Funding Squeeze
    if funding_rate < -0.01:
        score += 15
        confluences.append(f"Short Squeeze Scent (Funding: {funding_rate:.4f}%)")
    elif funding_rate > 0.03:
        score -= 15
        confluences.append(f"Long Flush Scent (Funding: {funding_rate:.4f}%)")

    # 6. INSTANT MOMENTUM & UNLAGGED PUMP/DUMP DETECTION
    if roc_1m >= 1.0 and vol_spurt and fast_ema_bullish:
        score += 15
        confluences.append(f"⚡ Instant Pump Impulse: +{roc_1m:.2f}% (Vol Surge: {vol_ratio:.1f}x)")
    elif roc_1m <= -1.0 and vol_spurt and fast_ema_bearish:
        score -= 15
        confluences.append(f"⚡ Instant Dump Impulse: {roc_1m:.2f}% (Vol Surge: {vol_ratio:.1f}x)")

    # 7. STRONG TREND ADX BOOST
    if adx_4h >= 30.0:
        if score >= 50:
            score += 10
        else:
            score -= 10
        confluences.append(f"💪 Strong Trend Momentum (4H ADX: {adx_4h:.1f})")

    # 8. DYNAMIC PRICE ACTION LEVEL VERIFICATION (SMART GUARD)
    if score >= 60:
        if chart_struct['is_breakout']:
            score += 15
            confluences.append("🔥 Dynamic Resistance Breakout Confirmed!")
        elif chart_struct['dist_res_pct'] < 0.3:
            score -= 25
            confluences.append("⚠️ Long Blocked: Price Hitting Direct Resistance")
        else:
            confluences.append(f"Chart Room to Rise: {chart_struct['dist_res_pct']:.2f}% to Res")

    elif score <= 40:
        if chart_struct['is_breakdown']:
            score -= 15
            confluences.append("💥 Dynamic Support Breakdown Confirmed!")
        elif chart_struct['dist_sup_pct'] < 0.3:
            score += 25
            confluences.append("⚠️ Short Blocked: Price Sitting Direct on Support")
        else:
            confluences.append(f"Chart Room to Fall: {chart_struct['dist_sup_pct']:.2f}% to Sup")

    # Final Classification Logic with BTC Guard Filter
    signal = "NEUTRAL 🟡"
    bias = "NO TRADE"

    if score >= 65:
        if btc_regime == "BEARISH" and symbol != "BTCUSDT":
            signal = "⚠️ BLOCKED LONG (BTC Bearish Risk)"
            bias = "HIGH RISK"
        else:
            signal = "🔥 LEGENDARY LONG"
            bias = "LONG"
    elif score <= 35:
        if btc_regime == "BULLISH" and symbol != "BTCUSDT":
            signal = "⚠️ BLOCKED SHORT (BTC Bullish Risk)"
            bias = "HIGH RISK"
        else:
            signal = "💥 LEGENDARY SHORT"
            bias = "SHORT"

    return {
        "status": "PASSED",
        "symbol": symbol,
        "price": live_price,
        "score": score,
        "signal": signal,
        "bias": bias,
        "funding": funding_rate,
        "rsi_4h": rsi_4h,
        "adx_4h": adx_4h,
        "support": chart_struct['support'],
        "resistance": chart_struct['resistance'],
        "ob_ratio": ob_ratio,
        "confluences": confluences
    }

def run_legendary_engine():
    print("=" * 80)
    print("   🏛️ LEGENDARY ENGINE v3.0 (LIVE CHART STRUCTURE & PRICE ACTION VERIFIED) 🏛️")
    print("=" * 80)

    print("\n⏳ Fetching BTC Macro Market Guard...")
    btc_regime, btc_price = get_btc_macro_regime()
    print(f"🌐 BTC Market Regime: [{btc_regime}] @ ${btc_price:.2f} USDT\n")

    print(f"🔍 Scanning {len(PAIRS)} Pairs for High Order-Book Depth, Low Slippage & Trend Strength...")
    print("-" * 80)

    results = []
    rejected = []
    for pair in PAIRS:
        res = analyze_legendary_setup(pair, btc_regime)
        if res:
            if res.get("status") == "PASSED":
                results.append(res)
            else:
                rejected.append(res)
        time.sleep(0.04)

    # Sort By Institutional Score Highest to Lowest
    results.sort(key=lambda x: x['score'], reverse=True)

    high_conviction = [r for r in results if r['bias'] in ['LONG', 'SHORT']]
    blocked_trades = [r for r in results if "BLOCKED" in r['signal']]
    neutral_trades = [r for r in results if r['bias'] not in ['LONG', 'SHORT'] and "BLOCKED" not in r['signal']]

    # Helper function for dynamic price formatting
    def fmt_p(price):
        return f"{price:.6f}".rstrip('0').rstrip('.') if price < 1 else f"{price:.2f}"

    # Output Printing
    print("\n" + "=" * 80)
    print("🎯 HIGH-CONVICTION SAFE SLIPPAGE TRADES (Score >= 65 or <= 35)")
    print("=" * 80)
    if high_conviction:
        for item in high_conviction:
            print(f"🪙 {item['symbol']:<10} | Price: ${fmt_p(item['price']):<10} | Score: {item['score']}/100 | Signal: {item['signal']}")
            print(f"   ├─ Funding Rate: {item['funding']:.4f}% | 4H RSI: {item['rsi_4h']:.1f} | 4H ADX: {item['adx_4h']:.1f} | OB Ratio: {item['ob_ratio']:.2f}x")
            print(f"   ├─ Key Support: ${fmt_p(item['support'])} | Key Resistance: ${fmt_p(item['resistance'])}")
            print(f"   └─ Confluences: {', '.join(item['confluences'])}\n")

        # -------------------------------------------------------------
        # PUSHBULLET ALERT TRIGGER (Triggered only when signals exist)
        # -------------------------------------------------------------
        alert_title = f"🚨 BINANCE TRADE ALERT ({len(high_conviction)} Signal Found)"
        alert_body = f"🌐 BTC Regime: {btc_regime} (${fmt_p(btc_price)})\n\n"
        for item in high_conviction:
            alert_body += f"🪙 {item['symbol']} | Signal: {item['signal']}\n"
            alert_body += f"💰 Price: ${fmt_p(item['price'])} | Score: {item['score']}/100\n"
            alert_body += f"📊 4H RSI: {item['rsi_4h']:.1f} | ADX: {item['adx_4h']:.1f} | OB: {item['ob_ratio']:.2f}x\n"
            alert_body += f"🎯 Supp: ${fmt_p(item['support'])} | Res: ${fmt_p(item['resistance'])}\n\n"
        
        send_pushbullet_notification(alert_title, alert_body)

    else:
        print("   (Koi high-probability safe trade spot nahi hui. Capital preserve karein!)\n")

    if blocked_trades:
        print("=" * 80)
        print("🛡️ BTC GUARD BLOCKED TRADES")
        print("=" * 80)
        for item in blocked_trades:
            print(f"⚠️ {item['symbol']:<10} | Signal: {item['signal']} | Score: {item['score']}/100")
            print(f"   └─ Reason: Macro BTC Trend ({btc_regime}) Altcoin direction ke opposite hai.\n")

    if rejected:
        print("=" * 80)
        print(f"🛡️ REJECTED COINS ({len(rejected)} Pairs filtered due to High Spread / Volatility / Sideways Risk)")
        print("=" * 80)
        for r in rejected[:15]:
            print(f"❌ {r['symbol']:<10} | Reason: {r['reason']}")
        if len(rejected) > 15:
            print(f"   ... and {len(rejected) - 15} more coins rejected for safe trading.")
        print("\n")

    print("=" * 80)
    print("🟡 LOW CONVICTION / NEUTRAL WATCHLIST SUMMARY")
    print("=" * 80)
    summary_list = [f"{i['symbol']}:{i['score']}" for i in neutral_trades]
    print("   " + (", ".join(summary_list) if summary_list else "None"))
    print("\n" + "=" * 80 + "\n")

if __name__ == "__main__":
    run_legendary_engine()
