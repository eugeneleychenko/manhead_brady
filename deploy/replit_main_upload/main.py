import sys
import os
import re
import threading
import logging
import time
import urllib.request
from joblib import load
from io import BytesIO
import numpy as np
import pandas as pd
import datetime as dt
from flask import Flask, request, jsonify

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(BASE_DIR, "models")

app = Flask(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(process)d:%(threadName)s] %(message)s",
)
app.logger.setLevel(logging.INFO)


def _utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Model state
# ---------------------------------------------------------------------------

model = scaler = encoder = None
_models_loaded = False
_models_lock = threading.Lock()
_model_state_lock = threading.Lock()
_model_state = {
    "state": "starting",
    "last_event": "Worker booted",
    "last_error": None,
    "updated_at": _utc_now_iso(),
    "load_time_seconds": None,
    "download_progress": None,  # set during download: {file, downloaded_mb, total_mb, percent}
}


def _set_model_state(state: str, last_event: str, last_error=None, load_time=None):
    with _model_state_lock:
        _model_state["state"] = state
        _model_state["last_event"] = last_event
        _model_state["last_error"] = last_error
        _model_state["updated_at"] = _utc_now_iso()
        if load_time is not None:
            _model_state["load_time_seconds"] = round(load_time, 2)


def _get_model_state_snapshot():
    with _model_state_lock:
        return dict(_model_state)


def _is_model_loaded() -> bool:
    with _models_lock:
        return _models_loaded


def _get_artifact_info(file_name: str):
    file_path = os.path.join(MODELS_DIR, file_name)
    exists = os.path.exists(file_path)
    size_bytes = os.path.getsize(file_path) if exists else 0
    return {
        "exists": exists,
        "size_bytes": size_bytes,
        "size_mb": round(size_bytes / (1024 * 1024), 2),
    }


def _get_memory_snapshot():
    total_mb = available_mb = process_max_rss_mb = None
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
        total_pages = os.sysconf("SC_PHYS_PAGES")
        available_pages = os.sysconf("SC_AVPHYS_PAGES")
        total_mb = round((page_size * total_pages) / (1024 * 1024), 2)
        available_mb = round((page_size * available_pages) / (1024 * 1024), 2)
    except (AttributeError, OSError, ValueError):
        pass
    try:
        import resource
        ru = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        process_max_rss_mb = round(
            ru / (1024 * 1024) if sys.platform == "darwin" else ru / 1024, 2
        )
    except Exception:
        pass
    return {
        "total_mb": total_mb,
        "available_mb": available_mb,
        "process_max_rss_mb": process_max_rss_mb,
    }


# ---------------------------------------------------------------------------
# Artifact download — fetches from DO Spaces if file is missing or empty.
# Uses a .lock file so only one gunicorn worker downloads at a time.
# Progress is written to _model_state["download_progress"] for /health.
# ---------------------------------------------------------------------------

# Default URLs — hardcoded so the app works even if Secrets aren't set.
# Override via env vars MODEL_DOWNLOAD_URL / SCALER_DOWNLOAD_URL / ENCODER_DOWNLOAD_URL.
_ARTIFACT_URLS = {
    "model_retrained.joblib": (
        os.environ.get("MODEL_DOWNLOAD_URL") or
        "https://mh-forecast.nyc3.cdn.digitaloceanspaces.com/model_retrained.joblib"
    ),
    "robust_scaler_retrained.joblib": (
        os.environ.get("SCALER_DOWNLOAD_URL") or
        "https://mh-forecast.nyc3.cdn.digitaloceanspaces.com/new_model/robust_scaler_retrained.joblib"
    ),
    "label_encoder_retrained.joblib": (
        os.environ.get("ENCODER_DOWNLOAD_URL") or
        "https://mh-forecast.nyc3.cdn.digitaloceanspaces.com/new_model/label_encoder_retrained.joblib"
    ),
}


_ARTIFACT_MIN_BYTES = {
    "model_retrained.joblib": 500_000_000,  # compressed ~701 MB
    "robust_scaler_retrained.joblib": 1024,
    "label_encoder_retrained.joblib": 1024,
}


