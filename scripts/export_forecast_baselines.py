"""Export the registered historical ACTIVE flags, without modifying forecast/source bytes."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from structural_break.config.paths import ProjectPaths
from structural_break.research.primary import checked_file, registered_manifest
from structural_break.services.forecast_baselines import validate_flags


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--evaluation-version", required=True)
    parser.add_argument("--results", type=Path, default=Path("demo/results"))
    args = parser.parse_args()
    if args.results.resolve().is_relative_to(args.workspace_root.resolve()):
        raise ValueError("Write the presentation export outside the read-only source workspace")
    manifest_path = args.results / "manifest.json"
    original = manifest_path.read_bytes()
    manifest = json.loads(original)
    forecast_path = args.results / "forecasts.parquet"
    forecast_sha = sha(forecast_path)
    if forecast_sha != manifest["files"]["forecasts.parquet"]:
        raise ValueError("Forecast checksum differs")
    forecasts = pd.read_parquet(forecast_path)
    if forecasts.year.gt(2023).any():
        raise ValueError("This supplemental baseline export is development-only")
    source_manifest, source = registered_manifest(
        ProjectPaths.resolve(Path.cwd(), args.workspace_root), args.evaluation_version, "evaluation"
    )
    path = checked_file(source_manifest.parent, source, "model_inputs")
    inputs = pd.read_parquet(path, columns=["event_id", "baseline1_eligible"])
    if inputs.event_id.duplicated().any():
        raise ValueError("Duplicate source event IDs")
    flags = forecasts[["event_id"]].merge(inputs, how="left", on="event_id", validate="one_to_one")
    validate_flags(flags, forecasts)
    if manifest_path.read_bytes() != original or sha(forecast_path) != forecast_sha:
        raise ValueError("Results changed during the baseline export")
    target = args.results / "baseline_events.parquet"
    flags.to_parquet(target, index=False)
    manifest["baseline_reference"] = {
        "schema_version": "forecast-baseline-flags-v1",
        "forecast_sha256": forecast_sha,
        "evaluation_version": args.evaluation_version,
        "source_manifest_sha256": sha(source_manifest),
        "source_inputs_sha256": sha(path),
    }
    manifest["files"][target.name] = sha(target)
    manifest_path.write_bytes(json.dumps(manifest, indent=1).encode())
    print(f"Exported historical ACTIVE flags for all {len(flags):,} current forecast events")


if __name__ == "__main__":
    main()
