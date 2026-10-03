"""Transparent price paths isolate target, episode and information-set rules."""

from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from structural_break.config.loader import load_config
from structural_break.data.market import session_schedule
from structural_break.ml.dataset import build_event_dataset, label_policy_version
from structural_break.ml.features import (
    FEATURE_COLUMNS,
    FEATURE_FAMILIES,
    OPTIONAL_FEATURES,
    feature_schema,
    validate_feature_timestamps,
)


def inputs(
    path: dict[int, float] | None = None, *, final: bool = False
) -> tuple[list[pd.DataFrame], int]:
    start = date(2023, 7, 1) if final else date(2020, 1, 1)
    end = date(2024, 6, 30) if final else date(2021, 12, 31)
    schedule = session_schedule(start, end)
    count = len(schedule)
    first = 150
    z = 0.4 * np.sin(np.arange(count) / 3)
    for offset, value in (path or {0: 2.2, 1: 0.3}).items():
        z[first + offset] = value
    rng = np.random.default_rng(2)
    common = 4 + np.cumsum(rng.normal(0, 0.01, count))
    price_rows, daily_rows, context_rows, crossing_rows = [], [], [], []
    for index, row in enumerate(schedule.to_dict("records")):
        day, at = row["trading_date"], row["data_available_at"]
        for ticker, values in (("KO", common + 0.02 * z), ("PEP", common)):
            close = float(np.exp(values[index]))
            price_rows.append(
                {
                    "ticker": ticker,
                    "trading_date": day,
                    "adj_close": close,
                    "close": close,
                    "high": close * 1.01,
                    "low": close * 0.99,
                    "volume": float(1_000_000 + 500_000 * np.sin(index / 4)),
                    "quality_flag": "OK",
                    "data_available_at": at,
                }
            )
        fresh = index > 0 and abs(z[index]) >= 2 and abs(z[index - 1]) < 2
        common_fields = {
            "pair_id": "KO__PEP",
            "relationship_snapshot_id": "rel_1",
            "alpha": 0.0,
            "beta": 1.0,
            "spread_mean": 0.0,
            "spread_std": 0.02,
            "pair_status": "ACTIVE",
        }
        daily_rows.append(
            {
                **common_fields,
                "trading_date": day,
                "z_score": z[index],
                "fresh_threshold_crossing": fresh,
                "data_available_at": at,
            }
        )
        if fresh:
            crossing_rows.append(
                {
                    **common_fields,
                    "event_date": day,
                    "event_timestamp": at,
                    "z_entry": z[index],
                    "baseline1_eligible": True,
                }
            )
        context_rows.append(
            {
                "sector_etf": "XLP",
                "trading_date": day,
                "spy_adj_close": float(np.exp(5 + 0.003 * index + 0.02 * np.sin(index / 7))),
                "sector_etf_adj_close": float(np.exp(4 + 0.002 * index + 0.01 * np.sin(index / 9))),
                "vix_close": float(20 + 3 * np.sin(index / 11)) if index else np.nan,
                "vix_observed_at_utc": at - pd.Timedelta(days=1) if index else pd.NaT,
                "vix_observation_date": schedule.iloc[index - 1]["trading_date"] if index else None,
                "data_available_at": at,
                "quality_flag": "OK",
            }
        )
    snapshots = pd.DataFrame(
        [
            {
                "relationship_snapshot_id": "rel_1",
                "pair_id": "KO__PEP",
                "estimation_timestamp": schedule.iloc[0]["data_available_at"],
                "effective_start_at": schedule.iloc[1]["session_open"],
                "window_start": schedule.iloc[0]["trading_date"],
                "pair_status": "ACTIVE",
                "coint_tstat": -4.0,
                "coint_pvalue": 0.01,
                "half_life_days": 3.0,
                "beta_drift_pct": 0.1,
            }
        ]
    )
    pairs = pd.DataFrame([{"pair_id": "KO__PEP", "leg_a": "KO", "leg_b": "PEP"}])
    securities = pd.DataFrame(
        [{"ticker": ticker, "sector_etf": "XLP", "sector": "TEST"} for ticker in ("KO", "PEP")]
    )
    return [
        pd.DataFrame(price_rows),
        pairs,
        securities,
        pd.DataFrame(context_rows),
        snapshots,
        pd.DataFrame(daily_rows),
        pd.DataFrame(crossing_rows),
    ], first


def build(frames: list[pd.DataFrame]) -> Any:
    return build_event_dataset(
        *frames,
        load_config(Path("configs")),
        data_snapshot_id="test-data",
        relationship_version="test-relationships",
        dataset_version="test-dataset",
    )


