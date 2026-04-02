"""
Backtest the Ashling (new) model against 7 completed Air Supply shows.

Prerequisites:
  - Ashling Flask API must be running on port 5000:
      cd "/Users/eugeneleychenko/Downloads/Ashling Manhead Share 3/Manhead_Handoff"
      source .venv/bin/activate
      python Python_scripts/run_all_products_sales_by_size_prediction_app.py

Usage:
  python3 run_backtest_new_model.py
"""

import os
import re
import io
import requests
import datetime
import numpy as np
import pandas as pd

FLASK_API_URL = "http://localhost:5001/api/predict"
BASE = os.path.dirname(os.path.abspath(__file__))

SPOTIFY_LISTENERS = 9197653   # Air Supply from spotify_monthly_listeners.csv
INSTAGRAM         = 347        # Air Supply from artist_metadata.csv
GENRE             = "Pop"      # Ashling encoder expects "Pop", not "Pop/Rock"
ARTIST_NAME       = "Air Supply"

CANADIAN_PROVINCES = {"AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT"}

os.makedirs(os.path.join(BASE, "inputs_new_model"), exist_ok=True)
os.makedirs(os.path.join(BASE, "predictions_new_model"), exist_ok=True)

# ── helpers ───────────────────────────────────────────────────────────────────

def clean_num(s):
    return float(str(s).replace("$", "").replace(",", "").strip()) if pd.notna(s) else 0


def holiday_status(date_obj):
    """1 if weekend or US federal holiday, else 0."""
    if date_obj.weekday() >= 5:
        return 1
    us_federal = {
        datetime.date(2025, 1, 1), datetime.date(2025, 1, 20), datetime.date(2025, 2, 17),
        datetime.date(2025, 5, 26), datetime.date(2025, 6, 19), datetime.date(2025, 7, 4),
        datetime.date(2025, 9, 1), datetime.date(2025, 10, 13), datetime.date(2025, 11, 11),
        datetime.date(2025, 11, 27), datetime.date(2025, 12, 25),
        datetime.date(2026, 1, 1), datetime.date(2026, 1, 19), datetime.date(2026, 2, 16),
        datetime.date(2026, 5, 25), datetime.date(2026, 6, 19), datetime.date(2026, 7, 4),
    }
    return 1 if date_obj in us_federal else 0


def venue_country(state):
    return "Canada" if state in CANADIAN_PROVINCES else "United States"


def geocode_city(city, state, country_code):
    """Return (lat, lon) for a city via Open-Meteo geocoding API."""
    query = f"{city} {state}"
    try:
        resp = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": query, "count": 1, "language": "en", "format": "json"},
            timeout=10
        )
        results = resp.json().get("results", [])
        if results:
            return results[0]["latitude"], results[0]["longitude"]
    except Exception as e:
        print(f"  Geocoding failed for {city}: {e}")
    return None, None


def fetch_weather(lat, lon, date_str):
    """Return dict with temperature_daily_mean, rain, snowfall for a date (YYYY-MM-DD)."""
    defaults = {"temperature_daily_mean": 15.0, "rain": 0.0, "snowfall": 0.0}
    if lat is None:
        return defaults
    try:
        resp = requests.get(
            "https://archive-api.open-meteo.com/v1/archive",
            params={
                "latitude": lat,
                "longitude": lon,
                "start_date": date_str,
                "end_date": date_str,
                "daily": "temperature_2m_mean,rain_sum,snowfall_sum",
                "timezone": "auto",
            },
            timeout=15
        )
        data = resp.json().get("daily", {})
        return {
            "temperature_daily_mean": (data.get("temperature_2m_mean") or [defaults["temperature_daily_mean"]])[0] or defaults["temperature_daily_mean"],
            "rain":     (data.get("rain_sum")     or [0.0])[0] or 0.0,
            "snowfall": (data.get("snowfall_sum") or [0.0])[0] or 0.0,
        }
    except Exception as e:
        print(f"  Weather fetch failed: {e}")
        return defaults


def parse_sales_report(filepath):
    rows = []
    for line in open(filepath).read().strip().split("\n"):
        if not line.strip():
            continue
        if line.startswith(("APPAREL", "OTHER", "MUSIC", "TOTAL", "GRAND", "SUBTOTAL", "SKU,", "UPC,")):
            continue
        parts = line.split(",")
        if len(parts) < 9:
            continue
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
        price_str = parts[8].strip('"').replace("$", "").replace(",", "")
        try:
            price = float(price_str)
        except Exception:
            price = 0.0
        rows.append({
            "SKU": sku, "Item Name": name, "productType": ptype,
            "product size": size, "actual_sold": sold, "product price": price
        })
    return pd.DataFrame(rows)


