# Mar_26_testing — Backtest: Predicted vs Actual Merch Sales

## Purpose
Backtest both the **old model** (Replit API) and **new Ashling model** (local Flask) against **7 completed Air Supply shows** (Dec 2025 - Feb 2026) to measure prediction accuracy and compare models.

## Key Findings

Both models **consistently over-predict** across all shows. The new model is directionally better but still far off.

### Three-Way Comparison

| Show | Actual | Old Model | New Model (shortcut) | New Model (proper pipeline) |
|------|--------|-----------|----------------------|-----------------------------|
| Toronto 12/17 | 198 | 1,139 | 639 | 697 |
| Tsuut'ina 12/19 | 173 | 809 | 611 | **DROPPED** |
| Edmonton 12/20 | 230 | 886 | 730 | 1,159 |
| San Jose 02/13 | 260 | 702 | 487 | 843 |
| Rancho Mirage 02/14 | 128 | 1,204 | 668 | 805 |
| Valley Center 02/15 | 164 | 1,169 | 683 | 827 |
| Maravillas 02/22 | 36 | 532 | 339 | 339 |

### Aggregate Metrics (Old vs New shortcut)

| Metric | Old Model | New Model (shortcut) |
|--------|-----------|----------------------|
| Avg Unit % Error | 589.9% | 337.2% |
| Avg MAE | 27.6 | 16.4 |
| Avg $/Head Error | $13.07 | $7.37 |
| Shows won | 0 / 7 | 7 / 7 |

---

## Raw Data (from atvenu exports)

```
raw_data/
├── tour_summary/
│   └── air-supply_Tour-Summary_all-tours-for-05-01-2025-to-02-22-2026.csv
└── sales_reports/   (7 per-show sales report CSVs)
    ├── air-supply_Sales-Report_all-tours-for-12-17-2025.csv
    ├── air-supply_Sales-Report_all-tours-for-12-19-2025.csv
    ├── air-supply_Sales-Report_all-tours-for-12-20-2025.csv
    ├── air-supply_Sales-Report_all-tours-for-02-13-2026.csv
    ├── air-supply_Sales-Report_all-tours-for-02-14-2026.csv
    ├── air-supply_Sales-Report_all-tours-for-02-15-2026.csv
    └── air-supply_Sales-Report_all-tours-for-02-22-2026.csv
```

---

## Old Model Backtest

**Script**: `run_backtest.py`
**API**: `https://fast-api-data-master-eugene59.replit.app/predict/size` (remote Replit)
**Input format**: 11 columns (artistName, Genre=Pop/Rock, showDate, venue info, attendance, product info)

### How to run
```bash
cd Mar_26_testing
python3 run_backtest.py
```
Outputs: `inputs/`, `predictions/`, `comparison/backtest_summary_all_shows.csv`

---

## New Model Backtest — Two Approaches

The new Ashling model needs ~24 columns including weather, Spotify, Instagram, HolidayStatus, venue capacity, etc. There are two ways to generate this enriched input.

### Approach A: Shortcut Script (run_backtest_new_model.py)

Does its own enrichment inline — looks up weather from Open-Meteo, hardcodes Spotify/Instagram for Air Supply, computes HolidayStatus, then calls the Flask API directly.

**Pros**: Self-contained, one command, processes all 7 shows.
**Cons**: Uses default weather (15°C) when geocoding fails, doesn't match Ashling's exact enrichment logic.

```bash
# Terminal 1 — start Flask API (port 5001 to avoid macOS AirPlay on 5000)
cd "/Users/eugeneleychenko/Downloads/Ashling Manhead Share 3/Manhead_Handoff"
source .venv/bin/activate
python Python_scripts/run_all_products_sales_by_size_prediction_app.py

# Terminal 2 — run backtest
cd Mar_26_testing
python3 run_backtest_new_model.py

# After both backtests — side-by-side comparison
python3 compare_models.py
```

Outputs: `inputs_new_model/`, `predictions_new_model/`, `comparison/backtest_summary_new_model.csv`, `comparison/model_comparison_summary.csv`

### Approach B: Proper Ashling Pipeline (Step 2 → Step 4)

