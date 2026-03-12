#!/usr/bin/env python3
"""
Bind validation utility for prediction consistency checks.

This script orchestrates:
- canonical input parity checks
- baseline generation for old/new hosted APIs
- strict CSV comparisons with integer-exact quantity checks
- comparison-tool column validation
- final bind report generation
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import requests


BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent
BIND_OUTPUTS_DIR = BASE_DIR / "bind_outputs"

CANONICAL_CSV_PATHS = [
    REPO_ROOT / "deploy" / "air_supply_formatted_3_4_26.csv",
    REPO_ROOT / "air_supply_formatted_3_4_26.csv",
]

OLD_API_BASE_URL = os.environ.get(
    "OLD_API_BASE_URL", "https://fast-api-data-master-eugene59.replit.app"
).rstrip("/")
NEW_API_BASE_URL = os.environ.get(
    "NEW_API_BASE_URL", "https://manhead-new-model-api.replit.app"
).rstrip("/")

INT_EXACT_COLUMNS = {"predicted_sales_quantity"}
FLOAT_TOLERANCE = 1e-6
MAX_MISMATCH_ROWS_PER_COLUMN = 12

ARTIFACT_MAP = {
    "baseline_old": BIND_OUTPUTS_DIR / "baseline_old.csv",
    "baseline_new": BIND_OUTPUTS_DIR / "baseline_new.csv",
    "new_local_streamlit": BIND_OUTPUTS_DIR / "new_local_streamlit.csv",
    "new_cloud_streamlit": BIND_OUTPUTS_DIR / "new_cloud_streamlit.csv",
    "comparison_mode_a": BIND_OUTPUTS_DIR / "comparison_mode_a.csv",
    "bind_report_csv": BIND_OUTPUTS_DIR / "bind_report.csv",
    "bind_report_md": BIND_OUTPUTS_DIR / "bind_report.md",
    "comparison_columns_report": BIND_OUTPUTS_DIR / "comparison_columns_report.json",
}


def ensure_output_dir() -> None:
    BIND_OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _serialize_value(value: Any) -> Any:
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    if pd.isna(value):
        return None
    return value


def save_json(data: Any, path: Path) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=True), encoding="utf-8")


def resolve_artifact(name_or_path: str) -> Path:
    path_candidate = Path(name_or_path)
    if path_candidate.exists():
        return path_candidate.resolve()
    alias = name_or_path
    if alias.endswith(".csv"):
        alias = alias[:-4]
    if alias in ARTIFACT_MAP:
        return ARTIFACT_MAP[alias]
    raise FileNotFoundError(
        f"Unknown artifact '{name_or_path}'. Known aliases: {', '.join(sorted(ARTIFACT_MAP.keys()))}"
    )


def load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing CSV: {path}")
    return pd.read_csv(path, encoding="utf-8-sig")


def write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def canonical_parity_check() -> dict[str, Any]:
    missing = [str(p) for p in CANONICAL_CSV_PATHS if not p.exists()]
    if missing:
        return {
            "ok": False,
            "reason": "missing_files",
            "missing_paths": missing,
        }

    hashes = {str(p): sha256_file(p) for p in CANONICAL_CSV_PATHS}
    unique_hashes = set(hashes.values())
    if len(unique_hashes) != 1:
        return {
            "ok": False,
            "reason": "hash_mismatch",
            "hashes": hashes,
        }

    row_counts = {}
    columns = {}
    for p in CANONICAL_CSV_PATHS:
        df = load_csv(p)
        row_counts[str(p)] = int(df.shape[0])
        columns[str(p)] = list(df.columns)

    return {
        "ok": True,
        "reason": "match",
        "hash": next(iter(unique_hashes)),
        "rows": row_counts,
        "columns": columns,
        "canonical_path": str(CANONICAL_CSV_PATHS[0]),
    }


def _raise_for_http_failure(resp: requests.Response, endpoint_label: str) -> None:
    if resp.status_code != 200:
        body = resp.text[:1200]
        raise RuntimeError(
            f"{endpoint_label} failed with HTTP {resp.status_code}. Response body: {body}"
        )


def wait_for_api_ready(
    base_url: str,
    *,
    endpoint_label: str,
    timeout_seconds: int = 300,
    poll_seconds: int = 5,
) -> None:
    deadline = time.time() + timeout_seconds
    last_state: dict[str, Any] = {}

    while time.time() < deadline:
        try:
            resp = requests.get(f"{base_url}/health", timeout=20)
            if resp.status_code == 200:
                payload = resp.json()
                if isinstance(payload, dict):
                    last_state = payload
                model_loaded = payload.get("model_loaded")
                status = str(payload.get("status", "")).lower()
                state = str(payload.get("state", "")).lower()
                if model_loaded is True or status == "ok" or state == "ready":
                    return
        except Exception as exc:  # noqa: BLE001
            last_state = {"error": str(exc)}
        time.sleep(poll_seconds)

    raise RuntimeError(
        f"{endpoint_label} did not become ready within {timeout_seconds}s. Last health state: {last_state}"
    )


def call_old_api_baseline(input_df: pd.DataFrame) -> pd.DataFrame:
    payload = input_df.astype(object).where(pd.notna(input_df), None).to_dict(orient="records")
    resp = requests.post(
        f"{OLD_API_BASE_URL}/predict/size",
        json={"data": payload},
        timeout=180,
    )
    _raise_for_http_failure(resp, "old_api /predict/size")
    data = resp.json().get("predictions")
    if not isinstance(data, list) or not data:
        raise RuntimeError("old_api returned empty or invalid 'predictions' list.")
    return pd.DataFrame(data)


def call_new_api_baseline(input_path: Path) -> pd.DataFrame:
    wait_for_api_ready(NEW_API_BASE_URL, endpoint_label="new_api")

    resp: requests.Response | None = None
    for attempt in range(1, 4):
        with input_path.open("rb") as f:
            files = {"csv_file": (input_path.name, f, "text/csv")}
            resp = requests.post(
                f"{NEW_API_BASE_URL}/api/predict",
                files=files,
                timeout=240,
            )
        if resp.status_code == 503 and attempt < 3:
            time.sleep(5)
            continue
        break

    if resp is None:
        raise RuntimeError("new_api /api/predict request did not execute.")
    _raise_for_http_failure(resp, "new_api /api/predict")
    payload = resp.json()
    data = payload.get("data", payload.get("predictions"))
    if not isinstance(data, list) or not data:
        raise RuntimeError("new_api returned empty or invalid prediction payload.")
    return pd.DataFrame(data)


def _series_to_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _is_numeric_comparable(left: pd.Series, right: pd.Series) -> bool:
    left_num = _series_to_numeric(left)
    right_num = _series_to_numeric(right)
    return bool((left_num.notna() | right_num.notna()).any())


def compare_series_strict(
    left_series: pd.Series,
    right_series: pd.Series,
    *,
    column_name: str,
    int_exact: bool,
    float_tol: float,
) -> dict[str, Any]:
    if int_exact:
        left_num = _series_to_numeric(left_series)
        right_num = _series_to_numeric(right_series)

        integral_left = left_num.isna() | np.isclose(left_num, np.round(left_num), atol=0, rtol=0)
        integral_right = right_num.isna() | np.isclose(right_num, np.round(right_num), atol=0, rtol=0)

        mismatch_mask = pd.Series(False, index=left_series.index)
        mismatch_mask |= ~(integral_left & integral_right)

        equal_num = pd.Series(False, index=left_series.index)
        both_nan = left_num.isna() & right_num.isna()
        both_num = left_num.notna() & right_num.notna()
        equal_num[both_nan] = True
        equal_num[both_num] = np.round(left_num[both_num]).astype(np.int64).values == np.round(
            right_num[both_num]
        ).astype(np.int64).values
        mismatch_mask |= ~equal_num
    elif _is_numeric_comparable(left_series, right_series):
        left_num = _series_to_numeric(left_series)
        right_num = _series_to_numeric(right_series)
        both_nan = left_num.isna() & right_num.isna()
        both_num = left_num.notna() & right_num.notna()
        close = pd.Series(False, index=left_series.index)
        close[both_nan] = True
        close[both_num] = np.isclose(
            left_num[both_num],
            right_num[both_num],
            rtol=0.0,
            atol=float_tol,
            equal_nan=True,
        )
        mismatch_mask = ~close
    else:
        left_text = left_series.fillna("").astype(str).str.strip()
        right_text = right_series.fillna("").astype(str).str.strip()
        mismatch_mask = left_text != right_text

    mismatch_idx = left_series.index[mismatch_mask].tolist()
    sample_rows = []
    for idx in mismatch_idx[:MAX_MISMATCH_ROWS_PER_COLUMN]:
        sample_rows.append(
            {
                "row_index": int(idx),
                "left": _serialize_value(left_series.loc[idx]),
                "right": _serialize_value(right_series.loc[idx]),
            }
        )

    return {
        "column": column_name,
        "is_match": len(mismatch_idx) == 0,
        "mismatch_count": int(len(mismatch_idx)),
        "mismatch_rows_preview": sample_rows,
    }


def compare_dataframes(
    left_df: pd.DataFrame,
    right_df: pd.DataFrame,
    *,
    left_label: str,
    right_label: str,
    column_map: dict[str, str] | None = None,
    int_exact_columns: Iterable[str] = INT_EXACT_COLUMNS,
    float_tol: float = FLOAT_TOLERANCE,
) -> dict[str, Any]:
    if left_df.shape[0] != right_df.shape[0]:
        return {
            "status": "MISMATCH",
            "reason": "row_count_mismatch",
            "left_label": left_label,
            "right_label": right_label,
            "left_rows": int(left_df.shape[0]),
            "right_rows": int(right_df.shape[0]),
            "column_results": [],
        }

    if column_map is None:
        left_cols = set(left_df.columns)
        right_cols = set(right_df.columns)
        missing_on_right = sorted(left_cols - right_cols)
        missing_on_left = sorted(right_cols - left_cols)
        if missing_on_right or missing_on_left:
            return {
                "status": "MISMATCH",
                "reason": "column_set_mismatch",
                "left_label": left_label,
                "right_label": right_label,
                "missing_on_right": missing_on_right,
                "missing_on_left": missing_on_left,
                "left_rows": int(left_df.shape[0]),
                "right_rows": int(right_df.shape[0]),
                "column_results": [],
            }
        mapping = {c: c for c in left_df.columns}
    else:
        mapping = column_map

    left_df = left_df.reset_index(drop=True)
    right_df = right_df.reset_index(drop=True)
    left_df.index = pd.RangeIndex(start=0, stop=len(left_df), step=1)
    right_df.index = pd.RangeIndex(start=0, stop=len(right_df), step=1)

    column_results = []
    any_mismatch = False
    for left_col, right_col in mapping.items():
        if left_col not in left_df.columns:
            raise KeyError(f"Left column missing: {left_col}")
        if right_col not in right_df.columns:
            raise KeyError(f"Right column missing: {right_col}")
        result = compare_series_strict(
            left_df[left_col],
            right_df[right_col],
            column_name=f"{left_col} vs {right_col}",
            int_exact=(left_col in int_exact_columns or right_col in int_exact_columns),
            float_tol=float_tol,
        )
        column_results.append(result)
        any_mismatch = any_mismatch or (not result["is_match"])

    return {
        "status": "MISMATCH" if any_mismatch else "MATCH",
        "reason": "value_mismatch" if any_mismatch else "all_equal",
        "left_label": left_label,
        "right_label": right_label,
        "left_rows": int(left_df.shape[0]),
        "right_rows": int(right_df.shape[0]),
        "column_results": column_results,
    }


def find_prediction_column(columns: list[str], model_tag: str) -> str:
    if model_tag == "old":
        candidates = [
            "old_predicted_sales_quantity",
            "old_model_predicted_sales_quantity",
            "old_prediction",
            "predicted_sales_quantity_old",
            "old_predicted_qty",
        ]
    else:
        candidates = [
            "new_predicted_sales_quantity",
            "new_model_predicted_sales_quantity",
            "new_prediction",
            "predicted_sales_quantity_new",
            "new_predicted_qty",
        ]
    for candidate in candidates:
        if candidate in columns:
            return candidate
    raise KeyError(
        f"Could not find {model_tag} prediction column in comparison output. "
        f"Expected one of: {candidates}"
    )


def cmd_check_canonical(_args: argparse.Namespace) -> int:
    ensure_output_dir()
    result = canonical_parity_check()
    if not result["ok"]:
        print(json.dumps(result, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0


def cmd_make_baseline(args: argparse.Namespace) -> int:
    ensure_output_dir()
    parity = canonical_parity_check()
    if not parity["ok"]:
        print(json.dumps(parity, indent=2))
        return 1

    canonical_path = Path(parity["canonical_path"])
    input_df = load_csv(canonical_path)

    if args.model == "old":
        output_df = call_old_api_baseline(input_df)
        output_path = ARTIFACT_MAP["baseline_old"]
    else:
        output_df = call_new_api_baseline(canonical_path)
        output_path = ARTIFACT_MAP["baseline_new"]

    if output_df.shape[0] != input_df.shape[0]:
        raise RuntimeError(
            f"Output row count mismatch for model={args.model}: "
            f"input={input_df.shape[0]} output={output_df.shape[0]}"
        )

    write_csv(output_df, output_path)
    print(
        json.dumps(
            {
                "status": "ok",
                "model": args.model,
                "output_path": str(output_path),
                "rows": int(output_df.shape[0]),
                "columns": list(output_df.columns),
            },
            indent=2,
        )
    )
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    left_path = resolve_artifact(args.left)
    right_path = resolve_artifact(args.right)
    left_df = load_csv(left_path)
    right_df = load_csv(right_path)
    result = compare_dataframes(
        left_df,
        right_df,
        left_label=left_path.name,
        right_label=right_path.name,
    )
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "MATCH" else 1


def cmd_check_artifact(args: argparse.Namespace) -> int:
    ensure_output_dir()
    path = resolve_artifact(args.name)
    if not path.exists():
        print(json.dumps({"status": "missing", "artifact": str(path)}, indent=2))
        return 1

    artifact_df = load_csv(path)
    result: dict[str, Any] = {
        "status": "ok",
        "artifact": str(path),
        "rows": int(artifact_df.shape[0]),
        "columns": list(artifact_df.columns),
    }

    if args.name in {"comparison_mode_a", "comparison_mode_a.csv"}:
        parity = canonical_parity_check()
        if not parity["ok"]:
            result["status"] = "error"
            result["reason"] = "canonical_parity_failed"
            result["canonical"] = parity
            print(json.dumps(result, indent=2))
            return 1
        canonical_rows = int(next(iter(parity["rows"].values())))
        if int(artifact_df.shape[0]) != canonical_rows:
            result["status"] = "error"
            result["reason"] = "row_count_mismatch"
            result["expected_rows"] = canonical_rows
            print(json.dumps(result, indent=2))
            return 1
        try:
            find_prediction_column(list(artifact_df.columns), "old")
            find_prediction_column(list(artifact_df.columns), "new")
        except KeyError as exc:
            result["status"] = "error"
            result["reason"] = "missing_prediction_columns"
            result["error"] = str(exc)
            print(json.dumps(result, indent=2))
            return 1

    print(json.dumps(result, indent=2))
    return 0


def validate_comparison_columns() -> dict[str, Any]:
    baseline_old_df = load_csv(ARTIFACT_MAP["baseline_old"])
    baseline_new_df = load_csv(ARTIFACT_MAP["baseline_new"])
    comparison_df = load_csv(ARTIFACT_MAP["comparison_mode_a"])

    old_col = find_prediction_column(list(comparison_df.columns), "old")
    new_col = find_prediction_column(list(comparison_df.columns), "new")

    old_left = baseline_old_df[["predicted_sales_quantity"]].copy()
    old_right = comparison_df[[old_col]].copy()
    old_result = compare_dataframes(
        old_left,
        old_right,
        left_label="baseline_old.csv",
        right_label="comparison_mode_a.csv",
        column_map={"predicted_sales_quantity": old_col},
    )

    new_left = baseline_new_df[["predicted_sales_quantity"]].copy()
    new_right = comparison_df[[new_col]].copy()
    new_result = compare_dataframes(
        new_left,
        new_right,
        left_label="baseline_new.csv",
        right_label="comparison_mode_a.csv",
        column_map={"predicted_sales_quantity": new_col},
    )

    return {
        "old_api_vs_comparison_old_column": old_result,
        "new_api_vs_comparison_new_column": new_result,
    }


def cmd_validate_comparison_columns(_args: argparse.Namespace) -> int:
    ensure_output_dir()
    result = validate_comparison_columns()
    save_json(result, ARTIFACT_MAP["comparison_columns_report"])
    print(json.dumps(result, indent=2))
    all_match = all(v["status"] == "MATCH" for v in result.values())
    return 0 if all_match else 1


def cmd_final_report(_args: argparse.Namespace) -> int:
    ensure_output_dir()

    checks: list[dict[str, Any]] = []

    def append_check(name: str, result: dict[str, Any]) -> None:
        checks.append(
            {
                "check": name,
                "status": result["status"],
                "reason": result.get("reason", ""),
                "left_label": result.get("left_label", ""),
                "right_label": result.get("right_label", ""),
            }
        )

    comparison_results = validate_comparison_columns()

    append_check(
        "old_api vs comparison_old_column",
        comparison_results["old_api_vs_comparison_old_column"],
    )

    new_local_result = compare_dataframes(
        load_csv(ARTIFACT_MAP["baseline_new"])[["predicted_sales_quantity"]],
        load_csv(ARTIFACT_MAP["new_local_streamlit"])[["predicted_sales_quantity"]],
        left_label="baseline_new.csv",
        right_label="new_local_streamlit.csv",
    )
    append_check("new_api vs new_local_streamlit", new_local_result)

    new_cloud_result = compare_dataframes(
        load_csv(ARTIFACT_MAP["baseline_new"])[["predicted_sales_quantity"]],
        load_csv(ARTIFACT_MAP["new_cloud_streamlit"])[["predicted_sales_quantity"]],
        left_label="baseline_new.csv",
        right_label="new_cloud_streamlit.csv",
    )
    append_check("new_api vs new_cloud_streamlit", new_cloud_result)

    append_check(
        "new_api vs comparison_new_column",
        comparison_results["new_api_vs_comparison_new_column"],
    )

    report_df = pd.DataFrame(checks)
    write_csv(report_df, ARTIFACT_MAP["bind_report_csv"])

    overall_pass = bool((report_df["status"] == "MATCH").all())
    md_lines = [
        "# Bind Report",
        "",
        f"Overall: {'PASS' if overall_pass else 'FAIL'}",
        "",
        "| Check | Status | Reason |",
        "|---|---|---|",
    ]
    for row in checks:
        md_lines.append(f"| {row['check']} | {row['status']} | {row['reason']} |")
    ARTIFACT_MAP["bind_report_md"].write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "overall": "PASS" if overall_pass else "FAIL",
                "report_csv": str(ARTIFACT_MAP["bind_report_csv"]),
                "report_md": str(ARTIFACT_MAP["bind_report_md"]),
                "checks": checks,
            },
            indent=2,
        )
    )
    return 0 if overall_pass else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bind validation CLI.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check_canonical = subparsers.add_parser(
        "check-canonical", help="Verify canonical CSV copies are identical."
    )
    check_canonical.set_defaults(func=cmd_check_canonical)

    make_baseline = subparsers.add_parser(
        "make-baseline", help="Generate direct API baseline for old or new model."
    )
    make_baseline.add_argument("--model", choices=["old", "new"], required=True)
    make_baseline.set_defaults(func=cmd_make_baseline)

    compare_cmd = subparsers.add_parser(
        "compare", help="Strict compare between two CSVs (artifact alias or path)."
    )
    compare_cmd.add_argument("--left", required=True, help="Artifact alias or CSV path.")
    compare_cmd.add_argument("--right", required=True, help="Artifact alias or CSV path.")
    compare_cmd.set_defaults(func=cmd_compare)

    check_artifact = subparsers.add_parser(
        "check-artifact", help="Validate expected artifact shape and required columns."
    )
    check_artifact.add_argument(
        "--name",
        required=True,
        help="Artifact alias or path (e.g. comparison_mode_a).",
    )
    check_artifact.set_defaults(func=cmd_check_artifact)

    validate_columns = subparsers.add_parser(
        "validate-comparison-columns",
        help="Compare comparison Mode A old/new columns with baselines.",
    )
    validate_columns.set_defaults(func=cmd_validate_comparison_columns)

    final_report = subparsers.add_parser(
        "final-report", help="Generate final bind report from all checks."
    )
    final_report.set_defaults(func=cmd_final_report)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
