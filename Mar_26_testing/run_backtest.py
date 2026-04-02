import pandas as pd
import numpy as np
import requests
import re
import os

API_BASE_URL = "https://fast-api-data-master-eugene59.replit.app"
BASE = os.path.dirname(os.path.abspath(__file__))

# ── 1. Load tour summary ──────────────────────────────────────────────────────
cols = [
    "Date","City","State","Zip","Venue","Venue Actual %","Capacity","Attend",
    "Currency","Exch. Rate","Per Head","Gross","Tax","Payment Fees","Venue Fee",
    "Venue Adjust.","Vend Fee","Ext Exp","Bootleg Exp","Selling Exp","Net Receipts"
]
ts = pd.read_csv(
    os.path.join(BASE, "raw_data/tour_summary/air-supply_Tour-Summary_all-tours-for-05-01-2025-to-02-22-2026.csv"),
    skiprows=4, header=None, names=cols
)
ts = ts[ts["Date"].str.contains("/", na=False)].copy()

def clean_num(s):
    return float(str(s).replace("$","").replace(",","").strip()) if pd.notna(s) else 0

ts["attend_int"] = ts["Attend"].apply(clean_num).astype(int)
ts["perhead_actual"] = ts["Per Head"].apply(clean_num)
ts["gross_actual"] = ts["Gross"].apply(clean_num)

# ── 2. Parse each sales report ────────────────────────────────────────────────
def parse_sales_report(filepath):
    rows = []
    for line in open(filepath).read().strip().split("\n"):
        if not line.strip():
            continue
        if line.startswith(("APPAREL","OTHER","MUSIC","TOTAL","GRAND","SUBTOTAL","SKU,","UPC,")):
            continue
        parts = line.split(",")
        if len(parts) < 9:
            continue
        # Accept rows with AIRS- SKU or blank SKU (international shows)
        sku_raw = parts[0].strip('"').strip()
        is_airs = sku_raw.startswith("AIRS-")
        is_blank_sku = sku_raw == "" and parts[1].strip('"').strip() != ""
        if not (is_airs or is_blank_sku):
            continue
        sku = sku_raw
        name = parts[1].strip('"')
        ptype = parts[2].strip('"')
        size = parts[4].strip('"') or "ONE SIZE"
        sold = int(parts[5]) if parts[5].strip().lstrip("-").isdigit() else 0
        price_str = parts[8].strip('"').replace("$","").replace(",","")
        try:
            price = float(price_str)
        except:
            price = 0.0
        rows.append({
            "SKU": sku, "Item Name": name, "productType": ptype,
            "product size": size, "actual_sold": sold, "product price": price
        })
    return pd.DataFrame(rows)

# ── 3. Process each show ──────────────────────────────────────────────────────
sales_dir = os.path.join(BASE, "raw_data/sales_reports")
sales_files = sorted([f for f in os.listdir(sales_dir) if f.endswith(".csv")])

all_comparisons = []
show_summaries = []

