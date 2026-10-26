"""Pre-registered alternative cointegration features and gates (DECISIONS 67).

``build`` recomputes each event's 504-session formation window from the frozen
prices, checks that OLS reproduces the stored relationship, and adds 21
diagnostics (``econometrics.alternatives``) without changing any event.
``models`` adds the block to Models A and B in the Decision 45 walk-forward.
``gate-explore`` scores six validity gates on 2006-2015 and fixes the best one;
``gate-confirm`` tests it on 2016-2021 and reports 2022-2023. The 2024-2025
final test is not read.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import sys
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from structural_break.econometrics import alternatives as alt
from structural_break.forecast import model_b as pb

PLAN_VERSION = "p6-coint-alternatives-v1"
FORMATION = 504
TARGET = "y_revert_success"
FEATURES = (
    "ci_eg_reverse_tstat",
    "ci_eg_max_pvalue",
    "ci_johansen_trace_ratio",
    "ci_johansen_maxeig_ratio",
    "ci_beta_gap_johansen",
    "ci_beta_gap_tls",
    "ci_tls_adf_t",
    "ci_minadf_t",
    "ci_beta_gap_minadf",
    "ci_minhl_halflife",
    "ci_beta_gap_minhl",
    "ci_kpss",
    "ci_hurst",
    "ci_vr20",
    "ci_z_johansen",
    "ci_z_tls",
    "ci_z_minadf",
    "ci_z_minhl",
    "ci_alt_z_min",
    "ci_kalman_beta_gap",
    "ci_kalman_z",
)
# Fixed clipping of heavy-tailed diagnostics (hedge-ratio gaps can exceed 50x).
CLIPS = {
    **{
        name: 3.0
        for name in FEATURES
        if name.startswith("ci_beta_gap") or name == "ci_kalman_beta_gap"
    },
    **{
        name: 10.0
        for name in FEATURES
        if name.startswith("ci_z_") or name in ("ci_alt_z_min", "ci_kalman_z")
    },
}
EXPLORE, CONFIRM, REPLICATE = (2006, 2015), (2016, 2021), (2022, 2023)
MIN_CONFIRM_YEARS = 4
ALPHA = 0.05
# Gates keep an event when the rule is True; everything else is withheld (earns 0).
GATES: dict[str, Callable[[pd.DataFrame], pd.Series]] = {
    "G1_johansen_rejects": lambda f: f["ci_johansen_trace_ratio"].ge(1.0),
    "G2_eg_both_directions": lambda f: f["ci_eg_max_pvalue"].lt(0.05),
    "G3_kpss_stationary": lambda f: f["ci_kpss"].lt(0.463),
    "G4_robust_divergence": lambda f: f["ci_alt_z_min"].ge(1.5),
    "G5_hurst_below_half": lambda f: f["ci_hurst"].lt(0.5),
    "G6_min_half_life_20": lambda f: f["ci_minhl_halflife"].le(20.0),
}
REFERENCE_GATE = "B1_engle_granger"
LOGISTIC_C = 0.01


# --------------------------------------------------------------------------- #
# Feature build
# --------------------------------------------------------------------------- #


def joint_history(prices: pd.DataFrame, leg_a: str, leg_b: str) -> pd.DataFrame:
    """Sessions where both legs have a valid adjusted close, as log prices y (A) and x (B)."""
    legs = []
    for side, ticker in (("y", leg_a), ("x", leg_b)):
        rows = prices.loc[prices["ticker"].eq(ticker)]
        flags = rows["quality_flag"].map(
            lambda v: isinstance(v, str) and set(v.split("|")) <= {"OK", "ZERO_VOLUME"}
        )
        ok = flags & rows["adj_close"].gt(0) & np.isfinite(rows["adj_close"])
        legs.append(
            pd.DataFrame(
                {
                    "trading_date": pd.to_datetime(rows.loc[ok, "trading_date"]).dt.date,
                    side: np.log(rows.loc[ok, "adj_close"].astype(float)),
                }
            )
        )
    return (
        legs[0].merge(legs[1], on="trading_date").sort_values("trading_date").reset_index(drop=True)
    )


def pair_features(history: pd.DataFrame, events: pd.DataFrame) -> list[dict[str, Any]]:
    """All features for one pair's events; each window ends before its relationship is used."""
    dates = list(history["trading_date"])
    y, x = history["y"].to_numpy(float), history["x"].to_numpy(float)
    kalman_beta, kalman_z = alt.kalman_path(y, x)
    position = {d: i for i, d in enumerate(dates)}
    cache: dict[Any, dict[str, float]] = {}
    rows = []
    for event in events.to_dict("records"):
        available = pd.Timestamp(event["relationship_available_at"]).tz_convert("UTC").date()
        stop = bisect.bisect_left(dates, available)
        if available not in cache:
            start = max(0, stop - FORMATION)
            cache[available] = (
                alt.window_statistics(y[start:stop], x[start:stop]) if stop - start >= 100 else {}
            )
        stats = cache[available]
        record: dict[str, Any] = {"event_id": event["event_id"]}
        day = pd.Timestamp(event["event_date"]).date()
        index = position.get(day)
        sign = math.copysign(1.0, float(event["entry_z"]))
        if stats:
            record["ols_beta_check"] = stats["ols_beta"] - float(event["beta"])
            record["ols_alpha_check"] = stats["ols_alpha"] - float(event["alpha"])
            for name in FEATURES:
                if name in stats:
                    record[name] = stats[name]
            if index is not None:
                aligned = []
                for method in ("johansen", "tls", "minadf", "minhl"):
                    value = (
                        y[index] - stats[f"{method}_beta"] * x[index] - stats[f"{method}_mean"]
                    ) / stats[f"{method}_std"]
                    record[f"ci_z_{method}"] = sign * value
                    aligned.append(sign * value)
                record["ci_alt_z_min"] = (
                    float(np.nanmin(aligned)) if np.isfinite(aligned).any() else np.nan
                )
                scale = max(abs(float(event["beta"])), 0.1)
                record["ci_kalman_beta_gap"] = (kalman_beta[index] - float(event["beta"])) / scale
                record["ci_kalman_z"] = sign * kalman_z[index]
        for name, bound in CLIPS.items():
            if name in record and record[name] is not None and np.isfinite(record[name]):
                record[name] = float(np.clip(record[name], -bound, bound))
        rows.append(record)
    return rows


