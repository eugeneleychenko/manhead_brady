"""
Thin wrapper for new-model deployment on Streamlit Community Cloud.
Uses the same app as prediction-streamlit.py but allows a separate deployment
with PREDICTION_API_BASE_URL=https://manhead-new-model-api.replit.app in secrets.
"""
import runpy
from pathlib import Path
_script_dir = Path(__file__).resolve().parent
runpy.run_path(str(_script_dir / "prediction-streamlit.py"), run_name="__main__")
