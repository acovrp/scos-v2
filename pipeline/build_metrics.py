# SCOS 2.0 Metrics Pre-Aggregator
# Location: C:\Users\User\Downloads\scos-v2\pipeline\build_metrics.py

import os
import json
import sqlite3
import datetime
from database import get_connection

metrics_json_path = r"C:\Users\User\Downloads\scos-v2\data\metrics.json"

def get_iso_week(date_str):
    # Format YYYY-MM-DD
    dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
    year, week, weekday = dt.isocalendar()
    return f"{year}-W{week:02d}"

def get_month(date_str):
    return date_str[:7] # YYYY-MM

def init_metrics_structure():
    return {
        "revenue": 0.0,
        "units": 0,
        "sessions": 0,
        "page_views": 0,
        "buybox_sum": 0.0,
        "buybox_count": 0,
        "ad_spend": 0.0,
        "ad_sales": 0.0,
        "clicks": 0,
        "impressions": 0
    }

def calculate_rates(m):
    # Calculate derived rate metrics safely
    m["acos"] = (m["ad_spend"] / m["ad_sales"] * 100.0) if m["ad_sales"] > 0 else 0.0
    m["tacos"] = (m["ad_spend"] / m["revenue"] * 100.0) if m["revenue"] > 0 else 0.0
    m["cvr"] = min(100.0, (m["units"] / m["sessions"] * 100.0)) if m["sessions"] > 0 else 0.0
    m["ctr"] = (m["clicks"] / m["impressions"] * 100.0) if m["impressions"] > 0 else 0.0
    m["buybox_pct"] = (m["buybox_sum"] / m["buybox_count"]) if m["buybox_count"] > 0 else None
    
    # Clean temporary sum fields
    if "buybox_sum" in m: del m["buybox_sum"]
    if "buybox_count" in m: del m["buybox_count"]
    
    # Safe Organic % calculation
    if m["revenue"] > 0:
        if m["ad_sales"] > m["revenue"] * 1.05:
            # Attribution anomaly — ad sales exceed revenue
            m["organic_pct"] = None # N/A
        else:
            m["organic_pct"] = max(0.0, (m["revenue"] - m["ad_sales"]) / m["revenue"] * 100.0)
    else:
        m["organic_pct"] = 100.0
        
    return m

def build_metrics():
    print("Building pre-aggregated metrics from SQLite DB...")
    conn = get_connection()
    cursor = conn.cursor()
    
    # 1. Load product catalog metadata
    cursor.execute("SELECT sku, category, line, name FROM products")
    products_metadata = {}
    for sku, cat, line, name in cursor.fetchall():
        products_metadata[sku] = {
            "category": cat,
            "line": line,
            "name": name
        }
        
    # 2. Fetch all daily sales records
    cursor.execute("SELECT date, sku, units, revenue, sessions, page_views, buybox_pct FROM daily_sales")
    sales_records = cursor.fetchall()
    
    # 3. Fetch all daily ads records
    cursor.execute("SELECT date, sku, ad_spend, ad_sales, clicks, impressions FROM daily_ads")
    ads_records = cursor.fetchall()
    
    conn.close()
    
    # Data storage structure
    # levels: portfolio, category, line, sku
    # periods: month, week
    raw_data = {
        "portfolio": {},
        "category": {},
        "line": {},
        "sku": {}
    }
    
    def add_metric(level, entity_key, period_key, metric_name, value):
        if entity_key not in raw_data[level]:
            raw_data[level][entity_key] = {}
        if period_key not in raw_data[level][entity_key]:
            raw_data[level][entity_key][period_key] = init_metrics_structure()
            
        raw_data[level][entity_key][period_key][metric_name] += value

    # Process sales
    for date, sku, units, revenue, sessions, page_views, bb in sales_records:
        meta = products_metadata.get(sku)
        if not meta:
            continue
            
        cat = meta["category"]
        line = meta["line"]
        
        periods = [get_month(date), get_iso_week(date)]
        
        for period in periods:
            for lvl, key in [("portfolio", "all"), ("category", cat), ("line", line), ("sku", sku)]:
                add_metric(lvl, key, period, "units", units)
                add_metric(lvl, key, period, "revenue", revenue)
                add_metric(lvl, key, period, "sessions", sessions)
                add_metric(lvl, key, period, "page_views", page_views)
                if bb is not None:
                    add_metric(lvl, key, period, "buybox_sum", bb)
                    add_metric(lvl, key, period, "buybox_count", 1)

    # Process ads
    for date, sku, spend, sales, clicks, impressions in ads_records:
        meta = products_metadata.get(sku)
        if not meta:
            continue
            
        cat = meta["category"]
        line = meta["line"]
        
        periods = [get_month(date), get_iso_week(date)]
        
        for period in periods:
            for lvl, key in [("portfolio", "all"), ("category", cat), ("line", line), ("sku", sku)]:
                add_metric(lvl, key, period, "ad_spend", spend)
                add_metric(lvl, key, period, "ad_sales", sales)
                add_metric(lvl, key, period, "clicks", clicks)
                add_metric(lvl, key, period, "impressions", impressions)

    # Calculate rates for all entities and periods
    aggregated_metrics = {
        "portfolio": {},
        "category": {},
        "line": {},
        "sku": {}
    }
    
    for lvl in raw_data:
        for entity in raw_data[lvl]:
            aggregated_metrics[lvl][entity] = {}
            for period in raw_data[lvl][entity]:
                metrics = raw_data[lvl][entity][period]
                aggregated_metrics[lvl][entity][period] = calculate_rates(metrics)
                
    # 4. Save in both JSON and JS format (JSON for APIs, JS for direct file:// load)
    os.makedirs(os.path.dirname(metrics_json_path), exist_ok=True)
    with open(metrics_json_path, 'w', encoding='utf-8') as f:
        json.dump(aggregated_metrics, f, indent=2)
        
    metrics_js_path = metrics_json_path.replace(".json", ".js")
    with open(metrics_js_path, 'w', encoding='utf-8') as f:
        f.write(f"const METRICS_DATA = {json.dumps(aggregated_metrics, indent=2)};")
        
    print(f"Pre-aggregated metrics written successfully to: {metrics_json_path} and {metrics_js_path}")
    print(f"Portfolio metrics count: {len(aggregated_metrics['portfolio'].get('all', {}))}")
    print(f"Categories computed: {list(aggregated_metrics['category'].keys())}")
    print(f"Product lines computed: {len(aggregated_metrics['line'])}")
    print(f"Variants computed: {len(aggregated_metrics['sku'])}")

if __name__ == "__main__":
    build_metrics()
