<coding_guidelines>
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
pip install streamlit pandas numpy requests openpyxl gql requests-toolbelt selenium webdriver-manager
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

---

## Organic Prediction Data Pipeline

Three Selenium scrapers feed the prediction model. All three log in to `artist.atvenu.com` with credentials stored in each script. They run headed (visible browser) by default.

### Pipeline Flowchart

```
bandsTableWithMerchIQ.csv (master band list + links)
        |                           |
        v                           v
Tour Forecast > Products     Tour Planning > Products
  (future dates + SKUs)        (price per SKU)
  tour_forecast_scraper.py     price_selenium.py
        |                           |
        v                           v
    Streamlit-ready CSV      band_sku_price_data.csv
        \                         /
         \                       /
          v                     v
         Organic Prediction (via API)
```

### Scraper 1: Band List Refresh — `band_list_refresh.py`

**Purpose**: Discovers all bands in the atVenu account, detects new bands, and finds their MerchIQ/Tour Forecast URLs (talent_id + tour_id).

**How it works**:
1. Logs in to `artist.atvenu.com`
2. Opens the account dropdown (`#react-select-mainNavAccountSelect-listbox`) to get all band names
3. For each NEW band (not already in CSV), selects it from the dropdown and extracts `talent_id` and `tour_id` from sidebar links
4. Re-checks existing bands without MerchIQ (they might have it now)
5. Backs up existing CSV before overwriting
6. Writes updated `bandsTableWithMerchIQ.csv`

**Run**: `python3 band_list_refresh.py`
**Runtime**: ~5-10 min for 200+ bands (depends on how many are new)
**Output**: `bandsTableWithMerchIQ.csv` — columns: `Band Name, Band Link, Has MerchIQ, MerchIQ Link`

**Key implementation details**:
- Uses `ActionChains` to click the react-select dropdown (avoids `ElementClickInterceptedException` from the single-value overlay div)
- Each band selection is wrapped in try/except so one failure doesn't kill the batch
- Chrome options: `--no-first-run --no-default-browser-check --disable-search-engine-choice-screen` (required to avoid Chrome dialogs blocking Selenium)

**atVenu URL patterns**:
- Band dashboard: `https://artist.atvenu.com/account/{account_id}/av/tours/{tour_id}/dashboard`
- Tour Forecast: `https://artist.atvenu.com/as/talents/{talent_id}/tours/{tour_id}/tour_forecast`
- Tour Forecast Products: `https://artist.atvenu.com/as/talents/{talent_id}/tour_forecast_merch_items?tour_id={tour_id}`
- Tour Planning Products: `https://artist.atvenu.com/as/talents/{talent_id}/tour_plan_merch_items?tour_id={tour_id}`

### Scraper 2: Tour Forecast Products — `tour_forecast_scraper.py`

**Purpose**: Scrapes all upcoming show dates, cities, and product SKUs for every band with MerchIQ. Outputs a Streamlit-ready CSV.

**How it works**:
1. Reads `bandsTableWithMerchIQ.csv` for bands with `Has MerchIQ = Yes`
2. Calls atVenu GraphQL API (`load_venue_capacity_from_api()` via `prediction/atvenu_api.py`) to pre-load venue capacity for all upcoming shows
3. For each band, navigates to their `tour_forecast_merch_items` page
4. Extracts show dates + cities from the header table (table index 9, `td.med-date` cells, format: `"MM/DD/YY\nCityName"`)
5. Extracts product names from `div.merch-item-row` divs
6. Extracts productType directly from the "Type" field in each `div.merch-item-row` DOM element (JS regex: `/Type\s+([A-Za-z][A-Za-z /-]*)/`), lowercased to match model encoder
7. Extracts SKUs from right-side data tables (`td.compact` cells)
8. Looks up prices from `prediction/band_sku_price_data.csv`
9. Looks up venue name/state/attendance from `tour_data.csv`, and venue capacity from the pre-loaded API data
10. Writes Streamlit-ready CSV