def _download_if_missing(file_name: str) -> None:
    """Download artifact from DO Spaces if not already on disk (or too small)."""
    url = _ARTIFACT_URLS[file_name]
    file_path = os.path.join(MODELS_DIR, file_name)
    lock_path = file_path + ".downloading"
    min_bytes = _ARTIFACT_MIN_BYTES.get(file_name, 1024)

    # Already present and correct size — skip
    if os.path.exists(file_path) and os.path.getsize(file_path) >= min_bytes:
        app.logger.info("%s already on disk (%.1f MB), skipping download.",
                        file_name, os.path.getsize(file_path) / (1024 * 1024))
        return

    # Another worker holds the lock — wait up to 20 minutes then re-check
    if os.path.exists(lock_path):
        app.logger.info("%s: another worker is downloading, waiting...", file_name)
        for _ in range(1200):
            time.sleep(1)
            if not os.path.exists(lock_path):
                break
        if os.path.exists(file_path) and os.path.getsize(file_path) >= min_bytes:
            return

    # Remove stale/wrong-size file before downloading
    if os.path.exists(file_path):
        app.logger.info("Removing stale %s (%.1f MB, need >= %.1f MB)",
                        file_name, os.path.getsize(file_path) / (1024*1024), min_bytes / (1024*1024))
        os.remove(file_path)

    os.makedirs(MODELS_DIR, exist_ok=True)
    try:
        with open(lock_path, "w") as f:
            f.write(str(os.getpid()))
    except Exception:
        pass

    tmp_path = file_path + ".tmp"
    try:
        app.logger.info("Downloading %s from %s ...", file_name, url)

        def _reporthook(block_num, block_size, total_size):
            if total_size <= 0:
                return
            downloaded = min(block_num * block_size, total_size)
            total_mb = round(total_size / (1024 * 1024), 1)
            downloaded_mb = round(downloaded / (1024 * 1024), 1)
            percent = round(downloaded / total_size * 100, 1)
            with _model_state_lock:
                _model_state["download_progress"] = {
                    "file": file_name,
                    "downloaded_mb": downloaded_mb,
                    "total_mb": total_mb,
                    "percent": percent,
                }
            if block_num % 500 == 0:
                app.logger.info("  %s: %.1f / %.1f MB (%.0f%%)",
                                file_name, downloaded_mb, total_mb, percent)

        urllib.request.urlretrieve(url, tmp_path, reporthook=_reporthook)
        os.replace(tmp_path, file_path)
        with _model_state_lock:
            _model_state["download_progress"] = None
        app.logger.info("Downloaded %s (%.1f MB)",
                        file_name, os.path.getsize(file_path) / (1024 * 1024))
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
    finally:
        try:
            os.remove(lock_path)
        except FileNotFoundError:
            pass


# ---------------------------------------------------------------------------
# Model loading — runs in a daemon thread at startup so health check returns
# immediately while the model is being deserialised in the background.
# ---------------------------------------------------------------------------

def _load_models():
    global model, scaler, encoder, _models_loaded

    # Skip if another worker already loaded the model in this process
    if _is_model_loaded():
        app.logger.info("Model already loaded in RAM, skipping.")
        return

    try:
        # Step 1 — download any missing artifacts from DO Spaces
        _set_model_state("downloading", "Checking / downloading artifacts from DO Spaces")
        for artifact in ("model_retrained.joblib", "robust_scaler_retrained.joblib", "label_encoder_retrained.joblib"):
            _download_if_missing(artifact)

        # Step 2 — deserialize with mmap for the large model file
        _set_model_state("loading", "Deserializing artifacts (mmap mode)")
        t0 = time.time()

        m_path = os.path.join(MODELS_DIR, "model_retrained.joblib")
        s_path = os.path.join(MODELS_DIR, "robust_scaler_retrained.joblib")
        e_path = os.path.join(MODELS_DIR, "label_encoder_retrained.joblib")

        for p in (m_path, s_path, e_path):
            if not os.path.exists(p):
                raise FileNotFoundError(f"Required artifact missing after download: {p}")

        app.logger.info("Loading model from %s ...", m_path)
        m = load(m_path)
        app.logger.info("Loading scaler ...")
        s = load(s_path)
        app.logger.info("Loading encoder ...")
        e = load(e_path)

        elapsed = time.time() - t0
        with _models_lock:
            model, scaler, encoder, _models_loaded = m, s, e, True
        _set_model_state("ready", "All artifacts loaded", load_time=elapsed)
        app.logger.info("All artifacts loaded in %.1fs (mmap mode)", elapsed)

    except Exception as ex:
        _set_model_state("error", "Model loading failed", str(ex))
        app.logger.exception("Model loading failed")


threading.Thread(target=_load_models, daemon=True, name="model-loader").start()


# ---------------------------------------------------------------------------
# Feature metadata
# ---------------------------------------------------------------------------

input_categorical_features = [
    "artistName", "Genre", "HolidayStatus",
    "venue name", "venue city", "venue state", "venue country",
    "venue postalCode", "merch category", "productType", "product size",
]

input_numerical_features = [
    "Show Day", "Show Month", "Day of Week Num",
    "attendance", "product price",
    "temperature_daily_mean", "rain", "snowfall",
    "spotifyMonthlyListeners", "Instagram", "venue capacity",
]

