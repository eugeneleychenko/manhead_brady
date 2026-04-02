"""
Side-by-side comparison of old model vs new Ashling model backtest results.

Run AFTER both backtest scripts have completed:
  python3 run_backtest.py            (old model)
  python3 run_backtest_new_model.py  (new model)

Output: comparison/model_comparison_summary.csv
"""

import os
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))

old_path = os.path.join(BASE, "comparison/backtest_summary_all_shows.csv")
new_path = os.path.join(BASE, "comparison/backtest_summary_new_model.csv")

if not os.path.exists(old_path):
    print(f"Missing: {old_path}  — run run_backtest.py first")
    exit(1)
if not os.path.exists(new_path):
    print(f"Missing: {new_path}  — run run_backtest_new_model.py first")
    exit(1)

old = pd.read_csv(old_path)
new = pd.read_csv(new_path)

old = old.rename(columns={
    "predicted_units":   "old_predicted_units",
    "units_pct_error":   "old_units_pct_error",
    "predicted_revenue": "old_predicted_revenue",
    "revenue_delta":     "old_revenue_delta",
    "predicted_perhead": "old_predicted_perhead",
    "perhead_delta":     "old_perhead_delta",
    "mae":               "old_mae",
    "mape":              "old_mape",
})

new = new.rename(columns={
    "predicted_units":   "new_predicted_units",
    "units_pct_error":   "new_units_pct_error",
    "predicted_revenue": "new_predicted_revenue",
    "revenue_delta":     "new_revenue_delta",
    "predicted_perhead": "new_predicted_perhead",
    "perhead_delta":     "new_perhead_delta",
    "mae":               "new_mae",
    "mape":              "new_mape",
})

key_cols = ["date", "city", "attendance", "actual_units", "actual_revenue", "actual_perhead"]
old_extra = ["old_predicted_units", "old_units_pct_error", "old_predicted_perhead", "old_perhead_delta", "old_mae", "old_mape"]
new_extra = ["new_predicted_units", "new_units_pct_error", "new_predicted_perhead", "new_perhead_delta", "new_mae", "new_mape"]

merged = pd.merge(
    old[key_cols + old_extra],
    new[["date", "city"] + new_extra],
    on=["date", "city"],
    how="outer"
)

# Which model was closer on units
def closer(row):
    try:
        return "OLD" if abs(row["old_units_pct_error"]) <= abs(row["new_units_pct_error"]) else "NEW"
    except Exception:
        return "N/A"

merged["better_model_units"] = merged.apply(closer, axis=1)

out_path = os.path.join(BASE, "comparison/model_comparison_summary.csv")
merged.to_csv(out_path, index=False)

print("=== MODEL COMPARISON (per show) ===")
print(merged[[
    "date", "city", "actual_units",
    "old_predicted_units", "old_units_pct_error",
    "new_predicted_units", "new_units_pct_error",
    "better_model_units"
]].to_string(index=False))

print("\n=== AGGREGATE METRICS ===")
print(f"{'':30s} {'OLD MODEL':>12} {'NEW MODEL':>12}")
print(f"{'Avg Unit % Error':30s} {merged['old_units_pct_error'].mean():>12.1f} {merged['new_units_pct_error'].mean():>12.1f}")
print(f"{'Avg MAE':30s} {merged['old_mae'].mean():>12.1f} {merged['new_mae'].mean():>12.1f}")
print(f"{'Avg MAPE':30s} {merged['old_mape'].mean():>12.1f} {merged['new_mape'].mean():>12.1f}")
print(f"{'Avg $/Head Error':30s} {merged['old_perhead_delta'].mean():>12.2f} {merged['new_perhead_delta'].mean():>12.2f}")
old_wins = (merged["better_model_units"] == "OLD").sum()
new_wins = (merged["better_model_units"] == "NEW").sum()
print(f"\nShows where old model closer: {old_wins}")
print(f"Shows where new model closer: {new_wins}")
print(f"\nSaved: {out_path}")