Uses Ashling's actual consolidation pipeline (`consolidate_pipeline.py`) to enrich data the way it was designed — geocoding, real historical weather, Spotify lookup, etc. Then feeds the enriched CSV to Step 4 (Flask prediction API).

**Pros**: Uses the exact same enrichment the model was trained on.
**Cons**: Manual file-swapping required, Tsuut'ina drops (geocoding fails on apostrophe), output needs cleaning.

#### Step-by-step:

1. **Back up existing files** in the Ashling project:
```bash
ASHLING="/Users/eugeneleychenko/Downloads/Ashling Manhead Share 3/Manhead_Handoff"
mkdir -p "$ASHLING/CSVs/_backup_sales" "$ASHLING/CSVs/_backup_tour" "$ASHLING/CSVs/_backup_merged"
mv "$ASHLING/CSVs/add_sales_reports_files_here/"*.csv "$ASHLING/CSVs/_backup_sales/"
mv "$ASHLING/CSVs/add_tour_summary_files_here/"*.csv "$ASHLING/CSVs/_backup_tour/"
cp "$ASHLING/CSVs/merged_files/"* "$ASHLING/CSVs/_backup_merged/"
```

2. **Copy our raw files in**:
```bash
cp Mar_26_testing/raw_data/sales_reports/*.csv "$ASHLING/CSVs/add_sales_reports_files_here/"
cp Mar_26_testing/raw_data/tour_summary/*.csv "$ASHLING/CSVs/add_tour_summary_files_here/"
```

3. **Run consolidation** (Step 2):
```bash
cd "$ASHLING" && .venv/bin/python Python_scripts/consolidate_pipeline.py
```
Output: `$ASHLING/CSVs/merged_files/merged_with_weather.csv` (287 rows, 24 columns)

4. **Clean the output** (IMPORTANT — consolidation outputs comma-formatted numbers that crash Flask):
```python
import pandas as pd, re
df = pd.read_csv('merged_with_weather.csv')
for col in ['attendance', 'venue capacity', 'product price']:
    df[col] = df[col].astype(str).apply(lambda x: re.sub(r'[\$,]', '', x))
    df[col] = pd.to_numeric(df[col], errors='coerce')
df.to_csv('merged_with_weather_clean.csv', index=False)
```

5. **Upload to Step 4** on `http://localhost:8504` or call Flask API directly:
```bash
curl -X POST http://localhost:5001/api/predict \
  -F "csv_file=@merged_with_weather_clean.csv" \
  -o predictions.json
```

6. **Restore originals**:
```bash
rm "$ASHLING/CSVs/add_sales_reports_files_here/"*.csv
rm "$ASHLING/CSVs/add_tour_summary_files_here/"*.csv
mv "$ASHLING/CSVs/_backup_sales/"*.csv "$ASHLING/CSVs/add_sales_reports_files_here/"
mv "$ASHLING/CSVs/_backup_tour/"*.csv "$ASHLING/CSVs/add_tour_summary_files_here/"
cp "$ASHLING/CSVs/_backup_merged/"* "$ASHLING/CSVs/merged_files/"
rm -rf "$ASHLING/CSVs/_backup_sales" "$ASHLING/CSVs/_backup_tour" "$ASHLING/CSVs/_backup_merged"
```

---

## Manual Validation (Toronto 12/17/2025)

We verified the automated backtest by running one show manually through both Streamlit UIs and comparing outputs.

**Old model**: Automated backtest matched manual Streamlit run **exactly** (1,139 total units, every row identical).

**New model**: Automated backtest matched Streamlit UI **exactly** (639 total units) when given the same enriched input file. The user's initial manual run got ~890 units because they uploaded the old-format 11-column input instead of the enriched 21-column input — the model still ran but encoded missing features as unknowns, producing different predictions.

Manual output files saved in `outputs/`:
```
outputs/
├── old-version-air-supply-toronto-qty-2026-03-05.csv
├── old-version-air-supply-toronto-head-2026-03-05.csv
├── new-version-air-supply-toronto-qty-2026-03-05.csv
└── new-version-air-supply-toronto-head-2026-03-05.csv
```

