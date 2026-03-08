"""
Thin wrapper for new-model deployment on Streamlit Community Cloud.
Runs the new-model Streamlit UI implementation from deploy/streamlit_ui.
"""
import runpy
import sys
from pathlib import Path

_repo_root = Path(__file__).resolve().parent.parent
_target_dir = _repo_root / "deploy" / "streamlit_ui"
_target = _target_dir / "streamlit_app.py"
sys.path.insert(0, str(_target_dir))
runpy.run_path(str(_target), run_name="__main__")
