# Streamlit Cloud Deployment Notes

## New-Model Prediction App
- **URL**: `https://mh-predict-new-model.streamlit.app`
- **Repo**: `eugeneleychenko/manhead_brady`
- **Branch**: `new-model-streamlit-ui`
- **Entry point**: `prediction/prediction-streamlit-new-model.py`
- **Secret key**: `PREDICTION_API_BASE_URL`
- **Secret value**: `https://manhead-new-model-api.replit.app`

## Runtime Notes
- App may be asleep when first opened. Wake-up can take ~30-40 seconds.
- Step 4 upload/download flow was validated against canonical input on 2026-03-12.

## Comparison App
- **URL**: `https://manheadbrady-eagsteu3r5xgac6nwlavff.streamlit.app/`
- **Repo**: `eugeneleychenko/manhead_brady`
- **Branch**: `new-model-streamlit-ui`
- **Entry point**: `prediction/prediction-comparison.py`
- **Secrets**:
  - `OLD_MODEL_API_BASE_URL = https://fast-api-data-master-eugene59.replit.app`
  - `NEW_MODEL_API_BASE_URL = https://manhead-new-model-api.replit.app`
- Mode A upload/run/download validation completed on 2026-03-12 with canonical CSV.