_PRICES: dict[str, pd.DataFrame] = {}


def _init(prices_path: str) -> None:
    _PRICES["prices"] = pd.read_parquet(
        prices_path, columns=["ticker", "trading_date", "adj_close", "quality_flag"]
    )


def _pair_job(arguments: tuple[str, str, pd.DataFrame]) -> list[dict[str, Any]]:
    leg_a, leg_b, events = arguments
    history = joint_history(_PRICES["prices"], leg_a, leg_b)
    return pair_features(history, events)


def build(workspace: Path, simulation: Path, output: Path, workers: int) -> Path:
    frame, _ = pb.load_data(workspace, simulation)
    if pd.to_datetime(frame["event_date"]).max() > pd.Timestamp(2023, 12, 31):
        raise ValueError("Development frame reaches into the locked final test")
    columns = ["event_id", "event_date", "entry_z", "alpha", "beta", "relationship_available_at"]
    jobs = [
        (str(group["leg_a"].iloc[0]), str(group["leg_b"].iloc[0]), group.loc[:, columns])
        for _, group in frame.groupby("pair_id", sort=True)
    ]
    prices = workspace / "market/source_v1/prices.parquet"
    rows: list[dict[str, Any]] = []
    with ProcessPoolExecutor(workers, initializer=_init, initargs=(str(prices),)) as pool:
        for number, result in enumerate(pool.map(_pair_job, jobs, chunksize=4), start=1):
            rows.extend(result)
            if number % 50 == 0:
                print(f"{pb._now()} {number}/{len(jobs)} pairs", flush=True)
    table = pd.DataFrame(rows)
    check = {
        "events": len(table),
        "with_features": int(table["ci_kpss"].notna().sum()),
        "max_abs_beta_difference": float(table["ols_beta_check"].abs().max()),
        "max_abs_alpha_difference": float(table["ols_alpha_check"].abs().max()),
        "share_beta_within_1e-6": float(table["ols_beta_check"].abs().le(1e-6).mean()),
        "plan_version": PLAN_VERSION,
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "build_check.json").write_text(json.dumps(check, indent=2))
    path = output / "coint_features.parquet"
    table.loc[:, ["event_id", *FEATURES]].to_parquet(path, index=False)
    print(json.dumps(check, indent=2))
    return path


# --------------------------------------------------------------------------- #
# Model test
# --------------------------------------------------------------------------- #


def _estimator(family: str) -> Any:
    from structural_break.research.evaluation import _estimator as factory

    params = {"C": LOGISTIC_C} if family == "logistic" else pb.FIXED_XGB
    return factory(family, params, pb.MODEL_SEED)