**Run**: `python3 tour_forecast_scraper.py`
**Runtime**: ~20 min for 160 bands (~8 sec/band)
**Output**: `tour_forecast_all_bands_{timestamp}.csv`
**Columns**: `artistName, Genre, showDate, venue name, venue city, venue state, attendance, venue capacity, product size, productType, product price, Item Name`

**DOM structure of the Tour Forecast Products page**:
- 19 tables total: tables 0-8 are left-side summary (2 cols), table 9 is the header with show dates, tables 10-18 are right-side per-show data (16+ cols)
- Show dates: `td.borderless.med-date.lighter` in table 9 (NOT th elements)
- SKU names: `td.compact` (first cell) in each row of tables 10-18
- Product names: first `h4/h3/strong` inside each `div.merch-item-row`
- Product type: extracted directly from page DOM via JS — looks for "Type" label then grabs the next text node (lowercased to match model encoder)

**productType mapping to model encoder**:
All atVenu Type values map 1:1 to the model encoder except `muscle tank` (becomes `unknown_category`). Known working types: `t-shirt`, `pullover hoodie`, `hat`, `koozie`, `accessories`, `blanket`, `bag`, `bandana`, `zip hoodie`, `long sleeve`, `tank top`, `crewneck`, `poster`, `vinyl`.

**Venue capacity from API**:
On startup, the scraper calls `load_venue_capacity_from_api()` which uses `prediction/atvenu_api.py` to query the atVenu GraphQL API for all upcoming shows across all bands. Returns venue capacity per (band, city, date) triple. This populates the `venue capacity` column (separate from `attendance` which comes from `tour_data.csv`).

**Known gaps**:
- Bands without upcoming shows produce 0 rows (expected)
- Some bands have shows but 0 SKU groups (products not set up in tour forecast)
- Genre mapping (`prediction/band_genre_map.csv`) is missing for newly added bands
- Venue/attendance is empty unless `tour_data.csv` has matching entries; the Streamlit app fills these via the atVenu live API at runtime
- `muscle tank` productType is not in the model encoder — maps to `unknown_category` (could remap to `tank top`)

### Scraper 3: SKU Prices — `price_selenium.py`

**Purpose**: Scrapes current product prices per SKU from Tour Planning > Products for all bands.

**How it works**:
1. Reads `bandsTableWithMerchIQ.csv` for MerchIQ links
2. Converts each link to a `tour_plan_merch_items` URL (handles both URL formats)
3. For each band, scrapes `div.merch-item-row` elements
4. Extracts SKU from `td.compact` and price from `input[data-qa="sale-price"]`
5. Writes to timestamped CSV

**Run**: `python3 price_selenium.py`
**Runtime**: ~15-20 min for all bands
**Output**: `band_product_data_{timestamp}.csv` — columns: `Band Name, SKU, Price`
**Canonical price file**: `prediction/band_sku_price_data.csv` (same format, manually updated from scraper output)

**URL conversion** (fixed April 2026):
- Pattern 1: `/talents/{id}/tours/{id}/...` in path -> `tour_plan_merch_items?tour_id={id}`
- Pattern 2: `/talents/{id}/tour_forecast_merch_items?tour_id={id}` -> `tour_plan_merch_items?tour_id={id}`
- The original script only handled Pattern 1, silently skipping bands with Pattern 2 URLs

---

## Data Files

### Root directory
| File | Description |
|------|-------------|
| `bandsTableWithMerchIQ.csv` | Master band list with MerchIQ links (201 bands, updated by `band_list_refresh.py`) |
| `tour_data.csv` | Historical tour data with venue/attendance (fetched from external URL) |
| `band_list_refresh.py` | Scraper #1: refreshes band list from atVenu dropdown |
| `tour_forecast_scraper.py` | Scraper #2: scrapes tour forecast products for all bands |
| `price_selenium.py` | Scraper #3: scrapes SKU prices from tour planning |
| `tour_forecast_all_bands_*.csv` | Output of scraper #2 (Streamlit-ready format) |
| `band_product_data_*.csv` | Output of scraper #3 (raw SKU prices) |

