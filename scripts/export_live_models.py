"""Export the final-test bagged models so the app can score events live.

Run in the checkout holding data/team and outputs/book (the final-test checkout). For each
final-test year it refits the pre-registered bagged B+rule+ou model exactly as the
walk-forward did, checks that it reproduces every published raw score, and saves:

- the five seed models as XGBoost boosters (``live/bag5-<year>-<seed>.ubj``);
- the 132 inputs of every event of that year (``live/inputs.parquet``);
- each year's calibration (slope and intercept on the log-odds), recovered from the
  published raw and calibrated probabilities and checked to reproduce all of them;
- ``live.json`` binding all of it to the published forecasts.

The app only loads these files; it never fits a model.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from structural_break import periods
from structural_break.forecast import harness

SCHEMA = "live-bag5-v1"
SPEC, SCHEME, PARAMS = "B+rule+ou", "recent", "bag5"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def logit(p: np.ndarray) -> np.ndarray:
    q = np.clip(p, 1e-9, 1 - 1e-9)
    return np.asarray(np.log(q / (1 - q)), dtype=float)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", type=Path, default=Path("demo/results"))
    parser.add_argument("--workspace-root", type=Path, default=Path("data/team"))
    parser.add_argument("--outputs-root", type=Path, default=Path("outputs"))
    parser.add_argument("--years", nargs="+", type=int, default=list(periods.final_years_open()))
    args = parser.parse_args()
    if not args.years or not set(args.years) <= set(periods.final_years_open()):
        parser.error("Only unlocked final-test years can be exported")
    manifest_path = args.results / "manifest.json"
    original = manifest_path.read_bytes()
    manifest = json.loads(original)
    source = args.results / "forecasts.parquet"
    if sha(source) != manifest["files"][source.name]:
        raise ValueError("Current forecast export failed its hash check")
    forecasts = pd.read_parquet(source).set_index("event_id")
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
    columns = list(harness.feature_sets(base, list(frame.columns))[SPEC])
    import xgboost as xgb

    folder = args.results / "live"
    folder.mkdir(exist_ok=True)
    inputs, calibration, files = [], {}, []
    for year in sorted(set(args.years)):
        train, _, test = harness.split(frame, year, SCHEME)
        published = forecasts.loc[forecasts.year.eq(year)]
        if set(test.event_id) != set(published.index):
            raise ValueError(f"Reconstructed and published {year} populations differ")
        model = harness._estimator(harness.PARAMS[PARAMS])
        model.fit(train[columns].astype(float), train[harness.TARGET].astype(int))
        x = test[columns].astype(float)
        raw = model.predict_proba(x)[:, 1]
        expected = published.loc[test.event_id, "raw_bag5"].to_numpy(float)
        if not np.allclose(raw, expected, atol=1e-6, rtol=1e-6):
            raise ValueError(f"Bagged {year} fit does not reproduce the published raw scores")
        slope, intercept = np.polyfit(
            logit(expected), logit(published.loc[test.event_id, "p_bag5"].to_numpy(float)), 1
        )
        calibrated = 1 / (1 + np.exp(-(slope * logit(raw) + intercept)))
        if not np.allclose(calibrated, published.loc[test.event_id, "p_bag5"], atol=1e-6):
            raise ValueError(f"The {year} calibration does not reproduce the published scores")
        calibration[str(year)] = [float(slope), float(intercept)]
        for index, component in enumerate(model.models):
            name = f"live/bag5-{year}-{42 + index}.ubj"
            component.get_booster().save_model(args.results / name)
            files.append(name)
        inputs.append(test[["event_id", *columns]].assign(year=year))
        print(f"Verified and saved bagged {year}: {len(test)} events", flush=True)
    table = pd.concat(inputs, ignore_index=True)
    table.to_parquet(args.results / "live/inputs.parquet", index=False)
    files.append("live/inputs.parquet")
    if manifest_path.read_bytes() != original or sha(source) != manifest["files"][source.name]:
        raise ValueError("Presentation changed while the models were being exported")
    metadata = {
        "schema_version": SCHEMA,
        "model": "bag5",
        "xgboost_version": xgb.__version__,
        "forecast_sha256": sha(source),
        "years": sorted(int(y) for y in args.years),
        "columns": columns,
        "seeds": [42 + i for i in range(int(harness.PARAMS[PARAMS]["seeds"]))],
        "calibration": calibration,
    }
    (args.results / "live.json").write_text(json.dumps(metadata, indent=1), encoding="utf-8")
    for name in [*files, "live.json"]:
        manifest["files"][name] = sha(args.results / name)
    manifest_path.write_bytes(json.dumps(manifest, indent=1).encode("utf-8"))
    print("Exported the final-test models for live scoring", flush=True)


if __name__ == "__main__":
    main()
