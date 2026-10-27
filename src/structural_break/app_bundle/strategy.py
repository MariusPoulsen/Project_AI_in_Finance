"""Compact, verified views of official Phase 6 historical experiments.

The experiment directory is checked against its own manifest (every artifact's
SHA-256) and against the selected primary/evaluation generation before anything
is read. Unknown executions keep their counts; they are never shown as zero.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from structural_break.app_bundle.contracts import RUNGS
from structural_break.backtest.historical_experiment import read_manifest

SUMMARY_FIELDS = (
    "population_n",
    "selected_n",
    "withheld_n",
    "unavailable_n",
    "selection_rate_all_rows",
    "selection_rate_available_rows",
)
ECONOMIC_FIELDS = (
    "priced_n",
    "unknown_return_n",
    "mean_net_return",
    "median_net_return",
    "mean_gross_return",
    "mean_trading_cost",
    "mean_borrow_cost",
    "mean_holding_sessions",
    "mean_mae",
    "mean_mfe",
    "net_positive_rate",
    "net_positive_n",
    "net_negative_n",
)


class ExperimentMismatchError(ValueError):
    """The experiment was built from a different accepted generation."""


def find_experiments(root: Path) -> list[Path]:
    """Experiment manifests under an acceptance/output directory, in path order."""
    if not root.exists():
        return []
    return sorted(root.glob("**/historical-experiments/*/manifest.json"))


def _verified_artifacts(manifest_path: Path) -> tuple[Any, dict[str, bytes]]:
    manifest = read_manifest(manifest_path)
    raw = json.loads(manifest_path.read_bytes())
    artifacts: dict[str, bytes] = {}
    for item in raw["artifacts"]:
        body = (manifest_path.parent / item["path"]).read_bytes()
        if hashlib.sha256(body).hexdigest() != item["sha256"]:
            raise ValueError(f"Phase 6 artifact checksum differs: {item['path']}")
        artifacts[item["path"]] = body
    return manifest, artifacts


def _rung_row(rung: str, data: dict[str, Any]) -> dict[str, Any]:
    if data.get("status") == "NOT_RUN":
        return {"rung": rung, "status": "NOT_RUN", "reason": data.get("reason")}
    economics = data.get("selected_economics") or {}
    labels = data.get("selected_labels") or {}
    counter = data.get("not_selected_counterfactual_economics") or {}
    statuses = economics.get("status_counts") or {}
    return {
        "rung": rung,
        "status": "RUN",
        **{name: data.get(name) for name in SUMMARY_FIELDS},
        **{name: economics.get(name) for name in ECONOMIC_FIELDS},
        "not_entered_n": statuses.get("NOT_ENTERED", 0),
        "unpriced_n": statuses.get("UNPRICED", 0),
        "complete_n": statuses.get("COMPLETE", 0),
        "label_success_rate": labels.get("label_success_rate"),
        "labelled_n": labels.get("labelled_n"),
        "label_successes": labels.get("label_successes"),
        "not_selected_priced_n": counter.get("priced_n"),
        "not_selected_mean_net_return": counter.get("mean_net_return"),
        "not_selected_net_positive_rate": counter.get("net_positive_rate"),
        "exit_reasons": json.dumps(economics.get("reason_counts") or {}, sort_keys=True),
    }


def _bootstrap(block: dict[str, Any] | None) -> dict[str, Any]:
    if not block:
        return {}
    boot = block.get("bootstrap") or {}
    return {
        "estimate": block.get("right_minus_left_mean"),
        "interval": boot.get("percentile_interval_95"),
        "unavailable_reason": boot.get("interval_unavailable_reason"),
        "contributing_months": boot.get("contributing_calendar_month_blocks_n"),
    }


def compact_experiment(
    manifest_path: Path,
    *,
    primary_version: str,
    evaluation_version: str,
) -> tuple[int, dict[str, Any], pd.DataFrame, pd.DataFrame]:
    """Return (horizon, summary, NAV marks, headline trades) for one experiment."""
    manifest, artifacts = _verified_artifacts(manifest_path)
    if not manifest.post_hoc_development or manifest.final_test_unlocked:
        raise ValueError("Only locked post-hoc development experiments can be displayed")
    binding = json.loads(artifacts["binding.json"])
    if (
        binding.get("primary_version") != primary_version
        or binding.get("evaluation", {}).get("version") != evaluation_version
    ):
        raise ExperimentMismatchError(
            "The Phase 6 experiment belongs to a different accepted generation"
        )
    reports = json.loads(artifacts["reports.json"])
    combinations = [item.model_dump(mode="json") for item in manifest.combinations]
    headline = next(item for item in combinations if item["role"] == "HEADLINE")
    rung_rows = []
    for item in combinations:
        report = reports[item["key"]]
        for rung in RUNGS:
            rung_row = _rung_row(rung, report["natural_rungs"].get(rung, {}))
            rung_row.update(
                combination=item["key"],
                role=item["role"],
                threshold=item["threshold"],
                execution_config_version=item["execution_config_version"],
            )
            rung_rows.append(rung_row)
    cost_grid = json.loads(artifacts["cost-grid.json"])
    costs = []
    for scenario in cost_grid["scenarios"]:
        for rung, data in scenario["rungs"].items():
            costs.append(
                {
                    "cost_bps_per_side": scenario["cost_bps_per_side"],
                    "annual_borrow_rate": scenario["annual_borrow_rate"],
                    "rung": rung,
                    "selected_n": data.get("selected_n"),
                    "priced_n": data.get("priced_n"),
                    "mean_net_return": data.get("mean_net_return"),
                }
            )
    uncertainty = json.loads(artifacts["uncertainty.json"])
    comparisons = []
    for key, data in uncertainty["comparisons"].items():
        row: dict[str, Any] = {"comparison": key, "left": data["left"], "right": data["right"]}
        if data.get("status") == "NOT_RUN":
            row.update(status="NOT_RUN", reason=data.get("reason"))
        else:
            row.update(
                status="RUN",
                common_known=_bootstrap(data.get("common_known_allocation_per_raw_candidate")),
                natural=_bootstrap(data.get("natural_selected_complete")),
                raw_candidate_population_n=data.get("raw_candidate_population_n"),
            )
        comparisons.append(row)
    portfolios = json.loads(artifacts["portfolios.json"])
    portfolio_rows = []
    marks = []
    for rung, data in portfolios.items():
        if data.get("status") == "NOT_RUN":
            portfolio_rows.append({"rung": rung, "status": "NOT_RUN", "reason": data.get("reason")})
            continue
        portfolio_rows.append(
            {
                "rung": rung,
                "status": "RUN",
                **{
                    name: data.get(name)
                    for name in (
                        "initial_nav",
                        "final_nav",
                        "maximum_drawdown",
                        "known_turnover",
                        "known_trading_cost",
                        "known_borrow_cost",
                    )
                },
                "limitations": data.get("limitations", []),
            }
        )
        for mark in data.get("marks", []):
            marks.append(
                {
                    "rung": rung,
                    "at": mark["at"],
                    "nav": mark.get("nav"),
                    "drawdown": mark.get("drawdown"),
                    "gross_exposure": mark.get("gross_exposure"),
                    "open_positions": mark.get("open_positions"),
                    "nav_unknown": mark.get("nav_unknown_since") is not None,
                }
            )
    nav = pd.DataFrame(marks)
    if not nav.empty:
        nav["at"] = pd.to_datetime(nav["at"], utc=True)
    trades = _headline_trades(artifacts, float(headline["threshold"]))
    headline_report = reports[headline["key"]]
    summary = {
        "experiment_id": manifest.experiment_id,
        "horizon": int(manifest.horizon_sessions),
        "event_count": int(manifest.event_count),
        "headline": headline,
        "combinations": combinations,
        "rungs": rung_rows,
        "cost_grid": costs,
        "comparisons": comparisons,
        "portfolios": portfolio_rows,
        "limitations": headline_report.get("limitations", []),
        "label_coverage": headline_report.get("label_coverage", {}),
        "calendar_months": uncertainty.get("calendar_months", []),
        "full_system": "NOT_RUN",
        "post_hoc_development": True,
        "final_test_read": False,
    }
    return int(manifest.horizon_sessions), summary, nav, trades


def _headline_trades(artifacts: dict[str, bytes], threshold: float) -> pd.DataFrame:
    executions = json.loads(artifacts["executions-primary.json"])["results"]
    selections = json.loads(artifacts["selections.json"])["thresholds"]
    chosen = next(item for item in selections if float(item["threshold"]) == threshold)
    flags: dict[str, dict[str, str]] = {}
    for row in chosen["rows"]:
        flags[row["event_id"]] = {item["rung"]: item["disposition"] for item in row["selections"]}
    output = []
    for result in executions:
        entry, exit_ = result.get("entry") or {}, result.get("exit") or {}
        row = {
            "event_id": result["event_id"],
            "pair_id": result["pair_id"],
            "status": result["status"],
            "reason": result["reason"],
            "signal_z": result.get("signal_z"),
            "entry_date": entry.get("session_date"),
            "exit_date": exit_.get("session_date"),
            "holding_sessions": result.get("holding_sessions"),
            "gross_return": result.get("gross_return"),
            "net_return": result.get("net_return"),
            "mae": result.get("mae"),
            "mfe": result.get("mfe"),
        }
        for rung in RUNGS:
            row[rung] = flags.get(result["event_id"], {}).get(rung, "UNKNOWN")
        output.append(row)
    return pd.DataFrame(output)
