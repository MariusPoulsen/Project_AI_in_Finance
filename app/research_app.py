"""Full read-only research application (PLAN P7). Launch with:

    uv run --frozen streamlit run app/research_app.py

Data source, in order: SB_APP_BUNDLE, demo/app_bundle, then the accepted
workspace (SB_WORKSPACE_ROOT). See app/README.md.
"""

import sys
from pathlib import Path

try:
    from structural_break.app_ui.main import run
except ModuleNotFoundError:  # hosted runtimes that did not install the project package
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from structural_break.app_ui.main import run

run()
