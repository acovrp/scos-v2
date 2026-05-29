# pipeline/build_targets_db.py
# Ingestion pipeline for annual operating plan (AOP) monthly targets into SQLite

import os
import sqlite3
import pandas as pd
import re
import sys

# Configure stdout encoding to prevent Windows terminal printing issues
sys.stdout.reconfigure(encoding='utf-8')

DB_PATH = r"C:\Users\User\Downloads\scos-v2\data\scos_core.db"

MAP_TARGET_PRODUCT_TO_ID = {
    'ohayo bed': 'mattressprot',
    'reversible comforter': 'comforterdb',
    '200 tc percale fitted bedsheet set': 'bedsheetset',
    '300 tc sateen fitted bedsheet': 'bedsheetset',
    'reversible summer comforter': 'comforterdb',
    'printed comforter': 'comforterdb',
    'luxe comforter': 'comforterdb',
    'winter reversible comforter': 'comforterdb',
    'summer luxe comforter': 'comforterdb',
    'jersey fitted sheets': 'bedsheetset',
    'weighted blanket': 'comforterdb',
    '200 tc percale pillow cases': 'bedsheetset',
    '300 tc sateen pillow cases': 'bedsheetset',
    'satin pillowcases': 'bedsheetset',
    'jersey pillow cases': 'bedsheetset',
    '200 tc percale duvet cover': 'bedsheetset',
    '300 tc sateen duvet cover': 'bedsheetset',
    'mattress cover': 'mattressprot',
    'memory foam mattress topper 2 inch': 'memoryfoamma',
    'mattress protector': 'mattressprot',
    'memory foam mattress topper 1 inch': 'memoryfoamma',
    'quilted mattress protector': 'mattressprot',
    'aeroflow foam mattress topper': 'memoryfoamma',
    'lumbar seat cushion': 'mattressprot',
    'slim seat cushion': 'mattressprot',
    'pro back cushion': 'mattressprot',
    'pro neck cushion': 'mattressprot',
    'pro seat cushion': 'mattressprot',
    'slim back cushion': 'mattressprot',
    'original mattress': 'originalmatt',
    'hybrid latex mattress': 'hybridlatexm',
    'the latex ortho mattress': 'latexorthom',
    'tri fold mattress': 'trifoldmattr',
    'ultima memory foam mattress': 'ultimamattre',
    'ultima natural latex mattress': 'ultimamatla',
    'cloud mattress': 'cloudspring',
    'baby mattress': 'originalmatt',
    'memory foam slim pillow': 'softtouchmem',
    'dog bed ortho': 'mattressprot',
    'dog bed original': 'mattressprot',
    'softtouch memory foam pillow': 'softtouchmem',
    'cloud pillow': 'cloudpillows',
    'cuddle pillow': 'cuddlepillow',
    'contour softtouch memory foam pillow': 'cervicalbamb',
    'fiber lite pillow': 'sleepycatlit',
    'hybrid pillow': 'mfpillowbamb',
    'microfiber slim pillow': 'sleepycatlit',
    'cooltec memory foam pillow': 'cervicalbamb',
    'small softtouch memory foam pillow': 'softtouchmem',
    'softtouch contour latex': 'mfpillowbamb',
    'softtouch standard latex': 'mfpillowbamb',
    'marshmallow pillow': 'mfpillowbamb',
    'wedge pillow': 'mfpillowbamb',
    'contour cooltec memory foam pillow': 'cervicalbamb',
    'dual comfort pillow': 'mfpillowbamb',
    'travel neck pillow': 'mfpillowbamb',
    'grid pillow': 'cloudpillows',
    'seika recliner': 'mattressprot'
}

def clean_and_normalize(name):
    n = str(name).lower()
    n = re.sub(r'[^a-z0-9]+', ' ', n)
    return ' '.join(n.split()).strip()