@pytest.mark.parametrize(
    "path,outcome,label,elapsed",
    [
        ({0: 2.2, 1: 0.5}, "CONVERGED", 1, 1),
        ({0: -2.2, 1: -0.5}, "CONVERGED", 1, 1),
        ({0: 2.2, 1: 3.0}, "STOPPED", 0, 1),
        ({0: -2.2, 1: -3.0}, "STOPPED", 0, 1),
        ({offset: 2.2 for offset in range(11)}, "TIMEOUT", 0, 10),
        ({0: 2.2, 1: -3.4, 2: 0.3}, "CONVERGED", 1, 2),
    ],
)
def test_frozen_success_stop_timeout(
    path: dict[int, float], outcome: str, label: int, elapsed: int
) -> None:
    frames, _ = inputs(path)
    result = build(frames)
    target = result.targets.iloc[0]
    assert target["outcome_type"] == outcome
    assert target["y_revert_success"] == label
    assert target["time_to_resolution"] == elapsed
    assert result.features.iloc[0]["feature_complete"]
    assert result.partitions.iloc[0]["supervised_eligible"]


def test_same_pair_crossings_suppressed_until_resolution_and_reset() -> None:
    frames, first = inputs({0: 2.2, 1: 0.8, 2: 2.2, 3: 0.4, 4: 0.9, 5: 2.2, 6: 0.3})
    result = build(frames)
    assert len(frames[-1]) == 3
    assert len(result.events) == 2
    dates = frames[-2]["trading_date"].tolist()
    assert result.events["event_date"].tolist() == [dates[first], dates[first + 5]]


def test_later_monthly_parameters_do_not_change_entry_target() -> None:
    frames, first = inputs({0: 2.2, 1: 2.3, 2: 2.4, 3: 0.3})
    later = frames[4].iloc[0].to_dict()
    later.update(
        relationship_snapshot_id="rel_later",
        effective_start_at=frames[5].iloc[first + 1]["data_available_at"],
        estimation_timestamp=frames[5].iloc[first]["data_available_at"],
    )
    frames[4] = pd.concat([frames[4], pd.DataFrame([later])], ignore_index=True)
    frames[5].loc[first + 1 :, "relationship_snapshot_id"] = "rel_later"
    frames[5].loc[first + 1 : first + 2, "z_score"] = 0.2
    result = build(frames)
    assert result.targets.iloc[0]["time_to_resolution"] == 3


def test_statistical_retirement_after_entry_does_not_censor() -> None:
    frames, first = inputs({0: 2.2, 1: 2.3, 2: 0.2})
    frames[5].loc[first + 1 :, "pair_status"] = "RETIRED"
    assert build(frames).targets.iloc[0]["outcome_type"] == "CONVERGED"


@pytest.mark.parametrize("kind", ["gap", "lifecycle"])
def test_missing_future_or_lifecycle_is_censored(kind: str) -> None:
    frames, first = inputs({0: 2.2, 1: 2.3, 2: 0.2})
    day = frames[5].iloc[first + 1]["trading_date"]
    if kind == "gap":
        frames[0] = frames[0].loc[
            ~(frames[0]["ticker"].eq("KO") & frames[0]["trading_date"].eq(day))
        ]
    else:
        frames[2]["active_to"] = day
    target = build(frames).targets.iloc[0]
    assert target["outcome_type"] == "CENSORED"
    assert pd.isna(target["y_revert_success"])
    assert not target["label_eligible"]


def test_boundary_embargo_excludes_even_early_convergence() -> None:
    frames, _ = inputs()
    # Move an existing event to five XNYS sessions before training ends.
    schedule = frames[5]
    index = len(schedule) - 6
    day, next_day = schedule.iloc[index]["trading_date"], schedule.iloc[index + 1]["trading_date"]
    frames[-1] = frames[-1].iloc[:1].copy()
    frames[-1]["event_date"] = day
    frames[-1]["event_timestamp"] = schedule.iloc[index]["data_available_at"]
    frames[-2]["fresh_threshold_crossing"] = False
    frames[-2].loc[index, "fresh_threshold_crossing"] = True
    frames[-2].loc[index, "z_score"] = 2.2
    for event_day, z in ((day, 2.2), (next_day, 0.2)):
        a = frames[0]["ticker"].eq("KO") & frames[0]["trading_date"].eq(event_day)
        b = frames[0]["ticker"].eq("PEP") & frames[0]["trading_date"].eq(event_day)
        frames[0].loc[a, "adj_close"] = frames[0].loc[b, "adj_close"].iloc[0] * np.exp(0.02 * z)
    result = build(frames)
    assert result.targets.iloc[0]["censor_reason"] == "PARTITION_EMBARGO"
    assert not result.partitions.iloc[0]["supervised_eligible"]
    assert pd.isna(result.targets.iloc[0]["resolution_date"])


