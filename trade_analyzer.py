import os
import time
from datetime import datetime, timezone
import requests
import mysql.connector
from mysql.connector import Error
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# ==========================================
# 1. BINANCE MARKET SCANNER (START TO CURRENT TIME)
# ==========================================

def get_max_price_before_sl_till_now(symbol, direction, entry_price, sl_price, start_time):
    """
    Trade Start Time se le kar CURRENT TIME tak Binance 1m candles scan karta hai.
    Stop Loss (SL) hit hone se pehle ki Maximum Favorable Price return karta hai.
    """
    if not symbol or not entry_price or not sl_price or not start_time:
        return entry_price

    # Symbol format cleanup (e.g. BTCUSDT)
    clean_symbol = symbol.replace("/", "").replace("-", "").upper()
    if not clean_symbol.endswith("USDT") and not clean_symbol.endswith("BUSD"):
        clean_symbol += "USDT"

    # Start Time & Current Time in Unix Timestamps (ms)
    if isinstance(start_time, datetime):
        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
        start_ts = int(start_time.timestamp() * 1000)
    else:
        start_ts = int(time.time() * 1000) - (3600 * 1000)

    # Current Time when script is executing
    current_ts = int(datetime.now(timezone.utc).timestamp() * 1000)

    max_favorable_price = entry_price
    sl_hit_detected = False

    # Binance 1000 candles max per request - Loop through batches till current_ts
    temp_start_ts = start_ts
    
    while temp_start_ts < current_ts and not sl_hit_detected:
        url = (
            f"https://api.binance.com/api/v3/klines"
            f"?symbol={clean_symbol}&interval=1m&startTime={temp_start_ts}&endTime={current_ts}&limit=1000"
        )
        
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                candles = response.json()
                if not candles:
                    break

                for candle in candles:
                    high_p = float(candle[2])
                    low_p = float(candle[3])

                    if direction.upper() == "LONG":
                        # Agar price ne SL touch kar diya toh scan stop
                        if low_p <= sl_price:
                            max_favorable_price = max(max_favorable_price, high_p)
                            sl_hit_detected = True
                            break
                        max_favorable_price = max(max_favorable_price, high_p)

                    elif direction.upper() == "SHORT":
                        # Agar price ne SL touch kar diya toh scan stop
                        if high_p >= sl_price:
                            max_favorable_price = min(max_favorable_price, low_p)
                            sl_hit_detected = True
                            break
                        max_favorable_price = min(max_favorable_price, low_p)

                # Next batch ke liye timestamp move karein (last candle close time + 1ms)
                last_candle_close_time = candles[-1][6]
                temp_start_ts = last_candle_close_time + 1
                
                # Rate limit protection for GitHub Actions
                time.sleep(0.1)
            else:
                print(f"[WARNING] Binance API Status Code: {response.status_code} for {clean_symbol}")
                break

        except Exception as e:
            print(f"[ERROR] Fetching Binance klines failed for {clean_symbol}: {e}")
            break

    return max_favorable_price


# ==========================================
# 2. DATABASE CONFIGURATION & DATA FETCHING
# ==========================================

def get_db_connection():
    try:
        connection = mysql.connector.connect(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", 3306)),
            user=os.getenv("DB_USER", "root"),
            password=os.getenv("DB_PASS", ""),
            database=os.getenv("DB_NAME", "crypto_db"),
            connection_timeout=10
        )
        return connection
    except Error as e:
        print(f"[ERROR] Database connection failed: {e}")
        return None

