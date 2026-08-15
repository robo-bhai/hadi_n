import requests
import pandas as pd
import numpy as np

BINANCE_SPOT_URL = "https://api.binance.com/api/v3/klines"

def fetch_klines(symbol="BTCUSDT", interval="4h", limit=100):
    """Binance Public API se klines (candlestick data) fetch karta hai."""
    url = f"{BINANCE_SPOT_URL}?symbol={symbol}&interval={interval}&limit={limit}"
    try:
        res = requests.get(url, timeout=5)
        if res.status_code != 200:
            print(f"❌ API Error: Status Code {res.status_code}")
            return None
        data = res.json()
        df = pd.DataFrame(data, columns=[
            'time', 'open', 'high', 'low', 'close', 'volume', 
            '_', '_', '_', '_', '_', '_'
        ])
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = df[col].astype(float)
        return df
    except Exception as e:
        print(f"❌ Request Failed: {e}")
        return None

def calculate_atr(df, period=14):
    """Average True Range (ATR) calculate karta hai ADX ke liye."""
    df = df.copy()
    high_low = df['high'] - df['low']
    high_close = (df['high'] - df['close'].shift(1)).abs()
    low_close = (df['low'] - df['close'].shift(1)).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.rolling(window=period).mean()

def calculate_adx(df, period=14):
    """ADX (Trend Strength) calculate karta hai ye dekhne ke liye ke trend strong hai ya choppy."""
    try:
        df = df.copy()
        df['up'] = df['high'] - df['high'].shift(1)
        df['down'] = df['low'].shift(1) - df['low']
        
        df['+dm'] = ((df['up'] > df['down']) & (df['up'] > 0)) * df['up']
        df['-dm'] = ((df['down'] > df['up']) & (df['down'] > 0)) * df['down']
        
        df['atr'] = calculate_atr(df, period)
        
        df['+di'] = 100 * (df['+dm'].ewm(alpha=1/period).mean() / df['atr'].replace(0, 0.00001))
        df['-di'] = 100 * (df['-dm'].ewm(alpha=1/period).mean() / df['atr'].replace(0, 0.00001))
        
        di_sum = (df['+di'] + df['-di']).replace(0, 0.00001)
        dx = 100 * (df['+di'] - df['-di']).abs() / di_sum
        adx = dx.ewm(alpha=1/period).mean()
        return adx.iloc[-1]
    except Exception:
        return 0.0

def analyze_market_trend(symbol="BTCUSDT", interval="4h"):
    print(f"🔍 Analyzing Market Trend for {symbol} on {interval} timeframe...\n")
    
    df = fetch_klines(symbol, interval=interval, limit=100)
    if df is None or len(df) < 50:
        print("❌ Data insufficient for analysis.")
        return

    # Technical Indicators Calculation
    df['EMA_20'] = df['close'].ewm(span=20, adjust=False).mean()
    df['EMA_50'] = df['close'].ewm(span=50, adjust=False).mean()
    
    latest = df.iloc[-1]
    price = latest['close']
    ema_20 = latest['EMA_20']
    ema_50 = latest['EMA_50']
    adx_val = calculate_adx(df, 14)

    # Trend Logic Decision
    trend = "CHOPPY / SIDEWAYS 🟡"
    
    if adx_val < 20.0:
        trend = "CHOPPY / SIDEWAYS (Weak Momentum) 🟡"
    else:
        if price > ema_20 and ema_20 > ema_50:
            trend = "UP TREND (BULLISH) 🚀"
        elif price < ema_20 and ema_20 < ema_50:
            trend = "DOWN TREND (BEARISH) 📉"
        else:
            trend = "CHOPPY / MIXED STRUCTURE ⚖️"

    # Print Report Card
    print("=" * 50)
    print(f"📊 MARKET TREND REPORT: {symbol}")
    print("=" * 50)
    print(f"💵 Current Price : ${price:,.2f}")
    print(f"📈 EMA 20        : ${ema_20:,.2f}")
    print(f"📉 EMA 50        : ${ema_50:,.2f}")
    print(f"💪 ADX Strength  : {adx_val:.2f} (Threshold: 20)")
    print(f"🎯 Market Status : {trend}")
    print("=" * 50)

if __name__ == "__main__":
    # Aap yahan koi bhi pair daal sakte hain jaise 'ETHUSDT', 'SOLUSDT', etc.
    target_symbol = "BTCUSDT"
    analyze_market_trend(symbol=target_symbol, interval="4h")
