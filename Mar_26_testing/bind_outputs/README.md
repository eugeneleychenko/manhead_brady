# Bind Outputs

This directory stores artifacts used by the bind validation chain.

## Canonical Baselines
- `baseline_old.csv`: direct output from old hosted API (`/predict/size`)
- `baseline_new.csv`: direct output from new hosted API (`/api/predict`)

## Streamlit Parity Artifacts
- `new_local_streamlit.csv`: output downloaded from local new-model Streamlit app
- `new_cloud_streamlit.csv`: output downloaded from deployed new-model Streamlit app

## Comparison Tool Artifact
- `comparison_mode_a.csv`: output downloaded from comparison app Mode A

Expected prediction columns in `comparison_mode_a.csv`:
- old model quantity column: one of
  - `old_predicted_sales_quantity`
  - `old_model_predicted_sales_quantity`
  - `old_prediction`
  - `predicted_sales_quantity_old`
  - `old_predicted_qty`
- new model quantity column: one of
  - `new_predicted_sales_quantity`
  - `new_model_predicted_sales_quantity`
  - `new_prediction`
  - `predicted_sales_quantity_new`
  - `new_predicted_qty`

## Reports
- `comparison_columns_report.json`: detailed comparison-tool column validation results
- `bind_report.csv`: machine-readable final pass/fail matrix
- `bind_report.md`: human-readable final pass/fail report

## Final Bind Checks
The final report must include all four checks:
1. `old_api` vs `comparison_old_column`
2. `new_api` vs `new_local_streamlit`
3. `new_api` vs `new_cloud_streamlit`
4. `new_api` vs `comparison_new_column`

All four must be `MATCH` for an overall bind `PASS`.
