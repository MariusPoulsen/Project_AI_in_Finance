"""Deterministic episodes, frozen-entry targets and chronological ML partitions.

Episode state advances one session at a time. The final-test branch uses only
already-observed data to maintain this causal registry; it never materialises
final outcomes, resolution metadata or labels.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, cast

import numpy as np
import pandas as pd

from structural_break.config.models import ProjectConfig
from structural_break.data.market import session_schedule
from structural_break.ml.features import (
    FEATURE_COLUMNS,
    FEATURE_FAMILIES,
    build_quantitative_features,
    feature_schema,
    validate_feature_timestamps,
)

EVENT_COLUMNS = (
    "event_id",
    "pair_id",
    "event_date",
    "event_timestamp",
    "sector",
    "divergence_sign",
    "entry_z",
    "relationship_snapshot_id",
    "alpha",
    "beta",
    "spread_mean",
    "spread_std",
    "feature_cutoff_timestamp",
    "feature_schema_version",
    "label_policy_version",
    "data_snapshot_id",
    "relationship_version",
    "dataset_version",
    "baseline1_eligible",
    "partition",
    "horizon_end_date",
    "feature_complete",
    "model_ready",
)
TARGET_COLUMNS = (
    "event_id",
    "label_policy_version",
    "y_revert_success",
    "outcome_type",
    "resolution_date",
    "time_to_resolution",
    "max_adverse_z",
    "max_favourable_z",
    "horizon_end_date",
    "label_eligible",
    "censor_reason",
    "data_snapshot_id",
    "relationship_version",
    "dataset_version",
)
PARTITION_COLUMNS = (
    "event_id",
    "partition",
    "supervised_eligible",
    "exclusion_reason",
    "horizon_end_date",
    "label_window_start",
    "embargo_days",
    "feature_complete",
    "data_snapshot_id",
    "relationship_version",
    "dataset_version",
)


@dataclass(frozen=True)
class EventDataset:
    events: pd.DataFrame
    features: pd.DataFrame
    targets: pd.DataFrame
    partitions: pd.DataFrame
    feature_schema: dict[str, Any]


def label_policy_version(config: ProjectConfig) -> str:
    """A scientific label identity, independent of job timing or model tuning."""
    settings = config.econometrics
    policy = {
        "declared_version": getattr(config.ml, "label_policy_version", "close-label-v1"),
        "entry_z": settings.entry_z,
        "success_z": settings.success_z,
        "adverse_z": settings.adverse_z,
        "horizon_days": settings.horizon_days,
        "numerical_epsilon": settings.numerical_epsilon,
        "parameters": "entry-frozen-alpha-beta-mean-std",
        "deduplication": "one-open-episode-inside-band-reset-v1",
        "missing_future": "censor-no-gap-bridge",
        "eligibility": "ACTIVE-at-entry-no-statistical-status-exit",
    }
    encoded = json.dumps(policy, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "label_" + hashlib.sha256(encoded).hexdigest()


def _event_id(pair_id: str, timestamp: pd.Timestamp, snapshot_id: str, policy: str) -> str:
    values = [pair_id, timestamp.isoformat(), snapshot_id, policy]
    return "evt_" + hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()


def _dates(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    for name in ("trading_date", "event_date"):
        if name in out:
            out[name] = pd.to_datetime(out[name]).dt.date
    return out


def _partition(day: date, config: ProjectConfig) -> tuple[str, date | None]:
    for name, period in (
        ("train", config.ml.train),
        ("validation", config.ml.validation),
        ("final_test", config.ml.final_test),
    ):
        if period.start <= day <= period.end:
            return name, period.end
    return "outside", None


def _price_z(
    pa: pd.Series[Any], pb: pd.Series[Any], event: dict[str, Any], cutoff: pd.Timestamp
) -> float | None:
    for row in (pa, pb):
        observed_value = row.get("data_available_at")
        if observed_value is None:
            raise ValueError("Episode price missing its availability timestamp")
        observed = pd.to_datetime(observed_value, utc=True)
        price = row.get("adj_close")
        if pd.isna(price) or not np.isfinite(float(price)) or float(price) <= 0:
            return None
        if str(row.get("quality_flag", "OK")) not in ("OK", "ZERO_VOLUME"):
            return None
        if pd.isna(observed) or observed > cutoff:
            raise ValueError("Episode price unavailable at its chronological session cutoff")
    spread = (
        np.log(float(pa["adj_close"]))
        - float(event["alpha"])
        - float(event["beta"]) * np.log(float(pb["adj_close"]))
    )
    return float((spread - float(event["spread_mean"])) / float(event["spread_std"]))


def _ended_lifecycle(day: date, rows: list[dict[str, Any]]) -> bool:
    for row in rows:
        for key in ("active_to", "manual_terminal_date"):
            value = row.get(key)
            if value is not None and not pd.isna(value) and day >= pd.Timestamp(value).date():
                return True
    return False


def _empty_features() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "event_id",
            *FEATURE_COLUMNS,
            "feature_schema_version",
            "feature_cutoff_timestamp",
            *[f"{name}_available_at" for name in FEATURE_FAMILIES],
            "vix_source_available_at",
            "data_snapshot_id",
            "relationship_snapshot_id",
            "relationship_version",
            "dataset_version",
            "feature_complete",
            "feature_quality_flags",
        ]
    )


def build_event_dataset(
    prices: pd.DataFrame,
    pairs: pd.DataFrame,
    securities: pd.DataFrame,
    market_context: pd.DataFrame,
    snapshots: pd.DataFrame,
    daily_states: pd.DataFrame,
    crossings: pd.DataFrame,
    config: ProjectConfig,
    *,
    data_snapshot_id: str,
    relationship_version: str,
    dataset_version: str = "unregistered",
) -> EventDataset:
    """Build ACTIVE event rows without fitting models or writing storage.

    Raw Baseline 0 crossings remain the upstream P2 registry. This event table
    is the non-overlapping Model A/B observation registry, including explicit
    feature/censor/partition exclusions rather than silently dropping rows.
    """
    prices, market_context = _dates(prices), _dates(market_context)
    daily_states, crossings = _dates(daily_states), _dates(crossings)
    if prices.duplicated(["ticker", "trading_date"]).any():
        raise ValueError("Duplicate price observations")
    if market_context.duplicated(["sector_etf", "trading_date"]).any():
        raise ValueError("Duplicate market-context observations")
    if daily_states.duplicated(["pair_id", "trading_date"]).any():
        raise ValueError("Duplicate daily pair state")
    if crossings.duplicated(["pair_id", "event_date"]).any():
        raise ValueError("Duplicate threshold crossing")
    if snapshots["relationship_snapshot_id"].duplicated().any():
        raise ValueError("Duplicate relationship snapshot")
    if securities["ticker"].duplicated().any() or pairs["pair_id"].duplicated().any():
        raise ValueError("Duplicate reference identity")
    if prices.empty:
        raise ValueError("Event construction needs frozen price observations")
    start, end = prices["trading_date"].min(), prices["trading_date"].max()
    extension = max(60, 3 * max(config.econometrics.horizon_days, config.ml.embargo_days) + 20)
    schedule = session_schedule(start, end + timedelta(days=extension))
    session_dates: list[date] = schedule["trading_date"].tolist()
    date_index = {day: number for number, day in enumerate(session_dates)}
    closes = dict(zip(session_dates, schedule["data_available_at"], strict=True))
    lookup = {
        str(key): {str(field): value for field, value in row.items()}
        for key, row in snapshots.set_index("relationship_snapshot_id").to_dict("index").items()
    }
    refs = {
        str(key): {str(field): value for field, value in row.items()}
        for key, row in securities.set_index("ticker").to_dict("index").items()
    }
    policy = label_policy_version(config)
    h = config.econometrics.horizon_days
    events: list[dict[str, Any]] = []
    features: list[dict[str, Any]] = []
    targets: list[dict[str, Any]] = []
    partitions: list[dict[str, Any]] = []
    for pair_record in pairs.sort_values("pair_id").to_dict("records"):
        pair = {str(key): value for key, value in pair_record.items()}
        pair_id = str(pair["pair_id"])
        a_ticker, b_ticker = str(pair["leg_a"]), str(pair["leg_b"])
        if a_ticker not in refs or b_ticker not in refs:
            raise ValueError(f"Missing security reference for {pair_id}")
        sector_etf = refs[a_ticker]["sector_etf"]
        if refs[b_ticker]["sector_etf"] != sector_etf:
            raise ValueError(f"Pair has conflicting sector ETF mapping: {pair_id}")
        a = prices.loc[prices["ticker"].eq(a_ticker)].copy()
        b = prices.loc[prices["ticker"].eq(b_ticker)].copy()
        ai = a.set_index("trading_date").reindex(session_dates)
        bi = b.set_index("trading_date").reindex(session_dates)
        context = market_context.loc[market_context["sector_etf"].eq(sector_etf)].copy()
        pair_snapshots = snapshots.loc[snapshots["pair_id"].eq(pair_id)]
        states = daily_states.loc[daily_states["pair_id"].eq(pair_id)].set_index("trading_date")
        crossing_rows = (
            crossings.loc[crossings["pair_id"].eq(pair_id)].set_index("event_date").to_dict("index")
        )
        if states.empty:
            continue
        armed = True
        pending: dict[str, Any] | None = None
        pending_target: dict[str, Any] | None = None
        adverse: list[float] = []
        for day in session_dates:
            if day > end:
                break
            cutoff = pd.Timestamp(closes[day])
            if pending is not None and day > pending["event_date"]:
                elapsed = date_index[day] - date_index[pending["event_date"]]
                z = _price_z(
                    cast("pd.Series[Any]", ai.loc[day]),
                    cast("pd.Series[Any]", bi.loc[day]),
                    pending,
                    cutoff,
                )
                lifecycle_end = _ended_lifecycle(day, [pair, refs[a_ticker], refs[b_ticker]])
                resolved = z is None or lifecycle_end
                outcome = "CENSORED" if resolved else ""
                if z is not None and not lifecycle_end:
                    if pending_target is not None and pending_target["outcome_type"] == "PENDING":
                        adverse.append(int(pending["divergence_sign"]) * z)
                    epsilon = config.econometrics.numerical_epsilon
                    if abs(z) <= config.econometrics.success_z + epsilon:
                        outcome, resolved = "CONVERGED", True
                    elif (
                        int(pending["divergence_sign"]) * z
                        >= config.econometrics.adverse_z - epsilon
                    ):
                        outcome, resolved = "STOPPED", True
                    elif elapsed >= h:
                        outcome, resolved = "TIMEOUT", True
                if resolved:
                    if pending_target is not None and pending_target["outcome_type"] == "PENDING":
                        pending_target.update(
                            {
                                "y_revert_success": 1
                                if outcome == "CONVERGED"
                                else (None if outcome == "CENSORED" else 0),
                                "outcome_type": outcome,
                                "resolution_date": day,
                                "time_to_resolution": elapsed,
                                "max_adverse_z": max(adverse) if adverse else None,
                                "max_favourable_z": min(adverse) if adverse else None,
                                "label_eligible": outcome != "CENSORED",
                                "censor_reason": "LIFECYCLE_ENDED"
                                if lifecycle_end
                                else ("MISSING_FUTURE_PRICE" if z is None else None),
                            }
                        )
                    pending, pending_target = None, None
                    adverse = []
            if day not in states.index:
                continue
            state = states.loc[day]
            if (
                pending is None
                and np.isfinite(float(state["z_score"]))
                and abs(float(state["z_score"])) < config.econometrics.entry_z
            ):
                armed = True
            crossing = crossing_rows.get(day)
            if crossing is None or pending is not None or not armed:
                continue
            if not bool(crossing["baseline1_eligible"]) or str(state["pair_status"]) != "ACTIVE":
                continue
            timestamp = pd.to_datetime(crossing["event_timestamp"], utc=True)
            if timestamp != cutoff or not bool(state["fresh_threshold_crossing"]):
                raise ValueError("Crossing does not match its observable daily pair state")
            if abs(float(crossing["z_entry"])) < (
                config.econometrics.entry_z - config.econometrics.numerical_epsilon
            ):
                raise ValueError("Crossing z does not reach the declared divergence boundary")
            snapshot_id = str(crossing["relationship_snapshot_id"])
            if snapshot_id != str(state["relationship_snapshot_id"]) or snapshot_id not in lookup:
                raise ValueError("Crossing relationship lineage does not match daily state")
            snapshot = lookup[snapshot_id]
            available_snapshots = pair_snapshots.loc[
                pd.to_datetime(pair_snapshots["effective_start_at"], utc=True).le(timestamp)
            ].sort_values("effective_start_at")
            if (
                available_snapshots.empty
                or str(available_snapshots.iloc[-1]["relationship_snapshot_id"]) != snapshot_id
            ):
                raise ValueError("Event does not use the latest effective relationship snapshot")
            for parameter in ("alpha", "beta", "spread_mean", "spread_std"):
                if parameter in snapshot and not np.isclose(
                    float(crossing[parameter]),
                    float(snapshot[parameter]),
                    atol=config.econometrics.numerical_epsilon,
                    rtol=0,
                ):
                    raise ValueError("Crossing parameters differ from its frozen relationship")
            if not np.isclose(
                float(crossing["z_entry"]),
                float(state["z_score"]),
                atol=config.econometrics.numerical_epsilon,
                rtol=0,
            ):
                raise ValueError("Crossing z does not match its observable daily state")
            partition, partition_end = _partition(day, config)
            horizon_end = session_dates[date_index[day] + h]
            embargo_end = session_dates[date_index[day] + config.ml.embargo_days]
            event = {
                "event_id": _event_id(pair_id, timestamp, snapshot_id, policy),
                "pair_id": pair_id,
                "event_date": day,
                "event_timestamp": timestamp,
                "sector": refs[a_ticker].get("sector", "UNKNOWN"),
                "divergence_sign": 1 if float(crossing["z_entry"]) > 0 else -1,
                "entry_z": float(crossing["z_entry"]),
                "relationship_snapshot_id": snapshot_id,
                "alpha": float(crossing["alpha"]),
                "beta": float(crossing["beta"]),
                "spread_mean": float(crossing["spread_mean"]),
                "spread_std": float(crossing["spread_std"]),
                "feature_cutoff_timestamp": timestamp,
                "feature_schema_version": config.ml.feature_schema_version,
                "label_policy_version": policy,
                "data_snapshot_id": data_snapshot_id,
                "relationship_version": relationship_version,
                "dataset_version": dataset_version,
                "baseline1_eligible": True,
                "partition": partition,
                "horizon_end_date": horizon_end,
            }
            for name in ("alpha", "beta", "spread_mean", "spread_std"):
                if not np.isfinite(event[name]) or (name == "spread_std" and event[name] <= 0):
                    raise ValueError("Non-estimable frozen parameters at divergence event")
            feature = build_quantitative_features(
                event,
                snapshot,
                pair_snapshots,
                a,
                b,
                context,
                session_dates,
                success_z=config.econometrics.success_z,
                schema_version=config.ml.feature_schema_version,
            )
            feature["dataset_version"] = dataset_version
            event["feature_complete"] = feature["feature_complete"]
            blocked: str | None = None
            if partition == "final_test":
                blocked = "FINAL_TEST_LOCKED"
            elif partition_end is None:
                blocked = "OUTSIDE_RESEARCH_PARTITIONS"
            elif embargo_end > partition_end:
                blocked = "PARTITION_EMBARGO"
            elif horizon_end > end:
                blocked = "INSUFFICIENT_FUTURE_HORIZON"
            target = {
                "event_id": event["event_id"],
                "label_policy_version": policy,
                "y_revert_success": None,
                "outcome_type": "LOCKED"
                if partition == "final_test"
                else ("CENSORED" if blocked else "PENDING"),
                "resolution_date": None,
                "time_to_resolution": None,
                "max_adverse_z": None,
                "max_favourable_z": None,
                "horizon_end_date": horizon_end,
                "label_eligible": False,
                "censor_reason": None if partition == "final_test" else blocked,
                "data_snapshot_id": data_snapshot_id,
                "relationship_version": relationship_version,
                "dataset_version": dataset_version,
            }
            partition_row = {
                "event_id": event["event_id"],
                "partition": partition,
                "supervised_eligible": False,
                "exclusion_reason": blocked,
                "horizon_end_date": horizon_end,
                "label_window_start": session_dates[date_index[day] + 1],
                "embargo_days": config.ml.embargo_days,
                "feature_complete": feature["feature_complete"],
                "data_snapshot_id": data_snapshot_id,
                "relationship_version": relationship_version,
                "dataset_version": dataset_version,
            }
            events.append(event)
            features.append(feature)
            targets.append(target)
            partitions.append(partition_row)
            pending, pending_target = event, target
            armed = False
            adverse = [int(event["divergence_sign"]) * float(event["entry_z"])]
    for event, target, partition_record in zip(events, targets, partitions, strict=True):
        if target["outcome_type"] == "PENDING":
            target.update(outcome_type="CENSORED", censor_reason="INSUFFICIENT_FUTURE_HORIZON")
        eligible = bool(
            event["feature_complete"]
            and target["label_eligible"]
            and event["partition"] in ("train", "validation")
        )
        partition_record["supervised_eligible"] = eligible
        if not eligible and partition_record["exclusion_reason"] is None:
            partition_record["exclusion_reason"] = (
                "INCOMPLETE_FEATURES" if not event["feature_complete"] else target["censor_reason"]
            )
        event["model_ready"] = bool(event["baseline1_eligible"] and event["feature_complete"])
    result = EventDataset(
        pd.DataFrame(events, columns=EVENT_COLUMNS),
        pd.DataFrame(features) if features else _empty_features(),
        pd.DataFrame(targets, columns=TARGET_COLUMNS),
        pd.DataFrame(partitions, columns=PARTITION_COLUMNS),
        feature_schema(config.ml.feature_schema_version),
    )
    validate_event_dataset(result)
    return result


def validate_event_dataset(dataset: EventDataset) -> None:
    """Verify event cardinality, target lock, boundary and predictor contracts."""
    frames = (dataset.events, dataset.features, dataset.targets, dataset.partitions)
    identities = set(dataset.events["event_id"])
    for frame in frames:
        if frame["event_id"].duplicated().any() or set(frame["event_id"]) != identities:
            raise ValueError("Event/feature/target/partition identities do not agree")
    validate_feature_timestamps(dataset.features)
    forbidden = {
        "y_revert_success",
        "outcome_type",
        "resolution_date",
        "pair_id",
        "ticker",
        "entry_z",
    }
    if forbidden & set(dataset.feature_schema["feature_columns"]):
        raise ValueError("Outcome or identity field entered the feature schema")
    if not dataset.events.empty:
        final_ids = set(
            dataset.events.loc[dataset.events["partition"].eq("final_test"), "event_id"]
        )
        final = dataset.targets.loc[dataset.targets["event_id"].isin(final_ids)]
        if final["y_revert_success"].notna().any() or not final["outcome_type"].eq("LOCKED").all():
            raise ValueError("Final-test labels were materialised before unlock")
        for name in ("resolution_date", "time_to_resolution", "max_adverse_z", "max_favourable_z"):
            if final[name].notna().any():
                raise ValueError("Final-test outcome metadata was materialised before unlock")
