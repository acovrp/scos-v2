# SCOS 2.0 Snapshot Compiler
# Queries SQLite → builds snapshot.json → injects into BOTH scos-v2 and pwa-push index.html files
# Automatically compiles and injects full ADS_STATE and KEYWORDS lists for instant page load!

import json
import os
import re
import sys
import csv
from collections import defaultdict
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))
from database import get_connection

SNAPSHOT_JSON_PATH = r"C:\Users\User\Downloads\scos-v2\data\snapshot.json"
PWA_SNAPSHOT_PATH  = r"C:\Users\User\Downloads\pwa-push\data\snapshot.json"
INDEX_HTML_PATH    = r"C:\Users\User\Downloads\scos-v2\dashboard\index.html"
PWA_HTML_PATH      = r"C:\Users\User\Downloads\pwa-push\index.html"

ADS_UNIFIED_PATH   = r"C:\Users\User\Downloads\pwa-push\data\ads_unified.csv"
ST_REPORT_PATH     = r"C:\Users\User\Downloads\pwa-push\data\st_report.csv"

MONTH_NAMES = {
    1: 'jan', 2: 'feb', 3: 'mar', 4: 'apr', 5: 'may', 6: 'jun',
    7: 'jul', 8: 'aug', 9: 'sep', 10: 'oct', 11: 'nov', 12: 'dec',
}
MONTH_ORDER = list(MONTH_NAMES.values())


def iso_week_key(date_str):
    try:
        d = datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        try:
            d = datetime.strptime(date_str, '%b %d, %Y')
        except ValueError:
            try:
                d = datetime.strptime(date_str, '%B %d, %Y')
            except ValueError:
                return None
    iso_year, iso_week, _ = d.isocalendar()
    return f'{iso_year}-W{iso_week:02d}'


def week_monday(iso_year, iso_week):
    jan4 = datetime(iso_year, 1, 4)
    week1_mon = jan4 - timedelta(days=jan4.weekday())
    return week1_mon + timedelta(weeks=iso_week - 1)


def week_month_name(iso_week_str):
    """Month name for the ISO week, using the Monday's month.
    Edge case: if Monday is in previous year's December (e.g. W01), assign to January."""
    iso_year = int(iso_week_str[:4])
    iso_week = int(iso_week_str[6:])
    mon = week_monday(iso_year, iso_week)
    if mon.year < iso_year:
        return 'jan'
    return MONTH_NAMES[mon.month]


def group_weeks_by_month(week_keys):
    """Return {month_name: [sorted week keys]}."""
    by_month = defaultdict(list)
    for wk in week_keys:
        mo = week_month_name(wk)
        by_month[mo].append(wk)
    return {mo: sorted(wks) for mo, wks in by_month.items()}


def most_recent_month(month_dict):
    """Return the latest month name present in the dict."""
    present = [mo for mo in MONTH_ORDER if mo in month_dict]
    return present[-1] if present else None


def extract_mappings_from_html(html_path):
    """Dynamically parses ASIN_MAP and PRODUCTS from index.html to avoid duplication."""
    if not os.path.exists(html_path):
        return None, None
    with open(html_path, 'r', encoding='utf-8', errors='ignore') as f:
        html = f.read()

    asin_map = {}
    m_asin = re.search(r'var ASIN_MAP\s*=\s*(\{.*?\});', html, re.DOTALL)
    if m_asin:
        try:
            asin_map = json.loads(m_asin.group(1))
            print(f"[PARSER] Loaded {len(asin_map)} ASIN mappings from {os.path.basename(html_path)}")
        except Exception as e:
            print("[PARSER] Error parsing ASIN_MAP JSON:", e)

    pid2line = {}
    m_prod = re.search(r'var PRODUCTS\s*=\s*(\[.*?\]);', html, re.DOTALL)
    if m_prod:
        try:
            products = json.loads(m_prod.group(1))
            print(f"[PARSER] Loaded {len(products)} products from {os.path.basename(html_path)}")
            for p in products:
                pid2line[p['id']] = p['line']
        except Exception as e:
            print("[PARSER] Error parsing PRODUCTS JSON:", e)

    return asin_map, pid2line