# ── 1. Load tour summary ──────────────────────────────────────────────────────

cols = [
    "Date", "City", "State", "Zip", "Venue", "Venue Actual %", "Capacity", "Attend",
    "Currency", "Exch. Rate", "Per Head", "Gross", "Tax", "Payment Fees", "Venue Fee",
    "Venue Adjust.", "Vend Fee", "Ext Exp", "Bootleg Exp", "Selling Exp", "Net Receipts"
]
ts = pd.read_csv(
    os.path.join(BASE, "raw_data/tour_summary/air-supply_Tour-Summary_all-tours-for-05-01-2025-to-02-22-2026.csv"),
    skiprows=4, header=None, names=cols
)
ts = ts[ts["Date"].str.contains("/", na=False)].copy()
ts["attend_int"]    = ts["Attend"].apply(clean_num).astype(int)
ts["capacity_int"]  = ts["Capacity"].apply(clean_num).astype(int)
ts["perhead_actual"] = ts["Per Head"].apply(clean_num)
ts["Zip"] = ts["Zip"].astype(str).str.strip().str.zfill(5)

# ── 2. Process each show ──────────────────────────────────────────────────────

sales_dir = os.path.join(BASE, "raw_data/sales_reports")
sales_files = sorted([f for f in os.listdir(sales_dir) if f.endswith(".csv")])

all_comparisons = []
show_summaries = []

