import os
from datetime import datetime
import requests
import mysql.connector
from mysql.connector import Error
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# ==========================================
# 1. DATABASE CONFIGURATION & DATA FETCHING
# ==========================================

def get_db_connection():
    """Database connection establish karta hai env variables se."""
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
    """Database se trades ka raw data fetch karta hai."""
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
                    tp2_price,
                    coin_qty,
                    pos_value,
                    leverage,
                    timestamp AS start_time,
                    COALESCE(updated_at, timestamp) AS close_time,
                    COALESCE(exit_reason, status, 'N/A') AS close_reason,
                    CASE 
                        WHEN tp_rrr_10_hit = 1 THEN 0.10
                        WHEN tp_rrr_05_hit = 1 THEN 0.05
                        WHEN tp_rrr_02_hit = 1 THEN 0.02
                        WHEN tp_050_hit = 1 THEN 0.05
                        WHEN tp_020_hit = 1 THEN 0.02
                        ELSE 0.00
                    END AS max_floating_profit_pct,
                    COALESCE(pnl, 0.0) AS net_profit
                FROM trades
                ORDER BY timestamp DESC
            """
            cursor.execute(query)
            trades = cursor.fetchall()
            print(f"[INFO] Successfully fetched {len(trades)} trades from database.")
            cursor.close()

        except Error as e:
            print(f"\n[ERROR] Query Execution Failed: {e}")
            trades = []

        finally:
            if connection.is_connected():
                connection.close()
    else:
        print("[WARNING] DB connection unavailable.")

    return trades

# ==========================================
# 2. EXCEL REPORT GENERATION WITH NEW COLUMNS
# ==========================================

def create_excel_report(trades_data, output_filename="Crypto_Trade_Report.xlsx"):
    """Excel sheet mein dynamic formulas ke sath naye columns add karta hai."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Trade Breakdown"
    ws.views.sheetView[0].showGridLines = True

    # Styling Colors
    HEADER_FILL = PatternFill(start_color="1E293B", end_color="1E293B", fill_type="solid") # Dark Slate
    HEADER_FONT = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
    
    PROFIT_FILL = PatternFill(start_color="D1FAE5", end_color="D1FAE5", fill_type="solid") # Soft Green
    PROFIT_FONT = Font(name="Segoe UI", size=10, color="065F46", bold=True)
    
    LOSS_FILL = PatternFill(start_color="FEE2E2", end_color="FEE2E2", fill_type="solid") # Soft Red
    LOSS_FONT = Font(name="Segoe UI", size=10, color="991B1B", bold=True)
    
    PEAK_FILL = PatternFill(start_color="FEF3C7", end_color="FEF3C7", fill_type="solid") # Soft Amber/Gold
    PEAK_FONT = Font(name="Segoe UI", size=10, color="92400E", bold=True)

    RR_FILL = PatternFill(start_color="E0F2FE", end_color="E0F2FE", fill_type="solid") # Soft Blue
    RR_FONT = Font(name="Segoe UI", size=10, color="0369A1", bold=True)

    REGULAR_FONT = Font(name="Segoe UI", size=10, color="1F2937")

    THIN_BORDER = Border(
        left=Side(style='thin', color='E5E7EB'),
        right=Side(style='thin', color='E5E7EB'),
        top=Side(style='thin', color='E5E7EB'),
        bottom=Side(style='thin', color='E5E7EB')
    )

    # Updated Column Headers (Explicitly showing Peak PnL, Peak R, and 1:2 Condition)
    headers = [
        "Pair",                   # Col A
        "Direction",              # Col B
        "Start Time",             # Col C
        "Close Time",             # Col D
        "Entry Price ($)",        # Col E
        "SL Price ($)",           # Col F
        "Quantity",               # Col G
        "Max Peak Price ($)",     # Col H (NEW)
        "Max Peak Floating PnL",  # Col I (NEW - Formula)
        "Max Peak R-Multiple",    # Col J (NEW - Formula)
        "Target 1:2 PnL ($)",     # Col K (NEW - Formula)
        "1:2 Condition Met?",     # Col L (NEW - Formula)
        "Actual Net PnL ($)",     # Col M
        "Close Reason"            # Col N
    ]
    
    ws.append(headers)
    
    # Format Header Row
    for col_num, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_num)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = THIN_BORDER
    ws.row_dimensions[1].height = 28

    # Populate Rows & Append Dynamic Excel Formulas
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
        max_float_pct = float(trade.get("max_floating_profit_pct", 0.0))
        net_pnl = float(trade.get("net_profit", 0.0))
        reason = str(trade.get("close_reason", "N/A"))

        # Effective Quantity Calculation
        effective_qty = coin_qty
        if effective_qty == 0 and pos_value > 0 and entry_price > 0:
            effective_qty = pos_value / entry_price

        # Calculate Max Peak Price reached before SL
        if direction == "SHORT":
            max_peak_price = entry_price * (1.0 - max_float_pct) if max_float_pct > 0 else entry_price
        else:
            max_peak_price = entry_price * (1.0 + max_float_pct) if max_float_pct > 0 else entry_price

        # --- EXCEL DYNAMIC FORMULAS ---
        # Col I (Max Peak PnL): Long -> (Peak - Entry)*Qty | Short -> (Entry - Peak)*Qty
        formula_peak_pnl = f'=IF(B{row_idx}="SHORT", (E{row_idx}-H{row_idx})*G{row_idx}, (H{row_idx}-E{row_idx})*G{row_idx})'
        
        # Col J (Max Peak R-Multiple): Peak PnL / Risk Dollar Amount
        formula_peak_r = f'=IF(ABS(E{row_idx}-F{row_idx})*G{row_idx}>0, I{row_idx}/(ABS(E{row_idx}-F{row_idx})*G{row_idx}), 0)'

        # Col K (Target 1:2 PnL): Risk Amount * 2
        formula_1_2_pnl = f'=(ABS(E{row_idx}-F{row_idx})*G{row_idx})*2'

        # Col L (Condition Met): Checks if Peak R reached >= 2.0
        formula_condition = f'=IF(J{row_idx}>=2.0, "1:2 Achieved", "Failed 1:2 (SL Hit)")'

        row_values = [
            trade.get("symbol", "N/A"), # Col A
            direction,                   # Col B
            start_str,                   # Col C
            close_str,                   # Col D
            entry_price,                 # Col E
            sl_price,                    # Col F
            effective_qty,               # Col G
            max_peak_price,              # Col H
            formula_peak_pnl,            # Col I (FORMULA)
            formula_peak_r,              # Col J (FORMULA)
            formula_1_2_pnl,             # Col K (FORMULA)
            formula_condition,           # Col L (FORMULA)
            net_pnl,                     # Col M
            reason                       # Col N
        ]
        
        ws.append(row_values)
        ws.row_dimensions[row_idx].height = 22

        # Cell Styling & Formatting
        for col_num in range(1, len(row_values) + 1):
            cell = ws.cell(row=row_idx, column=col_num)
            cell.border = THIN_BORDER
            cell.font = REGULAR_FONT
            cell.alignment = Alignment(vertical="center")

            # Center alignment for general info
            if col_num in [1, 2, 3, 4, 12, 14]:
                cell.alignment = Alignment(horizontal="center", vertical="center")

            # Currency Formatting for Prices & PnL
            if col_num in [5, 6, 8, 9, 11, 13]:
                cell.number_format = '$#,##0.00;($#,##0.00);"$0.00"'
                cell.alignment = Alignment(horizontal="right", vertical="center")

            # Column I: Peak PnL Highlighting
            if col_num == 9:
                cell.fill = PEAK_FILL
                cell.font = PEAK_FONT

            # Column J: R-Multiple Formatting
            if col_num == 10:
                cell.number_format = '0.00"R"'
                cell.alignment = Alignment(horizontal="center", vertical="center")

            # Column K: Target 1:2 PnL Highlighting
            if col_num == 11:
                cell.fill = RR_FILL
                cell.font = RR_FONT

            # Column M: Net PnL Colors
            if col_num == 13:
                if net_pnl > 0:
                    cell.fill = PROFIT_FILL
                    cell.font = PROFIT_FONT
                elif net_pnl < 0:
                    cell.fill = LOSS_FILL
                    cell.font = LOSS_FONT

            # Column N: Close Reason Styling
            if col_num == 14:
                if "TP" in reason.upper() or net_pnl > 0:
                    cell.fill = PROFIT_FILL
                    cell.font = PROFIT_FONT
                elif "SL" in reason.upper() or net_pnl < 0:
                    cell.fill = LOSS_FILL
                    cell.font = LOSS_FONT

    # Adjust Column Auto-Widths
    for col in ws.columns:
        col_letter = get_column_letter(col[0].column)
        max_len = max(len(str(cell.value or '')) for cell in col)
        ws.column_dimensions[col_letter].width = max(max_len + 4, 15)

    wb.save(output_filename)
    print(f"[SUCCESS] Updated report with new dynamic Excel columns saved to: {output_filename}")
    return output_filename

