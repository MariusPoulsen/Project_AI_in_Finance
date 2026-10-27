"""Export current study metadata and saved diagnostics, without fitting or final-test reads."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outputs-root", type=Path)
    args = parser.parse_args()
    folder = ROOT / "demo/book"
    specs = [
        (
            "BASELINE_0",
            "Baseline 0",
            "Deterministic benchmark",
            "Rule",
            "Every fresh divergence",
            "No fitting",
            "Policy cohort",
            "Probability metrics not applicable",
        ),
        (
            "BASELINE_1",
            "Baseline 1",
            "Deterministic benchmark",
            "Rule",
            "Econometrically ACTIVE",
            "Monthly relationship tests",
            "Policy cohort",
            "Probability metrics not applicable",
        ),
        (
            "A",
            "Model A",
            "Price reference",
            "Fixed XGBoost",
            "Quantitative prices and relationship",
            "Annual walk-forward · Decision 45",
            "Matched population",
            "Published metrics",
        ),
        (
            "R0",
            "Model B / R0",
            "Book selector",
            "Fixed XGBoost",
            "Quantitative + SEC metadata/tone",
            "Annual walk-forward · Decision 45",
            "Matched population",
            "Published metrics",
        ),
        (
            "B_rule_ou",
            "B+rule+ou · bag5",
            "Preregistered forecaster",
            "XGBoost · 5 seeds",
            "B + peer/state/earnings/momentum + OU",
            "Annual walk-forward; OOF calibration",
            "Matched population",
            "Published metrics",
        ),
        (
            "B_rule_ou_track",
            "B+rule+ou+track · bag5",
            "Post-hoc variant",
            "XGBoost · 5 seeds",
            "B+rule+ou + historical pair/stock track record",
            "Annual walk-forward; OOF calibration",
            "Matched population",
            "Published metrics",
        ),
        (
            "FULL",
            "Full model",
            "Agent-augmented forecaster",
            "Walk-forward logistic stack",
            "Bagged base logit + entry-desk scores and missingness",
            "Earlier labelled region years only",
            "Desk region · matched base comparator",
            "Separate regional comparison",
        ),
    ]
    fields = ["id", "Model", "Role", "Family", "Inputs", "Training", "Scope", "Status"]
    models = [dict(zip(fields, spec, strict=True)) for spec in specs]
    # Rounded, already-published development values; never present them as fresh evaluation.
    regional = [
        {
            "Model": "Desk base · no agent scores",
            "Period": "2011–2017",
            "ROC AUC": 0.640,
            "Brier score": 0.0917,
            "Log loss": None,
            "Events": None,
            "Source": "Decision 110d · rounded · top-40% region",
        },
        {
            "Model": "Full model",
            "Period": "2011–2017",
            "ROC AUC": 0.631,
            "Brier score": 0.0928,
            "Log loss": None,
            "Events": None,
            "Source": "Decision 110d · rounded · same region as desk base",
        },
    ]
    sources = {"Published regional comparison": "docs/DECISIONS.md §110d"}
    if args.outputs_root:
        report_path = args.outputs_root / "agent_desk/evaluation_holdout.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        regional = []
        for period, result in report["forecast"]["desk|B+rule+ou"].items():
            if period not in {"2011-2017", "2018-2023"}:
                raise ValueError("Only published development desk periods are allowed")
            for key, label in (("base", "Desk base · no agent scores"), ("agents", "Full model")):
                values = result[key]
                regional.append(
                    {
                        "Model": label,
                        "Period": period.replace("-", "–"),
                        "ROC AUC": values["auc"],
                        "Brier score": values["brier"],
                        "Log loss": values["log_loss"],
                        "Events": values["n"],
                        "Source": "Saved desk evaluation · matched region",
                    }
                )
        sources["Saved regional evaluation SHA-256"] = hashlib.sha256(
            report_path.read_bytes()
        ).hexdigest()
    availability = [
        {
            "Diagnostic": "Walk-forward metrics",
            "Status": "Available",
            "Scope": "Four matched forecasters",
        },
        {
            "Diagnostic": "ROC and reliability figures",
            "Status": "Available",
            "Scope": "Published 2018–2023 plots",
        },
        {
            "Diagnostic": "Full-model metrics",
            "Status": "Regional records only",
            "Scope": "Desk subset; see period and denominator",
        },
        {
            "Diagnostic": "Current per-event scores / SHAP / tuning receipts",
            "Status": "Not exported",
            "Scope": "No substitution from older models",
        },
        {
            "Diagnostic": "Book statistics",
            "Status": "Available",
            "Scope": "Four books; Decision 119a correction",
        },
        {
            "Diagnostic": "Daily NAV",
            "Status": "Two books exported",
            "Scope": "R0 with/without monitor",
        },
    ]
    result = {
        "schema_version": 1,
        "models": models,
        "regional": regional,
        "sources": sources,
        "availability": availability,
    }
    (folder / "study.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    for source, destination in (
        ("goal1_roc_holdout.png", "roc.png"),
        ("goal1_calibration_holdout.png", "calibration.png"),
    ):
        shutil.copyfile(ROOT / "docs/figures/quant" / source, folder / destination)
    print("Exported saved development diagnostics; run export_research_presentation.py to pin them")


if __name__ == "__main__":
    main()