def models(frame: pd.DataFrame, columns: dict[str, tuple[str, ...]]) -> dict[str, Any]:
    """Base model versus base plus the 21 features, both families, Models B and A."""
    years = (*pb.DECISION_YEARS, *pb.REFERENCE_YEARS)
    labelled = frame["supervised_eligible"].eq(True) & frame[TARGET].notna()
    signal_year = pd.to_datetime(frame["event_date"]).dt.year
    months = pd.to_datetime(frame["event_date"]).dt.strftime("%Y-%m")
    results: dict[str, Any] = {}
    for model in ("B", "A"):
        for family in ("logistic", "xgboost"):
            sq = {k: pd.Series(np.nan, index=frame.index) for k in ("base", "coint")}
            alloc = {k: pd.Series(np.nan, index=frame.index) for k in ("base", "coint")}
            for year in years:
                train, threshold_rows, test = pb.rolling_split(frame, year)
                both = pd.concat([threshold_rows, test])
                for key, cols in (
                    ("base", columns[model]),
                    ("coint", (*columns[model], *FEATURES)),
                ):
                    estimator = _estimator(family)
                    estimator.fit(train.loc[:, cols].astype(float), train[TARGET].astype(int))
                    scores = estimator.predict_proba(both.loc[:, cols].astype(float))[:, 1]
                    test_scores = pd.Series(scores[len(threshold_rows) :], index=test.index)
                    ok = labelled.loc[test.index]
                    sq[key].loc[test.index[ok]] = (
                        test_scores[ok] - test.loc[ok, TARGET].astype(float)
                    ) ** 2
                    cut = float(np.quantile(scores[: len(threshold_rows)], 1 - pb.TOP_SHARE))
                    alloc[key].loc[test.index] = pb.allocation(
                        test_scores >= cut, test["frozen|status"], test["frozen|net"]
                    )
            entry: dict[str, Any] = {}
            for measure, left, right in (
                ("brier_gain", sq["coint"], sq["base"]),  # base - coint: positive is better
                ("return_gain", alloc["base"], alloc["coint"]),
            ):
                for span, span_years in (
                    ("decision", pb.DECISION_YEARS),
                    ("reference", pb.REFERENCE_YEARS),
                ):
                    keep = signal_year.isin(span_years) & left.notna() & right.notna()
                    difference = (right - left)[keep]
                    stats = pb.bootstrap(difference.to_numpy(float), months[keep].to_numpy())
                    per_year = difference.groupby(signal_year[keep]).mean()
                    stats["per_year"] = {int(str(k)): float(v) for k, v in per_year.items()}
                    stats["years_positive"] = int((per_year > 0).sum())
                    entry[f"{measure}_{span}"] = stats
            for key in ("base", "coint"):
                keep = signal_year.isin(pb.DECISION_YEARS) & sq[key].notna()
                entry[f"brier_{key}"] = float(sq[key][keep].mean())
            results[f"{model}|{family}"] = entry
    adjusted = pb.holm(
        {k: results[k]["brier_gain_decision"]["p_one_sided"] for k in ("B|logistic", "B|xgboost")}
    )
    for key, p_holm in adjusted.items():
        stats = results[key]["brier_gain_decision"]
        stats["p_holm"] = p_holm
        stats["passes"] = bool(
            stats["estimate"] > 0
            and p_holm < ALPHA
            and stats["years_positive"] >= pb.MIN_POSITIVE_YEARS
        )
    return results


# --------------------------------------------------------------------------- #
# Gates
# --------------------------------------------------------------------------- #


def gate_contrast(frame: pd.DataFrame, name: str, span: tuple[int, int]) -> dict[str, Any]:
    """Gated minus trade-all per Baseline 0 candidate: a withheld trade earns 0."""
    year = pd.to_datetime(frame["event_date"]).dt.year
    data = frame.loc[frame["frozen|status"].eq("COMPLETE") & year.between(*span)]
    if name == REFERENCE_GATE:
        keep = data["baseline1_eligible"].eq(True)
    else:
        keep = GATES[name](data).fillna(False).astype(bool)
    net = data["frozen|net"].astype(float)
    difference = -(net * ~keep)
    stats = pb.bootstrap(
        difference.to_numpy(), pd.to_datetime(data["event_date"]).dt.strftime("%Y-%m").to_numpy()
    )
    per_year = difference.groupby(year.loc[data.index]).mean() * 1e4
    labelled = data[TARGET].notna()
    return stats | {
        "estimate_bps": stats["estimate"] * 1e4,
        "interval_95_bps": [v * 1e4 for v in stats["interval_95"]],
        "t": stats["estimate"] / max(float(np.std(difference)) / math.sqrt(len(difference)), 1e-12),
        "kept_share": float(keep.mean()),
        "kept_mean_net_bps": float(net[keep].mean() * 1e4) if keep.any() else None,
        "withheld_mean_net_bps": float(net[~keep].mean() * 1e4) if (~keep).any() else None,
        "kept_revert_rate": float(data.loc[keep & labelled, TARGET].mean()),
        "withheld_revert_rate": float(data.loc[~keep & labelled, TARGET].mean()),
        "per_year_bps": {int(str(k)): float(v) for k, v in per_year.items()},
        "years_positive": int((per_year > 0).sum()),
    }