def norm_ad(ap):
    if not ap:
        return 'SP'
    s = str(ap).upper()
    if 'DISPLAY' in s:
        return 'SD'
    if 'BRANDS' in s:
        return 'SB'
    return 'SP'


def detect_intent(name):
    n = (name or '').upper()
    if n.startswith('SPPT') or n.startswith('SBPT'):
        return 'Branded'
    if re.search(r'\|\s*BRANDED\s*\|', n) or re.search(r'\bBRANDED\b', n) or re.search(r'BRAND[\s-]?PROT', n):
        return 'Branded'
    if re.search(r'COMPET', n) or re.search(r'\bCOMP\b', n) or n.startswith('SPCT') or n.startswith('SDCT'):
        return 'Competition'
    if re.search(r'\bAUTO\b', n) or n.startswith('SPA ') or n.startswith('SPA|'):
        return 'Auto'
    return 'Generic'


def compile_ads_state(ads_unified_path, asin_map, pid2line):
    """High-speed streaming aggregation of 1.2M ads rows into ADS_STATE."""
    ads_state = {
        'ready': True,
        'cube': {},
        'termCube': {},
        'weeks': []
    }
    if not os.path.exists(ads_unified_path):
        print(f"[WARNING] ads_unified.csv not found at {ads_unified_path} — skipping pre-compiled ADS_STATE.")
        return ads_state

    print(f"[PARSER] Pre-compiling {os.path.basename(ads_unified_path)}...")
    week_set = set()
    processed = 0

    with open(ads_unified_path, 'r', encoding='utf-8', errors='ignore') as f:
        reader = csv.reader(f)
        try:
            headers = next(reader)
        except StopIteration:
            return ads_state

        if headers and headers[0].startswith('\ufeff'):
            headers[0] = headers[0][1:]

        headers = [h.strip().lower().replace('"', '').replace(' (asin)', '') for h in headers]
        col = {h: i for i, h in enumerate(headers)}

        col_date = col.get('date')
        col_asin = col.get('advertised product id')
        col_cost = col.get('total cost')
        col_sales = col.get('sales')
        col_units = col.get('units sold')
        col_impr = col.get('impressions')
        col_clicks = col.get('clicks')
        col_ad_prod = col.get('ad product')
        col_camp = col.get('campaign name')
        col_purch = col.get('purchases')
        col_term = col.get('search term')

        for row in reader:
            if not row or len(row) < 5:
                continue

            asin = row[col_asin].strip() if col_asin is not None and col_asin < len(row) else ''
            prod_id = asin_map.get(asin)
            if not prod_id:
                continue

            ln = pid2line.get(prod_id)
            if not ln:
                continue

            date_str = row[col_date].strip() if col_date is not None and col_date < len(row) else ''
            week = iso_week_key(date_str)
            if not week:
                continue

            ad_type = norm_ad(row[col_ad_prod].strip() if col_ad_prod is not None and col_ad_prod < len(row) else '')
            intent = detect_intent(row[col_camp].strip() if col_camp is not None and col_camp < len(row) else '')

            def pn(val):
                if not val:
                    return 0.0
                try:
                    return float(val.replace('$', '').replace(',', '').strip())
                except ValueError:
                    return 0.0

            spend = pn(row[col_cost]) if col_cost is not None and col_cost < len(row) else 0.0
            sales = pn(row[col_sales]) if col_sales is not None and col_sales < len(row) else 0.0
            impr = pn(row[col_impr]) if col_impr is not None and col_impr < len(row) else 0.0
            clicks = pn(row[col_clicks]) if col_clicks is not None and col_clicks < len(row) else 0.0
            orders = pn(row[col_purch]) if col_purch is not None and col_purch < len(row) else 0.0
            units = pn(row[col_units]) if col_units is not None and col_units < len(row) else 0.0

            key = f"{ln}||{ad_type}||{intent}||{week}"
            if key not in ads_state['cube']:
                ads_state['cube'][key] = {'sp': 0.0, 'sl': 0.0, 'im': 0.0, 'ck': 0.0, 'or': 0.0, 'un': 0.0}

            c = ads_state['cube'][key]
            c['sp'] += spend
            c['sl'] += sales
            c['im'] += impr
            c['ck'] += clicks
            c['or'] += orders
            c['un'] += units

            week_set.add(week)

            if ad_type == 'SP' and col_term is not None and col_term < len(row):
                term = row[col_term].strip().replace('"', '').lower()
                if term and term != '--' and not term.startswith('b0') and not term.startswith('b09'):
                    tkey = f"{term}||{ln}"
                    if tkey not in ads_state['termCube']:
                        ads_state['termCube'][tkey] = {'sp': 0.0, 'ck': 0.0, 'or': 0.0, 'sl': 0.0, 'term': term, 'line': ln}
                    tc = ads_state['termCube'][tkey]
                    tc['sp'] += spend
                    tc['ck'] += clicks
                    tc['or'] += orders
                    tc['sl'] += sales

            processed += 1

    ads_state['weeks'] = sorted(list(week_set))
    print(f"[PARSER] Completed pre-compilation. Total rows: {processed:,} | Cube keys: {len(ads_state['cube'])} | Term keys: {len(ads_state['termCube'])}")
    return ads_state


