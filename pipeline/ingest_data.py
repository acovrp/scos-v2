# SCOS 2.0 Daily Ingestion Pipeline
# Location: C:\Users\User\Downloads\scos-v2\pipeline\ingest_data.py

import os
import sqlite3
import pandas as pd
from database import get_connection

br_csv_path = r"C:\Users\User\Downloads\pwa-push\data\br_history.csv"
fk_csv_path = r"C:\Users\User\Downloads\pwa-push\data\fk_history.csv"
ads_csv_path = r"C:\Users\User\Downloads\pwa-push\data\ads_daily.csv"

def clean_str(val):
    if val is None:
        return None
    s = str(val).strip()
    if s in ('#N/A', 'None', 'none', 'null', 'NULL', ''):
        return None
    return s

def ingest_sales():
    print("Ingesting Amazon & Flipkart Sales data into SQLite core...")
    conn = get_connection()
    cursor = conn.cursor()
    
    # 1. Load products mapping from DB
    cursor.execute("SELECT sku, asin, fk_sku FROM products")
    rows = cursor.fetchall()
    
    asin_to_sku = {}
    fk_to_sku = {}
    
    for master_sku, asin, fk_sku in rows:
        if asin:
            asin_to_sku[asin] = master_sku
        if fk_sku:
            fk_to_sku[fk_sku] = master_sku
            
    # Clear old daily sales to avoid duplicates
    cursor.execute("DELETE FROM daily_sales")
    
    # 2. Parse Amazon Business Report
    if os.path.exists(br_csv_path):
        print(f"Reading Amazon sales from {br_csv_path}...")
        df_br = pd.read_csv(br_csv_path)
        
        # Columns: ['asin', 'date', 'sessions', 'units ordered', 'ordered product sales', 'page views', 'buy box percentage']
        br_rows = []
        for _, row in df_br.iterrows():
            asin = clean_str(row.get('asin'))
            date_raw = clean_str(row.get('date'))
            if not asin or not date_raw:
                continue
                
            master_sku = asin_to_sku.get(asin)
            if not master_sku:
                continue # Skip unmapped ASIN
                
            # Date formatting (ensure YYYY-MM-DD)
            try:
                date = pd.to_datetime(date_raw).strftime('%Y-%m-%d')
            except Exception:
                continue
                
            units = int(row.get('units ordered') or 0)
            revenue = float(row.get('ordered product sales') or 0.0)
            sessions = int(row.get('sessions') or 0)
            page_views = int(row.get('page views') or 0)
            
            bb_raw = row.get('buy box percentage')
            try:
                # Remove % if present and parse
                bb = float(str(bb_raw).replace('%', '').strip()) if bb_raw is not None else None
            except Exception:
                bb = None
                
            br_rows.append((date, master_sku, 'amazon', units, revenue, sessions, page_views, bb))
            
        if br_rows:
            cursor.executemany("""
                INSERT OR REPLACE INTO daily_sales (date, sku, channel, units, revenue, sessions, page_views, buybox_pct)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, br_rows)
            print(f"Successfully ingested {len(br_rows)} Amazon daily sales rows.")
            
    # 3. Parse Flipkart History
    if os.path.exists(fk_csv_path):
        print(f"Reading Flipkart sales from {fk_csv_path}...")
        df_fk = pd.read_csv(fk_csv_path)
        
        # Columns: ['date', 'sku', 'asin', 'product', 'category', 'units', 'listing_price', 'clf', 'oiv', 'customer_price']
        fk_rows = []
        for _, row in df_fk.iterrows():
            fk_sku = clean_str(row.get('sku'))
            date_raw = clean_str(row.get('date'))
            if not fk_sku or not date_raw:
                continue
                
            master_sku = fk_to_sku.get(fk_sku)
            if not master_sku:
                continue # Skip unmapped SKU
                
            try:
                date = pd.to_datetime(date_raw).strftime('%Y-%m-%d')
            except Exception:
                continue
                
            units = int(row.get('units') or 0)
            revenue = float(row.get('oiv') or 0.0) # gross gross revenue = oiv
            
            # Flipkart doesn't expose sessions/PV/BB in order reports
            fk_rows.append((date, master_sku, 'flipkart', units, revenue, 0, 0, None))
            
        if fk_rows:
            cursor.executemany("""
                INSERT OR REPLACE INTO daily_sales (date, sku, channel, units, revenue, sessions, page_views, buybox_pct)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, fk_rows)
            print(f"Successfully ingested {len(fk_rows)} Flipkart daily sales rows.")
            
    conn.commit()
    conn.close()

def ingest_ads():
    print("Ingesting daily ad spend data...")
    if not os.path.exists(ads_csv_path):
        print(f"Ad spend CSV not found at {ads_csv_path} — skipping.")
        return
        
    conn = get_connection()
    cursor = conn.cursor()
    
    # 1. Load products mapping
    cursor.execute("SELECT sku, asin FROM products WHERE asin IS NOT NULL")
    rows = cursor.fetchall()
    asin_to_sku = {asin: sku for sku, asin in rows}
    
    cursor.execute("DELETE FROM daily_ads")
    
    df_ads = pd.read_csv(ads_csv_path)
    
    # Columns: ['date', 'ad_type', 'asin', 'sku', 'impressions', 'clicks', 'spend', 'sales', 'orders', 'units']
    ads_rows = []
    
    # Group by (date, asin) to aggregate different ad types (SP, SB, SD)
    grouped = df_ads.groupby(['date', 'asin']).agg({
        'impressions': 'sum',
        'clicks': 'sum',
        'spend': 'sum',
        'sales': 'sum'
    }).reset_index()
    
    for _, row in grouped.iterrows():
        asin = clean_str(row.get('asin'))
        date_raw = clean_str(row.get('date'))
        if not asin or not date_raw:
            continue
            
        master_sku = asin_to_sku.get(asin)
        if not master_sku:
            continue
            
        try:
            date = pd.to_datetime(date_raw).strftime('%Y-%m-%d')
        except Exception:
            continue
            
        spend = float(row.get('spend') or 0.0)
        sales = float(row.get('sales') or 0.0)
        clicks = int(row.get('clicks') or 0)
        impressions = int(row.get('impressions') or 0)
        
        ads_rows.append((date, master_sku, 'amazon', spend, sales, clicks, impressions))
        
    if ads_rows:
        cursor.executemany("""
            INSERT OR REPLACE INTO daily_ads (date, sku, channel, ad_spend, ad_sales, clicks, impressions)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, ads_rows)
        print(f"Successfully ingested {len(ads_rows)} daily ad spend rows.")
        
    conn.commit()
    conn.close()

if __name__ == "__main__":
    ingest_sales()
    ingest_ads()
