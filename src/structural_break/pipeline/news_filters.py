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

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from structural_break.intelligence.recent_news import NEWS_FEATURE_COLUMNS
from structural_break.intelligence.recent_tone import TONE_FEATURE_COLUMNS
from structural_break.intelligence.timing import TIMING_FEATURE_COLUMNS
from structural_break.pipeline.sources import _sources, load_frame
from structural_break.pipeline.walkforward import (
    XGB_PARAMETERS,
)

PLAN_VERSION = "p6-sec-explore-v1"
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


# --------------------------------------------------------------------------- #
# Filters
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# Walk-forward models
# --------------------------------------------------------------------------- #


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