def fetch_trades_from_db():
    connection = get_db_connection()
    trades = []

    if connection and connection.is_connected():
        try:
            cursor = connection.cursor(dictionary=True)
            query = """
                SELECT 
                    symbol,
                    direction,
                    entry_price,
                    sl_price,
                    tp1_price,
                    coin_qty,
                    pos_value,
                    timestamp AS start_time,
                    COALESCE(updated_at, timestamp) AS close_time,
                    COALESCE(exit_reason, status, 'N/A') AS close_reason,
                    COALESCE(pnl, 0.0) AS net_profit
                FROM trades
                ORDER BY timestamp DESC
            """
            cursor.execute(query)
            trades = cursor.fetchall()
            print(f"[INFO] Fetched {len(trades)} trades from database.")
            cursor.close()
        except Error as e:
            print(f"[ERROR] Database Query Failed: {e}")
        finally:
            if connection.is_connected():
                connection.close()

    return trades


# ==========================================
# 3. EXCEL REPORT GENERATION
# ==========================================

def create_excel_report(trades_data, output_filename="Crypto_Trade_Report.xlsx"):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Trade Breakdown"
    ws.views.sheetView[0].showGridLines = True

    # Header & Accent Styles
    HEADER_FILL = PatternFill(start_color="0F172A", end_color="0F172A", fill_type="solid")
    HEADER_FONT = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
    
    PROFIT_FILL = PatternFill(start_color="D1FAE5", end_color="D1FAE5", fill_type="solid")
    PROFIT_FONT = Font(name="Segoe UI", size=10, color="065F46", bold=True)
    
    LOSS_FILL = PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid")
    LOSS_FONT = Font(name="Segoe UI", size=10, color="991B1B", bold=True)
    
    PEAK_FILL = PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid")
    PEAK_FONT = Font(name="Segoe UI", size=10, color="92400E", bold=True)

    WARN_FILL = PatternFill(start_color="FFEDD5", end_color="FFEDD5", fill_type="solid")
    WARN_FONT = Font(name="Segoe UI", size=10, color="C2410C", bold=True)

    REGULAR_FONT = Font(name="Segoe UI", size=10, color="1F2937")

    THIN_BORDER = Border(
        left=Side(style='thin', color='E5E7EB'),
        right=Side(style='thin', color='E5E7EB'),
        top=Side(style='thin', color='E5E7EB'),
        bottom=Side(style='thin', color='E5E7EB')
    )

    headers = [
        "Pair",                       # Col A
        "Side",                       # Col B
        "Start Time",                 # Col C
        "Close / Status Time",        # Col D
        "Entry Price ($)",            # Col E
        "SL Price ($)",               # Col F
        "Quantity",                   # Col G
        "Max Market Price Before SL", # Col H (FETCHED LIVE FROM BINANCE TILL NOW)
        "Max PnL Before SL ($)",      # Col I (EXACT MAXIMUM PROFIT YOU COULD HAVE TAKEN)
        "Max Peak R-Multiple",        # Col J (FORMULA)
        "1:2 Opportunity Status",     # Col K (STATUS)
        "Actual Net PnL ($)",         # Col L
        "Close Reason"                # Col M
    ]
    
    ws.append(headers)
    
    for col_num, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_num)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = THIN_BORDER
    ws.row_dimensions[1].height = 32

    for row_idx, trade in enumerate(trades_data, start=2):
        start_val = trade.get("start_time")
        close_val = trade.get("close_time")
        
        start_str = start_val.strftime("%Y-%m-%d %H:%M:%S") if isinstance(start_val, datetime) else str(start_val or "N/A")
        close_str = close_val.strftime("%Y-%m-%d %H:%M:%S") if isinstance(close_val, datetime) else str(close_val or "N/A")
        
        direction = str(trade.get("direction", "LONG")).upper()
        entry_price = float(trade.get("entry_price", 0.0))
        sl_price = float(trade.get("sl_price", 0.0))
        coin_qty = float(trade.get("coin_qty", 0.0))
        pos_value = float(trade.get("pos_value", 0.0))
        net_pnl = float(trade.get("net_profit", 0.0))
        reason = str(trade.get("close_reason", "N/A"))

        effective_qty = coin_qty
        if effective_qty == 0 and pos_value > 0 and entry_price > 0:
            effective_qty = pos_value / entry_price

        # Fetch Max Market Price from Start Time to NOW (Current Execution Time)
        print(f"[FETCHING] Scanning candles for {trade.get('symbol')} from start till NOW...")
        max_price_before_sl = get_max_price_before_sl_till_now(
            trade.get("symbol"), direction, entry_price, sl_price, start_val
        )

        # Dynamic Formulas in Excel
        # Col I (Max PnL Before SL): Calculated based on Long or Short
        formula_max_pnl = f'=IF(B{row_idx}="SHORT", (E{row_idx}-H{row_idx})*G{row_idx}, (H{row_idx}-E{row_idx})*G{row_idx})'
        
        # Col J (Max Peak R-Multiple): Max PnL / Risk Dollar Amount
        formula_peak_r = f'=IF(ABS(E{row_idx}-F{row_idx})*G{row_idx}>0, I{row_idx}/(ABS(E{row_idx}-F{row_idx})*G{row_idx}), 0)'

        # Col K (1:2 Opportunity Status): Check if trade passed 1:2
        formula_status = f'=IF(J{row_idx}>=2.0, "1:2 Achieved Before SL", IF(J{row_idx}>=1.0, "Partial TP Available (>=1R)", "Direct SL / No Profit"))'

        row_values = [
            trade.get("symbol", "N/A"),
            direction,
            start_str,
            close_str,
            entry_price,
            sl_price,
            effective_qty,
            max_price_before_sl,
            formula_max_pnl,
            formula_peak_r,
            formula_status,
            net_pnl,
            reason
        ]
        
        ws.append(row_values)
        ws.row_dimensions[row_idx].height = 22

        for col_num in range(1, len(row_values) + 1):
            cell = ws.cell(row=row_idx, column=col_num)
            cell.border = THIN_BORDER
            cell.font = REGULAR_FONT

            if col_num in [1, 2, 3, 4, 11, 13]:
                cell.alignment = Alignment(horizontal="center", vertical="center")

            # Currency Formatting
            if col_num in [5, 6, 8, 9, 12]:
                cell.number_format = '$#,##0.00;($#,##0.00);"$0.00"'
                cell.alignment = Alignment(horizontal="right", vertical="center")

            # Column I: Peak PnL Highlighting
            if col_num == 9:
                cell.fill = PEAK_FILL
                cell.font = PEAK_FONT

            # Column J: Peak R-Multiple
            if col_num == 10:
                cell.number_format = '0.00"R"'
                cell.alignment = Alignment(horizontal="center", vertical="center")

            # Column K: Status Highlighting
            if col_num == 11:
                cell.fill = WARN_FILL
                cell.font = WARN_FONT

            # Column L: Actual Net PnL
            if col_num == 12:
                if net_pnl > 0:
                    cell.fill = PROFIT_FILL
                    cell.font = PROFIT_FONT
                elif net_pnl < 0:
                    cell.fill = LOSS_FILL
                    cell.font = LOSS_FONT

            # Column M: Close Reason Styling
            if col_num == 13:
                if "TP" in reason.upper() or net_pnl > 0:
                    cell.fill = PROFIT_FILL
                    cell.font = PROFIT_FONT
                elif "SL" in reason.upper() or net_pnl < 0:
                    cell.fill = LOSS_FILL
                    cell.font = LOSS_FONT

    for col in ws.columns:
        col_letter = get_column_letter(col[0].column)
        max_len = max(len(str(cell.value or '')) for cell in col)
        ws.column_dimensions[col_letter].width = max(max_len + 4, 15)

    wb.save(output_filename)
    print(f"\n[SUCCESS] Excel report successfully generated: {output_filename}")
    return output_filename


# ==========================================
# 4. MAIN RUNNER
# ==========================================

def main():
    print("--- Starting Live Binance Market Analysis (Start Time -> Current Time) ---")
    trades = fetch_trades_from_db()
    if trades:
        create_excel_report(trades)
    else:
        print("[WARNING] No trades found in database.")

if __name__ == "__main__":
    main()
