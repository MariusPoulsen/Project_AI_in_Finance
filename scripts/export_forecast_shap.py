"""Explicit TreeSHAP export for every scored event; never invoked by app browsing.

Run in the checkout holding data/team and outputs/book. Reconstructs the unchanged annual
fits, verifies ALL their saved raw scores, then explains every event of each test year.

For each event and model the contributions are averaged over the bag's seed models (one for
R0, five for the bagged models) in log-odds. The export keeps each event's largest effects
plus one row with the sum of the rest, so the rows still add up exactly to the averaged
margin minus the averaged base value. A per-year summary over all inputs keeps the global
importance exact. Seed totals (base, margin and raw probability) are kept per seed so the
app can check them against the published forecasts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from structural_break import periods
from structural_break.forecast import harness
from structural_break.services.forecast_explanations import OTHER, SCHEMA, validate

SPECS = {
    "r0": ("B", "d45", "base"),
    "bag5": ("B+rule+ou", "recent", "bag5"),
    "track": ("B+rule+ou+track", "recent", "bag5"),
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def compact(
    model: str,
    events: pd.DataFrame,
    columns: list[str],
    values: np.ndarray,
    contributions: np.ndarray,
    top: int,
) -> list[dict[str, Any]]:
    """Each event's ``top`` largest seed-averaged contributions plus the sum of the rest."""
    rows: list[dict[str, Any]] = []
    order = np.argsort(-np.abs(contributions), axis=1, kind="stable")
    for position, event_id in enumerate(events.event_id):
        keep = order[position, :top]
        for number in keep:
            rows.append(
                {
                    "model": model,
                    "event_id": event_id,
                    "feature": columns[number],
                    "value": float(values[position, number]),
                    "contribution": float(contributions[position, number]),
                }
            )
        rest = float(np.delete(contributions[position], keep).sum())
        rows.append(
            {
                "model": model,
                "event_id": event_id,
                "feature": OTHER,
                "value": np.nan,
                "contribution": rest,
            }
        )
    return rows


def summary(model: str, year: int, columns: list[str], contributions: np.ndarray) -> pd.DataFrame:
    """Exact per-year totals over every event, for the global importance chart."""
    return pd.DataFrame(
        {
            "model": model,
            "year": year,
            "feature": columns,
            "n": len(contributions),
            "sum_abs": np.abs(contributions).sum(axis=0),
            "sum": contributions.sum(axis=0),
        }
    )