def _save(path: Path, value: dict[str, Any]) -> bytes:
    body = (
        json.dumps(
            value | {"plan_version": PLAN_VERSION, "run_date": date.today().isoformat()},
            indent=2,
            sort_keys=True,
            default=str,
        )
        + "\n"
    ).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    return body


def main(arguments: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("build", "models", "gate-explore", "gate-confirm"))
    parser.add_argument("--workspace-root", type=Path, default=Path("data/team"))
    parser.add_argument(
        "--simulation",
        type=Path,
        default=Path("outputs/p6_improvement/walkforward/simulation_frozen_exit.parquet"),
    )
    parser.add_argument("--output", type=Path, default=Path("outputs/p6_coint"))
    parser.add_argument("--workers", type=int, default=7)
    args = parser.parse_args(arguments)
    out = args.output
    if args.stage == "build":
        print(build(args.workspace_root, args.simulation, out, args.workers))
        return
    frame, columns = pb.load_data(args.workspace_root, args.simulation)
    features = pd.read_parquet(out / "coint_features.parquet")
    frame = frame.merge(features, on="event_id", how="left", validate="one_to_one")
    if args.stage == "models":
        result = models(frame, columns)
        _save(out / "models.json", {"decision": "DECISIONS 67", "models": result})
        for key, entry in result.items():
            b, r = entry["brier_gain_decision"], entry["return_gain_decision"]
            print(
                f"{key:12s} Brier gain {b['estimate'] * 1e4:+.2f}e-4 p {b['p_one_sided']:.3f}"
                f" ({b['years_positive']}/12) | return gain {r['estimate'] * 1e4:+.2f} bps"
                f" p {r['p_one_sided']:.3f} ({r['years_positive']}/12)"
            )
        return
    if args.stage == "gate-explore":
        rows = {name: gate_contrast(frame, name, EXPLORE) for name in (*GATES, REFERENCE_GATE)}
        positive = {k: v for k, v in rows.items() if k in GATES and v["estimate"] > 0}
        pool = positive or {k: rows[k] for k in GATES}
        best = max(pool, key=lambda k: pool[k]["t"])
        choice = {
            "name": best,
            "explore_t": rows[best]["t"],
            "explore_bps": rows[best]["estimate_bps"],
        }
        _save(out / "gate_exploration.json", {"years": EXPLORE, "gates": rows, "choice": choice})
        raw = (json.dumps(choice, indent=2, sort_keys=True) + "\n").encode()
        (out / "gate_choice.json").write_bytes(raw)
        print(json.dumps({"choice": choice, "sha256": hashlib.sha256(raw).hexdigest()}))
        for name, row in rows.items():
            print(
                f"{name:24s} {row['estimate_bps']:+6.2f} bps t {row['t']:+.2f}"
                f" kept {row['kept_share']:.2f}"
            )
        return
    raw = (out / "gate_choice.json").read_bytes()
    choice = json.loads(raw)
    confirm = {name: gate_contrast(frame, name, CONFIRM) for name in (*GATES, REFERENCE_GATE)}
    replicate = {name: gate_contrast(frame, name, REPLICATE) for name in (*GATES, REFERENCE_GATE)}
    chosen = confirm[choice["name"]]
    passes = bool(
        chosen["estimate"] > 0
        and chosen["p_one_sided"] < ALPHA
        and chosen["years_positive"] >= MIN_CONFIRM_YEARS
    )
    _save(
        out / "gate_confirmation.json",
        {
            "choice": choice,
            "choice_sha256": hashlib.sha256(raw).hexdigest(),
            "confirm": confirm,
            "replicate": replicate,
            "passes": passes,
        },
    )
    print(
        json.dumps(
            {
                "choice": choice["name"],
                "confirm_bps": chosen["estimate_bps"],
                "p": chosen["p_one_sided"],
                "years_positive": chosen["years_positive"],
                "replicate_bps": replicate[choice["name"]]["estimate_bps"],
                "passes": passes,
            }
        )
    )
    sys.stdout.flush()


if __name__ == "__main__":
    main()
