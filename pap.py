import os
import mysql.connector

# =========================================================
# ⚙️ AIVEN MYSQL CONFIGURATION
# =========================================================
DB_HOST = "mysql-paper-trading-nomistorage3-d0bf.d.aivencloud.com"
DB_PORT = 13722
DB_USER = "avnadmin"
# 🔒 Database Password loaded securely from GitHub Secrets / Environment Variables
DB_PASS = os.getenv("PASS_DB_2")
DB_NAME = "defaultdb"


def get_db_connection():
    """MySQL Database Connection Helper"""
    if not DB_PASS:
        raise ValueError("❌ ERROR: 'PASS_DB_2' environment variable / secret not set!")

    return mysql.connector.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASS,
        database=DB_NAME,
        ssl_disabled=False  # Aiven SSL Required
    )

# =========================================================
# 1. DATABASE INIT & RESET FUNCTION
# =========================================================
def reset_and_recreate_db():
    print("⏳ Connecting to Aiven MySQL Database...")
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        print("✅ Connected Successfully!")

        print("\n🗑️ Dropping existing tables (if any)...")
        cursor.execute("SET FOREIGN_KEY_CHECKS = 0;")
        cursor.execute("DROP TABLE IF EXISTS trades;")
        cursor.execute("DROP TABLE IF EXISTS portfolio;")
        cursor.execute("SET FOREIGN_KEY_CHECKS = 1;")
        print("✅ Old tables deleted!")

        print("\n🏗️ Creating 'portfolio' table...")
        cursor.execute("""
        CREATE TABLE portfolio (
            id INT PRIMARY KEY,
            total_capital DOUBLE NOT NULL,
            available_capital DOUBLE NOT NULL,
            frozen_margin DOUBLE DEFAULT 0.0
        );
        """)

        cursor.execute("""
        INSERT INTO portfolio (id, total_capital, available_capital, frozen_margin)
        VALUES (1, 1000.0, 1000.0, 0.0);
        """)
        print("✅ Portfolio table created & $1000.00 Capital initialized!")

        print("\n🏗️ Creating 'trades' table...")
        cursor.execute("""
        CREATE TABLE trades (
            id INT AUTO_INCREMENT PRIMARY KEY,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            symbol VARCHAR(20) NOT NULL,
            direction VARCHAR(10) NOT NULL,
            entry_price DOUBLE NOT NULL,
            sl_price DOUBLE NOT NULL,
            tp1_price DOUBLE NOT NULL,
            tp2_price DOUBLE NOT NULL,
            margin_frozen DOUBLE NOT NULL,
            pos_value DOUBLE NOT NULL,
            coin_qty DOUBLE NOT NULL,
            leverage INT NOT NULL,
            status VARCHAR(20) DEFAULT 'ACTIVE',
            pnl DOUBLE DEFAULT 0.0
        );
        """)
        print("✅ Trades history table created!")

        conn.commit()
        
        cursor.execute("SELECT * FROM portfolio WHERE id = 1;")
        row = cursor.fetchone()
        print("\n" + "="*50)
        print(f"🎉 DATABASE RESET COMPLETE!")
        print(f"📊 Portfolio Balance: Total=${row[1]}, Available=${row[2]}, Frozen=${row[3]}")
        print("="*50)

    except mysql.connector.Error as err:
        print(f"\n❌ MySQL Setup Error: {err}")
    finally:
        if 'conn' in locals() and conn.is_connected():
            cursor.close()
            conn.close()
            print("🔌 Setup connection closed.")


# =========================================================
# 2. DIRECT TRADE SAVER (SCANNER BRIDGE WITH DUPLICATE CHECK)
# =========================================================
def save_all_signals_in_db(trade):
    """
    Directly receives trade object/dict from scanner script,
    checks if active trade for symbol already exists (skips if yes),
    and saves it to MySQL trades table instantly.
    """
    if not trade or trade.get('bias') not in ['LONG', 'SHORT']:
        return False

    conn = None
    cursor = None

    try:
        conn = get_db_connection()
        # 💡 FIX: Using buffered=True prevents 'Unread result found' errors
        cursor = conn.cursor(buffered=True)

        symbol = trade.get('symbol')

        # 🔍 1. DUPLICATE CHECK (Active Trade Filter)
        check_query = "SELECT id FROM trades WHERE symbol = %s AND status = 'ACTIVE'"
        cursor.execute(check_query, (symbol,))
        existing_trade = cursor.fetchone()

        if existing_trade:
            print(f"⏭️ [SKIPPED] Active trade already exists for {symbol} (DB ID: {existing_trade[0]})")
            return False

        # Extract values directly from trade dictionary
        direction = trade.get('bias')
        entry_price = trade.get('entry', 0.0)
        sl_price = trade.get('sl', 0.0)
        tp1_price = trade.get('tp1', 0.0)
        tp2_price = trade.get('tp2', 0.0)
        margin_frozen = trade.get('margin_usdt', 0.0)
        pos_value = trade.get('pos_size_usdt', 0.0)
        coin_qty = trade.get('coin_qty', 0.0)
        leverage = trade.get('leverage', 1)

        # 📥 2. INSERT NEW ACTIVE TRADE
        insert_query = """
            INSERT INTO trades (
                symbol, direction, entry_price, sl_price, tp1_price, tp2_price,
                margin_frozen, pos_value, coin_qty, leverage, status, pnl
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'ACTIVE', 0.0)
        """

        vals = (
            symbol, direction, entry_price, sl_price, tp1_price, 
            tp2_price, margin_frozen, pos_value, coin_qty, leverage
        )

        cursor.execute(insert_query, vals)
        conn.commit()
        print(f"✅ [DB SAVED] Successfully saved active trade for {symbol} ({direction}) | Qty: {coin_qty}")
        return True

    except Exception as err:
        print(f"❌ [DB SAVE ERROR] Failed to save trade for {trade.get('symbol')}: {err}")
        return False

    finally:
        # Guarantee close database resources regardless of success or error
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()



if __name__ == "__main__":
    # Script test ya schema reset ke liye run ki ja sakti hai
    pass