### `prediction/` directory
| File | Description |
|------|-------------|
| `prediction-streamlit.py` | Main Streamlit app (~800 lines) |
| `band_genre_map.csv` | MH band name -> Band Name -> Genre (124 entries, needs updating for new bands) |
| `band_sku_price_data.csv` | Canonical SKU -> Price lookup used by the Streamlit app |
| `atvenu_api.py` | atVenu GraphQL API helper for live attendance estimation |

### atVenu login credentials (used by all 3 scrapers)
- URL: `https://artist.atvenu.com/users/sign_in`
- Login form: `#userEmail`, `#userPassword`, `button[type="submit"]`

---

## Full Prediction Workflow (End to End)

### Step 1: Refresh band list (run periodically)
```bash
python3 band_list_refresh.py
```
Updates `bandsTableWithMerchIQ.csv` with any new bands and their MerchIQ links.

### Step 2: Scrape tour forecast products
```bash
python3 tour_forecast_scraper.py
```
Produces `tour_forecast_all_bands_{timestamp}.csv` with all upcoming shows and SKUs.

### Step 3: Scrape/update SKU prices
```bash
python3 price_selenium.py
```
Produces `band_product_data_{timestamp}.csv`. Merge into `prediction/band_sku_price_data.csv`.

### Step 4: Generate predictions
Upload the tour forecast CSV to the Streamlit app (Page 2) or use Page 1 to format+predict for a single band.

### Alternative: Single-band manual flow
1. Go to atvenu > Band > Tours > MerchIQ > Tour Forecast > Products
2. Download the Excel file
3. Upload to Streamlit Page 1 (File Formatting)
4. App formats it, fills venue/attendance, looks up prices
5. Carry forward to Page 2 for prediction

---

## Streamlit App Workflow Detail

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

---

## Recent Changes

### April 2026: Automated Data Pipeline Scrapers

**Problem**: The prediction pipeline required manual data collection from atVenu:
- No way to detect new bands added to the account
- Tour forecast products (future shows + SKUs) required manual Excel download per band
- SKU price scraper (`price_selenium.py`) had a regex bug silently skipping bands with `tour_forecast_merch_items?tour_id=` URL format

**Solution**: Built 3 Selenium scrapers to automate the full pipeline:

1. **`band_list_refresh.py`** (NEW) — Scrapes the atVenu account dropdown to discover all bands, detect new ones, and extract their talent_id/tour_id. Uses ActionChains for react-select interaction.

2. **`tour_forecast_scraper.py`** (NEW) — Batch-scrapes Tour Forecast > Products for all bands with MerchIQ. Extracts show dates from `td.med-date` cells, SKUs from right-side data tables, productType directly from DOM "Type" field (lowercased), and venue capacity from atVenu GraphQL API. Outputs Streamlit-ready CSV with 12 columns.

3. **`price_selenium.py`** (FIXED) — Fixed URL conversion regex to handle both `/tours/{id}/` path pattern and `?tour_id={id}` query parameter pattern.

**Chrome/Selenium notes**:
- All scrapers require `--no-first-run --no-default-browser-check --disable-search-engine-choice-screen` Chrome options to prevent dialogs from blocking automation
- The atVenu react-select dropdown requires `ActionChains.move_to_element().click()` — direct `element.click()` throws `ElementClickInterceptedException` due to the `react-select__single-value` overlay div
- Each band processing is wrapped in try/except so one failure doesn't kill the batch

### March 2026: Migrated API to Reserved VM with Self-Healing DO Download
**Problem**: Autoscale ephemeral disk caused the 701 MB model to be re-downloaded on every cold start (~15 min downtime).