def ingest_channel_targets():
    print("Ingesting channel-level targets...")
    path = r"C:\Users\User\Downloads\AOP Data Latest with marketplace warehouse.xlsx"
    df = pd.read_excel(path, sheet_name="Sales 26-27", header=None)
    
    # Months are listed from March back to April
    months = ['mar', 'feb', 'jan', 'dec', 'nov', 'oct', 'sep', 'aug', 'jul', 'jun', 'may', 'apr']
    month_offsets = {month: idx for idx, month in enumerate(months)}
    
    channels = {
        'website': 2,
        'amazon': 16,
        'flipkart': 30
    }
    
    rows_of_interest = {
        'net_revenue': 4,
        'gross_revenue': 6,
        'mattress_units': 14,
        'accessory_units': 15
    }
    
    records = []
    
    for ch_name, start_col in channels.items():
        for month in months:
            offset = month_offsets[month]
            col_idx = start_col + offset
            
            row_data = {}
            for metric, row_idx in rows_of_interest.items():
                val = df.iloc[row_idx, col_idx]
                if pd.isna(val):
                    val = 0.0
                else:
                    val = float(val)
                row_data[metric] = val
            
            # Back out Lakhs to pure Rupees for revenues
            net_revenue_rs = row_data['net_revenue'] * 100000.0
            gross_revenue_rs = row_data['gross_revenue'] * 100000.0
            matt_units = int(round(row_data['mattress_units']))
            acc_units = int(round(row_data['accessory_units']))
            
            records.append((
                '2026-27',
                month,
                ch_name,
                net_revenue_rs,
                gross_revenue_rs,
                matt_units,
                acc_units
            ))
            
    # Connect and save
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM targets_channel_monthly WHERE year = '2026-27'")
    cursor.executemany("""
    INSERT INTO targets_channel_monthly (year, month, channel, net_revenue, gross_revenue, mattress_units, accessory_units)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, records)
    conn.commit()
    conn.close()
    print(f"Successfully ingested {len(records)} channel target records.")

def ingest_product_targets():
    print("Ingesting Amazon product targets...")
    path = r"C:\Users\User\Downloads\Amazon_AOP_FY2627_Targets.xlsx"
    df = pd.read_excel(path, sheet_name="Pivot Data")
    
    months_columns = ["Apr'26", "May'26", "Jun'26", "Jul'26", "Aug'26", "Sep'26", "Oct'26", "Nov'26", "Dec'26", "Jan'27", "Feb'27", "Mar'27"]
    
    # Pre-populate aggregated product monthly targets
    # product_id -> month_short -> total_revenue (already in pure Rupees)
    aggregated = {}
    
    for _, row in df.iterrows():
        raw_name = row['Product']
        norm_name = clean_and_normalize(raw_name)
        pid = MAP_TARGET_PRODUCT_TO_ID.get(norm_name)
        if not pid:
            print(f"Skipping unmapped product target: {raw_name}")
            continue
            
        if pid not in aggregated:
            aggregated[pid] = {m.split("'")[0].lower(): 0.0 for m in months_columns}
            
        for m_col in months_columns:
            val = row[m_col]
            if pd.isna(val):
                val = 0.0
            else:
                val = float(val)
            month_short = m_col.split("'")[0].lower()
            aggregated[pid][month_short] += val
            
    records = []
    for pid, month_vals in aggregated.items():
        for month, revenue in month_vals.items():
            records.append((
                '2026-27',
                month,
                'amazon',
                pid,
                revenue
            ))
            
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM targets_product_monthly WHERE year = '2026-27'")
    cursor.executemany("""
    INSERT INTO targets_product_monthly (year, month, channel, product_id, revenue)
    VALUES (?, ?, ?, ?, ?)
    """, records)
    conn.commit()
    conn.close()
    print(f"Successfully ingested {len(records)} product target records.")

if __name__ == "__main__":
    ingest_channel_targets()
    ingest_product_targets()
    print("All targets ingestion finished successfully.")
