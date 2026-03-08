"""
Thin wrapper for new-model deployment on Streamlit Community Cloud.
Runs the new-model Streamlit UI implementation from deploy/streamlit_ui.
"""
import runpy
from pathlib import Path

_repo_root = Path(__file__).resolve().parent.parent
_target = _repo_root / "deploy" / "streamlit_ui" / "streamlit_app.py"
runpy.run_path(str(_target), run_name="__main__")