---

## Known Issues & Bugs

### Tsuut'ina drops from proper pipeline
The apostrophe in "Tsuut'ina" causes Open-Meteo geocoding to fail → weather = NaN → model drops those rows entirely. Only 6 of 7 shows survive the proper pipeline.

### Consolidation outputs comma-formatted numbers
The `attendance`, `venue capacity`, and `product price` columns come out as `"3,844"` and `"$45.09"` — the Flask API's RobustScaler chokes on these. Must strip `$` and `,` before feeding to Step 4.

### venue capacity = attendance (pipeline bug)
In the consolidation output, `venue capacity` gets the same value as `attendance` (both `3,844` for Toronto). The tour summary CSV has a separate Capacity column (`3,000` for Toronto) but the pipeline appears to copy attendance into both.

### macOS AirPlay blocks port 5000
The Ashling Flask API defaults to port 5000, but macOS AirPlay Receiver uses it. Either:
- Disable AirPlay in System Settings > General > AirDrop & Handoff
- Change `flask_port = 5001` in `paths_config.txt` (currently set to 5001)

### Ashling venv missing dependencies
The `.venv` shipped without some packages needed for consolidation. Install:
```bash
cd "/Users/eugeneleychenko/Downloads/Ashling Manhead Share 3/Manhead_Handoff"
.venv/bin/pip install requests-cache openmeteo-requests retry-requests selenium webdriver-manager
```

---

## Full Directory Structure

```
Mar_26_testing/
├── CLAUDE.md                          ← this file
├── PLAN.md                            ← original planning doc
├── run_backtest.py                    ← old model backtest (Replit API)
├── run_backtest_new_model.py          ← new model backtest (shortcut, Flask API)
├── compare_models.py                  ← side-by-side old vs new comparison
│
├── raw_data/                          ← source data from atvenu
│   ├── tour_summary/                  ← 1 tour summary CSV
│   └── sales_reports/                 ← 7 per-show sales report CSVs
│
├── inputs/                            ← old model formatted inputs (11 cols)
├── inputs_new_model/                  ← new model enriched inputs
│   ├── backtest_input_new_*.csv       ← generated by shortcut script (21 cols)
│   ├── backtest_input_step2_enriched.csv       ← raw output from Ashling Step 2
│   └── backtest_input_step2_enriched_clean.csv ← cleaned (no commas/$) for Flask
│
├── predictions/                       ← old model prediction outputs
├── predictions_new_model/             ← new model prediction outputs + comparisons
│   └── backtest_pred_step2_pipeline_all_shows.csv ← from proper pipeline run
│
├── comparison/
│   ├── backtest_summary_all_shows.csv        ← old model summary
│   ├── backtest_summary_new_model.csv        ← new model (shortcut) summary
│   ├── model_comparison_summary.csv          ← side-by-side both models
│   ├── backtest_comparison_*.csv             ← per-show old model comparisons
│   └── backtest_all_shows_detail.csv         ← all shows old model, SKU-level
│
├── outputs/                           ← manual Streamlit validation files
│   ├── old-version-air-supply-toronto-*.csv
│   └── new-version-air-supply-toronto-*.csv
│
└── controls/                          ← manual spot-check
    └── sample_backtest_spotcheck_12_17_2025_toronto.csv
```

## Apps Reference

| App | URL | Port Config |
|-----|-----|-------------|
| Old Model Streamlit | http://localhost:8502 | hardcoded |
| New Model Streamlit | http://localhost:8504 | hardcoded |
| New Model Flask API | http://localhost:5001 | `paths_config.txt` → `flask_port = 5001` |
| Old Model API (remote) | https://fast-api-data-master-eugene59.replit.app | N/A |

### Starting all services
```bash
# Old model Streamlit
cd prediction && /Users/eugeneleychenko/Library/Python/3.9/bin/streamlit run prediction-streamlit.py --server.port 8502

# New model Flask API (start first, takes ~20s to load 2.9GB model)
cd "/Users/eugeneleychenko/Downloads/Ashling Manhead Share 3/Manhead_Handoff"
source .venv/bin/activate && python Python_scripts/run_all_products_sales_by_size_prediction_app.py

# New model Streamlit
cd "/Users/eugeneleychenko/Downloads/Ashling Manhead Share 3/Manhead_Handoff"
source .venv/bin/activate && streamlit run Python_scripts/streamlit_app.py --server.port 8504
```

