"""Explore-then-confirm search over three SEC blocks (DECISIONS 55; exploratory).

The owner asked for every block to be explored in many ways. To keep the
result interpretable, the years are split:

* ``explore`` scores every pre-listed variant on exploration years only
  (filters 2006-2015, walk-forward models 2010-2015), picks one variant per
  block with a fixed rule and writes ``choices.json``. No 2016-2023 outcome
  is read.
* ``confirm`` evaluates only the three chosen variants on 2016-2021, with a
  Holm correction across the three blocks.

Blocks: filing timing (Decision 47), Gemma recent news (Decision 50) and
FinBERT recent-news tone (Decision 51). Following the pairs-trading
literature (divergences on firm-specific news converge less often; bad news
drifts), each block is tried as a trade filter that skips the event when its
condition is known to hold, on all events (Baseline 0) and on econometrically
valid pairs (Baseline 1), and as walk-forward model variants. Every contrast
is a paired per-candidate net-return difference under the frozen Decision 36
execution policy, with calendar-month block bootstrap uncertainty.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from structural_break.intelligence.recent_news import NEWS_FEATURE_COLUMNS
from structural_break.intelligence.recent_tone import TONE_FEATURE_COLUMNS
from structural_break.intelligence.timing import TIMING_FEATURE_COLUMNS
from structural_break.pipeline.sources import _sources, load_frame
from structural_break.pipeline.walkforward import (
    TOP_SHARE,
    XGB_PARAMETERS,
    allocation,
    rolling_split,
)
from structural_break.research.evaluation import _estimator
from structural_break.storage.files import write_bytes

PLAN_VERSION = "p6-sec-explore-v1"
FILTER_EXPLORE = (2006, 2015)
MODEL_EXPLORE = (2010, 2015)
CONFIRM = (2016, 2021)
DRAWS, SEED, ALPHA, MIN_CONFIRM_YEARS = 2000, 5557, 0.05, 4
BLOCKS = {
    "timing": TIMING_FEATURE_COLUMNS,
    "news": NEWS_FEATURE_COLUMNS,
    "tone": TONE_FEATURE_COLUMNS,
}
TARGET = "y_revert_success"


# --------------------------------------------------------------------------- #
# Derived mover columns (point-in-time: 1-day abnormal returns at the signal)
# --------------------------------------------------------------------------- #


def add_mover_columns(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    a, b = out["abnormal_return_A_1d"].astype(float), out["abnormal_return_B_1d"].astype(float)
    known = a.notna() & b.notna()
    mover_a = a.abs() >= b.abs()
    out["mover_known"] = known
    out["mover_fell"] = known & np.where(mover_a, a < 0, b < 0)

    def pick(a_column: str, b_column: str) -> pd.Series:
        values = np.where(mover_a, out[a_column], out[b_column]).astype(float)
        return pd.Series(np.where(known, values, np.nan), index=out.index)

    out["mover_8k_1s"] = pick("sec_a_8k_1s", "sec_b_8k_1s")
    out["mover_earnings_3s"] = pick("sec_a_earnings_3s", "sec_b_earnings_3s")
    for field in ("material", "negative", "positive", "earnings", "corporate"):
        out[f"mover_news_{field}"] = pick(f"news_a_{field}", f"news_b_{field}")
        out[f"other_news_{field}"] = pick(f"news_b_{field}", f"news_a_{field}")
    out["mover_tone_negative"] = pick("news_tone_a_negative", "news_tone_b_negative")
    return out


def _is(series: pd.Series) -> pd.Series:
    """Known and true; unknown never triggers a skip."""
    return series.astype(float).fillna(0.0).gt(0.5)


FILTERS: dict[str, tuple[str, Callable[[pd.DataFrame], pd.Series]]] = {
    "T1_mover_8k_1s": ("timing", lambda f: _is(f["mover_8k_1s"])),
    "T2_mover_any_filing_3s": ("timing", lambda f: _is(f["sec_mover_filed_3s"])),
    "T3_mover_earnings_3s": ("timing", lambda f: _is(f["mover_earnings_3s"])),
    "T4_one_sided_8k_1s": ("timing", lambda f: _is(f["sec_one_sided_8k_1s"])),
    "T5_either_earnings_3s": (
        "timing",
        lambda f: _is(f["sec_a_earnings_3s"]) | _is(f["sec_b_earnings_3s"]),
    ),
    "T6_mover_8k_1s_and_fell": ("timing", lambda f: _is(f["mover_8k_1s"]) & f["mover_fell"]),
    "N1_mover_material": ("news", lambda f: _is(f["news_mover_material"])),
    "N2_mover_news_explains_move": ("news", lambda f: _is(f["news_mover_explains_move"])),
    "N3_mover_material_negative": ("news", lambda f: _is(f["mover_news_negative"])),
    "N4_mover_negative_and_fell": (
        "news",
        lambda f: _is(f["mover_news_negative"]) & f["mover_fell"],
    ),
    "N5_one_sided_material": ("news", lambda f: _is(f["news_one_sided_material"])),
    "N6_mover_corporate": ("news", lambda f: _is(f["mover_news_corporate"])),
    "N7_mover_earnings": ("news", lambda f: _is(f["mover_news_earnings"])),
    "N8_mover_material_not_common": (
        "news",
        lambda f: _is(f["mover_news_material"]) & ~_is(f["other_news_material"]),
    ),
    "S1_mover_tone_below_-0.1": ("tone", lambda f: f["news_tone_mover_net"].lt(-0.1)),
    "S2_mover_tone_aligned_0.2": ("tone", lambda f: f["news_tone_mover_aligned"].ge(0.2)),
    "S3_mover_negative_tone_and_fell": (
        "tone",
        lambda f: f["news_tone_mover_net"].lt(-0.1) & f["mover_fell"],
    ),
    "S4_tone_contrast_0.3": ("tone", lambda f: f["news_tone_contrast"].abs().ge(0.3)),
    "S5_mover_negative_prob_0.2": ("tone", lambda f: f["mover_tone_negative"].ge(0.2)),
}
# DECISIONS 57: one combined filter, chosen after the Decision 56 confirmation,
# tested once on 2022-2023 (no filter outcome from those years had been read).
FILTERS["R1_fresh_news_filter"] = (
    "combined",
    lambda f: _is(f["mover_earnings_3s"]) | f["mover_tone_negative"].ge(0.2),
)
REPLICATE = (2022, 2023)
REPLICATION_FILTER = "R1_fresh_news_filter"
POPULATIONS = ("B0", "B1")
MODELS: dict[str, dict[str, Any]] = {
    "M1_logistic_C0.1": {"family": "logistic", "params": {"C": 0.1}, "base": "B"},
    "M2_logistic_C1": {"family": "logistic", "params": {"C": 1.0}, "base": "B"},
    "M3_mover_fell_interactions": {
        "family": "logistic",
        "params": {"C": 0.01},
        "base": "B",
        "interact": True,
    },
    "M4_xgboost": {"family": "xgboost", "params": XGB_PARAMETERS, "base": "B"},
    "M5_A_plus_block": {"family": "logistic", "params": {"C": 0.01}, "base": "A"},
}


# --------------------------------------------------------------------------- #
# Statistics
# --------------------------------------------------------------------------- #


def bootstrap(difference: np.ndarray, months: np.ndarray) -> dict[str, Any]:
    """Mean difference with month-block resampling: interval, SE and one-sided p."""
    labels = sorted(set(months.tolist()))
    if not labels:
        return {"estimate": None, "n": 0}
    index = {label: i for i, label in enumerate(labels)}
    blocks = np.array([index[m] for m in months.tolist()])
    sums = np.bincount(blocks, weights=difference, minlength=len(labels))
    counts = np.bincount(blocks, minlength=len(labels)).astype(float)
    rng = np.random.default_rng(SEED)
    sample = rng.integers(0, len(labels), (DRAWS, len(labels)))
    means = sums[sample].sum(axis=1) / np.maximum(counts[sample].sum(axis=1), 1)
    estimate = float(difference.mean())
    se = float(means.std(ddof=1))
    return {
        "estimate": estimate,
        "estimate_bps": estimate * 1e4,
        "interval_95_bps": [float(v) * 1e4 for v in np.quantile(means, [0.025, 0.975])],
        "se_bps": se * 1e4,
        "t": estimate / se if se > 0 else 0.0,
        "p_one_sided": float((means <= 0).mean()),
        "months": len(labels),
        "n": int(len(difference)),
    }


def _years_positive(difference: pd.Series, years: pd.Series) -> dict[str, float]:
    return {str(y): float(group.mean() * 1e4) for y, group in difference.groupby(years)}


# --------------------------------------------------------------------------- #
# Filters
# --------------------------------------------------------------------------- #


def filter_contrast(
    frame: pd.DataFrame, name: str, population: str, span: tuple[int, int]
) -> dict[str, Any]:
    _, rule = FILTERS[name]
    year = pd.to_datetime(frame["event_date"]).dt.year
    rows = frame["frozen|status"].eq("COMPLETE") & year.between(*span)
    if population == "B1":
        rows &= frame["baseline1_eligible"].eq(True)
    data = frame.loc[rows]
    skip = rule(data).fillna(False).astype(bool)
    net = data["frozen|net"].astype(float)
    difference = -(net * skip)  # kept trades unchanged; a skipped trade earns 0 instead of net
    stats = bootstrap(
        difference.to_numpy(), pd.to_datetime(data["event_date"]).dt.strftime("%Y-%m").to_numpy()
    )
    labelled = data[TARGET].notna()
    return stats | {
        "skipped_share": float(skip.mean()),
        "skipped_n": int(skip.sum()),
        "skipped_mean_net_bps": float(net[skip].mean() * 1e4) if skip.any() else None,
        "kept_mean_net_bps": float(net[~skip].mean() * 1e4) if (~skip).any() else None,
        "all_mean_net_bps": float(net.mean() * 1e4),
        "skipped_revert_rate": float(data.loc[skip & labelled, TARGET].mean())
        if (skip & labelled).any()
        else None,
        "kept_revert_rate": float(data.loc[~skip & labelled, TARGET].mean())
        if (~skip & labelled).any()
        else None,
        "per_year_bps": _years_positive(difference, pd.to_datetime(data["event_date"]).dt.year),
    }


# --------------------------------------------------------------------------- #
# Walk-forward models
# --------------------------------------------------------------------------- #


def _columns(
    base: tuple[str, ...], block: tuple[str, ...], interact: bool, frame: pd.DataFrame
) -> tuple[pd.DataFrame, tuple[str, ...]]:
    if not interact:
        return frame, (*base, *block)
    extra = frame.copy()
    names = []
    fell = extra["mover_fell"].astype(float)
    for column in block:
        for tag, weight in (("fell", fell), ("rose", 1.0 - fell)):
            name = f"ix_{column}_{tag}"
            extra[name] = extra[column].astype(float) * weight
            names.append(name)
    return extra, (*base, *block, *names)


def model_allocations(
    frame: pd.DataFrame,
    columns: tuple[str, ...],
    family: str,
    params: dict[str, Any],
    years: Sequence[int],
) -> pd.Series:
    """Top-20 % per-candidate allocations (Decision 45 walk-forward) for ``years``."""
    result = pd.Series(np.nan, index=frame.index)
    for year in years:
        train, threshold_rows, test = rolling_split(frame, year)
        estimator = _estimator(family, params, 42)
        estimator.fit(train.loc[:, columns].astype(float), train[TARGET].astype(int))
        both = pd.concat([threshold_rows, test])
        scores = estimator.predict_proba(both.loc[:, columns].astype(float))[:, 1]
        simulated = threshold_rows["frozen|status"].notna().to_numpy()
        cut = float(np.quantile(scores[: len(threshold_rows)][simulated], 1.0 - TOP_SHARE))
        test_scores = pd.Series(scores[len(threshold_rows) :], index=test.index)
        priced = test["frozen|status"].notna()
        result.loc[test.index[priced]] = allocation(
            test_scores[priced] >= cut,
            test.loc[priced, "frozen|status"],
            test.loc[priced, "frozen|net"],
        )
    return result


def model_contrast(
    frame: pd.DataFrame,
    block: str,
    name: str,
    columns: dict[str, tuple[str, ...]],
    span: tuple[int, int],
) -> dict[str, Any]:
    spec = MODELS[name]
    base = columns[spec["base"]]
    years = list(range(span[0], span[1] + 1))
    extended, variant = _columns(base, BLOCKS[block], bool(spec.get("interact")), frame)
    left = model_allocations(extended, base, spec["family"], spec["params"], years)
    right = model_allocations(extended, variant, spec["family"], spec["params"], years)
    known = left.notna() & right.notna()
    difference = (right - left)[known]
    dates = pd.to_datetime(frame.loc[known, "event_date"])
    return bootstrap(difference.to_numpy(), dates.dt.strftime("%Y-%m").to_numpy()) | {
        "per_year_bps": _years_positive(difference, dates.dt.year),
    }


# --------------------------------------------------------------------------- #
# Stages
# --------------------------------------------------------------------------- #


def load(
    workspace: Path, features: Sequence[Path], simulation: Path
) -> tuple[pd.DataFrame, dict[str, tuple[str, ...]]]:
    frame, report = load_frame(workspace, _sources(workspace).binding.evaluation.version)
    for path in features:
        frame = frame.merge(pd.read_parquet(path), on="event_id", how="left", validate="one_to_one")
    simulated = pd.read_parquet(simulation, columns=["event_id", "frozen|status", "frozen|net"])
    frame = frame.merge(simulated, on="event_id", how="left", validate="one_to_one")
    columns = {
        "A": tuple(report["models"]["logistic"]["A"]["feature_columns"]),
        "B": tuple(report["models"]["logistic"]["B_both"]["feature_columns"]),
    }
    return add_mover_columns(frame), columns


def variant_list() -> list[tuple[str, str, str]]:
    """(block, kind, name) for every Decision 55 variant (the R1 filter is separate)."""
    rows = [
        (block, f"filter_{pop}", name)
        for name, (block, _) in FILTERS.items()
        if block != "combined"
        for pop in POPULATIONS
    ]
    rows += [(block, "model", name) for block in BLOCKS for name in MODELS]
    return rows


def evaluate_variant(
    frame: pd.DataFrame,
    columns: dict[str, tuple[str, ...]],
    block: str,
    kind: str,
    name: str,
    filter_span: tuple[int, int],
    model_span: tuple[int, int],
) -> dict[str, Any]:
    if kind.startswith("filter_"):
        return filter_contrast(frame, name, kind.removeprefix("filter_"), filter_span)
    return model_contrast(frame, block, name, columns, model_span)


def explore(
    frame: pd.DataFrame, columns: dict[str, tuple[str, ...]], say: Callable[[str], None]
) -> dict[str, Any]:
    results = []
    for block, kind, name in variant_list():
        say(f"explore {block} {kind} {name}")
        stats = evaluate_variant(frame, columns, block, kind, name, FILTER_EXPLORE, MODEL_EXPLORE)
        results.append({"block": block, "kind": kind, "name": name, **stats})
    choices = {}
    for block in BLOCKS:
        candidates = [r for r in results if r["block"] == block and r.get("estimate") is not None]
        positive = [r for r in candidates if r["estimate"] > 0]
        best = max(positive or candidates, key=lambda r: r["t"])
        choices[block] = {
            "kind": best["kind"],
            "name": best["name"],
            "explore_t": best["t"],
            "explore_estimate_bps": best["estimate_bps"],
        }
    return {
        "plan_version": PLAN_VERSION,
        "filter_years": FILTER_EXPLORE,
        "model_years": MODEL_EXPLORE,
        "variants": results,
        "choices": choices,
    }


def confirm(
    frame: pd.DataFrame, columns: dict[str, tuple[str, ...]], choices: dict[str, Any]
) -> dict[str, Any]:
    rows = {}
    for block, choice in choices.items():
        stats = evaluate_variant(
            frame, columns, block, choice["kind"], choice["name"], CONFIRM, CONFIRM
        )
        years = stats.get("per_year_bps", {})
        rows[block] = {**choice, **stats, "years_positive": sum(v > 0 for v in years.values())}
    order = sorted(rows, key=lambda b: rows[b]["p_one_sided"])
    running = 0.0
    for rank, block in enumerate(order):
        adjusted = min(1.0, max(running, (len(order) - rank) * rows[block]["p_one_sided"]))
        running = adjusted
        rows[block]["p_holm"] = adjusted
        rows[block]["passes"] = bool(
            adjusted < ALPHA
            and rows[block]["estimate"] > 0
            and rows[block]["years_positive"] >= MIN_CONFIRM_YEARS
        )
    return {"plan_version": PLAN_VERSION, "confirm_years": CONFIRM, "blocks": rows}


def main(arguments: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("explore", "confirm", "replicate"))
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--features", type=Path, action="append", required=True)
    parser.add_argument("--simulation", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(arguments)
    say = lambda message: print(message, file=sys.stderr, flush=True)  # noqa: E731
    frame, columns = load(args.workspace_root, args.features, args.simulation)
    out = args.output_dir
    if args.stage == "explore":
        result = explore(frame, columns, say) | {"run_date": date.today().isoformat()}
        body = (json.dumps(result, indent=2, sort_keys=True, default=str) + "\n").encode()
        write_bytes(out / "exploration.json", body)
        choices = (json.dumps(result["choices"], indent=2, sort_keys=True) + "\n").encode()
        write_bytes(out / "choices.json", choices)
        print(
            json.dumps(
                {
                    "choices": result["choices"],
                    "choices_sha256": hashlib.sha256(choices).hexdigest(),
                }
            )
        )
        return
    if args.stage == "replicate":
        rows = {
            name: filter_contrast(frame, name, "B0", REPLICATE)
            for name in (REPLICATION_FILTER, "T3_mover_earnings_3s", "S5_mover_negative_prob_0.2")
        }
        main_row = rows[REPLICATION_FILTER]
        verdict = bool(main_row["estimate"] > 0 and main_row["p_one_sided"] < ALPHA)
        result = {
            "plan_version": PLAN_VERSION,
            "years": REPLICATE,
            "filters": rows,
            "passes": verdict,
            "run_date": date.today().isoformat(),
        }
        text = json.dumps(result, indent=2, sort_keys=True, default=str) + "\n"
        write_bytes(out / "replication.json", text.encode())
        summary = {"passes": verdict, "estimate_bps": main_row["estimate_bps"]}
        print(json.dumps(summary | {"p": main_row["p_one_sided"]}))
        return
    choices_raw = (out / "choices.json").read_bytes()
    result = confirm(frame, columns, json.loads(choices_raw)) | {
        "choices_sha256": hashlib.sha256(choices_raw).hexdigest(),
        "run_date": date.today().isoformat(),
    }
    write_bytes(
        out / "confirmation.json",
        (json.dumps(result, indent=2, sort_keys=True, default=str) + "\n").encode(),
    )
    print(
        json.dumps(
            {
                block: {
                    "passes": r["passes"],
                    "estimate_bps": r["estimate_bps"],
                    "p_holm": r["p_holm"],
                }
                for block, r in result["blocks"].items()
            }
        )
    )


if __name__ == "__main__":
    main()
