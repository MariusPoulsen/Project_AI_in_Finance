"""Tiny synthetic registered workspace for historical-adapter tests.

Every file is invented: four tickers, two pairs and four fresh crossings in late
2023. The workspace mimics the registered manifest chain only so the adapters'
binding, reconciliation and refusal rules can be exercised offline.
"""

import hashlib
import json
from datetime import date, datetime
from math import exp, log
from pathlib import Path
from typing import Any

import pandas as pd

from structural_break.backtest.contracts import canonical_sessions

HORIZON = 10
SESSIONS = canonical_sessions(date(2023, 10, 2), date(2023, 12, 29))
DAYS = [row[0] for row in SESSIONS]
PROTOCOL = {
    "fit_start": "2023-10-02",
    "calibration_start": "2023-10-16",
    "calibration_end": "2023-10-31",
    "assessment_start": "2023-11-01",
    "assessment_end": "2023-12-31",
    "development_end": "2023-12-31",
    "candidate_threshold": 0.65,
    "final_test_locked": True,
    "entry_z": 2.0,
}
PAIRS: dict[str, dict[str, Any]] = {
    "AAA__BBB": {"beta": 0.8, "sector": "Technology", "base_b": 50.0, "drift": 0.001},
    "CCC__DDD": {"beta": 1.2, "sector": "Health Care", "base_b": 30.0, "drift": -0.0005},
}
ALPHA, MEAN, STD = 0.1, 0.0, 0.05
# z at selected closes; every other session sits at 0.3 inside no band.
Z_PATHS = {
    "AAA__BBB": {
        date(2023, 11, 3): 1.5,
        date(2023, 11, 6): 2.4,  # E1, ACTIVE, A 0.25 / B 0.70
        date(2023, 11, 7): 2.0,
        date(2023, 11, 8): 1.4,
        date(2023, 11, 9): 0.9,
        date(2023, 11, 10): 0.4,  # convergence close
        date(2023, 11, 17): 1.8,
        date(2023, 11, 20): 2.3,  # S1: fresh raw crossing omitted from h10 events
        date(2023, 11, 21): 1.0,
        date(2023, 12, 19): 1.2,
        **{day: 2.5 for day in DAYS if day >= date(2023, 12, 20)},  # E2, truncated path
    },
    "CCC__DDD": {
        date(2023, 11, 9): -1.0,
        date(2023, 11, 10): -2.2,  # E3, WATCH, entry session has a ZERO_VOLUME leg
    },
}
EVENTS = {
    "E1": ("AAA__BBB", date(2023, 11, 6), "ACTIVE", {"A": 0.25, "B": 0.70}, 1.0),
    "E2": ("AAA__BBB", date(2023, 12, 20), "ACTIVE", None, None),
    "E3": ("CCC__DDD", date(2023, 11, 10), "WATCH", {"A": 0.50, "B": 0.80}, 0.0),
}
SUPPRESSED = {"S1": ("AAA__BBB", date(2023, 11, 20), "ACTIVE")}


def _z(pair_id: str, day: date) -> float:
    return Z_PATHS[pair_id].get(day, 0.3)


def session_close(day: date) -> datetime:
    return next(row[2] for row in SESSIONS if row[0] == day)


def _open(day: date) -> datetime:
    return next(row[1] for row in SESSIONS if row[0] == day)


def _json(path: Path, value: object) -> str:
    raw = json.dumps(value, sort_keys=True).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _parquet(path: Path, frame: pd.DataFrame) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, index=False)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _snapshot_z(pair_id: str, close_a: float, close_b: float) -> float:
    beta = PAIRS[pair_id]["beta"]
    return (log(close_a) - ALPHA - beta * log(close_b) - MEAN) / STD


def _partition(day: date, protocol: dict[str, Any]) -> str:
    if day >= date.fromisoformat(protocol["assessment_start"]):
        return "assessment"
    if day >= date.fromisoformat(protocol["calibration_start"]):
        return "calibration"
    return "fit"


