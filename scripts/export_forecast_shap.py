"""Explicit development-only TreeSHAP export; never invoked by app browsing.

Run in the development checkout holding data/team and outputs/book. Reconstructs
the unchanged annual fits, verifies ALL their saved raw scores, then explains a
target-blind event sample. Bagged components are explained separately in margin
space; their margins must never be presented as the bag's averaged probability.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from structural_break.forecast import harness
from structural_break.services.forecast_explanations import validate

SPECS = {
    "r0": ("B", "d45", "base"),
    "bag5": ("B+rule+ou", "recent", "bag5"),
    "track": ("B+rule+ou+track", "recent", "bag5"),
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sample(events: pd.DataFrame, limit: int) -> pd.DataFrame:
    """Stable selection without looking at outcomes, confidence or feature values."""
    order = events.event_id.map(lambda x: hashlib.sha256(str(x).encode()).hexdigest())
    return events.assign(_order=order).sort_values("_order").head(limit).drop(columns="_order")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=Path("demo/results"))
    parser.add_argument("--workspace-root", type=Path, default=Path("data/team"))
    parser.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    parser.add_argument("--years", nargs="+", type=int, default=list(range(2018, 2024)))
    parser.add_argument("--events-per-year", type=int, default=40)
    args = parser.parse_args()
    if not args.years or min(args.years) < 2010 or max(args.years) > 2023:
        parser.error("Only development years 2010–2023 can be explained by this command")
    if args.events_per_year < 1:
        parser.error("events-per-year must be positive")
    manifest_path = args.results / "manifest.json"
    original_bytes = manifest_path.read_bytes()
    manifest = json.loads(original_bytes)
    source = args.results / "forecasts.parquet"
    if sha(source) != manifest["files"][source.name]:
        raise ValueError("Current forecast export failed its hash check")
    forecasts = pd.read_parquet(source)
    harness_args = harness.parser().parse_args(
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
    frame, base, _ = harness.load(harness_args)
    # Track inputs are already bound to the published forecast, never regenerated here.
    track = args.outputs_root / "book/track_features.parquet"
    if track.is_file():
        track_frame = pd.read_parquet(track)
        missing = [c for c in track_frame if c not in frame and c != "event_id"]
        frame = frame.merge(
            track_frame[["event_id", *missing]], on="event_id", how="left", validate="one_to_one"
        )
    sets = harness.feature_sets(base, list(frame.columns))
    import xgboost as xgb

    totals: list[dict[str, Any]] = []
    contributions: list[dict[str, Any]] = []
    for model_key, (spec, scheme, params_key) in SPECS.items():
        columns = sets[spec]
        if not set(columns) <= set(frame):
            raise ValueError(f"Missing published inputs for {model_key}")
        for year in sorted(set(args.years)):
            train, _, test = harness.split(frame, year, scheme)
            if test.empty:
                continue
            published = forecasts.loc[forecasts.year.eq(year)].set_index("event_id")
            if set(test.event_id) != set(published.index):
                raise ValueError("Reconstructed and published annual populations differ")
            estimator = harness._estimator(harness.PARAMS[params_key])
            estimator.fit(train[list(columns)].astype(float), train[harness.TARGET].astype(int))
            all_raw = estimator.predict_proba(test[list(columns)].astype(float))[:, 1]
            expected = published.loc[test.event_id, f"raw_{model_key}"].to_numpy(float)
            if not np.allclose(all_raw, expected, atol=1e-6, rtol=1e-6):
                raise ValueError(
                    f"Annual {model_key}/{year} fit does not reproduce published scores"
                )
            chosen = sample(test, args.events_per_year)
            x = chosen[list(columns)].astype(float)
            input_values = x.to_numpy(dtype=float)
            components = estimator.models if hasattr(estimator, "models") else [estimator]
            for index, component in enumerate(components):
                booster = component.get_booster()
                matrix = xgb.DMatrix(x, feature_names=list(columns))
                shap = booster.predict(matrix, pred_contribs=True)
                margins = booster.predict(matrix, output_margin=True)
                raw = component.predict_proba(x)[:, 1]
                for position, event in enumerate(chosen.itertuples()):
                    totals.append(
                        {
                            "model": model_key,
                            "event_id": event.event_id,
                            "year": year,
                            "seed": 42 + index,
                            "base": float(shap[position, -1]),
                            "margin": float(margins[position]),
                            "raw_probability": float(raw[position]),
                        }
                    )
                    for number, feature in enumerate(columns):
                        contributions.append(
                            {
                                "model": model_key,
                                "event_id": event.event_id,
                                "seed": 42 + index,
                                "feature": feature,
                                "value": float(input_values[position, number]),
                                "contribution": float(shap[position, number]),
                            }
                        )
            print(
                f"Verified {model_key}/{year}: {len(test)} scores; explained {len(chosen)} events",
                flush=True,
            )
    event_frame, value_frame = pd.DataFrame(totals), pd.DataFrame(contributions)
    validate(event_frame, value_frame, forecasts)
    if (
        manifest_path.read_bytes() != original_bytes
        or sha(source) != manifest["files"][source.name]
    ):
        raise ValueError("Presentation changed while SHAP was being generated")
    event_frame.to_parquet(args.results / "shap_events.parquet", index=False)
    value_frame.to_parquet(args.results / "shap_values.parquet", index=False)
    metadata = {
        "schema_version": "current-tree-shap-v1",
        "xgboost_version": xgb.__version__,
        "forecast_sha256": sha(source),
        "events_per_year": args.events_per_year,
        "sampling": "Lowest SHA-256(event_id), independently in each year",
        "units": "Native TreeSHAP log-odds of each seed component; not bag probability",
        "source_hashes": {
            str(p.relative_to(args.outputs_root)): sha(p)
            for p in (
                args.outputs_root / "book/features.parquet",
                args.outputs_root / "book/ou_features.parquet",
                track,
            )
            if p.is_file()
        },
    }
    (args.results / "shap.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    for name in ("shap_events.parquet", "shap_values.parquet", "shap.json"):
        manifest["files"][name] = sha(args.results / name)
    manifest_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print("Exported verified current-model SHAP; no research outputs were modified", flush=True)


if __name__ == "__main__":
    main()
