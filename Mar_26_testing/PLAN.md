# Backtesting Plan: Prediction Model Accuracy

## Goal
Compare predicted merch sales vs actual sales for past Air Supply shows to measure model accuracy.

## What We Need From You

### 1. Tour Summary Export (CSV/Excel)
- **Source**: atvenu.com > Air Supply > Reports > Tour Summary
- **URL pattern**: `https://artist.atvenu.com/as/talents/18219/report/reports/tour_summary`
- **Date range**: Pick a completed tour (e.g., "50th Anniversary Q4 US/Can" Oct 2025 - Feb 2026)
- **What it gives us**: Date, City, State, Zip, Venue, Capacity, Attendance, $/Head, Gross per show
- **Save as**: `Mar_26_testing/air_supply_tour_summary.csv`

### 2. Sales Report Export (CSV)
- **Source**: atvenu.com > Air Supply > Reports > Sales Report
- **Same tour/date range** as the Tour Summary
- **What it gives us**: SKU, Name, Type, Size, Sold (actual), Avg. Price per product
- **IMPORTANT**: Need the per-show breakdown, not just tour totals. If the export only gives totals, we'll need individual show Sales Reports.
- **Save as**: `Mar_26_testing/air_supply_sales_report.csv`

### 3. Inventory File for That Same Tour (if available)
- **Source**: atvenu.com > Tour Forecast > Products (for the same completed tour)
- **This is optional** -- we can reconstruct the product list from the Sales Report
- **Save as**: `Mar_26_testing/air_supply_past_inventory.xlsx`

## What I'll Build

### Step 1: Parse Actuals
- Read Tour Summary → extract per-show: date, city, venue, state, attendance, actual $/head, actual gross
- Read Sales Report → extract per-show per-SKU: actual quantity sold, price

### Step 2: Build Prediction Input
- For each past show, create a formatted input row per product/size (same format as `Air_supply_formatted_*.csv`)
- Use **real attendance** from Tour Summary (not 80% estimate)
- Use **real prices** from Sales Report

### Step 3: Run Predictions
- Send formatted data to the prediction API (`/predict/size` and `/predict/perhead`)
- Get back: predicted_sales_quantity, %_item_sales_per_category, predicted_$/head

### Step 4: Compare
Generate a comparison report with:

**Per-Show Metrics:**
| Show | City | Attendance | Actual $/Head | Predicted $/Head | Δ | % Error |

**Per-Product Metrics:**
| Show | Product | Size | Actual Sold | Predicted Sold | Δ | % Error |

**Aggregate Metrics:**
- MAE (Mean Absolute Error) for quantity predictions
- MAPE (Mean Absolute Percentage Error) 
- R² score
- Per-show total predicted vs actual
- Size distribution accuracy (does it get S/M/L/XL ratios right?)

### Step 5: Visualizations (optional)
- Scatter plot: predicted vs actual per product
- Bar chart: predicted vs actual per show
- Heatmap: error by product type × size

## Key Questions

1. **Per-show Sales Report**: Does the Sales Report export break down by individual show date, or is it aggregated across the tour? If aggregated, we'll need to download individual show reports.

2. **Which tour to test**: The "50th Anniversary Q4 US/Can" (Oct 2025 - Feb 2026) has the most recent data. The shows from screenshot 1 (Miami 02/03, Sarasota 05/04, Uncasville 05/10, etc.) look like good candidates.

3. **Multiple bands**: Want to test just Air Supply first, or also include another band (e.g., Deftones, B-52's) to see if accuracy varies by genre?

## File Structure After Completion
```
Mar_26_testing/
├── PLAN.md                          ← this file
├── air_supply_tour_summary.csv      ← YOU PROVIDE (from atvenu)
├── air_supply_sales_report.csv      ← YOU PROVIDE (from atvenu)
├── air_supply_past_inventory.xlsx   ← YOU PROVIDE (optional)
├── backtest_input.csv               ← I BUILD (formatted prediction input)
├── backtest_predictions.csv         ← I BUILD (model output)
├── backtest_comparison.csv          ← I BUILD (predicted vs actual)
├── backtest_report.md               ← I BUILD (summary with metrics)
├── Air_supply_formatted_*.csv       ← already here (future prediction)
└── Air_supply_predicted_*.csv       ← already here (future prediction)
```
