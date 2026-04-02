# Manhead Prediction App (Old/Current Production)

## Overview
Streamlit app for predicting merchandise sales at concerts. Deployed at https://mh-predict.streamlit.app/

Source: `prediction/prediction-streamlit.py`

## Running Locally
```bash
cd prediction
/Users/eugeneleychenko/Library/Python/3.9/bin/streamlit run prediction-streamlit.py --server.port 8502
```
URL: http://localhost:8502

## Dependencies
```bash
pip install streamlit pandas numpy requests openpyxl gql requests-toolbelt
```

## Architecture
- **Streamlit UI** (single file, ~800 lines) with 3 pages: File Formatting, Prediction, About
- **External Prediction API** at `https://manhead-new-prediction-mar-26.replit.app` (Flask + gunicorn on Replit)
  - `/predict/size` — Sales Quantity By Size
  - `/predict/perhead` — Per Head Revenue
  - `/health` — Returns `{"model_loaded": bool, "state": "ready"|"loading"|"downloading"|"error", "status": "ok", "download_progress": {...}}`
  - `/status` — Detailed artifact info, memory snapshot, system info
  - Replit project: https://replit.com/@eugene59/ManheadNewPredictionMar26
- **atVenu GraphQL API** at `https://api.atvenu.com` — fetches venue capacity for future shows

### Prediction API — Model & Cold Start Notes
- Model file: `model_retrained.joblib` — **compressed 701 MB** on disk, ~3 GB RSS when loaded
- Other artifacts: `label_encoder_retrained.joblib` (44 KB), `robust_scaler_retrained.joblib` (3.1 KB)
- Deployment type: **Reserved VM** (2 vCPU / 8 GB RAM, $80/mo) — always-on, **persistent disk**
- Cold start after restart: **~30-60s** (deserialization only — model file stays on disk permanently)
- **First boot only**: downloads 701 MB model from DO Spaces (~2-3 min), then persists forever
- Model source: `https://mh-forecast.nyc3.cdn.digitaloceanspaces.com/model_retrained.joblib`
- Self-healing download logic in `main.py` (`_download_if_missing()`): checks disk on every boot, re-downloads only if file is missing or < 500 MB
- **Known issue**: `check_api_health()` in the Streamlit app only checks HTTP 200, not `state == "ready"`, so it can show "API available ✅" while the model is still loading

### Why Reserved VM (not Autoscale)
- Autoscale has **ephemeral disk** — model file disappears on every scale-to-zero, causing 15+ min cold starts (re-download 701 MB + load)
- Reserved VM has **persistent disk** — model survives restarts
- 4 GB RAM is not enough: compressed model expands to ~3 GB during deserialization; 8 GB required
- `mmap_mode='r'` (joblib) cannot be used — Replit containers have a hard file descriptor limit that mmap exceeds for this model size

### Local `deploy/replit_main_upload/main.py`
Source of truth for the deployed code (~560 lines). Key sections:
- `_ARTIFACT_URLS` — hardcoded DO Spaces URLs with env var overrides
- `_ARTIFACT_MIN_BYTES` — `model_retrained.joblib`: 500 MB minimum (rejects stale/partial files)
- `_download_if_missing()` — download with `.downloading` lock file + progress tracking
- `_model_state["download_progress"]` — exposed on `/health` during active download
- `_load_models()` — background thread: download check → `joblib.load(m_path)` (no mmap)

### Test File for Predictions
Use `air_supply_formatted_3_4_26.csv` (root dir, 252 rows) — already formatted with the correct columns:
`artistName, Genre, showDate, venue name, venue city, venue state, attendance, product size, productType, product price, Item Name`
Upload directly on Prediction page (Page 2), no reformatting needed.

## Data Files (in `prediction/`)
- `band_genre_map.csv` — maps MH band name → Band Name → Genre
- `band_sku_price_data.csv` — SKU → Price lookup (populated by `price_selenium.py`)
- `atvenu_api.py` — helper module for atVenu GraphQL API calls

## Workflow