def make_workspace(
    root: Path,
    *,
    previous_z_shift: float = 0.0,
    extra_event_fields: dict[str, Any] | None = None,
    protocol_overrides: dict[str, Any] | None = None,
    horizon: int = HORIZON,
) -> tuple[str, str]:
    """Write the registered chain; return the evaluation manifest path and checksum."""
    protocol = {**PROTOCOL, **(protocol_overrides or {})}
    closes: dict[tuple[str, date], float] = {}
    price_rows = []
    for pair_id, spec in PAIRS.items():
        leg_a, leg_b = pair_id.split("__")
        for index, day in enumerate(DAYS):
            close_b = spec["base_b"] * exp(spec["drift"] * index)
            close_a = exp(ALPHA + spec["beta"] * log(close_b) + MEAN + STD * _z(pair_id, day))
            closes[(leg_a, day)], closes[(leg_b, day)] = close_a, close_b
            for ticker, adjusted in ((leg_a, close_a), (leg_b, close_b)):
                # Raw prices differ by a dividend factor; adjusted open = open * adj/close.
                zero = ticker == "DDD" and day == date(2023, 11, 13)
                shares = 1_000_000.0 + 1000.0 * index
                price_rows.append(
                    {
                        "ticker": ticker,
                        "trading_date": day,
                        "open": adjusted * 0.999 * 1.01,
                        "close": adjusted * 1.01,
                        "adj_close": adjusted,
                        "quality_flag": "ZERO_VOLUME" if zero else "OK",
                        "volume": 0.0 if zero else shares,
                        "dollar_volume": 0.0 if zero else adjusted * 1.01 * shares,
                    }
                )
    market = root / "market/source_v1"
    market_files = {
        "prices.parquet": _parquet(market / "prices.parquet", pd.DataFrame(price_rows)),
        "pair_universe.parquet": _parquet(
            market / "pair_universe.parquet",
            pd.DataFrame(
                [
                    {
                        "pair_id": pair_id,
                        "leg_a": pair_id.split("__")[0],
                        "leg_b": pair_id.split("__")[1],
                        "sector": spec["sector"],
                        "active_to": None,
                    }
                    for pair_id, spec in PAIRS.items()
                ]
            ),
        ),
        "security_master.parquet": _parquet(
            market / "security_master.parquet",
            pd.DataFrame(
                [
                    {"ticker": ticker, "sector": PAIRS[pair_id]["sector"]}
                    for pair_id in PAIRS
                    for ticker in pair_id.split("__")
                ]
            ),
        ),
    }
    market_sha = _json(
        market / "manifest.json",
        {
            "data_snapshot_id": "market_fixture0000000000",
            "final_test_prices_collected": False,
            "files": market_files,
        },
    )
    registry_version = "research_registry_" + "1" * 24
    registry = root / "artifacts/research" / registry_version
    pair_manifests = []
    for pair_id, spec in PAIRS.items():
        leg_a, leg_b = pair_id.split("__")
        crossings = []
        for crossing_id, (owner, day, status, *_rest) in {**EVENTS, **SUPPRESSED}.items():
            if owner != pair_id:
                continue
            previous = DAYS[DAYS.index(day) - 1]
            crossings.append(
                {
                    "pair_id": pair_id,
                    "crossing_id": "cross_" + crossing_id,
                    "event_date": day,
                    "relationship_snapshot_id": "snap_" + pair_id,
                    "alpha": ALPHA,
                    "beta": spec["beta"],
                    "spread_mean": MEAN,
                    "spread_std": STD,
                    "pair_status": status,
                    "previous_z_score": _snapshot_z(
                        pair_id, closes[(leg_a, previous)], closes[(leg_b, previous)]
                    )
                    + previous_z_shift,
                    "z_entry": _snapshot_z(pair_id, closes[(leg_a, day)], closes[(leg_b, day)]),
                }
            )
        snapshot = pd.DataFrame(
            [
                {
                    "relationship_snapshot_id": "snap_" + pair_id,
                    "pair_id": pair_id,
                    "alpha": ALPHA,
                    "beta": spec["beta"],
                    "spread_mean": MEAN,
                    "spread_std": STD,
                    "window_end": date(2023, 10, 31),
                    "effective_start_at": pd.Timestamp(_open(date(2023, 11, 1))),
                }
            ]
        )
        directory = registry / "pairs" / pair_id
        files = [
            {
                "name": "raw_crossings",
                "path": "raw_crossings.parquet",
                "sha256": _parquet(directory / "raw_crossings.parquet", pd.DataFrame(crossings)),
            },
            {
                "name": "relationship_snapshots",
                "path": "relationship_snapshots.parquet",
                "sha256": _parquet(directory / "relationship_snapshots.parquet", snapshot),
            },
        ]
        pair_manifests.append(
            {
                "pair_id": pair_id,
                "sha256": _json(directory / "manifest.json", {"pair_id": pair_id, "files": files}),
            }
        )
    events, targets, predictions = [], [], []
    for event_id, (pair_id, day, _status, scores, label) in EVENTS.items():
        leg_a, leg_b = pair_id.split("__")
        events.append(
            {
                "event_id": event_id,
                "pair_id": pair_id,
                "event_date": day,
                "event_timestamp": pd.Timestamp(session_close(day)),
                "feature_cutoff_timestamp": pd.Timestamp(session_close(day)),
                "relationship_snapshot_id": "snap_" + pair_id,
                "alpha": ALPHA,
                "beta": PAIRS[pair_id]["beta"],
                "spread_mean": MEAN,
                "spread_std": STD,
                "entry_z": _snapshot_z(pair_id, closes[(leg_a, day)], closes[(leg_b, day)]),
                "label_policy_version": "label-fixture-v1",
                **(extra_event_fields or {}).get(event_id, {}),
            }
        )
        window = canonical_sessions(day, date(2023, 12, 29))
        complete = len(window) > horizon
        targets.append(
            {
                "event_id": event_id,
                "label_policy_version": "label-fixture-v1",
                "y_revert_success": label if complete else float("nan"),
                "label_eligible": complete and label is not None,
                "horizon_end_date": window[horizon][0] if complete else None,
            }
        )
        if scores is not None:
            predictions.append(
                {
                    "event_id": event_id,
                    "event_date": day,
                    "research_partition": _partition(day, protocol),
                    "baseline1_eligible": _status == "ACTIVE",
                    "y_revert_success": label,
                    "logistic_A_calibrated": scores["A"],
                    "logistic_B_both_calibrated": scores["B"],
                    "xgboost_A_calibrated": scores["A"] - 0.05,
                    "xgboost_B_both_calibrated": scores["B"] - 0.05,
                }
            )
    # Point-in-time stress context: previous-session VIX at a 16:16 New York proxy
    # clock and trailing market volatility at the signal close. E2 has neither,
    # so it must stay UNKNOWN in every stress slice.
    features = []
    for event_id, (_pair_id, day, _status, _scores, _label) in EVENTS.items():
        previous = DAYS[DAYS.index(day) - 1]
        known = event_id != "E2"
        features.append(
            {
                "event_id": event_id,
                "feature_cutoff_timestamp": pd.Timestamp(session_close(day)),
                "vix_level": {"E1": 18.0, "E3": 33.0}.get(event_id, float("nan")),
                "vix_source_available_at": pd.Timestamp(session_close(previous))
                + pd.Timedelta(minutes=16)
                if known
                else pd.NaT,
                "market_rv20": {"E1": 0.15, "E3": 0.45}.get(event_id, float("nan")),
                "market_available_at": pd.Timestamp(session_close(day)) if known else pd.NaT,
            }
        )
    registry_files = [
        {
            "name": f"h{horizon}_events",
            "path": f"h{horizon}_events.parquet",
            "sha256": _parquet(registry / f"h{horizon}_events.parquet", pd.DataFrame(events)),
        },
        {
            "name": f"h{horizon}_targets",
            "path": f"h{horizon}_targets.parquet",
            "sha256": _parquet(registry / f"h{horizon}_targets.parquet", pd.DataFrame(targets)),
        },
        {
            "name": f"h{horizon}_features",
            "path": f"h{horizon}_features.parquet",
            "sha256": _parquet(registry / f"h{horizon}_features.parquet", pd.DataFrame(features)),
        },
    ]
    registry_sha = _json(
        registry / "manifest.json",
        {
            "stage": "registry",
            "research_version": registry_version,
            "final_test_read": False,
            "protocol": protocol,
            "protocol_hash": "a" * 64,
            "inputs": [
                {"role": "market", "path": "market/source_v1/manifest.json", "sha256": market_sha}
            ],
            "files": registry_files,
            "pair_manifests": pair_manifests,
        },
    )
    evaluation_version = "research_evaluation_" + "2" * 24
    evaluation = root / "artifacts/research" / evaluation_version
    model_files = []
    for name in ("logistic_A", "logistic_B_both"):
        path = evaluation / "models" / f"{name}.joblib"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(f"synthetic bundle {name}".encode())
        model_files.append(
            {
                "name": name,
                "path": f"models/{name}.joblib",
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    relative = f"artifacts/research/{evaluation_version}/manifest.json"
    sha = _json(
        root / relative,
        {
            "stage": "evaluation",
            "research_version": evaluation_version,
            "final_test_read": False,
            "protocol": protocol,
            "protocol_hash": "a" * 64,
            "identity_inputs": {
                "horizon": horizon,
                "registry_version": registry_version,
                "registry_manifest_sha256": registry_sha,
            },
            "parents": [
                {
                    "role": "registry",
                    "path": f"artifacts/research/{registry_version}/manifest.json",
                    "sha256": registry_sha,
                }
            ],
            "files": [
                {
                    "name": "predictions",
                    "path": "predictions.parquet",
                    "sha256": _parquet(
                        evaluation / "predictions.parquet", pd.DataFrame(predictions)
                    ),
                }
            ],
            "model_files": model_files,
        },
    )
    return relative, sha
