# Deployment Notes — Ashling New Model API

> Canonical deployment docs now live in:
> `Ashling Manhead Share 3/Manhead_Handoff/replit-deployment/DEPLOYMENT_NOTES.md`
>
> This copy is retained for local historical context inside `manhead_brady`.

## Current Rollout Status (March 8, 2026)

```
[Streamlit Frontend] → [Size API: Replit Autoscale] + [Per-Head API: Legacy Replit] → [Model on DO Spaces]
```

- **Size API (new)**: `https://manhead-new-model-api.replit.app` — Replit Autoscale (4 vCPU / 8 GiB RAM)
- **Per-head API (legacy)**: `https://fast-api-data-master-eugene59.replit.app`
- **Size rollback target**: `https://fast-api-data-master-eugene59.replit.app`
- **Model storage**: DigitalOcean Spaces

### Active model artifact URL (use origin, not CDN)
- `https://mh-forecast.nyc3.digitaloceanspaces.com/model_retrained.joblib` (735000866 bytes, compressed)
- The CDN URL currently serves a stale 2.9 GB object for the same key; avoid using the CDN URL for deployment downloads.

### Validation snapshot
- `/health` on new API reports `model_loaded: true`, `state: ready`, `last_error: null`
- `/status` confirms all three artifacts present; `model_retrained.joblib` is ~700.95 MB
- `/api/predict` smoke test with `air_supply_formatted_3_4_26.csv`: HTTP 200, 252 output rows
- Local Streamlit Step 4 check on `http://localhost:8503`: predictions generated successfully, preview table and CSV download confirmed

### Frontend routing and rollback
- `prediction/prediction-streamlit.py` now supports split routing via env vars:
  - `SIZE_API_BASE_URL` (default: new size API)
  - `PERHEAD_API_BASE_URL` (default: legacy per-head API)
- **Rollback**: set `SIZE_API_BASE_URL=https://fast-api-data-master-eugene59.replit.app`

---

## Historical Notes (March 7, 2026)

## Model Files (hosted on DO Spaces)

| File | Size | URL |
|------|------|-----|
| `model_retrained.joblib` | 2.717 GB | `https://mh-forecast.nyc3.cdn.digitaloceanspaces.com/new_model/model_retrained.joblib` |
| `robust_scaler_retrained.joblib` | 3.1 KB | `https://mh-forecast.nyc3.cdn.digitaloceanspaces.com/new_model/robust_scaler_retrained.joblib` |
| `label_encoder_retrained.joblib` | 44 KB | `https://mh-forecast.nyc3.cdn.digitaloceanspaces.com/new_model/label_encoder_retrained.joblib` |

## What Works

- **Dev URL** (`https://3e229c21-...kirk.replit.dev`): Model loads, health check returns `model_loaded: true`, predictions return correct results (tested with 22-row Air Supply CSV)
- **Background thread model loading**: Flask starts immediately, model loads in a separate thread
- **Root route `/`**: Returns 200 so Replit health check passes even before model is loaded
- **`_download_if_missing()`**: Downloads model files from URLs set in Replit Secrets if not present on disk

## What Failed (and Why)

### Attempt 1: Autoscale Deployment
- **What**: Tried to deploy with 2.7GB model in the workspace using Autoscale (4 vCPU / 8 GiB RAM)
- **Result**: Container build timed out every time
- **Why**: Autoscale builds a Docker container that includes all workspace files. A 2.7GB model makes the container too large to build within Replit's build timeout.

### Attempt 2: Reserved VM (0.5 vCPU / 2 GiB RAM) — model in workspace
- **What**: Switched to Reserved VM which copies files directly (no container build). Model was in the workspace.
- **Result**: Deployment timed out at health check (step 3) every time
- **Why**: Model deserialization takes ~30+ seconds and holds Python's **Global Interpreter Lock (GIL)**. Even with background threads, the GIL prevents the Flask request handler from responding to health check probes during model loading. Gunicorn sync workers are single-threaded per-worker, so a GIL-blocked worker can't serve any requests.

### Attempt 3: Background thread + multiple workers
- **What**: Moved model loading to `threading.Thread(daemon=True)`, added `--workers 2` to gunicorn
- **Result**: Still timed out
- **Why**: Each gunicorn worker independently imports `main.py` and starts its own background thread. Both workers hold their GIL during deserialization. No worker is free to handle health checks.

### Attempt 4: `machineType` in `.replit`
- **What**: Added `machineType = "e2-standard-2"` to `[deployment]` section
- **Result**: Ignored — VM stayed at 0.5 vCPU / 2 GiB RAM
- **Why**: Machine size is only configurable through the Replit Publish UI wizard, not `.replit` file.

## Root Cause: Python GIL + Health Check Timeout

The fundamental issue: Python's GIL is held during CPU-bound model deserialization (joblib unpickling a 2.7GB ExtraTreesRegressor). No amount of threading can fix this because threads share the GIL. The only solutions are:

1. **Don't load the model during deployment** (our final approach)
2. Use multiprocessing (separate process for model loading, but adds complexity)
3. Use a VM large enough that loading is fast enough to beat the health check timeout