output_features = [
    "artistName", "Genre", "showDate", "HolidayStatus",
    "venue name", "venue city", "venue state", "venue country", "venue postalCode",
    "merch category", "productType", "product size",
    "Show Day", "Show Month", "Day of Week Num",
    "attendance", "product price", "temperature_daily_mean",
    "spotifyMonthlyListeners", "Instagram", "venue capacity",
    "predicted_sales_quantity", "%_item_sales_per_category",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clean_numeric_cols(df: pd.DataFrame) -> pd.DataFrame:
    for col in input_numerical_features:
        if col in df.columns and df[col].dtype == object:
            df[col] = (
                df[col].astype(str)
                .apply(lambda x: re.sub(r"[\$,\s]", "", x))
            )
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def build_model_inputs(df: pd.DataFrame, route_tag: str = "api"):
    if "showDate" not in df.columns:
        raise KeyError("Missing required column 'showDate' in input data.")

    df = _clean_numeric_cols(df)
    df["showDate"] = pd.to_datetime(df["showDate"])
    df["Show Day"] = df["showDate"].dt.day
    df["Show Month"] = df["showDate"].dt.month
    df["Day of Week Num"] = df["showDate"].dt.weekday + 1

    present_num_features = [f for f in input_numerical_features if f in df.columns]
    df_num = df[present_num_features].copy()

    for feature in present_num_features:
        if isinstance(scaler, dict) and feature in scaler:
            df_num[[feature]] = scaler[feature].transform(df_num[[feature]])
        else:
            app.logger.warning("[%s] Scaler for '%s' not found; leaving unscaled.", route_tag, feature)

    if not isinstance(encoder, dict):
        raise TypeError("Loaded encoder object is not a dict.")

    encoded_cat_parts = []
    for feature in input_categorical_features:
        if feature not in df.columns or feature not in encoder:
            continue
        series = (
            df[feature].astype(str).str.strip()
            .str.replace("\xa0", " ").str.lower()
        )
        enc = encoder[feature]
        series = series.apply(lambda x: x if x in enc.classes_ else "unknown_category")
        encoded_cat_parts.append(pd.DataFrame({feature: enc.transform(series)}, index=df.index))

    df_cat_encoded = pd.concat(encoded_cat_parts, axis=1) if encoded_cat_parts else pd.DataFrame(index=df_num.index)
    df_model_input = pd.concat([df_num, df_cat_encoded], axis=1)
    df_model_input.dropna(inplace=True)

    if hasattr(model, "feature_names_in_"):
        df_model_input = df_model_input.reindex(columns=list(model.feature_names_in_), fill_value=0)

    df_aligned = df.loc[df_model_input.index].copy()
    return df_model_input, df_aligned


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/", methods=["GET"])
def root():
    state = _get_model_state_snapshot()
    return jsonify({"status": "ok", "model_loaded": _is_model_loaded(), "state": state["state"]}), 200


@app.route("/health", methods=["GET"])
def health():
    state = _get_model_state_snapshot()
    is_loaded = _is_model_loaded()
    resp = {
        "status": "ok" if is_loaded else "loading",
        "model_loaded": is_loaded,
        "state": state["state"],
        "last_error": state["last_error"],
        "models": {
            "size_model": is_loaded,
            "per_head_model": is_loaded,
        },
    }
    if state.get("download_progress"):
        resp["download_progress"] = state["download_progress"]
    return jsonify(resp), 200


@app.route("/status", methods=["GET"])
def status():
    artifacts = [
        "model_retrained.joblib",
        "robust_scaler_retrained.joblib",
        "label_encoder_retrained.joblib",
    ]
    return jsonify({
        "model_loaded": _is_model_loaded(),
        "state": _get_model_state_snapshot(),
        "artifacts": {name: _get_artifact_info(name) for name in artifacts},
        "system": {
            "pid": os.getpid(),
            "python_version": sys.version.split()[0],
            "platform": sys.platform,
            "memory": _get_memory_snapshot(),
        },
    }), 200


def _model_not_ready_response():
    state = _get_model_state_snapshot()
    return jsonify({
        "error": "Model not ready yet. Check /health or /status.",
        "state": state["state"],
        "last_error": state["last_error"],
    }), 503


def _to_number(series: pd.Series) -> pd.Series:
    return pd.to_numeric(
        series.astype(str).str.replace(r"[^0-9\.\-]", "", regex=True),
        errors="coerce",
    )


def _predict_size_df(df: pd.DataFrame, route_tag: str) -> pd.DataFrame:
    df_model_input, df = build_model_inputs(df, route_tag=route_tag)
    if df_model_input.empty:
        raise ValueError("No rows left after cleaning; nothing to predict.")

    predictions = model.predict(df_model_input)
    df["predicted_sales_quantity"] = np.round(predictions).astype(int)

    group_cols = ["artistName", "showDate", "productType"]
    missing_group = [c for c in group_cols if c not in df.columns]
    if missing_group:
        raise KeyError(f"Missing columns for percentage calculation: {missing_group}")

    df["%_item_sales_per_category"] = df.groupby(group_cols)["predicted_sales_quantity"].transform(
        lambda x: round((x / x.sum()) * 100, 2)
    )

    if "showDate" in df.columns:
        df["showDate"] = pd.to_datetime(df["showDate"], errors="coerce").dt.strftime("%Y-%m-%d")

    present_output_cols = [c for c in output_features if c in df.columns]
    return df[present_output_cols]


def _predict_per_head_df(df_size: pd.DataFrame) -> pd.DataFrame:
    show_key_cols = ["artistName", "venue name", "venue city", "venue state", "showDate"]
    for col in show_key_cols:
        if col not in df_size.columns:
            df_size[col] = ""
    for col in ["attendance", "predicted_sales_quantity", "product price"]:
        if col not in df_size.columns:
            df_size[col] = np.nan

    qty_num = _to_number(df_size["predicted_sales_quantity"])
    price_num = _to_number(df_size["product price"])
    attendance_num = _to_number(df_size["attendance"])
    predicted_revenue_row = qty_num * price_num

    show_agg = (
        pd.DataFrame(
            {
                "predicted_revenue_row": predicted_revenue_row,
                "attendance_num": attendance_num,
            }
        )
        .join(df_size[show_key_cols])
        .groupby(show_key_cols, dropna=False)
        .agg(
            show_predicted_revenue=("predicted_revenue_row", "sum"),
            show_attendance=("attendance_num", "max"),
        )
        .reset_index()
    )
    show_agg["predicted_$_per_head"] = (
        show_agg["show_predicted_revenue"]
        / show_agg["show_attendance"].replace({0: pd.NA})
    )
    show_agg["predicted_$_per_head"] = pd.to_numeric(
        show_agg["predicted_$_per_head"], errors="coerce"
    ).round(3)

    per_head_df = df_size.merge(
        show_agg[show_key_cols + ["predicted_$_per_head"]],
        on=show_key_cols,
        how="left",
    )
    output_cols = [
        "Genre",
        "artistName",
        "attendance",
        "predicted_$_per_head",
        "showDate",
        "venue city",
        "venue name",
        "venue state",
    ]
    for col in output_cols:
        if col not in per_head_df.columns:
            per_head_df[col] = np.nan
    return per_head_df[output_cols]


def _parse_legacy_json_records():
    payload = request.get_json(silent=True) or {}
    data = payload.get("data")
    if not isinstance(data, list):
        raise ValueError("Expected JSON body with key 'data' as a list.")
    return pd.DataFrame(data)


@app.route("/api/predict", methods=["POST"])
def api_predict():
    if not _is_model_loaded():
        return _model_not_ready_response()
    try:
        if "csv_file" not in request.files:
            return jsonify({"error": "No file part 'csv_file' in the request"}), 400

        file = request.files["csv_file"]
        file_bytes = file.read()
        df = pd.read_csv(BytesIO(file_bytes), encoding="utf-8-sig")

        output_df = _predict_size_df(df, route_tag="api")
        return jsonify({"data": output_df.to_dict(orient="records")}), 200

    except (ValueError, KeyError) as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        app.logger.error("/api/predict error: %s", e, exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/predict/size", methods=["POST"])
def predict_size_legacy():
    if not _is_model_loaded():
        return _model_not_ready_response()
    try:
        df = _parse_legacy_json_records()
        output_df = _predict_size_df(df, route_tag="predict-size")
        return jsonify({"predictions": output_df.to_dict(orient="records")}), 200
    except (ValueError, KeyError) as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        app.logger.error("/predict/size error: %s", e, exc_info=True)
        return jsonify({"error": str(e)}), 500


@app.route("/predict/perhead", methods=["POST"])
def predict_perhead_legacy():
    if not _is_model_loaded():
        return _model_not_ready_response()
    try:
        df = _parse_legacy_json_records()
        size_df = _predict_size_df(df, route_tag="predict-perhead")
        per_head_df = _predict_per_head_df(size_df.copy())
        return jsonify({"predictions": per_head_df.to_dict(orient="records")}), 200
    except (ValueError, KeyError) as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        app.logger.error("/predict/perhead error: %s", e, exc_info=True)
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(debug=False, host="0.0.0.0", port=port)