### File Formatting (Page 1)
1. User selects band from dropdown (63 Manhead bands)
2. User uploads inventory file (CSV/Excel) from atvenu Tour Forecast > Products
3. Show dates/cities are parsed from column headers (format: `"City - MM/DD/YY ($X.XX/head)"`)
4. Product prices looked up by SKU from `band_sku_price_data.csv`
5. Venue name, state, attendance filled from stored tour data (external CSV)
6. **If attendance is missing**: falls back to atVenu live API, fetches venue capacity, uses 80% as estimated attendance (cached per band per session)
7. Output: formatted CSV ready for prediction

### Prediction (Page 2)
1. Upload formatted CSV or carry forward from Page 1
2. Choose: "Sales Quantity By Size" or "Per Head Revenue"
3. Data POSTed to Replit FastAPI, predictions returned
4. Download results as CSV

## Recent Changes (March 2026)

### Migrated API to Reserved VM with Self-Healing DO Download (March 20, 2026)
**Problem**: Autoscale ephemeral disk caused the 701 MB model to be re-downloaded on every cold start (~15 min downtime). The model would also silently disappear if the instance recycled.

**Solution**:
- Created new Replit project with **Reserved VM** (2 vCPU / 8 GB, $80/mo) — persistent disk, always on
- Added self-healing download logic to `main.py`: on boot, checks if model is on disk; if missing/stale, downloads from DO Spaces automatically
- New API URL: `https://manhead-new-prediction-mar-26.replit.app`
- Old URL (`manhead-new-model-api.replit.app`) is still running on Autoscale but should be decommissioned

**What was tried and failed**:
- `mmap_mode='r'` (joblib): hits Replit's hard file descriptor limit; "Too many open files" error
- Uncompressed 2.78 GB model on 1 vCPU / 4 GB: OOM killed during load
- Compressed 701 MB model on 1 vCPU / 4 GB: OOM killed (~3 GB RSS needed for deserialization)
- `ulimit -n 65536` in run command: "Operation not permitted" on Replit containers

**Files changed**:
- `deploy/replit_main_upload/main.py` — complete rewrite with DO download logic, health tracking, progress reporting



### Added: atVenu Live API for Attendance Estimation
**Problem**: The stored `tour_data.csv` (fetched from external URL) often lacks data for bands with upcoming shows, leaving attendance at 0 and making predictions impossible.

**Solution**: Added `prediction/atvenu_api.py` which:
- Calls the atVenu GraphQL API (`https://api.atvenu.com`) using API token
- Fetches venue capacity for all future shows
- Estimates attendance as 80% of capacity
- Includes a city-to-state mapping for US/Canadian cities (the API doesn't return state directly)
- Results cached in `st.session_state` to avoid re-fetching on UI interactions

**Files changed**:
- `prediction/atvenu_api.py` — NEW: atVenu GraphQL API helper
- `prediction/prediction-streamlit.py` — Added `fill_missing_from_live_api()`, imported `atvenu_api`, wired into File Formatting flow after `update_venue_details()`

**Suppressed noisy warnings**: `update_venue_details()` no longer emits per-row "No venue match found" warnings when a band isn't in stored tour data. Shows a single info message instead.

## Data Source Reference

| Data | Source | How |
|------|--------|-----|
| Inventory/Products | atvenu.com > Band > Tours > MerchIQ > Tour Forecast > Products | Excel download |
| Attendance (stored) | `atvenu-forecast.votintsev.com/tour_data.csv` | Auto-fetched on app load |
| Attendance (live) | atVenu GraphQL API → 80% of capacity | Auto-fetched when stored data missing |
| Product Prices | `band_sku_price_data.csv` | Populated by `price_selenium.py` scraping atvenu |
| Genre | `band_genre_map.csv` | Static local file |
| Sales Report (manual) | atvenu.com > Band > Reports > Tour > Sales Report | CSV export, has Avg. Price per SKU |

## Related Projects
- **Ashling New Model**: `/Users/eugeneleychenko/Downloads/Ashling Manhead Share 3/` — Flask + Streamlit 5-step pipeline with retrainable ExtraTreesRegressor model
- **atVenu Forecast App**: `/Users/eugeneleychenko/Downloads/AV Forecast/AtVenu-Forecast/` — Streamlit app for viewing tour data from atVenu API