# ==========================================
# 3. NTFY NOTIFICATION ALERT
# ==========================================

def send_ntfy_notification(total_trades, net_pnl):
    """Execution update ntfy topic par push karta hai."""
    ntfy_topic = os.getenv("NTFY_TOPIC")
    if not ntfy_topic:
        print("[INFO] NTFY_TOPIC not configured. Skipping notification.")
        return

    pnl_symbol = "🟢 +" if net_pnl >= 0 else "🔴 "
    message = f"Analyzed {total_trades} trades breakdown.\nTotal PnL: {pnl_symbol}${net_pnl:.2f}\nNew Excel Report Generated."
    
    try:
        requests.post(
            f"https://ntfy.sh/{ntfy_topic}",
            data=message.encode('utf-8'),
            headers={
                "Title": "Trade Breakdown Updated",
                "Priority": "default",
                "Tags": "chart_with_upwards_trend,file_folder"
            },
            timeout=10
        )
        print("[INFO] Notification sent to ntfy.")
    except Exception as e:
        print(f"[ERROR] Failed to send ntfy notification: {e}")

# ==========================================
# 4. MAIN RUNNER
# ==========================================

def main():
    print("--- Starting Updated Trade Analysis Breakdown ---")
    trades = fetch_trades_from_db()
    
    if trades:
        report_file = create_excel_report(trades)
        total_pnl = sum(float(t.get("net_profit", 0.0)) for t in trades)
        send_ntfy_notification(len(trades), total_pnl)
    else:
        print("[WARNING] No trades found in database.")

if __name__ == "__main__":
    main()