def test_final_targets_locked_but_causal_episode_rule_retained() -> None:
    frames, _ = inputs({0: 2.2, 1: 0.8, 2: 2.2, 3: 0.4, 4: 0.9, 5: 2.2, 6: 0.3}, final=True)
    result = build(frames)
    assert len(result.events) == 2
    assert result.events["partition"].eq("final_test").all()
    assert result.targets["outcome_type"].eq("LOCKED").all()
    for name in (
        "y_revert_success",
        "resolution_date",
        "time_to_resolution",
        "max_adverse_z",
        "max_favourable_z",
    ):
        assert result.targets[name].isna().all()
    assert not result.partitions["supervised_eligible"].any()
    assert result.events["model_ready"].all()


def test_future_prices_cannot_change_any_entry_feature() -> None:
    frames, first = inputs()
    original = build(frames)
    day = frames[5].iloc[first]["trading_date"]
    frames[0].loc[frames[0]["trading_date"].gt(day), "adj_close"] *= 1.9
    frames[3].loc[frames[3]["trading_date"].gt(day), ["spy_adj_close", "vix_close"]] *= 2
    changed = build(frames)
    assert_frame_equal(original.features.iloc[:1], changed.features.iloc[:1])


def test_ids_and_labels_reproducible_and_sensitive_to_label_policy() -> None:
    frames, _ = inputs()
    a, b = build(frames), build(frames)
    assert_frame_equal(a.events, b.events)
    assert_frame_equal(a.targets, b.targets)
    config = load_config(Path("configs"))
    other = config.model_copy(
        update={"econometrics": config.econometrics.model_copy(update={"horizon_days": 9})}
    )
    assert label_policy_version(config) != label_policy_version(other)


def test_missing_trailing_session_rejects_features_without_filling() -> None:
    frames, first = inputs()
    missing_day = frames[5].iloc[first - 2]["trading_date"]
    frames[0] = frames[0].loc[
        ~(frames[0]["ticker"].eq("KO") & frames[0]["trading_date"].eq(missing_day))
    ]
    result = build(frames)
    assert not result.features.iloc[0]["feature_complete"]
    assert not result.partitions.iloc[0]["supervised_eligible"]
    assert pd.isna(result.features.iloc[0]["corr_20"])


@pytest.mark.parametrize("family", list(FEATURE_FAMILIES))
def test_timestamp_check_for_every_feature_family(family: str) -> None:
    frames, _ = inputs()
    features = build(frames).features
    features.loc[0, f"{family}_available_at"] = features.loc[
        0, "feature_cutoff_timestamp"
    ] + pd.Timedelta(seconds=1)
    with pytest.raises(ValueError, match="availability"):
        validate_feature_timestamps(features)


def test_future_price_source_and_future_snapshot_rejected() -> None:
    frames, first = inputs()
    at = frames[5].iloc[first]["data_available_at"]
    frames[0].loc[
        frames[0]["trading_date"].eq(frames[5].iloc[first]["trading_date"]), "data_available_at"
    ] = at + pd.Timedelta(hours=1)
    with pytest.raises(ValueError, match="timestamp exceeds"):
        build(frames)
    frames, first = inputs()
    frames[4]["estimation_timestamp"] = frames[5].iloc[first]["data_available_at"] + pd.Timedelta(
        days=1
    )
    with pytest.raises(ValueError, match="Future relationship"):
        build(frames)


def test_schema_exact_order_optional_missing_and_exclusions() -> None:
    schema = feature_schema("test-v1")
    assert tuple(schema["feature_columns"]) == FEATURE_COLUMNS
    assert len(FEATURE_COLUMNS) == 36
    assert {row["name"] for row in schema["columns"] if row["allow_missing"]} == OPTIONAL_FEATURES
    assert not ({"pair_id", "ticker", "outcome_type", "y_revert_success"} & set(FEATURE_COLUMNS))


def test_vix_requires_exact_previous_xnys_session_without_stale_carry() -> None:
    frames, first = inputs()
    frames[3].loc[first, "vix_observation_date"] = frames[3].iloc[first - 2]["trading_date"]
    with pytest.raises(ValueError, match="exact previous XNYS"):
        build(frames)


def test_later_effective_snapshot_prevents_using_older_valid_fit() -> None:
    frames, first = inputs()
    newer = frames[4].iloc[0].to_dict()
    newer.update(
        relationship_snapshot_id="rel_new",
        effective_start_at=frames[5].iloc[first - 1]["data_available_at"],
    )
    frames[4] = pd.concat([frames[4], pd.DataFrame([newer])], ignore_index=True)
    with pytest.raises(ValueError, match="latest effective"):
        build(frames)


def test_crossing_values_must_match_frozen_fit_and_declared_boundary() -> None:
    frames, _ = inputs()
    frames[4]["beta"] = 1.2
    with pytest.raises(ValueError, match="parameters differ"):
        build(frames)
    frames, _ = inputs()
    frames[6]["z_entry"] = 1.8
    with pytest.raises(ValueError, match="divergence boundary"):
        build(frames)