## Final Approach: External Model Storage

1. Model files hosted on Digital Ocean Spaces (not in Replit workspace)
2. Deployment is lightweight (~50KB of code) — deploys instantly
3. Health check passes immediately (`model_loaded: false` is still HTTP 200)
4. Background thread downloads model from DO Spaces after deployment succeeds
5. Once downloaded and loaded, `model_loaded: true` and predictions work
6. Reserved VM is always-on, so model persists on disk — only downloads once

## Replit Configuration

### Secrets
| Key | Value |
|-----|-------|
| `MODEL_DOWNLOAD_URL` | `https://mh-forecast.nyc3.cdn.digitaloceanspaces.com/new_model/model_retrained.joblib` |
| `SCALER_DOWNLOAD_URL` | `https://mh-forecast.nyc3.cdn.digitaloceanspaces.com/new_model/robust_scaler_retrained.joblib` |
| `ENCODER_DOWNLOAD_URL` | `https://mh-forecast.nyc3.cdn.digitaloceanspaces.com/new_model/label_encoder_retrained.joblib` |
| `SESSION_SECRET` | (random string for Flask) |

### `.replit` deployment section
```toml
[deployment]
deploymentTarget = "gce"
run = ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "300", "main:app"]
```

### Key code in `main.py`
- `threading.Thread(target=_load_models_background, daemon=True).start()` — non-blocking startup
- `@app.route("/")` and `@app.route("/health")` — both return HTTP 200 regardless of model state
- `_download_if_missing()` — downloads from DO Spaces URL if file not on disk

## Cost
- Replit Core plan: $20/month (includes credits)
- Reserved VM (0.5 vCPU / 2 GB): $20/month (offset by plan credits)
- DO Spaces: ~$5/month (250GB storage + 1TB transfer included)

## Re-deploying After VM Restart
If the Reserved VM restarts and the model files are lost:
1. The app starts, health check passes (model_loaded: false)
2. Background thread re-downloads from DO Spaces (~5-10 min for 2.7GB)
3. Once loaded, predictions resume automatically

---

## Current Status — March 7, 2026

### Deployment
- Production URL live: `https://manhead-flask-api.replit.app` — returns HTTP 200
- Published ~1 hour after the final lightweight-workspace approach
- All 4 Secrets confirmed visible in the Production app secrets panel in the Replit UI: `SESSION_SECRET`, `MODEL_DOWNLOAD_URL`, `SCALER_DOWNLOAD_URL`, `ENCODER_DOWNLOAD_URL`

### Problem: Model Never Loads (`model_loaded: false` after 90+ minutes)
Polled `/health` every 2 minutes for 90+ minutes — always returns `{"model_loaded": false, "status": "loading"}`.

**Deployment logs observed** (via Replit Publishing > Logs tab):
- 10:12:11–10:12:52: Repeated `System` entries — `healthcheck failed error=healthc...` (expected: Flask hadn't started yet)
- 10:12:41+: `User` entries — gunicorn worker PIDs 17, 21, 22 started up successfully
- **No log entries after 10:12:51** — no "Downloading..." messages, no errors, no "Model loaded" message, nothing

### Suspected Root Causes (unconfirmed — needs investigation)

**Theory 1 — Not enough RAM to load the model (most likely)**
The VM is 2 GiB RAM. The model file is 2.717 GB on disk. Python/joblib fully deserializes the model into in-memory Python objects by default (no memory-mapping). An ExtraTreesRegressor with 2.7 GB on disk likely needs 5–10 GB of RAM when expanded into Python objects. The background thread would hit a `MemoryError`, which is caught by the broad `except Exception` block and printed — but `print()` output from background threads in gunicorn workers may not surface in Replit's production log stream.

**Theory 2 — Secrets not available to production workers**
Some secrets showed a "broken chain" icon in the Replit UI (vs. a solid chain icon for others). If `MODEL_DOWNLOAD_URL` is not actually set in the production environment, `_download_if_missing()` hits the `if not url: return` early exit, the model file never exists on disk, and `load()` raises `FileNotFoundError` — which is silently caught and printed (same visibility issue as above).

**Theory 3 — Race condition / file corruption with 2 workers**
Both gunicorn workers start background download threads simultaneously. `urllib.request.urlretrieve` writes directly to the target path with no locking. If both workers write to `models/model_retrained.joblib` concurrently, the file could be corrupted, causing `joblib.load()` to fail.

### Next Steps to Try (in order of effort)

1. **Add a `/status` debug endpoint** — reports env var presence (true/false, not values), disk file sizes in MODELS_DIR, and available system memory. Deploy and call it to immediately confirm which theory is correct.

2. **Try `mmap_mode='r'` in `joblib.load()`** — memory-maps the file instead of copying it fully into RAM. For a model this large, this could reduce peak RAM usage from ~8 GB to near-zero (pages loaded on demand). May work on 2 GiB VM.

3. **Add download locking** — use a `.lock` file or `threading.Lock` so only one worker downloads at a time, eliminating the race condition.

4. **Upgrade VM** — if RAM is the confirmed bottleneck, Replit's next tier is 2 vCPU / 8 GiB RAM at $80/month.
