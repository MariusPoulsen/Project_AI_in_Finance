"""Pin existing development presentation files; never read research/final-test outputs.

Run explicitly after exporting demo/book. This registers provenance and model roles,
not new results. The app never calls this script.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    folder = ROOT / "demo/book"
    source = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
    roles = [
        (
            "A",
            "Model A",
            "Price reference",
            "Quantitative price features. The reference for the incremental SEC comparison.",
        ),
        (
            "R0",
            "Model B / R0",
            "Adopted book selector",
            "Original fixed-XGBoost Model B adds SEC evidence to prices. R0 still selects trades.",
        ),
        (
            "B_rule_ou",
            "B+rule+ou · bag5",
            "Preregistered forecaster",
            "Adds the reversion rule and Ornstein–Uhlenbeck features, bagged over five seeds. "
            "The preregistered Goal 1 choice; improved forecasting did not select a better book.",
        ),
        (
            "B_rule_ou_track",
            "B+rule+ou+track · bag5",
            "Post-hoc best observed",
            "Adds pair-track features. Best observed point estimates, chosen after inspection; "
            "not an independent confirmation of model selection.",
        ),
    ]
    definition = (
        "Fresh |z| >= 2 divergence; convergence to |z| <= 0.5 within 20 sessions "
        "before |z| >= 3. Matched labelled walk-forward events."
    )
    manifest = {
        "schema_version": 1,
        "final_test": "locked",
        "files": {
            name: hashlib.sha256((folder / name).read_bytes()).hexdigest()
            for name in ("summary.json", "book_daily.parquet")
        },
        "models": [
            {
                "id": key,
                "source_name": row["model"],
                "name": name,
                "role": role,
                "explanation": explanation,
            }
            for (key, name, role, explanation), row in zip(roles, source["goal1"], strict=True)
        ],
        "cohorts": {
            "2018–2023 · confirmation": {
                "id": "walk-forward-labelled-2018-2023",
                "n": 10940,
                "definition": definition,
            },
            "2010–2017 · selection": {
                "id": "walk-forward-labelled-2010-2017",
                "n": 11048,
                "definition": definition,
            },
        },
        "source": "demo/book export; docs/FORECASTING_AND_BOOK.md; Decisions 105–117. "
        "Development periods were reused during research; not an untouched final test.",
        "precision": "Forecast metrics are rounded published point estimates. "
        "Per-event current-model predictions, uncertainty and calibration arrays "
        "are not included. Hashes identify presentation bytes, not scientific acceptance.",
    }
    (folder / "presentation.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print("Pinned demo/book/presentation.json (development presentation only)")


if __name__ == "__main__":
    main()
