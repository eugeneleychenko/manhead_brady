# Testing Runbook

This document explains how to run the full testing workflow for:
- hosted old/new API parity
- new-model Streamlit UI parity (local + cloud)
- comparison app parity (Mode A)
- converter Step 6 smoke testing
- final bind pass/fail report generation

All commands below are run from the repo root:
`manhead_brady`

---

## 1) Prerequisites

- Python 3 with dependencies installed (at minimum: `pandas`, `requests`, `numpy`, `streamlit`)
- Access to hosted APIs:
  - old: `https://fast-api-data-master-eugene59.replit.app`
  - new: `https://manhead-new-model-api.replit.app`
- Access to Streamlit apps:
  - new-model app: `https://mh-predict-new-model.streamlit.app`
  - comparison app: `https://manheadbrady-eagsteu3r5xgac6nwlavff.streamlit.app/`
- Canonical input files must both exist:
  - `deploy/air_supply_formatted_3_4_26.csv`
  - `air_supply_formatted_3_4_26.csv`

Reference docs:
- `prediction/streamlit_cloud_deploy_notes.md`
- `Mar_26_testing/bind_outputs/README.md`
- `Mar_26_testing/bind_validation.py`

---

## 2) Bind CLI Commands

Use the bind utility for all deterministic checks:

```bash
python3 Mar_26_testing/bind_validation.py --help
```

Primary commands:

```bash
python3 Mar_26_testing/bind_validation.py check-canonical
python3 Mar_26_testing/bind_validation.py make-baseline --model old
python3 Mar_26_testing/bind_validation.py make-baseline --model new
python3 Mar_26_testing/bind_validation.py compare --left baseline_new --right new_local_streamlit
python3 Mar_26_testing/bind_validation.py compare --left baseline_new --right new_cloud_streamlit
python3 Mar_26_testing/bind_validation.py check-artifact --name comparison_mode_a
python3 Mar_26_testing/bind_validation.py validate-comparison-columns
python3 Mar_26_testing/bind_validation.py final-report
```

---

## 3) Full Final Pass Procedure

### Phase A - Preflight

1. Verify canonical input parity:

```bash
python3 Mar_26_testing/bind_validation.py check-canonical
```

Expected: `ok: true` and both CSVs have 252 rows.

2. Rebuild baselines:

```bash
python3 Mar_26_testing/bind_validation.py make-baseline --model old
python3 Mar_26_testing/bind_validation.py make-baseline --model new
```

Expected artifacts:
- `Mar_26_testing/bind_outputs/baseline_old.csv`
- `Mar_26_testing/bind_outputs/baseline_new.csv`

---

### Phase B - New-Model UI Parity

#### Local UI parity

1. Start local Streamlit app:

```bash
PREDICTION_API_BASE_URL="https://manhead-new-model-api.replit.app" \
streamlit run prediction/prediction-streamlit-new-model.py --server.port 8501
```

2. Open `http://localhost:8501`.
3. In **Step 4**, upload `deploy/air_supply_formatted_3_4_26.csv`.
4. Click **Run prediction** and download CSV.
5. Save downloaded file as:
   `Mar_26_testing/bind_outputs/new_local_streamlit.csv`

6. Validate:

```bash
python3 Mar_26_testing/bind_validation.py compare --left baseline_new --right new_local_streamlit
```

Expected: `status: MATCH`.

#### Cloud UI parity

1. Open `https://mh-predict-new-model.streamlit.app`.
2. In **Step 4**, upload `deploy/air_supply_formatted_3_4_26.csv`.
3. Click **Run prediction** and download CSV.
4. Save downloaded file as:
   `Mar_26_testing/bind_outputs/new_cloud_streamlit.csv`

5. Validate:

```bash
python3 Mar_26_testing/bind_validation.py compare --left baseline_new --right new_cloud_streamlit
```

Expected: `status: MATCH`.

---

### Phase C - Comparison App Parity (Mode A)

1. Open `https://manheadbrady-eagsteu3r5xgac6nwlavff.streamlit.app/`.
2. In **Mode A**, upload `deploy/air_supply_formatted_3_4_26.csv`.
3. Run comparison and download CSV.
4. Save downloaded file as:
   `Mar_26_testing/bind_outputs/comparison_mode_a.csv`

5. Validate output shape:

```bash
python3 Mar_26_testing/bind_validation.py check-artifact --name comparison_mode_a
```

6. Validate old/new columns against baselines:

```bash
python3 Mar_26_testing/bind_validation.py validate-comparison-columns
```

Expected: both old and new checks are `MATCH`.

---

### Phase D - Converter V1 Smoke Test

1. In local app (`http://localhost:8501`), go to:
   **Step 6: Sales Report -> Prediction Input Converter**
2. Upload:
   - Sales report: `Mar_26_testing/raw_data/sales_reports/air-supply_Sales-Report_all-tours-for-02-22-2026.csv`
   - Tour summary: `Mar_26_testing/raw_data/tour_summary/air-supply_Tour-Summary_all-tours-for-05-01-2025-to-02-22-2026.csv`
3. Set Band name = `Air Supply`.
4. Click **Convert to prediction input CSV**.
5. Verify:
   - success banner appears
   - preview table appears
   - output has 21 columns
   - **Download converted prediction input CSV** works
   - **Send to Predict (coming soon)** is present and disabled

Optional sanity check (command-line converter logic smoke):

```bash
python3 -m py_compile deploy/streamlit_ui/converter_utils.py deploy/streamlit_ui/streamlit_app.py
```

---

### Phase E - Final Bind Report

Run:

```bash
python3 Mar_26_testing/bind_validation.py final-report
```

Expected output files:
- `Mar_26_testing/bind_outputs/bind_report.csv`
- `Mar_26_testing/bind_outputs/bind_report.md`

Expected result: overall `PASS`.

Pass criteria (all required):
1. `old_api` vs `comparison_old_column` => `MATCH`
2. `new_api` vs `new_local_streamlit` => `MATCH`
3. `new_api` vs `new_cloud_streamlit` => `MATCH`
4. `new_api` vs `comparison_new_column` => `MATCH`

---

## 4) Troubleshooting

- **New API stuck loading (`503` / `state: loading`)**
  - wait and retry `make-baseline --model new`
  - cold starts can take several minutes

- **Cloud Streamlit sleeping**
  - open app and wake it
  - retry upload/run after wake-up

- **Comparison artifact validation fails**
  - confirm `comparison_mode_a.csv` has required old/new predicted quantity columns
  - rerun Mode A and redownload

- **Row mismatch**
  - verify canonical file used is `air_supply_formatted_3_4_26.csv`
  - rerun baselines before re-checking UI outputs