---

## Cloud Deployment (Planned)

### Current Old Model — Replit Config (confirmed via browser inspection, March 2026)

| Setting | Value |
|---------|-------|
| **Replit Account** | eugene59 |
| **Plan** | Replit Core ($20/month, renews 3/29/2026) |
| **Repl Name** | FastApiDataMaster |
| **Deployment Type** | Autoscale |
| **Resources** | 4 vCPU / 8 GiB RAM / 3 Max instances |
| **Runtime** | Python 3.11, Nix channel `stable-24_05` |
| **Run Command** | `gunicorn --bind 0.0.0.0:5000 --reuse-port --reload main:app` |
| **Live URL** | https://fast-api-data-master-eugene59.replit.app |
| **Model files** | `persisted_models/` — 4 small joblib files (encoder, model, model_per_head, scaler) — all well under 1GB |

Key `.replit` settings:
```toml
modules = ["python-3.11"]
[nix]
channel = "stable-24_05"
[deployment]
deploymentTarget = "autoscale"
run = ["gunicorn", "--bind", "0.0.0.0:5000", "main:app"]
```

### New Model — Target Architecture

```
User → Render (Streamlit UI, single URL)
          ↓ HTTP POST /api/predict
       Replit (Flask API + 2.7GB model, Autoscale 4 vCPU / 8 GiB RAM)
          ↓ (Step 2 consolidation)
       Open-Meteo API (weather, free, no auth)
```

### Key Changes vs Local Version

**Flask API (Replit)**:
- Remove `paths_config.txt` dependency — use relative paths from within the Repl
- Simplify `audit_logger.py` — writes to disk which doesn't persist on Autoscale
- Add `/health` endpoint
- Fix comma-formatting bug server-side: strip `$` and `,` from numeric cols before scaling
- Pin `scikit-learn==1.7.2` (version model was trained on)
- Model cold-start: ~20-30s on first request after idle; consider Reserved VM ($12/mo) if unacceptable

**Streamlit UI (Render)**:
- Point `FLASK_API_URL` at Replit URL via env var (not localhost)
- Replace Selenium Spotify scraping with static CSV lookup (`spotify_monthly_listeners.csv`)
- Remove Step 3 (Train Model) — retraining not available from cloud
- Open-Meteo weather calls work as-is (plain HTTP requests)
- Add `requirements.txt` without Selenium/Playwright/webdriver-manager

### Deployment Files

All cloud-ready modified files live in `deploy/` (sibling to `Mar_26_testing/`):
```
deploy/
├── flask_api/          ← upload this to a new Replit Repl
│   ├── main.py         ← modified Flask app (no paths_config, /health endpoint, comma fix)
│   ├── audit_logger.py ← simplified (no-op safe version)
│   ├── requirements.txt
│   └── .replit         ← matches old model config
└── streamlit_ui/       ← deploy this to Render
    ├── streamlit_app.py ← modified (no Step 3, FLASK_API_URL from env, no Selenium)
    ├── consolidate_pipeline.py ← modified (CSV Spotify lookup instead of Selenium)
    ├── revenue_per_head.py
    ├── audit_logger.py ← simplified
    ├── requirements.txt
    ├── Dockerfile
    └── render.yaml
```

### Replit CLI / MCP Research (March 2026)

**No CLI or MCP for Replit deployment exists.** Research findings:
- Replit does not have an official CLI for pushing files or triggering deployments
- The community `replit-cli` (2021) is unmaintained and doesn't support deployment
- Replit's MCP support is one-directional: Replit Agent *consumes* external MCP servers, but Replit itself is not exposed as an MCP server
- There is no public API for programmatic deployment triggers
- **Deployment must be done manually via the Replit web UI**: create Repl → upload files → configure → click Publish
- We use `agent-browser` (headed browser automation) to perform the Replit upload and publish steps