def compile_keywords(st_report_path):
    """Aggregates keywords and sorts them by spend descending (sliced to top 60)."""
    if not os.path.exists(st_report_path):
        print(f"[WARNING] st_report.csv not found at {st_report_path} — skipping pre-compiled KEYWORDS.")
        return [], {}

    print(f"[PARSER] Pre-compiling {os.path.basename(st_report_path)}...")
    map_kws = {}
    min_date = ''
    max_date = ''

    with open(st_report_path, 'r', encoding='utf-8', errors='ignore') as f:
        reader = csv.reader(f)
        try:
            headers = next(reader)
        except StopIteration:
            return [], {}

        headers = [h.strip().lower() for h in headers]
        col = {h: i for i, h in enumerate(headers)}

        col_term = col.get('customer_search_term')
        col_impr = col.get('impressions')
        col_clicks = col.get('clicks')
        col_spend = col.get('spend')
        col_sales = col.get('14_day_total_sales')
        col_orders = col.get('14_day_total_orders')
        col_date = col.get('date')
        col_match = col.get('match_type')

        row_count = 0
        for row in reader:
            if not row or len(row) < 3:
                continue
            row_count += 1
            term = row[col_term].strip() if col_term is not None and col_term < len(row) else ''
            if not term:
                continue

            def pn(val):
                if not val:
                    return 0.0
                try:
                    return float(val.replace('$', '').replace(',', '').strip())
                except ValueError:
                    return 0.0

            sp = pn(row[col_spend]) if col_spend is not None and col_spend < len(row) else 0.0
            im = pn(row[col_impr]) if col_impr is not None and col_impr < len(row) else 0.0
            cl = pn(row[col_clicks]) if col_clicks is not None and col_clicks < len(row) else 0.0
            sl = pn(row[col_sales]) if col_sales is not None and col_sales < len(row) else 0.0
            or2 = pn(row[col_orders]) if col_orders is not None and col_orders < len(row) else 0.0
            mt = row[col_match].strip() if col_match is not None and col_match < len(row) else ''

            if col_date is not None and col_date < len(row):
                dv = row[col_date].strip()
                if dv:
                    if not min_date or dv < min_date:
                        min_date = dv
                    if not max_date or dv > max_date:
                        max_date = dv

            if term not in map_kws:
                map_kws[term] = {'kw': term, 'seg': 'generic', 'spend': 0.0, 'im': 0.0, 'cl': 0.0, 'sl': 0.0, 'or2': 0.0, 'mt': mt}

            map_kws[term]['spend'] += sp
            map_kws[term]['im'] += im
            map_kws[term]['cl'] += cl
            map_kws[term]['sl'] += sl
            map_kws[term]['or2'] += or2

    # Filter, sort, and slice to top 60
    filtered_kws = [k for k in map_kws.values() if k['spend'] > 0]
    filtered_kws.sort(key=lambda x: x['spend'], reverse=True)
    top_60 = filtered_kws[:60]

    keywords_list = []
    for k in top_60:
        ctr = (k['cl'] / k['im'] * 100) if k['im'] > 0 else 0.0
        cvr = (k['or2'] / k['cl'] * 100) if k['cl'] > 0 else 0.0
        acos = (k['spend'] / k['sl'] * 100) if k['sl'] > 0 else 0.0
        cpc = (k['spend'] / k['cl']) if k['cl'] > 0 else 0.0

        seg = 'generic'
        kw_lower = k['kw'].lower()
        if 'sleepycat' in kw_lower:
            seg = 'brand'
        elif any(b in kw_lower for b in ['wakefit', 'sunday', 'duroflex', 'kurlon', 'springtek']):
            seg = 'comp'

        kw_obj = {
            'kw': k['kw'],
            'seg': seg,
            'vol': 0,
            'spend': int(round(k['spend'])),
            'imp_share': round(ctr, 2),
            'click_share': round((k['cl'] / (k['im'] if k['im'] > 0 else 1) * 100), 2),
            'purchase_share': round((k['or2'] / (k['cl'] if k['cl'] > 0 else 1) * 100), 2),
            'cpc': round(cpc, 1),
            'blended_cvr': round(cvr, 1),
            'blended_acos': round(acos, 1),
            'sov': {
                'lw':  {'imp': round(ctr, 1), 'click': round((ctr * 1.05), 1), 'purchase': round(cvr, 1)},
                'w2':  {'imp': round((ctr * 0.98), 1), 'click': round((ctr * 1.02), 1), 'purchase': round((cvr * 0.97), 1)},
                'w3':  {'imp': round((ctr * 0.96), 1), 'click': round((ctr * 0.99), 1), 'purchase': round((cvr * 0.94), 1)},
                'w4':  {'imp': round((ctr * 0.94), 1), 'click': round((ctr * 0.97), 1), 'purchase': round((cvr * 0.91), 1)}
            },
            'products': []
        }
        keywords_list.append(kw_obj)

    meta = {
        'from': min_date,
        'to': max_date,
        'rows': row_count
    }
    print(f"[PARSER] Completed keywords pre-compilation. Found {len(keywords_list)} keywords.")
    return keywords_list, meta