for fname in sales_files:
    m = re.search(r"(\d{2})-(\d{2})-(\d{4})", fname)
    if not m:
        continue
    date_str_slash = f"{m.group(1)}/{m.group(2)}/{m.group(3)}"
    date_str_iso   = f"{m.group(3)}-{m.group(1)}-{m.group(2)}"
    date_obj       = datetime.date(int(m.group(3)), int(m.group(1)), int(m.group(2)))

    show_row = ts[ts["Date"] == date_str_slash]
    if show_row.empty:
        print(f"  SKIP {date_str_slash} — not in tour summary")
        continue
    show = show_row.iloc[0]
    attendance = show["attend_int"]
    capacity   = show["capacity_int"]
    city       = show["City"]
    state      = show["State"].strip()
    venue_name = show["Venue"]
    postal     = show["Zip"]
    country    = venue_country(state)
    slug = f"{m.group(3)}_{m.group(1)}_{m.group(2)}_{city.lower().replace(' ','_').replace(chr(39),'')}"

    print(f"\nProcessing {date_str_slash} | {city} | Attn={attendance:,}")

    # Weather
    print(f"  Geocoding {city}, {state} ...")
    lat, lon = geocode_city(city, state, "CA" if country == "Canada" else "US")
    weather  = fetch_weather(lat, lon, date_str_iso)
    print(f"  Weather: temp={weather['temperature_daily_mean']:.1f}°C rain={weather['rain']} snow={weather['snowfall']}")

    # Parse actuals
    sales_df = parse_sales_report(os.path.join(sales_dir, fname))
    sales_df = sales_df[sales_df["product price"] > 0].copy()

    # Build enriched input
    h_status = holiday_status(date_obj)
    input_rows = []
    for _, item in sales_df.iterrows():
        input_rows.append({
            "artistName":              ARTIST_NAME,
            "Genre":                   GENRE,
            "showDate":                date_str_iso,
            "HolidayStatus":           h_status,
            "venue name":              venue_name,
            "venue city":              city,
            "venue state":             state,
            "venue country":           country,
            "venue postalCode":        postal,
            "merch category":          item["Item Name"],
            "productType":             item["productType"],
            "product size":            item["product size"],
            "attendance":              attendance,
            "product price":           item["product price"],
            "temperature_daily_mean":  weather["temperature_daily_mean"],
            "rain":                    weather["rain"],
            "snowfall":                weather["snowfall"],
            "spotifyMonthlyListeners": SPOTIFY_LISTENERS,
            "Instagram":               INSTAGRAM,
            "venue capacity":          capacity,
            "spotifyMissing":          0,
            # passthrough for comparison later
            "_actual_sold":            item["actual_sold"],
            "_item_name":              item["Item Name"],
        })

    input_df = pd.DataFrame(input_rows)

    # Save input (drop internal columns)
    input_save = input_df.drop(columns=["_actual_sold", "_item_name"])
    input_path = os.path.join(BASE, f"inputs_new_model/backtest_input_new_{slug}.csv")
    input_save.to_csv(input_path, index=False)

    # Call Ashling Flask API
    print(f"  Calling Flask API ...")
    try:
        with open(input_path, "rb") as f:
            resp = requests.post(
                FLASK_API_URL,
                files={"csv_file": (os.path.basename(input_path), f, "text/csv")},
                timeout=180
            )
        if resp.status_code != 200:
            print(f"  ERROR {resp.status_code}: {resp.text[:300]}")
            continue
        preds_data = resp.json().get("data", [])
        if not preds_data:
            print(f"  ERROR: empty response data")
            continue
        preds = pd.DataFrame(preds_data)
    except Exception as e:
        print(f"  API call failed: {e}")
        continue

    preds.to_csv(os.path.join(BASE, f"predictions_new_model/backtest_pred_new_{slug}.csv"), index=False)

    # Build comparison
    comp = input_df[["_item_name", "productType", "product size", "product price", "_actual_sold"]].copy()
    comp.columns = ["Item Name", "productType", "product size", "product price", "actual_sold"]
    comp["predicted_sold"] = preds["predicted_sales_quantity"].values
    comp["delta"]     = comp["predicted_sold"] - comp["actual_sold"]
    comp["abs_error"] = comp["delta"].abs()
    comp["pct_error"] = np.where(
        comp["actual_sold"] > 0,
        (comp["abs_error"] / comp["actual_sold"] * 100).round(1),
        np.nan
    )
    comp.insert(0, "show_date",  date_str_slash)
    comp.insert(1, "city",       city)
    comp.insert(2, "attendance", attendance)
    comp.to_csv(os.path.join(BASE, f"predictions_new_model/backtest_comparison_new_{slug}.csv"), index=False)
    all_comparisons.append(comp)

    actual_units = comp["actual_sold"].sum()
    pred_units   = comp["predicted_sold"].sum()
    actual_rev   = (comp["actual_sold"]    * comp["product price"]).sum()
    pred_rev     = (comp["predicted_sold"] * comp["product price"]).sum()

    show_summaries.append({
        "date":               date_str_slash,
        "city":               city,
        "attendance":         attendance,
        "actual_units":       actual_units,
        "predicted_units":    pred_units,
        "units_delta":        pred_units - actual_units,
        "units_pct_error":    round(abs(pred_units - actual_units) / actual_units * 100, 1) if actual_units else None,
        "actual_revenue":     round(actual_rev, 2),
        "predicted_revenue":  round(pred_rev, 2),
        "revenue_delta":      round(pred_rev - actual_rev, 2),
        "actual_perhead":     round(actual_rev / attendance, 2) if attendance else None,
        "predicted_perhead":  round(pred_rev / attendance, 2) if attendance else None,
        "perhead_delta":      round((pred_rev - actual_rev) / attendance, 2) if attendance else None,
        "mae":                round(comp["abs_error"].mean(), 1),
        "mape":               round(comp[comp["actual_sold"] > 0]["pct_error"].mean(), 1),
    })
    print(f"  Units: actual={actual_units} predicted={pred_units} | "
          f"Revenue: actual=${actual_rev:,.0f} predicted=${pred_rev:,.0f}")

# ── 3. Save summary ───────────────────────────────────────────────────────────
if show_summaries:
    summary_df = pd.DataFrame(show_summaries)
    summary_df.to_csv(os.path.join(BASE, "comparison/backtest_summary_new_model.csv"), index=False)

    master = pd.concat(all_comparisons, ignore_index=True)
    master.to_csv(os.path.join(BASE, "predictions_new_model/backtest_all_shows_detail_new.csv"), index=False)

    print()
    print("=== NEW MODEL SUMMARY ACROSS ALL SHOWS ===")
    print(summary_df[[
        "date", "city", "attendance", "actual_units", "predicted_units",
        "units_pct_error", "actual_perhead", "predicted_perhead", "mae", "mape"
    ]].to_string(index=False))
    print(f"\nOverall MAE  : {master['abs_error'].mean():.1f} units")
    print(f"Overall MAPE : {master[master['actual_sold'] > 0]['pct_error'].mean():.1f}%")
    print(f"Overall units: actual={master['actual_sold'].sum()} predicted={master['predicted_sold'].sum()}")
else:
    print("\nNo shows processed successfully.")
