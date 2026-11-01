"""Export complete development diagnostics, cached evidence and Full stack SHAP.

All analytical sources are read-only. This explicit offline job reproduces the
unchanged logistic stack and checks every published Full/base score; it makes
no network/provider calls and never reads a final-test checkout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd

from structural_break.agents import desk_runner as desk
from structural_break.agents.debate import Case
from structural_break.forecast import harness
from structural_break.services import current_monitor, full_explanations


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--outputs-root", type=Path, required=True)
    parser.add_argument("--results", type=Path, default=Path("demo/results"))
    args = parser.parse_args()
    for root in (args.workspace_root, args.outputs_root):
        if args.results.resolve().is_relative_to(root.resolve()):
            raise ValueError("Write outside the read-only analytical sources")
    manifest_path = args.results / "manifest.json"
    original = manifest_path.read_bytes()
    manifest = json.loads(original)
    forecast_path = args.results / "forecasts.parquet"
    if sha(forecast_path) != manifest["files"][forecast_path.name]:
        raise ValueError("Forecast checksum differs")
    forecasts = pd.read_parquet(forecast_path)
    if forecasts.year.gt(2023).any() or manifest.get("final_test_included"):
        raise ValueError("This exporter accepts development results only")
    evaluation = (
        args.workspace_root / "artifacts/research/research_evaluation_16a431c4fea73ffd35f56062"
    )
    sources = [
        evaluation / "model_inputs.parquet",
        evaluation / "predictions.parquet",
        evaluation / "report.json",
        args.outputs_root / "book/features.parquet",
        args.outputs_root / "book/ou_features.parquet",
        args.outputs_root / "book/scores__B+rule+ou__recent-bag5.parquet",
        args.outputs_root / "agent_desk/entry_inventory.parquet",
    ]
    source_hashes = {str(p): sha(p) for p in sources}
    arguments = harness.parser().parse_args(
        [
            "summary",
            "--workspace-root",
            str(args.workspace_root),
            "--features",
            str(args.outputs_root / "book/features.parquet"),
            "--simulation",
            str(args.outputs_root / "walkforward/simulation_frozen_exit.parquet"),
            "--exits-dir",
            str(args.outputs_root / "news_exit"),
        ]
    )
    frame, _, _ = harness.load(arguments)
    fields = [c for c in frame if c in current_monitor.INPUTS]
    inputs = forecasts[["event_id"]].merge(
        frame[["event_id", *fields]],
        on="event_id",
        how="left",
        validate="one_to_one",
        indicator=True,
    )
    if not inputs.pop("_merge").eq("both").all():
        raise ValueError("Some scored events have no current model input row")
    print(f"Verified current inputs for {len(inputs):,} events, {len(fields)} features", flush=True)
    output = args.outputs_root / "agent_desk"
    inventory = pd.read_parquet(output / "entry_inventory.parquet")
    records: list[dict[str, Any]] = []
    event_ids = set(forecasts.event_id)
    digest = hashlib.sha256()
    for record in inventory.to_dict("records"):
        event_id = str(record["event_id"])
        if event_id not in event_ids:
            continue
        case_path = output / "entry_cases" / f"{event_id}.json"
        result_path = output / "entry_results" / f"{event_id}.json"
        case = json.loads(case_path.read_bytes()) if case_path.is_file() else None
        result = desk.load_result(output, "entry", event_id)
        if case is not None:
            parsed = Case.from_json(case)
            if result and result.get("case_sha256") != parsed.digest:
                raise ValueError(f"Stale agent result for {event_id}")
            stamp = pd.Timestamp(case["event"]["event_timestamp"])
            for chunk in case["event"]["evidence"]:
                if pd.Timestamp(chunk["source_timestamp"]) > stamp:
                    raise ValueError("Agent evidence timestamp is later than event close")
        if result and case is None:
            raise ValueError("Agent result lacks its source case")
        compact = None
        if result:
            compact = {
                k: result.get(k)
                for k in (
                    "status",
                    "scores",
                    "analyst_scores",
                    "debated",
                    "prompt_version",
                    "graph_version",
                    "case_sha256",
                )
            }
            compact["stages"] = {
                name: {k: stage.get(k) for k in ("status", "model", "error", "report", "rejected")}
                for name, stage in result.get("stages", {}).items()
            }
        for path in (case_path, result_path):
            if path.is_file():
                digest.update((path.name + sha(path)).encode())
        records.append(
            {
                "event_id": event_id,
                "status": str(record["status"]),
                "case_json": json.dumps(
                    {
                        "event": {
                            k: case["event"][k]
                            for k in (
                                "event_id",
                                "pair_id",
                                "event_timestamp",
                                "evidence",
                                "lineage",
                            )
                        }
                    },
                    ensure_ascii=False,
                )
                if case
                else "null",
                "result_json": json.dumps(compact, ensure_ascii=False),
            }
        )
    cases = pd.DataFrame(records)
    print(f"Verified {len(cases):,} cached desk records and point-in-time evidence", flush=True)
    table = desk.entry_features(output, "desk")
    targets = frame.set_index("event_id")["y_revert_success"]
    table["y"] = table.event_id.map(targets)
    probabilities = (
        pd.read_parquet(args.outputs_root / "book/scores__B+rule+ou__recent-bag5.parquet")
        .set_index("event_id")
        .probability
    )
    table["base_score"] = table.event_id.map(probabilities)
    table = table.dropna(subset=["y", "base_score"]).reset_index(drop=True)
    table["y"] = table.y.astype(int)
    totals, values = full_explanations.reconstruct(table)
    full_explanations.validate(totals, values, forecasts)
    print(
        f"Verified exact Full/base explanations for {totals.event_id.nunique():,} events",
        flush=True,
    )
    if (
        original != manifest_path.read_bytes()
        or sha(forecast_path) != manifest["files"][forecast_path.name]
        or any(sha(Path(p)) != expected for p, expected in source_hashes.items())
    ):
        raise ValueError("Sources changed while exporting; no publication")
    for name, data in (
        ("diagnostic_inputs", inputs),
        ("event_cases", cases),
        ("full_shap_events", totals),
        ("full_shap_values", values),
    ):
        target = args.results / f"{name}.parquet"
        data.to_parquet(target, index=False, compression="zstd")
        manifest["files"][target.name] = sha(target)
    manifest["investigation_reference"] = {
        "schema_version": "development-investigations-v1",
        "forecast_sha256": sha(forecast_path),
        "source_hashes": source_hashes,
        "desk_records_sha256": digest.hexdigest(),
        "input_events": len(inputs),
        "input_features": fields,
        "full_background": "Annual training mean, interventional linear SHAP in log-odds; "
        "interaction is a separate input",
    }
    manifest_path.write_bytes(json.dumps(manifest, indent=1).encode())
    print("Published development investigation sidecars; source outputs unchanged", flush=True)


if __name__ == "__main__":
    main()
