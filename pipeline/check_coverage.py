# SCOS 2.0 Revenue Coverage Validator
# Location: C:\Users\User\Downloads\scos-v2\pipeline\check_coverage.py

import os
import sqlite3
import pandas as pd
from database import get_connection

br_csv_path = r"C:\Users\User\Downloads\pwa-push\data\br_history.csv"
fk_csv_path = r"C:\Users\User\Downloads\pwa-push\data\fk_history.csv"
preview_path = r"C:\Users\User\Downloads\scos-v2\data\coverage_check.txt"

def run_coverage_check():
    print("Running SCOS 2.0 revenue coverage audit...")
    
    # 1. Load mappings from SQLite Core Database
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT asin, fk_sku, fsn FROM products WHERE asin IS NOT NULL OR fk_sku IS NOT NULL")
    rows = cursor.fetchall()
    conn.close()
    
    mapped_asins = set(r[0] for r in rows if r[0])
    mapped_fk_skus = set(r[1] for r in rows if r[1])
    mapped_fsns = set(r[2] for r in rows if r[2])
    
    print(f"Loaded {len(mapped_asins)} ASINs and {len(mapped_fk_skus)} Flipkart SKUs from Database.")

    # 2. Check Amazon Coverage
    amz_total_rev = 0.0
    amz_mapped_rev = 0.0
    unmapped_amz = {}
    
    if os.path.exists(br_csv_path):
        df_br = pd.read_csv(br_csv_path)
        for _, row in df_br.iterrows():
            asin = str(row.get('asin')).strip()
            sales = float(row.get('ordered product sales') or 0.0)
            amz_total_rev += sales
            if asin in mapped_asins:
                amz_mapped_rev += sales
            else:
                unmapped_amz[asin] = unmapped_amz.get(asin, 0.0) + sales
    else:
        print(f"Warning: Amazon Business Report CSV not found at {br_csv_path}")

    amz_pct = (amz_mapped_rev / amz_total_rev * 100) if amz_total_rev > 0 else 100.0

    # 3. Check Flipkart Coverage
    fk_total_rev = 0.0
    fk_mapped_rev = 0.0
    unmapped_fk = {}
    
    if os.path.exists(fk_csv_path):
        df_fk = pd.read_csv(fk_csv_path)
        for _, row in df_fk.iterrows():
            sku = str(row.get('sku')).strip()
            oiv = float(row.get('oiv') or 0.0)
            fk_total_rev += oiv
            if sku in mapped_fk_skus:
                fk_mapped_rev += oiv
            else:
                unmapped_fk[sku] = unmapped_fk.get(sku, 0.0) + oiv
    else:
        print(f"Warning: Flipkart History CSV not found at {fk_csv_path}")

    fk_pct = (fk_mapped_rev / fk_total_rev * 100) if fk_total_rev > 0 else 100.0

    # 4. Overall Combined Coverage
    total_rev = amz_total_rev + fk_total_rev
    mapped_rev = amz_mapped_rev + fk_mapped_rev
    combined_pct = (mapped_rev / total_rev * 100) if total_rev > 0 else 100.0

    # Sort unmapped
    sorted_unmapped_amz = sorted(unmapped_amz.items(), key=lambda x: x[1], reverse=True)
    sorted_unmapped_fk = sorted(unmapped_fk.items(), key=lambda x: x[1], reverse=True)

    # 5. Output Report
    report_lines = []
    report_lines.append("=========================================")
    report_lines.append("SCOS 2.0 REVENUE COVERAGE AUDIT")
    report_lines.append("=========================================")
    report_lines.append(f"Amazon Revenue Coverage:   {amz_pct:.2f}% (Mapped: Rs {amz_mapped_rev:,.2f} / Total: Rs {amz_total_rev:,.2f})")
    report_lines.append(f"Flipkart Revenue Coverage: {fk_pct:.2f}% (Mapped: Rs {fk_mapped_rev:,.2f} / Total: Rs {fk_total_rev:,.2f})")
    report_lines.append(f"Combined Revenue Coverage: {combined_pct:.2f}% (Mapped: Rs {mapped_rev:,.2f} / Total: Rs {total_rev:,.2f})")
    
    status_msg = "PASS" if combined_pct >= 98.0 else "WARNING: UNDER 98% COVERAGE"
    report_lines.append(f"Audit Status:              {status_msg}")
    report_lines.append("=========================================\n")

    if sorted_unmapped_amz:
        report_lines.append("Top Unmapped Amazon ASINs by Revenue:")
        report_lines.append("-" * 45)
        for asin, sales in sorted_unmapped_amz[:15]:
            report_lines.append(f"  ASIN: {asin:12} | Unmapped Sales: Rs {sales:,.2f}")
        report_lines.append("")

    if sorted_unmapped_fk:
        report_lines.append("Top Unmapped Flipkart SKUs by Revenue:")
        report_lines.append("-" * 45)
        for sku, sales in sorted_unmapped_fk[:15]:
            report_lines.append(f"  SKU: {sku:24} | Unmapped Sales: Rs {sales:,.2f}")
        report_lines.append("")

    report_content = "\n".join(report_lines)
    print(report_content)

    os.makedirs(os.path.dirname(preview_path), exist_ok=True)
    with open(preview_path, 'w', encoding='utf-8') as f:
        f.write(report_content)
    print(f"\nReport written to: {preview_path}")

if __name__ == "__main__":
    run_coverage_check()