def main() -> None:
    last_year = periods.data_end().year
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=Path("demo/results"))
    parser.add_argument("--workspace-root", type=Path, default=Path("data/team"))
    parser.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    parser.add_argument("--years", nargs="+", type=int, default=list(range(2010, last_year + 1)))
    parser.add_argument("--top", type=int, default=15, help="Largest effects kept per event")
    parser.add_argument("--checkpoint-dir", type=Path, default=Path(".design/shap-checkpoints"))
    args = parser.parse_args()
    if not args.years or min(args.years) < 2010 or max(args.years) > last_year:
        parser.error(f"Years must lie in 2010–{last_year} (later years are locked)")
    if args.top < 1:
        parser.error("top must be positive")
    manifest_path = args.results / "manifest.json"
    original_bytes = manifest_path.read_bytes()
    manifest = json.loads(original_bytes)
    source = args.results / "forecasts.parquet"
    if sha(source) != manifest["files"][source.name]:
        raise ValueError("Current forecast export failed its hash check")
    forecasts = pd.read_parquet(source)
    if args.results.resolve().is_relative_to(
        args.workspace_root.resolve()
    ) or args.results.resolve().is_relative_to(args.outputs_root.resolve()):
        raise ValueError("Presentation writes must be outside the read-only sources")
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

    # Bind checkpoints to the exact reconstructed training/test data, parameters and
    # fitting implementation, not timestamps or just a presentation-file identity.
    bound_columns = sorted(
        {c for columns in sets.values() for c in columns}
        | {"event_id", "event_date", "horizon_end_date", "supervised_eligible", harness.TARGET}
    )
    frame_digest = hashlib.sha256(
        pd.util.hash_pandas_object(frame[bound_columns], index=True).to_numpy().tobytes()
    ).hexdigest()
    implementation = sha(Path(harness.__file__))
    totals: list[pd.DataFrame] = []
    values: list[pd.DataFrame] = []
    summaries: list[pd.DataFrame] = []
    names = ("events.parquet", "values.parquet", "summary.parquet")
    for model_key, (spec, scheme, params_key) in SPECS.items():
        columns = list(sets[spec])
        if not set(columns) <= set(frame):
            raise ValueError(f"Missing published inputs for {model_key}")
        for year in sorted(set(args.years)):
            checkpoint = args.checkpoint_dir / f"{model_key}-{year}-all-top{args.top}"
            binding = hashlib.sha256(
                json.dumps(
                    [
                        SCHEMA,
                        sha(source),
                        frame_digest,
                        implementation,
                        columns,
                        harness.PARAMS[params_key],
                        xgb.__version__,
                        args.top,
                    ]
                ).encode()
            ).hexdigest()
            receipt = checkpoint / "receipt.json"
            if receipt.is_file():
                saved = json.loads(receipt.read_bytes())
                if saved["binding"] == binding and all(
                    sha(checkpoint / name) == digest for name, digest in saved["files"].items()
                ):
                    totals.append(pd.read_parquet(checkpoint / "events.parquet"))
                    values.append(pd.read_parquet(checkpoint / "values.parquet"))
                    summaries.append(pd.read_parquet(checkpoint / "summary.parquet"))
                    print(f"Reused verified {model_key}/{year}", flush=True)
                    continue
            train, _, test = harness.split(frame, year, scheme)
            if test.empty:
                continue
            published = forecasts.loc[forecasts.year.eq(year)].set_index("event_id")
            if set(test.event_id) != set(published.index):
                raise ValueError("Reconstructed and published annual populations differ")
            estimator = harness._estimator(harness.PARAMS[params_key])
            estimator.fit(train[columns].astype(float), train[harness.TARGET].astype(int))
            x = test[columns].astype(float)
            all_raw = estimator.predict_proba(x)[:, 1]
            expected = published.loc[test.event_id, f"raw_{model_key}"].to_numpy(float)
            if not np.allclose(all_raw, expected, atol=1e-6, rtol=1e-6):
                raise ValueError(
                    f"Annual {model_key}/{year} fit does not reproduce published scores"
                )
            components = estimator.models if hasattr(estimator, "models") else [estimator]
            matrix = xgb.DMatrix(x, feature_names=columns)
            seed_rows = []
            contributions = np.zeros((len(test), len(columns)))
            for index, component in enumerate(components):
                booster = component.get_booster()
                shap = booster.predict(matrix, pred_contribs=True)
                margins = booster.predict(matrix, output_margin=True)
                raw = component.predict_proba(x)[:, 1]
                contributions += shap[:, :-1] / len(components)
                seed_rows.append(
                    pd.DataFrame(
                        {
                            "model": model_key,
                            "event_id": test.event_id.to_numpy(),
                            "year": year,
                            "seed": 42 + index,
                            "base": shap[:, -1].astype(float),
                            "margin": margins.astype(float),
                            "raw_probability": raw.astype(float),
                        }
                    )
                )
            year_totals = pd.concat(seed_rows, ignore_index=True)
            year_values = pd.DataFrame(
                compact(model_key, test, columns, x.to_numpy(float), contributions, args.top)
            )
            year_summary = summary(model_key, year, columns, contributions)
            checkpoint.mkdir(parents=True, exist_ok=True)
            for name, table in zip(names, (year_totals, year_values, year_summary), strict=True):
                table.to_parquet(checkpoint / name, index=False)
            receipt.write_text(
                json.dumps(
                    {"binding": binding, "files": {name: sha(checkpoint / name) for name in names}}
                )
            )
            totals.append(year_totals)
            values.append(year_values)
            summaries.append(year_summary)
            print(f"Verified and explained {model_key}/{year}: {len(test)} events", flush=True)
    event_frame = pd.concat(totals, ignore_index=True)
    value_frame = pd.concat(values, ignore_index=True)
    summary_frame = pd.concat(summaries, ignore_index=True)
    validate(event_frame, value_frame, forecasts, summary_frame)
    if (
        manifest_path.read_bytes() != original_bytes
        or sha(source) != manifest["files"][source.name]
    ):
        raise ValueError("Presentation changed while SHAP was being generated")
    event_frame.to_parquet(args.results / "shap_events.parquet", index=False)
    value_frame.to_parquet(args.results / "shap_values.parquet", index=False)
    summary_frame.to_parquet(args.results / "shap_summary.parquet", index=False)
    metadata = {
        "schema_version": SCHEMA,
        "xgboost_version": xgb.__version__,
        "forecast_sha256": sha(source),
        "years": [int(min(args.years)), int(max(args.years))],
        "coverage": "Every scored event of each year",
        "top_features": args.top,
        "units": "Native TreeSHAP log-odds averaged over the bag's seed models; the remaining "
        "inputs are summed in one row",
        "source_hashes": {
            p.relative_to(args.outputs_root).as_posix(): sha(p)
            for p in (
                args.outputs_root / "book/features.parquet",
                args.outputs_root / "book/ou_features.parquet",
                track,
            )
            if p.is_file()
        },
    }
    (args.results / "shap.json").write_bytes(json.dumps(metadata, indent=2).encode("utf-8"))
    for name in ("shap_events.parquet", "shap_values.parquet", "shap_summary.parquet", "shap.json"):
        manifest["files"][name] = sha(args.results / name)
    manifest_path.write_bytes(json.dumps(manifest, indent=1).encode("utf-8"))
    print("Exported verified current-model SHAP; no research outputs were modified", flush=True)


if __name__ == "__main__":
    main()
