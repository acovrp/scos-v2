# SCOS 2.0 Database Core Layer
# Location: C:\Users\User\Downloads\scos-v2\pipeline\database.py

import os
import sqlite3

DB_PATH = r"C:\Users\User\Downloads\scos-v2\data\scos_core.db"

def get_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    # 1. Products Master Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS products (
        sku TEXT PRIMARY KEY,       -- Master SKU (canonical variant identifier)
        asin TEXT,                  -- Amazon ASIN
        fk_sku TEXT,                -- Flipkart SKU
        fsn TEXT,                   -- Flipkart FSN
        name TEXT NOT NULL,         -- Product display name
        category TEXT NOT NULL,     -- Category (Mattress, Pillow, Bedding, Topper, Furniture, Other)
        line TEXT NOT NULL,         -- UI parent product line (e.g. original, hybridla)
        mrp REAL,                   -- Maximum Retail Price
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        active INTEGER DEFAULT 1
    )
    """)
    
    # 2. Daily Sales Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS daily_sales (
        date TEXT NOT NULL,         -- YYYY-MM-DD
        sku TEXT NOT NULL,          -- Master SKU
        channel TEXT NOT NULL,      -- 'amazon', 'flipkart', 'quick_commerce'
        units INTEGER DEFAULT 0,
        revenue REAL DEFAULT 0.0,
        sessions INTEGER DEFAULT 0,
        page_views INTEGER DEFAULT 0,
        buybox_pct REAL,
        PRIMARY KEY (date, sku, channel),
        FOREIGN KEY (sku) REFERENCES products (sku)
    )
    """)
    
    # 3. Daily Ads Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS daily_ads (
        date TEXT NOT NULL,         -- YYYY-MM-DD
        sku TEXT NOT NULL,          -- Master SKU
        channel TEXT NOT NULL,      -- 'amazon', 'flipkart'
        ad_spend REAL DEFAULT 0.0,
        ad_sales REAL DEFAULT 0.0,
        clicks INTEGER DEFAULT 0,
        impressions INTEGER DEFAULT 0,
        PRIMARY KEY (date, sku, channel),
        FOREIGN KEY (sku) REFERENCES products (sku)
    )
    """)
    
    # 4. Daily Inventory Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS daily_inventory (
        date TEXT NOT NULL,         -- YYYY-MM-DD
        sku TEXT NOT NULL,          -- Master SKU
        channel TEXT NOT NULL,      -- 'amazon', 'flipkart', 'blinkit', 'zepto', 'instamart'
        stock_level INTEGER DEFAULT 0,
        sales_velocity_30d REAL DEFAULT 0.0,
        PRIMARY KEY (date, sku, channel),
        FOREIGN KEY (sku) REFERENCES products (sku)
    )
    """)
    
    # Indexes
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sales_date ON daily_sales (date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sales_sku ON daily_sales (sku)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ads_date ON daily_ads (date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ads_sku ON daily_ads (sku)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_asin ON products (asin)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_fk_sku ON products (fk_sku)")
    
    conn.commit()
    conn.close()
    print("Database tables initialized successfully.")

if __name__ == "__main__":
    init_db()
