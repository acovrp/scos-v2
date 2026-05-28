import sqlite3
import json
import os

DB_PATH = r"C:\Users\User\Downloads\scos-v2\data\scos_core.db"
catalog_json_path = r"C:\Users\User\Downloads\scos-v2\data\catalog.json"

unmapped_asins = ['B0DZP8GXDV', 'B0GLNNJ51N', 'B0GQ9TRGRT', 'B0GYF7QZ8Q', 'B0FSTJ7FFJ', 'B0FSTCNH49', 'B0GVG2KQDX', 'B0GLNFQTY9', 'B0FR9CYKW6', 'B0FSTD9JDC', 'B0FR98QN94', 'B0FR98NSZ9', 'B0GVFH6X8X', 'B0FR97MMHL', 'B0FR96YX38']
unmapped_skus = ['SCORIG-78x72x6', 'SC-Fk-ORIG-D-72x48x5', 'SC-F-MFPILW-P-28x18', 'SC-PETBEDORTHO-M.Red-XL-52X28', 'SC-FK-CNC-BLK-SMALL', 'SC-F-SLSTPILWCS-C-52x20']

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

print("--- Database Check ---")
for asin in unmapped_asins:
    cursor.execute("SELECT sku, name, category, line, mrp, asin, fk_sku FROM products WHERE asin = ?", (asin,))
    r = cursor.fetchall()
    if r:
        print(f"ASIN {asin} found in DB: {r}")
    else:
        # Check if it appears in any column by loose query
        cursor.execute("SELECT sku, name, asin, fk_sku FROM products WHERE sku LIKE ? OR name LIKE ?", (f"%{asin}%", f"%{asin}%"))
        r2 = cursor.fetchall()
        if r2:
            print(f"ASIN {asin} loose match in DB: {r2}")

for sku in unmapped_skus:
    cursor.execute("SELECT sku, name, category, line, mrp, asin, fk_sku FROM products WHERE sku = ? OR fk_sku = ?", (sku, sku))
    r = cursor.fetchall()
    if r:
        print(f"SKU {sku} found in DB: {r}")
    else:
        cursor.execute("SELECT sku, name, asin, fk_sku FROM products WHERE sku LIKE ? OR name LIKE ? OR fk_sku LIKE ?", (f"%{sku}%", f"%{sku}%", f"%{sku}%"))
        r2 = cursor.fetchall()
        if r2:
            print(f"SKU {sku} loose match in DB: {r2}")

print("\n--- Catalog JSON Check ---")
if os.path.exists(catalog_json_path):
    with open(catalog_json_path, 'r', encoding='utf-8') as f:
        catalog = json.load(f)
    for asin in unmapped_asins:
        found = False
        for k, v in catalog.items():
            if v.get('asin') == asin:
                print(f"ASIN {asin} found in JSON: key={k}, val={v}")
                found = True
        if not found:
            pass
            
    for sku in unmapped_skus:
        found = False
        for k, v in catalog.items():
            if k == sku or v.get('fk_sku') == sku:
                print(f"SKU {sku} found in JSON: key={k}, val={v}")
                found = True

conn.close()