**Solution**:
- Created new Replit project with **Reserved VM** (2 vCPU / 8 GB, $80/mo)
- Added self-healing download logic to `main.py`
- New API URL: `https://manhead-new-prediction-mar-26.replit.app`

### March 2026: Added atVenu Live API for Attendance Estimation
**Problem**: Stored `tour_data.csv` often lacks data for bands with upcoming shows.

**Solution**: `prediction/atvenu_api.py` calls atVenu GraphQL API, fetches venue capacity, estimates attendance as 80% of capacity.

---

## Data Source Reference

| Data | Source | Automated? | Script |
|------|--------|-----------|--------|
| Band list + MerchIQ links | atVenu account dropdown | Yes | `band_list_refresh.py` |
| Tour forecast (shows + SKUs + productType) | Tour Forecast > Products page + DOM Type field | Yes | `tour_forecast_scraper.py` |
| Venue capacity | atVenu GraphQL API (pre-loaded on scraper start) | Yes | `tour_forecast_scraper.py` via `atvenu_api.py` |
| SKU prices | Tour Planning > Products page | Yes | `price_selenium.py` |
| Attendance (stored) | `atvenu-forecast.votintsev.com/tour_data.csv` | Auto-fetched on app load | — |
| Attendance (live) | atVenu GraphQL API (80% of capacity) | Auto-fetched when stored data missing | `prediction/atvenu_api.py` |
| Genre mapping | `prediction/band_genre_map.csv` | No (static file, needs manual updates) | — |
| Sales Report | atvenu > Band > Reports > Tour > Sales Report | No (manual CSV export) | — |

## atVenu API Documentation

Local copies of the official atVenu API docs are at:
`/Users/eugeneleychenko/Projects/manhead-monthly-settlement-dash/AV_Docs/`

| File | Contents |
|------|----------|
| `How_to_use_Public_API.txt` | Auth, endpoints, GraphQL schema overview |
| `Settlement_Read_Specific_Examples.txt` | Settlement query examples |
| `Transaction_Read_Specific_Examples.txt` | Transaction query examples |
| `atVenu - API - HowtousetheatVenuPublicAPI.pdf` | PDF version of the above |
| `atVenu - API - SettlementReadSpecificExamples.pdf` | PDF version |
| `atVenu - API - Transaction Read Specific Examples.pdf` | PDF version |

## Hosted Apps

| App | URL | Source |
|-----|-----|--------|
| Old model Streamlit | https://mh-predict.streamlit.app/ | `prediction/prediction-streamlit.py` |
| New model Streamlit | https://mh-predict-new-model.streamlit.app/ | `prediction/prediction-streamlit-new-model.py` → `deploy/streamlit_ui/streamlit_app.py` |
| Prediction API (Replit) | https://manhead-new-prediction-mar-26.replit.app | `deploy/replit_main_upload/main.py` |

**New model Streamlit data files** (on Streamlit Cloud, served from `deploy/streamlit_ui/CSVs/features/`):
- `band_sku_price_data.csv` — must be synced from `prediction/band_sku_price_data.csv` before deploy
- `band_genre_map.csv`, `artist_metadata.csv`, `spotify_monthly_listeners.csv` — enrichment lookups
- Venue/attendance is fetched live (tour_data.csv URL + atVenu API fallback), not from local files

## Related Projects
- **Ashling New Model**: `/Users/eugeneleychenko/Downloads/Ashling 2026/Ashling Manhead Share 3/` — Flask + Streamlit 5-step pipeline with retrainable ExtraTreesRegressor model
- **atVenu Forecast App**: `/Users/eugeneleychenko/Downloads/AV Forecast/AtVenu-Forecast/` — Streamlit app for viewing tour data from atVenu API
- **Manhead Monthly Settlement Dashboard**: `/Users/eugeneleychenko/Projects/manhead-monthly-settlement-dash/` — contains atVenu API docs in `AV_Docs/`
</coding_guidelines>