for fname in sales_files:
    m = re.search(r"(\d{2})-(\d{2})-(\d{4})", fname)
    if not m:
        continue
    date_str = f"{m.group(1)}/{m.group(2)}/{m.group(3)}"

    show_row = ts[ts["Date"] == date_str]
    if show_row.empty:
        print(f"  SKIP {date_str} - not in tour summary")
        continue
    show = show_row.iloc[0]
    attendance = show["attend_int"]
    city = show["City"]
    slug = f"{m.group(3)}_{m.group(1)}_{m.group(2)}_{city.lower().replace(' ','_').replace(chr(39),'')}"

    print(f"Processing {date_str} | {city} | Attn={attendance:,} | $/Head={show['Per Head']}")

    sales_df = parse_sales_report(os.path.join(sales_dir, fname))
    sales_df = sales_df[sales_df["product price"] > 0].copy()

    # Build prediction input
    input_rows = []
    for _, item in sales_df.iterrows():
        input_rows.append({
            "artistName": "Air Supply",
            "Genre": "Pop/Rock",
            "showDate": pd.to_datetime(date_str).strftime("%Y-%m-%d"),
            "venue name": show["Venue"],
            "venue city": city,
            "venue state": show["State"],
            "attendance": attendance,
            "product size": item["product size"],
            "productType": item["productType"],
            "product price": item["product price"],
            "Item Name": item["Item Name"],
        })
    input_df = pd.DataFrame(input_rows)
    input_df.to_csv(os.path.join(BASE, f"inputs/backtest_input_{slug}.csv"), index=False)

    # Call API
    data_list = input_df.replace({np.nan: None}).to_dict(orient="records")
    resp = requests.post(f"{API_BASE_URL}/predict/size", json={"data": data_list}, timeout=120)
    if resp.status_code != 200:
        print(f"  ERROR {resp.status_code}: {resp.text[:200]}")
        continue
    preds = pd.DataFrame(resp.json()["predictions"])
    preds.to_csv(os.path.join(BASE, f"predictions/backtest_pred_{slug}.csv"), index=False)

    # Build comparison
    comp = sales_df[["Item Name","productType","product size","product price","actual_sold"]].copy()
    comp = comp[comp["product price"] > 0].reset_index(drop=True)
    comp["predicted_sold"] = preds["predicted_sales_quantity"].values
    comp["delta"] = comp["predicted_sold"] - comp["actual_sold"]
    comp["abs_error"] = comp["delta"].abs()
    comp["pct_error"] = np.where(
        comp["actual_sold"] > 0,
        (comp["abs_error"] / comp["actual_sold"] * 100).round(1),
        np.nan
    )
    comp.insert(0, "show_date", date_str)
    comp.insert(1, "city", city)
    comp.insert(2, "attendance", attendance)
    comp.to_csv(os.path.join(BASE, f"comparison/backtest_comparison_{slug}.csv"), index=False)
    all_comparisons.append(comp)

    actual_units = comp["actual_sold"].sum()
    pred_units = comp["predicted_sold"].sum()
    actual_rev = (comp["actual_sold"] * comp["product price"]).sum()
    pred_rev = (comp["predicted_sold"] * comp["product price"]).sum()
    show_summaries.append({
        "date": date_str,
        "city": city,
        "attendance": attendance,
        "actual_units": actual_units,
        "predicted_units": pred_units,
        "units_delta": pred_units - actual_units,
        "units_pct_error": round(abs(pred_units - actual_units) / actual_units * 100, 1) if actual_units else None,
        "actual_revenue": round(actual_rev, 2),
        "predicted_revenue": round(pred_rev, 2),
        "revenue_delta": round(pred_rev - actual_rev, 2),
        "actual_perhead": round(actual_rev / attendance, 2) if attendance else None,
        "predicted_perhead": round(pred_rev / attendance, 2) if attendance else None,
        "perhead_delta": round((pred_rev - actual_rev) / attendance, 2) if attendance else None,
        "mae": round(comp["abs_error"].mean(), 1),
        "mape": round(comp[comp["actual_sold"] > 0]["pct_error"].mean(), 1),
    })
    print(f"  Units: actual={actual_units} predicted={pred_units} | "
          f"Revenue: actual=${actual_rev:,.0f} predicted=${pred_rev:,.0f}")

# ── 4. Save summary ───────────────────────────────────────────────────────────
summary_df = pd.DataFrame(show_summaries)
summary_df.to_csv(os.path.join(BASE, "comparison/backtest_summary_all_shows.csv"), index=False)

master = pd.concat(all_comparisons, ignore_index=True)
master.to_csv(os.path.join(BASE, "comparison/backtest_all_shows_detail.csv"), index=False)

print()
print("=== SUMMARY ACROSS ALL SHOWS ===")
print(summary_df[[
    "date","city","attendance","actual_units","predicted_units",
    "units_pct_error","actual_perhead","predicted_perhead","mae","mape"
]].to_string(index=False))
print(f"\nOverall MAE  : {master['abs_error'].mean():.1f} units")
print(f"Overall MAPE : {master[master['actual_sold'] > 0]['pct_error'].mean():.1f}%")
print(f"Overall units: actual={master['actual_sold'].sum()} predicted={master['predicted_sold'].sum()}")