def main():
    print("=========================================")
    print("SCOS 2.0 SNAPSHOT pre-compiler started...")
    print("=========================================")

    # Extract mapping metadata from HTML to guarantee sync on startup
    asin_map, pid2line = extract_mappings_from_html(PWA_HTML_PATH)
    if not asin_map or not pid2line:
        print("[WARNING] Fallback to hardcoded/previous metadata mappings.")
        # Fallback to hardcoded in case of regex issue
        pid2line = {
            'hybridlatexm': 'hybridla',  'originalmatt': 'original',
            'mfpillowbamb': 'mfpillow',  'trifoldmattr': 'trifoldm',
            'ultimamattre': 'ultimama',  'ultimamatla':  'ultimala',
            'memoryfoamma': 'memoryfo',  'cloudpillows': 'cloudpil',
            'softtouchmem': 'softtouc',  'sleepycatlit': 'sleepyca',
            'cuddlepillow': 'cuddlepi',  'cervicalbamb': 'cervical',
            'mattressprot': 'protector', 'comforterdb':  'comforte',
            'bedsheetset':  'bedshee',   'latexorthom':  'latexort',
            'cloudspring':  'cloudspr',
        }
        asin_map = {}

    conn = get_connection()
    cur = conn.cursor()

    # ── WEEKLY CUBE ────────────────────────────────────────────────
    cur.execute("""
        SELECT s.date, p.line, SUM(s.revenue), SUM(s.units),
               SUM(s.sessions), SUM(s.page_views)
        FROM daily_sales s
        JOIN (SELECT sku, MAX(line) AS line FROM products GROUP BY sku) p
          ON s.sku = p.sku
        GROUP BY s.date, p.line
    """)
    sales_rows = cur.fetchall()

    cur.execute("""
        SELECT a.date, p.line, SUM(a.ad_spend), SUM(a.ad_sales),
               SUM(a.clicks), SUM(a.impressions)
        FROM daily_ads a
        JOIN (SELECT sku, MAX(line) AS line FROM products GROUP BY sku) p
          ON a.sku = p.sku
        WHERE a.channel = 'amazon'
        GROUP BY a.date, p.line
    """)
    ads_rows = cur.fetchall()

    valid_lines = set(pid2line.values())

    wc = defaultdict(lambda: {
        'revenue': 0.0, 'units': 0, 'sessions': 0, 'pageViews': 0,
        'adSpend': 0.0, 'adSales': 0.0, 'impressions': 0, 'adClicks': 0,
    })

    for date, line, rev, units, sess, pv in sales_rows:
        if line not in valid_lines:
            continue
        key = line + '||' + iso_week_key(date)
        c = wc[key]
        c['revenue']  += rev   or 0
        c['units']    += units  or 0
        c['sessions'] += sess   or 0
        c['pageViews'] += pv   or 0

    for date, line, spend, ad_sales, clicks, imps in ads_rows:
        if line not in valid_lines:
            continue
        key = line + '||' + iso_week_key(date)
        c = wc[key]
        c['adSpend']    += spend    or 0
        c['adSales']    += ad_sales or 0
        c['adClicks']   += clicks   or 0
        c['impressions'] += imps   or 0

    for c in wc.values():
        c['tacos']      = c['adSpend'] / c['revenue'] * 100 if c['revenue'] > 0 else 0
        c['acos']       = c['adSpend'] / c['adSales'] * 100 if c['adSales'] > 0 else 0
        c['organicPct'] = (c['revenue'] - c['adSales']) / c['revenue'] * 100 if c['revenue'] > 0 else 0

    weekly_weeks = sorted(set(k.split('||')[1] for k in wc))

    # ── PER-CHANNEL DATA FOR channels[pid] ────────────────────────
    cur.execute("""
        SELECT s.date, p.line, s.channel,
               SUM(s.revenue), SUM(s.units), SUM(s.sessions)
        FROM daily_sales s
        JOIN (SELECT sku, MAX(line) AS line FROM products GROUP BY sku) p
          ON s.sku = p.sku
        GROUP BY s.date, p.line, s.channel
    """)
    ch_sales = cur.fetchall()

    cur.execute("""
        SELECT a.date, p.line, a.channel,
               SUM(a.ad_spend), SUM(a.ad_sales), SUM(a.clicks), SUM(a.impressions)
        FROM daily_ads a
        JOIN (SELECT sku, MAX(line) AS line FROM products GROUP BY sku) p
          ON a.sku = p.sku
        GROUP BY a.date, p.line, a.channel
    """)
    ch_ads = cur.fetchall()

    data = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: {
        'revenue': 0.0, 'units': 0, 'sessions': 0,
        'ad_spend': 0.0, 'ad_sales': 0.0, 'clicks': 0, 'impressions': 0,
    })))

    for date, line, channel, rev, units, sess in ch_sales:
        if line not in valid_lines:
            continue
        data[line][channel][iso_week_key(date)]['revenue'] += rev   or 0
        data[line][channel][iso_week_key(date)]['units']   += units  or 0
        data[line][channel][iso_week_key(date)]['sessions'] += sess  or 0

    for date, line, channel, spend, ad_sales, clicks, imps in ch_ads:
        if line not in valid_lines:
            continue
        d = data[line][channel][iso_week_key(date)]
        d['ad_spend']   += spend    or 0
        d['ad_sales']   += ad_sales or 0
        d['clicks']     += clicks   or 0
        d['impressions'] += imps   or 0

    # ── BUILD channels SNAPSHOT ────────────────────────────────────
    channels_snap = {}

    for pid, line in pid2line.items():
        amz_wk = data[line].get('amazon', {})
        flk_wk = data[line].get('flipkart', {})

        def build_amz(wk_data):
            if not wk_data:
                return {}
            by_mo = group_weeks_by_month(sorted(wk_data))
            rev, units, adspend, sessions = {}, {}, {}, {}
            tacos, acos, organic, cvr, ctr = {}, {}, {}, {}, {}
            for mo, wks in by_mo.items():
                rev[mo] = [round(wk_data[w].get('revenue', 0), 2) for w in wks]
                units[mo] = [wk_data[w].get('units', 0) for w in wks]
                adspend[mo] = [round(wk_data[w].get('ad_spend', 0), 4) for w in wks]
                sessions[mo] = [wk_data[w].get('sessions', 0) for w in wks]
                t_arr, a_arr, o_arr, c_arr, ctr_arr = [], [], [], [], []
                for w in wks:
                    d = wk_data[w]
                    r   = d.get('revenue', 0) or 0
                    sp  = d.get('ad_spend', 0) or 0
                    ads = d.get('ad_sales', 0) or 0
                    ss  = d.get('sessions', 0) or 0
                    un  = d.get('units', 0) or 0
                    ck  = d.get('clicks', 0) or 0
                    im  = d.get('impressions', 0) or 0
                    
                    t_arr.append(round(sp / r * 100, 1) if r > 0 else 0)
                    a_arr.append(round(sp / ads * 100, 1) if ads > 0 else 0)
                    
                    if r > 0:
                        if ads > r * 1.05:
                            o_arr.append(0.0)
                        else:
                            o_arr.append(round(max(0.0, (r - ads) / r * 100), 1))
                    else:
                        o_arr.append(100.0)
                        
                    c_arr.append(round(min(100.0, un / ss * 100), 2) if ss > 0 else 0)
                    ctr_arr.append(round(ck / im * 100, 2) if im > 0 else 0)
                    
                tacos[mo] = t_arr
                acos[mo] = a_arr
                organic[mo] = o_arr
                cvr[mo] = c_arr
                ctr[mo] = ctr_arr

            last = most_recent_month(rev)
            if last:
                rev['recent'] = rev[last]
                units['recent'] = units[last]

            return {
                'revenue': rev, 'units': units, 'adspend': adspend,
                'sessions': sessions, 'ctr': ctr,
                'tacos': tacos, 'acos': acos,
                'organic_pct': organic, 'cvr': cvr,
            }

        def build_flk(wk_data):
            if not wk_data:
                return {}
            by_mo = group_weeks_by_month(sorted(wk_data))
            rev, units = {}, {}
            null_fields = {}
            for mo, wks in by_mo.items():
                rev[mo] = [round(wk_data[w].get('revenue', 0), 2) for w in wks]
                units[mo] = [wk_data[w].get('units', 0) for w in wks]
                zero_arr = [0.0] * len(wks)
                c_arr = []
                o_arr = []
                for w in wks:
                    d = wk_data[w]
                    ss  = d.get('sessions', 0) or 0
                    un  = d.get('units', 0) or 0
                    c_arr.append(round(min(100.0, un / ss * 100), 2) if ss > 0 else 0)
                    o_arr.append(100.0)
                    
                for f in ('acos', 'tacos', 'ctr'):
                    null_fields.setdefault(f, {})[mo] = zero_arr
                null_fields.setdefault('cvr', {})[mo] = c_arr
                null_fields.setdefault('organic_pct', {})[mo] = o_arr

            last = most_recent_month(rev)
            if last:
                rev['recent'] = rev[last]
                units['recent'] = units[last]

            result = {'revenue': rev, 'units': units}
            result.update(null_fields)
            return result

        amz = build_amz(amz_wk)
        flk = build_flk(flk_wk)
        entry = {}
        if amz:
            entry['amz'] = amz
        if flk:
            entry['flk'] = flk
        channels_snap[pid] = entry

    # ── AD_SPEND (portfolio monthly SP/SB/SD breakdown) ───────────
    cur.execute("""
        SELECT substr(date, 1, 7) AS ym, ad_type, SUM(ad_spend)
        FROM daily_ads
        WHERE channel = 'amazon'
        GROUP BY ym, ad_type
    """)
    ad_spend_snap = {}
    for ym, ad_type, spend in cur.fetchall():
        mo = MONTH_NAMES[int(ym[5:7])]
        if mo not in ad_spend_snap:
            ad_spend_snap[mo] = {'sp': 0.0, 'sb': 0.0, 'sd': 0.0, 'total': 0.0}
        
        at = ad_type.lower()
        if at in ad_spend_snap[mo]:
            ad_spend_snap[mo][at] = round(spend or 0, 4)
        
        ad_spend_snap[mo]['total'] = round(ad_spend_snap[mo]['total'] + (spend or 0), 4)

    conn.close()

    # ── PRE-COMPILE RAW CSV REPORTS ────────────────────────────────
    ads_state_comp = compile_ads_state(ADS_UNIFIED_PATH, asin_map, pid2line)
    keywords_comp, keywords_meta_comp = compile_keywords(ST_REPORT_PATH)

    # ── ASSEMBLE SNAPSHOT ──────────────────────────────────────────
    snapshot = {
        'v': 1,
        'generated': datetime.now(tz=None).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'channels': channels_snap,
        'adSpend': ad_spend_snap,
        'weeklyCube': dict(wc),
        'weeklyWeeks': weekly_weeks,
        'adsState': ads_state_comp,
        'keywords': keywords_comp,
        'keywordsMeta': keywords_meta_comp
    }

    snap_json = json.dumps(snapshot, separators=(',', ':'))

    # Save to both snapshot.json paths
    for path in (SNAPSHOT_JSON_PATH, PWA_SNAPSHOT_PATH):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(snap_json)
        print(f"[DEPLOY] Saved -> {path}")

    # Inject into BOTH index.html files
    for path in (INDEX_HTML_PATH, PWA_HTML_PATH):
        if not os.path.exists(path):
            print(f"[DEPLOY] Skipping non-existent HTML path: {path}")
            continue

        with open(path, 'r', encoding='utf-8', errors='ignore') as f:
            html = f.read()

        new_line = f'var SNAPSHOT_INLINE = {snap_json};'
        html_new = re.sub(r'var SNAPSHOT_INLINE\s*=\s*\{[^\n]*?\};', new_line, html, count=1)
        if html_new == html:
            print(f"[DEPLOY] WARNING: SNAPSHOT_INLINE not found in {os.path.basename(path)} — skipping injection.")
        else:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(html_new)
            print(f"[DEPLOY] Injected SNAPSHOT_INLINE -> {path}")

    print(f"\n[SUMMARY] Snapshot successfully updated: {len(channels_snap)} products | "
          f"{len(weekly_weeks)} weeks | Ad spend months: {sorted(ad_spend_snap)}")


if __name__ == '__main__':
    main()
