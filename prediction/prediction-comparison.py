from __future__ import annotations

import os
from io import BytesIO, StringIO

import pandas as pd
import requests
import streamlit as st


DEFAULT_OLD_API_BASE_URL = "https://fast-api-data-master-eugene59.replit.app"
DEFAULT_NEW_API_BASE_URL = "https://manhead-new-prediction-mar-26.replit.app"

OLD_API_BASE_URL = os.environ.get(
    "OLD_MODEL_API_BASE_URL",
    os.environ.get("OLD_API_BASE_URL", DEFAULT_OLD_API_BASE_URL),
).rstrip("/")
NEW_API_BASE_URL = os.environ.get(
    "NEW_MODEL_API_BASE_URL",
    os.environ.get("PREDICTION_API_BASE_URL", DEFAULT_NEW_API_BASE_URL),
).rstrip("/")


def call_old_api(input_df: pd.DataFrame) -> pd.DataFrame:
    payload = input_df.astype(object).where(pd.notna(input_df), None).to_dict(orient="records")
    resp = requests.post(
        f"{OLD_API_BASE_URL}/predict/size",
        json={"data": payload},
        timeout=240,
    )
    if resp.status_code != 200:
        raise RuntimeError(
            f"Old API returned {resp.status_code}: {resp.text[:1200]}"
        )
    body = resp.json()
    predictions = body.get("predictions", body.get("data"))
    if not isinstance(predictions, list) or not predictions:
        raise RuntimeError("Old API returned an empty prediction payload.")
    return pd.DataFrame(predictions)


def call_new_api(upload_name: str, upload_bytes: bytes, input_df: pd.DataFrame) -> pd.DataFrame:
    files = {"csv_file": (upload_name, upload_bytes, "text/csv")}
    resp = requests.post(
        f"{NEW_API_BASE_URL}/api/predict",
        files=files,
        timeout=240,
    )

    # Compatibility fallback when only legacy route is available.
    if resp.status_code == 404:
        payload = input_df.astype(object).where(pd.notna(input_df), None).to_dict(orient="records")
        resp = requests.post(
            f"{NEW_API_BASE_URL}/predict/size",
            json={"data": payload},
            timeout=240,
        )

    if resp.status_code != 200:
        raise RuntimeError(
            f"New API returned {resp.status_code}: {resp.text[:1200]}"
        )
    body = resp.json()
    predictions = body.get("data", body.get("predictions"))
    if not isinstance(predictions, list) or not predictions:
        raise RuntimeError("New API returned an empty prediction payload.")
    return pd.DataFrame(predictions)


def _to_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def build_mode_a_output(
    input_df: pd.DataFrame,
    old_df: pd.DataFrame,
    new_df: pd.DataFrame,
) -> pd.DataFrame:
    if input_df.shape[0] != old_df.shape[0] or input_df.shape[0] != new_df.shape[0]:
        raise ValueError(
            "Row count mismatch between input and prediction outputs. "
            f"input={input_df.shape[0]} old={old_df.shape[0]} new={new_df.shape[0]}"
        )

    out = input_df.reset_index(drop=True).copy()
    old_df = old_df.reset_index(drop=True)
    new_df = new_df.reset_index(drop=True)

    if "predicted_sales_quantity" not in old_df.columns:
        raise KeyError("Old API output missing 'predicted_sales_quantity'.")
    if "predicted_sales_quantity" not in new_df.columns:
        raise KeyError("New API output missing 'predicted_sales_quantity'.")

    out["old_predicted_sales_quantity"] = _to_numeric(old_df["predicted_sales_quantity"])
    out["new_predicted_sales_quantity"] = _to_numeric(new_df["predicted_sales_quantity"])
    out["delta_predicted_sales_quantity"] = (
        out["new_predicted_sales_quantity"] - out["old_predicted_sales_quantity"]
    )

    if "%_item_sales_per_category" in old_df.columns and "%_item_sales_per_category" in new_df.columns:
        out["old_pct_item_sales_per_category"] = _to_numeric(old_df["%_item_sales_per_category"])
        out["new_pct_item_sales_per_category"] = _to_numeric(new_df["%_item_sales_per_category"])
        out["delta_pct_item_sales_per_category"] = (
            out["new_pct_item_sales_per_category"] - out["old_pct_item_sales_per_category"]
        )

    return out


st.set_page_config(page_title="Model Comparison Tool", layout="wide")
st.title("Model Comparison Tool")
st.write("Compare old and new prediction model outputs on the same formatted CSV input.")

with st.expander("API endpoints in use"):
    st.write(f"Old model API: `{OLD_API_BASE_URL}`")
    st.write(f"New model API: `{NEW_API_BASE_URL}`")

mode = st.radio(
    "Choose comparison mode",
    ("Mode A — Future shows", "Mode B — Backtest (deferred)"),
    index=0,
)

if mode == "Mode A — Future shows":
    st.subheader("Mode A: Side-by-side predictions for future shows")
    st.write(
        "Upload a formatted prediction CSV. The tool calls both old and new APIs, then "
        "returns a side-by-side output with delta columns."
    )

    uploaded_file = st.file_uploader(
        "Upload formatted CSV",
        type=["csv"],
        key="mode_a_file_uploader",
    )

    if uploaded_file is not None:
        st.caption(f"Selected file: `{uploaded_file.name}`")
        upload_bytes = uploaded_file.getvalue()

        try:
            input_df = pd.read_csv(BytesIO(upload_bytes), encoding="utf-8-sig")
        except Exception as exc:
            st.error(f"Could not read CSV: {exc}")
        else:
            st.write(f"Rows detected: **{input_df.shape[0]}**")
            st.dataframe(input_df.head(30), use_container_width=True)

            if st.button("Run Mode A comparison"):
                with st.spinner("Calling old and new APIs..."):
                    try:
                        old_df = call_old_api(input_df)
                        new_df = call_new_api(uploaded_file.name, upload_bytes, input_df)
                        out_df = build_mode_a_output(input_df, old_df, new_df)
                    except Exception as exc:
                        st.error(f"Comparison failed: {exc}")
                    else:
                        st.success("Comparison complete.")
                        st.dataframe(out_df, use_container_width=True)

                        csv_buffer = StringIO()
                        out_df.to_csv(csv_buffer, index=False)
                        out_csv = csv_buffer.getvalue()

                        st.download_button(
                            label="Download Mode A comparison CSV",
                            data=out_csv,
                            file_name="comparison_mode_a.csv",
                            mime="text/csv",
                        )
else:
    st.subheader("Mode B: Backtest (deferred)")
    st.info(
        "Mode B is intentionally deferred in this phase. "
        "This app currently supports Mode A only."
    )
    st.write(
        "Planned Mode B scope includes uploading formatted CSV + sales report CSV, "
        "then computing MAE/MAPE and winner metrics per show."
    )
