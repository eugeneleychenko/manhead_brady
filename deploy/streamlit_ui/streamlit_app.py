from __future__ import annotations
import os
import sys
import json
import hashlib
import requests
import tempfile
import subprocess
import pandas as pd
import streamlit as st
from io import StringIO, BytesIO
from audit_logger import log_event, sha256_bytes, sha256_file


def find_paths_config(start_dir: str, filename: str = "paths_config.txt") -> str:
    cur = os.path.abspath(start_dir)
    while True:
        cand = os.path.join(cur, filename)
        if os.path.exists(cand):
            return cand
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    raise FileNotFoundError(f"Could not find {filename} by searching upward from: {start_dir}")

def load_paths(config_path: str) -> dict:
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"paths_config.txt not found at: {config_path}")
    base_dir = os.path.dirname(os.path.abspath(config_path))
    paths = {}
    with open(config_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if key and value:
                if (
                    (not os.path.isabs(value))
                    and (not value.lower().startswith(("http://", "https://")))
                    and (not value.isdigit())
                ):
                    value = os.path.normpath(os.path.join(base_dir, value))
                paths[key] = value
    return paths

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = find_paths_config(SCRIPT_DIR)
PATHS = load_paths(CONFIG_PATH)

REPO_ROOT = os.path.dirname(os.path.abspath(CONFIG_PATH))
STREAMLIT_DOWNLOADS_DIR = os.path.join(REPO_ROOT, "outputs")
try:
    os.makedirs(STREAMLIT_DOWNLOADS_DIR, exist_ok=True)
except (OSError, PermissionError):
    STREAMLIT_DOWNLOADS_DIR = "/tmp/streamlit_downloads"
    os.makedirs(STREAMLIT_DOWNLOADS_DIR, exist_ok=True)

def save_streamlit_download_copy(file_name: str, data_bytes: bytes) -> str | None:
    out_path = os.path.join(STREAMLIT_DOWNLOADS_DIR, file_name)
    try:
        with open(out_path, "wb") as f:
            f.write(data_bytes)
        return out_path
    except Exception:
        return None

import os as _os
# Preferred env var for hosted cutover/rollback, with FLASK_API_URL kept for compatibility.
_flask_base = _os.environ.get(
    "PREDICTION_API_BASE_URL",
    _os.environ.get("FLASK_API_URL", f"http://localhost:{int(PATHS.get('flask_port', '5000'))}"),
)
API_BASE_URL = _flask_base.rstrip("/")
FLASK_API_URL = API_BASE_URL + "/api/predict"

def _call_prediction_api_with_fallback(upload_name: str, upload_bytes: bytes, timeout: int = 120):
    files = {"csv_file": (upload_name, upload_bytes, "text/csv")}
    response = requests.post(f"{API_BASE_URL}/api/predict", files=files, timeout=timeout)
    route_used = "api_predict"

    # Control API compatibility: fallback to legacy /predict/size contract.
    if response.status_code == 404:
        route_used = "legacy_predict_size"
        df = pd.read_csv(BytesIO(upload_bytes), encoding="utf-8-sig")
        if "showDate" in df.columns:
            df["showDate"] = pd.to_datetime(df["showDate"], errors="coerce").dt.strftime("%Y-%m-%d")
        json_rows = df.astype(object).where(pd.notna(df), None).to_dict(orient="records")
        response = requests.post(
            f"{API_BASE_URL}/predict/size",
            json={"data": json_rows},
            timeout=timeout,
        )
    return response, route_used

st.set_page_config(page_title="Merch Sales Prediction", layout="wide")

st.title("Merch Sales Prediction by Size")
st.write("Upload and enrich your data, then get predictions from the Flask model API.")

st.markdown("---")
st.header("Step 1: Add New Artist Data")

add_artist_choice = st.radio(
    "Do you want to add new artist information?",
    ("No", "Yes"),
    index=0,
    key="add_artist_choice",
)

ARTIST_METADATA_PATH = PATHS["artist_meta_csv"]
INSTAGRAM_COL = "Instagram_followers"

try:
    os.makedirs(os.path.dirname(ARTIST_METADATA_PATH), exist_ok=True)
except (OSError, PermissionError):
    pass

if "artist_entries" not in st.session_state:
    st.session_state["artist_entries"] = []

if add_artist_choice == "Yes":
    st.write("Add metadata for new artists (up to 5 artists at a time). ")

    num_artist_rows = st.selectbox(
        "How many artist entries do you want to add?",
        options=[1, 2, 3, 4, 5],
        index=0,
        key="num_artist_rows",
    )

    with st.form("artist_form"):
        st.subheader("Artist Information")

        artist_list = []
        for i in range(num_artist_rows):
            st.markdown(f"**Artist Entry {i + 1}**")

            col1, col2, col3 = st.columns(3)

            with col1:
                artist_name = st.text_input(
                    f"Artist Name (Entry {i + 1})",
                    placeholder="Example: Jelly Roll",
                    key=f"artist_name_{i}",
                )

            with col2:
                instagram = st.text_input(
                    f"Instagram Followers (Entry {i + 1})",
                    placeholder="526000",
                    key=f"instagram_{i}",
                )

            with col3:
                genre = st.text_input(
                    f"Genre (Entry {i + 1})",
                    placeholder="Country Rock",
                    key=f"genre_{i}",
                )

            artist_list.append(
                {
                    "artistName": artist_name,
                    INSTAGRAM_COL: instagram,
                    "Genre": genre,
                }
            )

            st.markdown("---")

        submitted = st.form_submit_button("Add new data")

        if submitted:
            cleaned_artists = [row for row in artist_list if row["artistName"].strip()]

            log_event(
                step="step1_artist_meta",
                status="start",
                details={
                    "artist_meta_path": ARTIST_METADATA_PATH,
                    "entries_requested": int(num_artist_rows),
                    "entries_submitted": int(len(artist_list)),
                    "entries_nonempty": int(len(cleaned_artists)),
                },
            )

            if not cleaned_artists:
                log_event(
                    step="step1_artist_meta",
                    status="warning",
                    details={
                        "artist_meta_path": ARTIST_METADATA_PATH,
                        "warning": "No non-empty artistName values submitted",
                    },
                )
                st.error("Please enter at least one artist name.")
            else:
                if os.path.exists(ARTIST_METADATA_PATH):
                    try:
                        existing_df = pd.read_csv(ARTIST_METADATA_PATH)
                    except PermissionError as e:
                        log_event(
                            step="step1_artist_meta",
                            status="error",
                            details={
                                "artist_meta_path": ARTIST_METADATA_PATH,
                                "error": f"PermissionError reading artist metadata: {e}",
                            },
                        )
                        st.error(
                            "Could not read artist_metadata.csv. "
                            "Please close it if it's open in Excel or another program and try again."
                        )
                        existing_df = pd.DataFrame(columns=["artistName", INSTAGRAM_COL, "Genre"])
                    except Exception as e:
                        log_event(
                            step="step1_artist_meta",
                            status="error",
                            details={
                                "artist_meta_path": ARTIST_METADATA_PATH,
                                "error": f"Error reading artist metadata: {e}",
                            },
                        )
                        st.error(f"Could not read artist_metadata.csv: {e}")
                        existing_df = pd.DataFrame(columns=["artistName", INSTAGRAM_COL, "Genre"])
                else:
                    existing_df = pd.DataFrame(columns=["artistName", INSTAGRAM_COL, "Genre"])

                if "Instagram" in existing_df.columns:
                    if INSTAGRAM_COL not in existing_df.columns:
                        existing_df = existing_df.rename(columns={"Instagram": INSTAGRAM_COL})
                    else:
                        existing_df[INSTAGRAM_COL] = existing_df[INSTAGRAM_COL].fillna(existing_df["Instagram"])
                    existing_df = existing_df.drop(columns=["Instagram"])

                for col in ["artistName", INSTAGRAM_COL, "Genre"]:
                    if col not in existing_df.columns:
                        existing_df[col] = ""

                new_df = pd.DataFrame(cleaned_artists)
                new_df = new_df[["artistName", INSTAGRAM_COL, "Genre"]]

                updated_df = pd.concat([existing_df, new_df], ignore_index=True)

                try:
                    updated_df.to_csv(ARTIST_METADATA_PATH, index=False)
                except PermissionError as e:
                    log_event(
                        step="step1_artist_meta",
                        status="error",
                        details={
                            "artist_meta_path": ARTIST_METADATA_PATH,
                            "error": f"PermissionError writing artist metadata: {e}",
                            "rows_attempted_add": int(len(cleaned_artists)),
                        },
                    )
                    st.error(
                        "Could not update artist_metadata.csv. "
                        "Most likely the file is open in Excel or another application. "
                        "Please close it and try again."
                    )
                except Exception as e:
                    log_event(
                        step="step1_artist_meta",
                        status="error",
                        details={
                            "artist_meta_path": ARTIST_METADATA_PATH,
                            "error": f"Error writing artist metadata: {e}",
                            "rows_attempted_add": int(len(cleaned_artists)),
                        },
                    )
                    st.error(f"Could not update artist_metadata.csv: {e}")
                else:
                    st.session_state["artist_entries"].extend(cleaned_artists)

                    file_hash = sha256_file(ARTIST_METADATA_PATH) if os.path.exists(ARTIST_METADATA_PATH) else ""
                    log_event(
                        step="step1_artist_meta",
                        status="success",
                        details={
                            "artist_meta_path": ARTIST_METADATA_PATH,
                            "rows_added": int(len(cleaned_artists)),
                            "rows_total_after": int(updated_df.shape[0]),
                            "artist_meta_hash": file_hash,
                        },
                    )

                    st.success(f"Added {len(cleaned_artists)} artist row(s) to artist_metadata.csv.")

if st.session_state["artist_entries"]:
    st.subheader("Artists added in this session")
    df_artists_session = pd.DataFrame(st.session_state["artist_entries"])
    st.dataframe(df_artists_session, use_container_width=True)

    csv_artists_buf = StringIO()
    df_artists_session.to_csv(csv_artists_buf, index=False)

    artists_csv_str = csv_artists_buf.getvalue()
    save_streamlit_download_copy("artist_info_session.csv", artists_csv_str.encode("utf-8"))

    st.download_button(
        label="Download This Session's Artist Info CSV",
        data=artists_csv_str,
        file_name="artist_info_session.csv",
        mime="text/csv",
    )

st.markdown("---")
st.header("Step 2: Format and Consolidate Data")

st.write(
    "This runs the consolidation script, writes a consolidated snapshot, "
    "and appends it into the continuously-updated master dataset (full-row dedupe)."
)

if st.button("Run consolidation pipeline"):
    script_path = PATHS["consolidation_script_path"]
    final_csv = PATHS["final_out"]
    stats_path = PATHS["consolidation_stats_json"]
    master_path = PATHS.get("master_training_dataset", "")

    log_event(
        step="step2_consolidate",
        status="start",
        details={
            "script_path": script_path,
            "final_out": final_csv,
            "stats_json": stats_path,
            "master_training_dataset": master_path,
        },
    )

    with st.spinner("Running consolidation script..."):
        try:
            result = subprocess.run(
                [sys.executable, script_path],
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            log_event(
                step="step2_consolidate",
                status="error",
                details={
                    "script_path": script_path,
                    "final_out": final_csv,
                    "stats_json": stats_path,
                    "master_training_dataset": master_path,
                    "returncode": int(e.returncode) if e.returncode is not None else None,
                    "stdout": (e.stdout or "")[:4000],
                    "stderr": (e.stderr or "")[:4000],
                },
            )

            st.error("Consolidation script failed.")
            if e.stdout:
                st.code(e.stdout)
            if e.stderr:
                st.code(e.stderr)
        else:
            st.success("Consolidation completed successfully.")

            stats = None
            if os.path.exists(stats_path):
                with open(stats_path, "r", encoding="utf-8") as f:
                    stats = json.load(f)

                st.subheader("Master dataset append results")
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Master rows before", stats.get("master_rows_before", "—"))
                c2.metric("Snapshot rows", stats.get("new_rows_in_snapshot", "—"))
                c3.metric("Rows added", stats.get("rows_added", "—"))
                c4.metric("Master rows after", stats.get("master_rows_after", "—"))

                st.caption(f"Master path: {stats.get('master_path', '—')}")
            else:
                st.warning(f"Stats file not found: {stats_path}")

            df_final = None
            if os.path.exists(final_csv):
                df_final = pd.read_csv(final_csv)

                st.subheader("Preview of consolidated snapshot (merged_with_weather.csv)")
                st.dataframe(df_final.head(200), use_container_width=True)

                csv_str = df_final.to_csv(index=False)
                save_streamlit_download_copy("merged_with_weather.csv", csv_str.encode("utf-8"))

                st.download_button(
                    label="Download consolidated snapshot CSV",
                    data=csv_str,
                    file_name="merged_with_weather.csv",
                    mime="text/csv",
                )
            else:
                st.error(f"Expected output file not found: {final_csv}")

            details = {
                "script_path": script_path,
                "final_out": final_csv,
                "stats_json": stats_path,
                "master_training_dataset": master_path,
                "stdout": (result.stdout or "")[:2000],
                "stderr": (result.stderr or "")[:2000],
            }

            if stats is not None:
                details.update({
                    "master_rows_before": stats.get("master_rows_before"),
                    "new_rows_in_snapshot": stats.get("new_rows_in_snapshot"),
                    "rows_added": stats.get("rows_added"),
                    "master_rows_after": stats.get("master_rows_after"),
                    "master_path": stats.get("master_path"),
                })

            if os.path.exists(final_csv):
                details["final_out_hash"] = sha256_file(final_csv)
                if df_final is not None:
                    details["final_out_rows"] = int(df_final.shape[0])
                    details["final_out_cols"] = list(df_final.columns)

            if os.path.exists(stats_path):
                details["stats_json_hash"] = sha256_file(stats_path)

            if master_path and os.path.exists(master_path):
                details["master_hash"] = sha256_file(master_path)

            log_event(step="step2_consolidate", status="success", details=details)

st.markdown("---")
st.header("Step 4: Run Predictions")

st.write("Upload a CSV and get predictions from the Flask model API.")

uploaded_file = st.file_uploader(
    "Upload your CSV file for prediction",
    type=["csv"],
    key="prediction_uploader",
)

if uploaded_file is not None:
    st.write("File name:", uploaded_file.name)

    if st.button("Run prediction"):
        file_bytes = uploaded_file.getvalue()
        file_hash = sha256_bytes(file_bytes)

        log_event(
            step="step4_predict",
            status="start",
            details={"input_file": uploaded_file.name, "input_hash": file_hash},
        )

        with st.spinner("Calling prediction API and running model..."):
            try:
                response, route_used = _call_prediction_api_with_fallback(
                    uploaded_file.name, file_bytes, timeout=120
                )
                response.raise_for_status()
            except requests.RequestException as e:
                log_event(
                    step="step4_predict",
                    status="error",
                    details={"input_file": uploaded_file.name, "input_hash": file_hash, "error": str(e)},
                )
                st.error(f"Error calling prediction API: {e}")
            else:
                try:
                    payload = response.json()
                except ValueError:
                    log_event(
                        step="step4_predict",
                        status="error",
                        details={"input_file": uploaded_file.name, "input_hash": file_hash, "error": "API did not return valid JSON"},
                    )
                    st.error("API did not return valid JSON.")
                else:
                    if "error" in payload:
                        log_event(
                            step="step4_predict",
                            status="error",
                            details={"input_file": uploaded_file.name, "input_hash": file_hash, "error": payload.get("error")},
                        )
                        st.error(f"API returned an error: {payload['error']}")
                    else:
                        data = payload.get("data", payload.get("predictions", []))

                        if not data:
                            log_event(
                                step="step4_predict",
                                status="warning",
                                details={"input_file": uploaded_file.name, "input_hash": file_hash, "warning": "API returned no data"},
                            )
                            st.warning("API returned no data.")
                        else:
                            df_pred = pd.DataFrame(data)

                            log_event(
                                step="step4_predict",
                                status="success",
                                details={
                                    "input_file": uploaded_file.name,
                                    "input_hash": file_hash,
                                    "route_used": route_used,
                                    "rows_out": int(df_pred.shape[0]),
                                    "cols_out": list(df_pred.columns),
                                },
                            )

                            st.success("Predictions generated successfully.")
                            st.subheader("Preview of predictions")
                            st.dataframe(df_pred, use_container_width=True)

                            csv_buffer = StringIO()
                            df_pred.to_csv(csv_buffer, index=False)

                            pred_csv_str = csv_buffer.getvalue()
                            save_streamlit_download_copy(
                                "predicted_sales_streamlit.csv",
                                pred_csv_str.encode("utf-8"),
                            )

                            st.download_button(
                                label="Download predictions as CSV",
                                data=pred_csv_str,
                                file_name="predicted_sales_streamlit.csv",
                                mime="text/csv",
                            )

st.markdown("---")
st.header("Step 5: Calculate Revenue Per Head")

st.write("Upload the Step 4 prediction output CSV. Step 5 will run automatically.")

STEP5_SCRIPT_PATH = PATHS["revph_script_path"]
STEP5_OUTPUT_PATH = PATHS["revph_output_csv"]
STEP5_SUMMARY_PATH = PATHS["revph_summary_json"]

revph_file = st.file_uploader(
    "Upload Step 4 output CSV",
    type=["csv"],
    key="revph_uploader_v3",
)

if "step5_last_hash" not in st.session_state:
    st.session_state["step5_last_hash"] = None
if "step5_out_csv_path" not in st.session_state:
    st.session_state["step5_out_csv_path"] = None
if "step5_summary_path" not in st.session_state:
    st.session_state["step5_summary_path"] = None

if "step5_logged_success_hash" not in st.session_state:
    st.session_state["step5_logged_success_hash"] = None

def _run_step5_script(uploaded_bytes: bytes):
    tmp_dir = tempfile.gettempdir()
    file_hash = hashlib.sha256(uploaded_bytes).hexdigest()[:16]

    input_path = os.path.join(tmp_dir, f"step5_input_{file_hash}.csv")
    output_path = STEP5_OUTPUT_PATH
    summary_path = STEP5_SUMMARY_PATH

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    os.makedirs(os.path.dirname(summary_path), exist_ok=True)

    with open(input_path, "wb") as f:
        f.write(uploaded_bytes)

    result = subprocess.run(
        [
            sys.executable,
            STEP5_SCRIPT_PATH,
            "--input", input_path,
            "--output", output_path,
            "--summary", summary_path,
            "--round", "3",
        ],
        capture_output=True,
        text=True,
    )

    return result, output_path, summary_path, file_hash

if revph_file is not None:
    st.write("File name:", revph_file.name)

    uploaded_bytes = revph_file.getvalue()
    current_hash = hashlib.sha256(uploaded_bytes).hexdigest()[:16]

    if st.session_state["step5_last_hash"] != current_hash:
        log_event(
            step="step5_revph",
            status="start",
            details={"input_file": revph_file.name, "input_hash": current_hash},
        )

        with st.spinner("Running Step 5 calculations..."):
            result, out_csv_path, summary_path, file_hash = _run_step5_script(uploaded_bytes)

        if result.returncode != 0:
            log_event(
                step="step5_revph",
                status="error",
                details={
                    "input_file": revph_file.name,
                    "input_hash": current_hash,
                    "returncode": int(result.returncode),
                    "stderr": (result.stderr or "")[:4000],
                    "stdout": (result.stdout or "")[:4000],
                },
            )

            st.error("Step 5 script failed.")
            if result.stdout:
                with st.expander("stdout"):
                    st.code(result.stdout)
            if result.stderr:
                with st.expander("stderr"):
                    st.code(result.stderr)
        else:
            st.session_state["step5_last_hash"] = current_hash
            st.session_state["step5_out_csv_path"] = out_csv_path
            st.session_state["step5_summary_path"] = summary_path

            st.session_state["step5_logged_success_hash"] = None

    out_csv_path = st.session_state.get("step5_out_csv_path")
    summary_path = st.session_state.get("step5_summary_path")

    if out_csv_path and os.path.exists(out_csv_path):
        try:
            df_out = pd.read_csv(out_csv_path)
        except Exception as e:
            st.error(f"Could not read Step 5 output CSV: {e}")
            df_out = None

        if df_out is not None:
            st.success("Revenue Per Head Calculated.")

            st.subheader("Preview output (with $/head)")
            st.dataframe(df_out.head(300), use_container_width=True)

            try:
                with open(out_csv_path, "rb") as f:
                    out_bytes = f.read()
                save_streamlit_download_copy("predicted_sales_with_revenue_per_head.csv", out_bytes)
            except Exception:
                pass

            with open(out_csv_path, "rb") as f:
                st.download_button(
                    label="Download Step 5 output CSV",
                    data=f.read(),
                    file_name="predicted_sales_with_revenue_per_head.csv",
                    mime="text/csv",
                )

            summary = None
            if summary_path and os.path.exists(summary_path):
                try:
                    with open(summary_path, "r", encoding="utf-8") as f:
                        summary = json.load(f)
                except Exception as e:
                    st.error(f"Could not read summary JSON: {e}")
                    summary = None

                try:
                    with open(summary_path, "rb") as f:
                        summary_bytes = f.read()
                    save_streamlit_download_copy("revenue_per_head_summary.json", summary_bytes)
                except Exception:
                    pass

            if st.session_state.get("step5_logged_success_hash") != current_hash:
                log_event(
                    step="step5_revph",
                    status="success",
                    details={
                        "input_file": revph_file.name,
                        "input_hash": current_hash,
                        "output_csv": out_csv_path,
                        "summary_json": summary_path,
                        "rows_out": int(df_out.shape[0]),
                        "shows": (summary or {}).get("shows"),
                        "warnings": (summary or {}).get("warnings", []),
                        "attendance_inconsistent_shows": (summary or {}).get("attendance_inconsistent_shows"),
                    },
                )
                st.session_state["step5_logged_success_hash"] = current_hash

            if summary:
                summary_df = pd.DataFrame([{
                    "Total Predicted Sales": summary.get("total_predicted_sales"),
                    "Average Sales Per Product": summary.get("avg_sales_per_product"),
                    "Product Types": summary.get("product_types"),
                    "Shows": summary.get("shows"),
                }])

                st.subheader("Summary Statistics")
                st.dataframe(
                    summary_df.style.format({
                        "Total Predicted Sales": "{:,.0f}",
                        "Average Sales Per Product": "{:,.2f}",
                        "Product Types": "{:,.0f}",
                        "Shows": "{:,.0f}",
                    }),
                    use_container_width=True,
                    hide_index=True,
                )