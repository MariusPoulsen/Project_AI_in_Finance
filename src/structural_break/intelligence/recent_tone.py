"""FinBERT tone of each company's recent 8-K news (DECISIONS 51).

v2's FinBERT block scored the same stale evidence packs as the v2 catalysts:
mostly quarterly-report text about two months old. This block scores the
recent-news packs instead (the 8-K Item chunk and press-release headline from
the three sessions before the signal), with v2's pinned model, revision and
sentence-quality preprocessing. It runs locally; no API is called.

A company's tone is the token-weighted mean of FinBERT's positive, negative
and neutral probabilities over its scored windows. A company with known filing
coverage and no recent 8-K has no news, which is coded as zero tone; unknown
coverage or text with no scorable window stays null.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, cast

import pandas as pd

from structural_break.intelligence.sentiment import (
    QUALITY_PREPROCESSING_VERSION,
    FinBERTPolicy,
    SentimentBackend,
    _window_plan,
)

TONE_VERSION = "sec-recent-news-tone-v1"
TONE_POLICY = FinBERTPolicy(preprocessing_version=QUALITY_PREPROCESSING_VERSION)
TONE_FEATURE_COLUMNS = (
    "news_tone_a_net",
    "news_tone_b_net",
    "news_tone_a_negative",
    "news_tone_b_negative",
    "news_tone_contrast",
    "news_tone_mover_net",
    "news_tone_mover_aligned",
)


def score_pack(
    pack: Mapping[str, Any], backend: SentimentBackend, policy: FinBERTPolicy = TONE_POLICY
) -> dict[str, Any]:
    """Token-weighted FinBERT probabilities over every chunk of one company's pack."""
    totals = {"positive": 0.0, "negative": 0.0, "neutral": 0.0}
    tokens = windows_scored = windows_available = 0
    for chunk in pack["chunks"]:
        plan, windows, counts = _window_plan(chunk["chunk_text"], backend, policy)
        windows_available += int(counts.get("window_count", len(windows)))
        plan, windows = (
            plan[: policy.max_windows_per_chunk],
            windows[: policy.max_windows_per_chunk],
        )
        if not windows:
            continue
        for meta, probabilities in zip(plan, backend.predict(windows), strict=True):
            weight = int(meta["token_count"])
            tokens += weight
            for label in totals:
                totals[label] += weight * float(probabilities[label])
        windows_scored += len(windows)
    record: dict[str, Any] = {
        "tone_version": TONE_VERSION,
        "model": f"{policy.model_name}@{policy.model_revision}",
        "preprocessing_version": policy.preprocessing_version,
        "windows_scored": windows_scored,
        "windows_available": windows_available,
        "tokens": tokens,
        "status": "OK" if tokens else "NO_SCORABLE_TEXT",
    }
    if tokens:
        record.update({label: value / tokens for label, value in totals.items()})
    return record


def _leg_tone(
    window: Mapping[str, Any], record: Mapping[str, Any] | None
) -> tuple[float, float] | None:
    """(net, negative) for one leg; None when unknown."""
    if not window["known"]:
        return None
    if not len(window["filing_ids"]):
        return 0.0, 0.0
    if record is None or record.get("status") != "OK":
        return None
    return float(record["positive"]) - float(record["negative"]), float(record["negative"])


def tone_features(
    events: pd.DataFrame,
    windows: pd.DataFrame,
    records: Callable[[str], Mapping[str, Any] | None],
) -> pd.DataFrame:
    """Seven fixed tone features per event; nulls mark unknown recent news."""
    by_event = {
        (row["event_id"], row["leg"]): row
        for row in cast(list[dict[str, Any]], windows.to_dict("records"))
    }
    rows = []
    for event in cast(list[dict[str, Any]], events.to_dict("records")):
        tones = {}
        for leg in ("a", "b"):
            window = by_event[(event["event_id"], leg)]
            key = window["leg_key"]
            tones[leg] = _leg_tone(window, records(key) if isinstance(key, str) else None)
        values: dict[str, float | None] = {}
        for leg in ("a", "b"):
            tone = tones[leg]
            values[f"news_tone_{leg}_net"] = None if tone is None else tone[0]
            values[f"news_tone_{leg}_negative"] = None if tone is None else tone[1]
        a, b = tones["a"], tones["b"]
        values["news_tone_contrast"] = None if a is None or b is None else a[0] - b[0]
        move_a, move_b = event.get("abnormal_return_A_1d"), event.get("abnormal_return_B_1d")
        if move_a is None or move_b is None or pd.isna(move_a) or pd.isna(move_b):
            values["news_tone_mover_net"] = values["news_tone_mover_aligned"] = None
        else:
            mover, move = (
                ("a", float(move_a)) if abs(move_a) >= abs(move_b) else ("b", float(move_b))
            )
            tone = tones[mover]
            sign = 1.0 if move > 0 else -1.0 if move < 0 else 0.0
            values["news_tone_mover_net"] = None if tone is None else tone[0]
            values["news_tone_mover_aligned"] = None if tone is None else tone[0] * sign
        rows.append(values)
    result = pd.DataFrame(rows, columns=list(TONE_FEATURE_COLUMNS), dtype=float)
    result.insert(0, "event_id", events["event_id"].to_numpy())
    return result
