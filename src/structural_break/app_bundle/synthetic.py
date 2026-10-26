"""SYNTHETIC PREVIEW bundle: invented prices, events and SEC flags, real code paths.

This exists so the application can be developed, demonstrated and smoke-tested
without the group snapshot. Every ticker, price, label and SEC flag is invented.
The project's own `evaluate_matched_models` fits the matched A/B ladder on the
invented events, so reports, predictions and saved models have exactly the
published structures. The bundle is marked `synthetic: true` and the app shows a
red banner on every page. Nothing here is a research result.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from structural_break.app_bundle.analytics import (
    events_table,
    explain_models,
    feature_profile,
    model_curves,
)
from structural_break.app_bundle.contracts import (
    BUNDLE_SCHEMA_VERSION,
    EXPLAINED_VARIANTS,
    FAMILIES,
    RUNGS,
    AppBundle,
    BundleIdentity,
    HorizonData,
)
from structural_break.app_bundle.features import TONE_COLUMNS
from structural_break.app_bundle.workspace import bundle_digest, pair_table
from structural_break.intelligence.event_features import EVENT_FEATURE_NAMES
from structural_break.intelligence.sentiment import SENTIMENT_FEATURE_COLUMNS
from structural_break.ml.features import FEATURE_COLUMNS
from structural_break.research.evaluation import evaluate_matched_models
from structural_break.research.intelligence import METADATA_FEATURE_COLUMNS
from structural_break.research.protocol import ResearchProtocol, load_protocol

GROUPS = (
    ("Beverages", "Consumer Staples"),
    ("Household products", "Consumer Staples"),
    ("Money-centre banks", "Financials"),
    ("Regional banks", "Financials"),
    ("Integrated oil", "Energy"),
    ("Railroads", "Industrials"),
    ("Semiconductors", "Information Technology"),
    ("Managed care", "Health Care"),
    ("Electric utilities", "Utilities"),
    ("Home improvement retail", "Consumer Discretionary"),
    ("Payments networks", "Financials"),
    ("Aerospace & defence", "Industrials"),
)
SYLLABLES = ("AR", "BE", "CO", "DA", "EL", "FI", "GO", "HA", "IN", "JU", "KE", "LO", "MI", "NO")
CATALYSTS = ("EARNINGS", "GUIDANCE", "M_AND_A", "REGULATORY", "LITIGATION", "MANAGEMENT")


@dataclass(frozen=True)
class _Pair:
    pair_id: str
    leg_a: str
    leg_b: str
    group: str
    sector: str
    beta: float
    half_life: float
    break_rate: float


def _tickers(count: int, rng: np.random.Generator) -> list[str]:
    names: set[str] = set()
    while len(names) < count:
        names.add("".join(rng.choice(SYLLABLES, 2)) + rng.choice(list("QXZVW")))
    return sorted(names)


def _universe(pairs: int, rng: np.random.Generator) -> list[_Pair]:
    tickers = _tickers(2 * pairs, rng)
    output = []
    for index in range(pairs):
        group, sector = GROUPS[index % len(GROUPS)]
        a, b = tickers[2 * index], tickers[2 * index + 1]
        output.append(
            _Pair(
                f"{a}__{b}",
                a,
                b,
                group,
                sector,
                float(rng.uniform(0.6, 1.5)),
                float(rng.uniform(25, 140)),
                float(rng.uniform(0.0, 0.0015)),
            )
        )
    return output


def _simulate_prices(
    pair: _Pair, days: pd.DatetimeIndex, market: np.ndarray[Any, Any], rng: np.random.Generator
) -> tuple[np.ndarray[Any, Any], np.ndarray[Any, Any]]:
    n = len(days)
    factor = np.log(rng.uniform(20, 120)) + np.cumsum(0.9 * market + rng.normal(0.0002, 0.011, n))
    phi = np.exp(-np.log(2) / pair.half_life)
    spread = np.zeros(n)
    level = 0.0
    for t in range(1, n):
        if rng.random() < pair.break_rate:
            level += rng.normal(0, 0.12)  # structural break: the equilibrium moves
        spread[t] = level + phi * (spread[t - 1] - level) + rng.normal(0, 0.009)
    log_b = factor + rng.normal(0, 0.004, n)
    log_a = 0.2 + pair.beta * factor + spread
    return np.exp(log_a), np.exp(log_b)


def _relationships(
    log_a: np.ndarray[Any, Any], log_b: np.ndarray[Any, Any], days: pd.DatetimeIndex, window: int
) -> tuple[pd.DataFrame, np.ndarray[Any, Any], np.ndarray[Any, Any], np.ndarray[Any, Any]]:
    """Monthly trailing OLS snapshots and the next month's frozen daily z-scores."""
    n = len(days)
    z = np.full(n, np.nan)
    spread_out = np.full(n, np.nan)
    status = np.array(["INSUFFICIENT"] * n, dtype=object)
    months = pd.Series(np.arange(n), index=days).groupby(days.to_period("M")).agg(["min", "max"])
    snapshots = []
    previous_beta = None
    for _, (start, stop) in months.iterrows():
        if start < window:
            continue
        y, x = log_a[start - window : start], log_b[start - window : start]
        design = np.column_stack([np.ones(window), x])
        alpha, beta = np.linalg.lstsq(design, y, rcond=None)[0]
        residual = y - alpha - beta * x
        mean, std = float(residual.mean()), float(residual.std(ddof=1))
        lagged = residual[:-1] - mean
        rho = float(np.dot(lagged, residual[1:] - mean) / np.dot(lagged, lagged))
        half_life = float(-np.log(2) / np.log(rho)) if 0 < rho < 1 else float("inf")
        tstat = float(
            (rho - 1)
            / (np.std(residual[1:] - rho * residual[:-1]) / np.sqrt(np.dot(lagged, lagged)))
        )
        # Logistic fit through the two-variable Engle–Granger 1%/5% critical values.
        pvalue = float(1 / (1 + np.exp(2.944 - 2.95 * (tstat + 3.34))))
        state = (
            "ACTIVE"
            if pvalue < 0.05 and half_life <= 60
            else ("WATCH" if pvalue < 0.10 else "INVALID")
        )
        drift = abs(beta / previous_beta - 1) if previous_beta else 0.0
        previous_beta = beta
        snapshots.append(
            {
                "estimation_date": days[start - 1].date(),
                "effective_start": days[start].date(),
                "effective_end": days[stop].date(),
                "pair_status": state,
                "status_reason": "" if state == "ACTIVE" else "WEAK_COINTEGRATION",
                "n_obs": window,
                "alpha": float(alpha),
                "beta": float(beta),
                "spread_mean": mean,
                "spread_std": std,
                "eg_tstat": tstat,
                "eg_pvalue": pvalue,
                "half_life_days": half_life if np.isfinite(half_life) else None,
                "beta_drift_pct": 100 * drift,
            }
        )
        block = slice(start, stop + 1)
        spread_out[block] = log_a[block] - alpha - beta * log_b[block]
        z[block] = (spread_out[block] - mean) / std
        status[block] = state
    return pd.DataFrame(snapshots), spread_out, z, status


def _label(z: np.ndarray[Any, Any], start: int, horizon: int) -> tuple[int, int]:
    sign = np.sign(z[start])
    for step in range(1, horizon + 1):
        index = start + step
        if index >= len(z) or not np.isfinite(z[index]):
            return 0, min(index, len(z) - 1)
        if abs(z[index]) <= 0.5:
            return 1, index
        if sign * z[index] >= 3.0:
            return 0, index
    return 0, start + horizon


def _sec_features(
    rows: pd.DataFrame, y: np.ndarray[Any, Any], rng: np.random.Generator
) -> pd.DataFrame:
    n = len(rows)
    years = pd.to_datetime(rows["event_date"]).dt.year.to_numpy()
    features: dict[str, Any] = {}
    for leg in ("a", "b"):
        unknown = rng.random(n) < np.clip(0.35 - 0.02 * (years - 2004), 0.03, 0.4)
        recency = rng.exponential(25, n)
        features[f"sec_{leg}_recent_8k_count_30d"] = np.where(unknown, np.nan, rng.poisson(1.1, n))
        features[f"sec_{leg}_days_since_latest_8k"] = np.where(unknown, np.nan, recency)
        features[f"sec_{leg}_recent_items_2_02_earnings"] = np.where(
            unknown, np.nan, (recency < 10).astype(float)
        )
        features[f"sec_{leg}_recent_items_5_02_management"] = np.where(
            unknown, np.nan, (rng.random(n) < 0.06).astype(float)
        )
        features[f"sec_{leg}_periodic_recency_days"] = np.where(
            unknown, np.nan, rng.uniform(1, 95, n)
        )
        features[f"sec_{leg}_metadata_coverage_unknown"] = unknown.astype(float)
    features["sec_recent_8k_count_asymmetry"] = np.nan_to_num(
        features["sec_a_recent_8k_count_30d"]
    ) - np.nan_to_num(features["sec_b_recent_8k_count_30d"])
    features["sec_one_sided_recent_8k"] = (
        np.abs(features["sec_recent_8k_count_asymmetry"]) > 0
    ).astype(float)
    known = rng.random(n) < np.clip(0.2 + 0.04 * (years - 2004), 0.2, 0.9)
    for leg in ("a", "b"):
        positive = rng.beta(2, 5, n)
        negative = rng.beta(2, 5, n) + np.where(y == 0, 0.04, 0.0)
        neutral = np.clip(1 - positive - negative, 0, 1)
        features[f"sentiment_{leg}_positive"] = np.where(known, positive, np.nan)
        features[f"sentiment_{leg}_negative"] = np.where(known, negative, np.nan)
        features[f"sentiment_{leg}_neutral"] = np.where(known, neutral, np.nan)
        features[f"sentiment_{leg}_net"] = np.where(known, positive - negative, np.nan)
        features[f"sentiment_{leg}_token_coverage"] = np.where(known, rng.uniform(0.3, 1, n), 0.0)
        features[f"sentiment_{leg}_unknown"] = (~known).astype(float)
    features["sentiment_net_contrast"] = features["sentiment_a_net"] - features["sentiment_b_net"]
    features["sentiment_net_asymmetry"] = np.abs(features["sentiment_net_contrast"])
    features["sentiment_both_known"] = known.astype(float)
    features["sentiment_window_count"] = np.where(known, rng.poisson(3, n), 0)
    features["sentiment_chunk_count"] = np.where(known, rng.poisson(9, n), 0)
    frame = pd.DataFrame(features)
    for name in EVENT_FEATURE_NAMES:
        frame[name] = 0.0
    scheduled = rng.random(n) < min(1.0, 500 / max(n, 1))
    for i in range(n):
        if not scheduled[i]:
            for group in ("event_type", "affected_leg", "materiality", "direction"):
                frame.at[i, f"{group}_UNKNOWN"] = 1.0
            frame.at[i, "relationship_relevance_UNKNOWN"] = 1.0
            continue
        weights = np.array([4, 2, 1, 1, 1, 1, 6], dtype=float)
        if y[i] == 0:
            weights[2:5] *= 2.5  # invented: deal/regulatory news preceding failed reversion
        kind = rng.choice([*CATALYSTS, "NONE"], p=weights / weights.sum())
        frame.at[i, f"event_type_{kind}"] = 1.0
        leg = "NONE" if kind == "NONE" else rng.choice(["A", "B", "BOTH"])
        frame.at[i, f"affected_leg_{leg}"] = 1.0
        frame.at[
            i, f"materiality_{'LOW' if kind == 'NONE' else rng.choice(['LOW', 'MEDIUM', 'HIGH'])}"
        ] = 1.0
        frame.at[i, f"direction_{rng.choice(['POSITIVE', 'NEGATIVE', 'NEUTRAL'])}"] = 1.0
        frame.at[i, f"relationship_relevance_{rng.choice(['DIRECT', 'INDIRECT', 'NONE'])}"] = 1.0
        frame.at[i, "one_sided_event"] = float(leg in {"A", "B"})
        frame.at[i, "source_count"] = float(rng.integers(1, 4))
        frame.at[i, "document_recency_days"] = float(rng.uniform(0, 20))
        frame.at[i, "extraction_confidence"] = float(rng.uniform(0.5, 0.98))
        frame.at[i, "evidence_available"] = 1.0
    return frame


def _protocol(small: bool) -> ResearchProtocol:
    root = Path(__file__).resolve().parents[3]
    protocol = load_protocol(root / "configs" / "research_v2.yaml")
    if small:
        protocol = protocol.model_copy(update={"bootstrap_replicates": 60})
    return protocol


def synthetic_bundle(*, pairs: int = 36, seed: int = 5557, small: bool = False) -> AppBundle:
    rng = np.random.default_rng(seed)
    protocol = _protocol(small)
    days = pd.bdate_range("2004-01-02", "2023-12-29")
    market = rng.normal(0.0003, 0.010, len(days))
    vix = 18 + 6 * np.abs(
        pd.Series(rng.normal(0, 1, len(days))).rolling(60, 1).mean().to_numpy() * 4
    )
    universe = _universe(pairs, rng)
    event_rows: list[dict[str, Any]] = []
    states, prices, snapshots, crossings = [], [], [], []
    fit_start = pd.Timestamp(protocol.fit_start)
    for pair in universe:
        price_a, price_b = _simulate_prices(pair, days, market, rng)
        snaps, spread, z, status = _relationships(np.log(price_a), np.log(price_b), days, 504)
        snaps.insert(0, "pair_id", pair.pair_id)
        snapshots.append(snaps)
        visible = days >= fit_start
        betas = pd.Series(np.nan, index=days)
        for record in snaps.to_dict("records"):
            span = slice(
                pd.Timestamp(record["effective_start"]), pd.Timestamp(record["effective_end"])
            )
            betas.loc[span] = record["beta"]
        states.append(
            pd.DataFrame(
                {
                    "pair_id": pair.pair_id,
                    "trading_date": days[visible].date,
                    "spread": spread[visible],
                    "z_score": z[visible],
                    "abs_z": np.abs(z[visible]),
                    "pair_status": status[visible],
                    "beta": betas.to_numpy()[visible],
                }
            )
        )
        for ticker, values in ((pair.leg_a, price_a), (pair.leg_b, price_b)):
            prices.append(
                pd.DataFrame(
                    {
                        "ticker": ticker,
                        "trading_date": days[visible].date,
                        "adj_close": values[visible],
                    }
                )
            )
        returns_a = np.diff(np.log(price_a), prepend=np.nan)
        returns_b = np.diff(np.log(price_b), prepend=np.nan)
        armed = True
        for t in range(1, len(days)):
            if not np.isfinite(z[t]) or not np.isfinite(z[t - 1]):
                continue
            if abs(z[t]) <= 1.0:
                armed = True  # a new divergence needs the spread to settle first
            if days[t] < fit_start or not armed:
                continue
            if abs(z[t]) < 2.0 or abs(z[t - 1]) >= 2.0:
                continue
            armed = False
            sign = float(np.sign(z[t]))
            active = status[t] == "ACTIVE"
            crossings.append(
                {
                    "pair_id": pair.pair_id,
                    "event_date": days[t].date(),
                    "direction": int(sign),
                    "z_entry": float(z[t]),
                    "baseline1_eligible": bool(active),
                    "pair_status": status[t],
                }
            )
            window = z[max(0, t - 60) : t + 1]
            snap: Any = snaps.loc[pd.to_datetime(snaps["effective_start"]).le(days[t])].iloc[-1]
            row: dict[str, Any] = {
                "event_id": f"syn-{pair.pair_id}-{days[t].date().isoformat()}",
                "event_date": days[t].date(),
                "pair_id": pair.pair_id,
                "leg_a": pair.leg_a,
                "leg_b": pair.leg_b,
                "sector": pair.sector,
                "business_group": pair.group,
                "baseline1_eligible": bool(active),
                "z_signed": float(z[t]),
                "abs_z": float(abs(z[t])),
                "divergence_sign": sign,
                "adverse_z_velocity_1d": float(sign * (z[t] - z[t - 1])),
                "adverse_z_velocity_5d": float(sign * (z[t] - z[max(0, t - 5)])),
                "spread_vol_20": float(np.nanstd(np.diff(spread[max(0, t - 20) : t + 1]))),
                "spread_vol_ratio_20_60": float(
                    np.nanstd(np.diff(spread[t - 20 : t + 1]))
                    / max(float(np.nanstd(np.diff(spread[t - 60 : t + 1]))), 1e-9)
                ),
                "days_since_equilibrium": float(
                    len(window) - 1 - np.max(np.flatnonzero(np.abs(window) < 0.5), initial=0)
                ),
                "equilibrium_crossings_60": float(np.sum(np.diff(np.sign(window)) != 0)),
                "max_abs_z_20": float(np.nanmax(np.abs(z[t - 20 : t + 1]))),
                "coint_tstat": float(snap["eg_tstat"]),
                "coint_pvalue": float(snap["eg_pvalue"]),
                "coint_strength": float(-np.log(max(snap["eg_pvalue"], 1e-6))),
                "half_life": snap["half_life_days"],
                "beta_abs": float(abs(snap["beta"])),
                "beta_drift_pct": float(snap["beta_drift_pct"]),
                "corr_20": float(
                    np.corrcoef(returns_a[t - 19 : t + 1], returns_b[t - 19 : t + 1])[0, 1]
                ),
                "corr_60": float(
                    np.corrcoef(returns_a[t - 59 : t + 1], returns_b[t - 59 : t + 1])[0, 1]
                ),
                "valid_months_last_6": float(rng.integers(3, 7) if active else rng.integers(0, 4)),
                "market_return_1d": float(market[t]),
                "market_return_5d": float(market[t - 4 : t + 1].sum()),
                "sector_return_1d": float(market[t] + rng.normal(0, 0.004)),
                "sector_return_5d": float(market[t - 4 : t + 1].sum() + rng.normal(0, 0.01)),
                "vix_level": float(vix[t - 1]),
                "vix_change_5d": float(vix[t - 1] - vix[max(0, t - 6)]),
                "market_rv20": float(np.std(market[t - 19 : t + 1]) * np.sqrt(252)),
                "aligned_relative_return_5d": float(
                    sign * (returns_a[t - 4 : t + 1].sum() - returns_b[t - 4 : t + 1].sum())
                ),
                "aligned_relative_return_20d": float(
                    sign * (returns_a[t - 19 : t + 1].sum() - returns_b[t - 19 : t + 1].sum())
                ),
                "abnormal_return_A_1d": float(returns_a[t] - market[t]),
                "abnormal_return_B_1d": float(returns_b[t] - market[t]),
                "volume_z_A_20": float(rng.normal(0.3, 1)),
                "volume_z_B_20": float(rng.normal(0.3, 1)),
                "relative_realised_vol_20": float(
                    np.std(returns_a[t - 19 : t + 1]) / max(np.std(returns_b[t - 19 : t + 1]), 1e-9)
                ),
                "log_min_adv20": float(rng.normal(18, 1)),
                "adv_ratio": float(rng.lognormal(0, 0.5)),
                "max_range_proxy20": float(rng.uniform(0.01, 0.05)),
            }
            for horizon in (protocol.primary_horizon, *protocol.sensitivity_horizons):
                success, end_index = _label(z, t, horizon)
                row[f"y_{horizon}"] = success
                row[f"end_{horizon}"] = (days[t] + pd.offsets.BDay(horizon)).date()
                row[f"resolution_{horizon}"] = days[end_index].date()
            event_rows.append(row)
    base = pd.DataFrame(event_rows).sort_values(["event_date", "pair_id"]).reset_index(drop=True)
    sec = _sec_features(base, base[f"y_{protocol.primary_horizon}"].to_numpy(), rng)
    base = pd.concat([base, sec], axis=1)
    base["tone_aligned_contrast"] = base["divergence_sign"] * base["sentiment_net_contrast"]
    blocks = {
        "metadata": METADATA_FEATURE_COLUMNS,
        "tone": TONE_COLUMNS,
        "catalyst": EVENT_FEATURE_NAMES,
        "both": (*EVENT_FEATURE_NAMES, *TONE_COLUMNS, *METADATA_FEATURE_COLUMNS),
    }
    assert set(SENTIMENT_FEATURE_COLUMNS) <= set(TONE_COLUMNS)
    pair_series_ids = tuple(item.pair_id for item in universe)
    horizons: dict[int, HorizonData] = {}
    end = protocol.development_end
    for horizon in (protocol.primary_horizon, *protocol.sensitivity_horizons):
        rows = base.copy()
        rows["y_revert_success"] = rows[f"y_{horizon}"]
        rows["horizon_end_date"] = rows[f"end_{horizon}"]
        rows["supervised_eligible"] = pd.to_datetime(rows["horizon_end_date"]).dt.date.le(end)
        evaluation = evaluate_matched_models(
            rows.drop(
                columns=[
                    c
                    for c in rows
                    if str(c).startswith(("y_", "end_", "resolution_")) and c != "y_revert_success"
                ]
            ),
            FEATURE_COLUMNS,
            blocks,
            protocol,
        )
        models = {
            f"{family}_{variant}": joblib.load(io.BytesIO(evaluation.models[f"{family}_{variant}"]))
            for family in FAMILIES
            for variant in EXPLAINED_VARIANTS
        }
        predictions = evaluation.predictions
        assessment = predictions.loc[predictions["research_partition"].eq("assessment"), "event_id"]
        contributions, totals, importance = explain_models(
            rows,
            models,
            predictions["event_id"].tolist(),
            importance_ids=assessment.tolist(),
            top_k=10,
        )
        strategy, nav, trades = _strategy(predictions, rows, horizon, rng)
        horizons[horizon] = HorizonData(
            report=evaluation.report,
            events=events_table(predictions, rows),
            curves=model_curves(predictions),
            importance=importance,
            contributions=contributions,
            contribution_totals=totals,
            feature_profile=feature_profile(rows, blocks["both"] + FEATURE_COLUMNS),
            strategy=strategy,
            strategy_nav=nav,
            strategy_trades=trades,
        )
    primary_predictions = horizons[protocol.primary_horizon].events
    protocol_json = protocol.model_dump(mode="json")
    identity = BundleIdentity(
        schema_version=BUNDLE_SCHEMA_VERSION,
        source="synthetic",
        synthetic=True,
        primary_version="SYNTHETIC_PREVIEW_primary",
        registry_version="SYNTHETIC_PREVIEW_registry",
        intelligence_version="SYNTHETIC_PREVIEW_evidence",
        evaluations={h: f"SYNTHETIC_PREVIEW_evaluation_h{h}" for h in horizons},
        experiments={h: f"SYNTHETIC_PREVIEW_backtest_h{h}" for h in horizons},
        protocol=protocol_json,
        showcase_pairs=pair_series_ids,
        explanation_status="AVAILABLE",
        bundle_id=bundle_digest({"synthetic": True, "seed": seed, "pairs": pairs, "small": small}),
    )
    return AppBundle(
        identity=identity,
        horizons=horizons,
        pairs=pair_table(primary_predictions, pair_series_ids, all_available=False),
        pair_state=pd.concat(states, ignore_index=True),
        pair_prices=pd.concat(prices, ignore_index=True),
        pair_snapshots=pd.concat(snapshots, ignore_index=True),
        pair_crossings=pd.DataFrame(crossings),
    )


def _strategy(
    predictions: pd.DataFrame, rows: pd.DataFrame, horizon: int, rng: np.random.Generator
) -> tuple[dict[str, Any], pd.DataFrame, pd.DataFrame]:
    """Invented four-rung ladder in the compact Phase 6 summary structure."""
    assessed = predictions.loc[predictions["research_partition"].eq("assessment")].copy()
    assessed = assessed.merge(
        rows[["event_id", f"resolution_{horizon}"]], on="event_id", how="left"
    )
    success = assessed["y_revert_success"].to_numpy()
    net = np.where(
        success == 1,
        rng.normal(0.011, 0.008, len(assessed)),
        rng.normal(-0.003, 0.012, len(assessed)),
    )
    status = np.where(rng.random(len(assessed)) < 0.08, "NOT_ENTERED", "COMPLETE")
    status = np.where(
        (status == "COMPLETE") & (rng.random(len(assessed)) < 0.03), "UNPRICED", status
    )
    priced = status == "COMPLETE"
    trades = pd.DataFrame(
        {
            "event_id": assessed["event_id"],
            "pair_id": assessed["pair_id"],
            "status": status,
            "reason": np.where(
                priced,
                np.where(
                    success == 1,
                    "CONVERGENCE",
                    rng.choice(["ADVERSE_STOP", "TIMEOUT"], len(assessed)),
                ),
                np.where(status == "NOT_ENTERED", "BETA_OUTSIDE_LIMIT", "INCOMPLETE_SESSION_PATH"),
            ),
            "signal_z": rows.set_index("event_id").loc[assessed["event_id"], "z_signed"].to_numpy(),
            "entry_date": assessed["event_date"].astype(str),
            "exit_date": assessed[f"resolution_{horizon}"].astype(str),
            "holding_sessions": np.where(
                priced, rng.integers(2, horizon + 1, len(assessed)), np.nan
            ),
            "gross_return": np.where(priced, net + 0.0011, np.nan),
            "net_return": np.where(priced, net, np.nan),
            "mae": np.where(priced, -np.abs(rng.normal(0.02, 0.01, len(assessed))), np.nan),
            "mfe": np.where(priced, np.abs(rng.normal(0.02, 0.01, len(assessed))), np.nan),
        }
    )
    a = assessed["logistic_A_calibrated"].to_numpy()
    b = assessed["logistic_B_both_calibrated"].to_numpy()
    threshold = float(np.quantile(b, 0.9))
    picks = {
        "BASELINE_0": np.ones(len(assessed), dtype=bool),
        "BASELINE_1": assessed["baseline1_eligible"].to_numpy(dtype=bool),
        "MODEL_A": assessed["baseline1_eligible"].to_numpy(dtype=bool) & (a >= threshold),
        "MODEL_B": assessed["baseline1_eligible"].to_numpy(dtype=bool) & (b >= threshold),
    }
    for rung, mask in picks.items():
        trades[rung] = np.where(mask, "SELECTED", "WITHHELD")
    trades["FULL_SYSTEM"] = "NOT_RUN"
    rung_rows: list[dict[str, Any]] = []
    nav_rows: list[dict[str, Any]] = []
    dates = pd.to_datetime(assessed["event_date"]).to_numpy()
    for rung in RUNGS:
        if rung == "FULL_SYSTEM":
            rung_rows.append(
                {
                    "rung": rung,
                    "status": "NOT_RUN",
                    "reason": "CONTROLLER_GENERATION_NOT_ACCEPTED",
                    "combination": "SYNTHETIC",
                    "role": "HEADLINE",
                    "threshold": threshold,
                }
            )
            continue
        mask = picks[rung]
        chosen = mask & priced
        values = net[chosen]
        not_chosen = (~mask) & priced
        rung_rows.append(
            {
                "rung": rung,
                "status": "RUN",
                "population_n": len(assessed),
                "selected_n": int(mask.sum()),
                "withheld_n": int((~mask).sum()),
                "unavailable_n": 0,
                "priced_n": int(chosen.sum()),
                "unknown_return_n": int((mask & ~priced).sum()),
                "not_entered_n": int((mask & (status == "NOT_ENTERED")).sum()),
                "unpriced_n": int((mask & (status == "UNPRICED")).sum()),
                "complete_n": int(chosen.sum()),
                "mean_net_return": float(values.mean()) if len(values) else None,
                "median_net_return": float(np.median(values)) if len(values) else None,
                "mean_holding_sessions": float(np.nanmean(trades.loc[chosen, "holding_sessions"]))
                if chosen.any()
                else None,
                "net_positive_rate": float((values > 0).mean()) if len(values) else None,
                "label_success_rate": float(success[mask].mean()) if mask.any() else None,
                "labelled_n": int(mask.sum()),
                "label_successes": int(success[mask].sum()),
                "not_selected_priced_n": int(not_chosen.sum()),
                "not_selected_mean_net_return": float(net[not_chosen].mean())
                if not_chosen.any()
                else None,
                "not_selected_net_positive_rate": float((net[not_chosen] > 0).mean())
                if not_chosen.any()
                else None,
                "exit_reasons": "{}",
                "combination": "SYNTHETIC",
                "role": "HEADLINE",
                "threshold": threshold,
                "execution_config_version": "SYNTHETIC",
            }
        )
        daily = pd.Series(np.where(chosen, net * 0.02, 0.0), index=dates).groupby(level=0).sum()
        curve = (1 + daily).cumprod()
        drawdown = curve / curve.cummax() - 1
        for at, value, fall in zip(curve.index, curve.to_numpy(), drawdown.to_numpy(), strict=True):
            nav_rows.append(
                {
                    "rung": rung,
                    "at": pd.Timestamp(str(at), tz="UTC"),
                    "nav": float(value),
                    "drawdown": float(fall),
                    "gross_exposure": None,
                    "open_positions": None,
                    "nav_unknown": False,
                }
            )
    for factor, label in ((0.5, "THRESHOLD_SENSITIVITY"), (1.5, "THRESHOLD_SENSITIVITY")):
        for row in [r for r in rung_rows if r["role"] == "HEADLINE"]:
            copy = dict(row)
            copy.update(
                role=label, threshold=threshold * factor, combination=f"SYNTHETIC x{factor}"
            )
            if copy.get("selected_n") is not None and row["rung"].startswith("MODEL"):
                copy["selected_n"] = int(row["selected_n"] * (2.2 if factor < 1 else 0.3))
            rung_rows.append(copy)
    costs: list[dict[str, Any]] = []
    for cost in (2.5, 5.0, 10.0, 20.0):
        for borrow in (0.0, 0.01, 0.03, 0.10):
            for row in [r for r in rung_rows if r["role"] == "HEADLINE" and r["status"] == "RUN"]:
                mean = row["mean_net_return"]
                costs.append(
                    {
                        "cost_bps_per_side": cost,
                        "annual_borrow_rate": borrow,
                        "rung": row["rung"],
                        "selected_n": row["selected_n"],
                        "priced_n": row["priced_n"],
                        "mean_net_return": None
                        if mean is None
                        else mean - 2 * (cost - 5) / 1e4 - (borrow - 0.01) * 10 / 252,
                    }
                )
    comparisons: list[dict[str, Any]] = []
    for left, right in zip(RUNGS[:-1], RUNGS[1:], strict=True):
        if right == "FULL_SYSTEM":
            comparisons.append(
                {
                    "comparison": f"{left}__{right}",
                    "left": left,
                    "right": right,
                    "status": "NOT_RUN",
                    "reason": "CONTROLLER_GENERATION_NOT_ACCEPTED",
                }
            )
            continue
        estimate = float(rng.normal(0, 0.0004))
        width = float(abs(rng.normal(0.0015, 0.0005)))
        comparisons.append(
            {
                "comparison": f"{left}__{right}",
                "left": left,
                "right": right,
                "status": "RUN",
                "common_known": {
                    "estimate": estimate,
                    "interval": [estimate - width, estimate + width],
                    "unavailable_reason": None,
                    "contributing_months": 24,
                },
                "natural": {
                    "estimate": None,
                    "interval": None,
                    "unavailable_reason": "INSUFFICIENT_POPULATED_CALENDAR_MONTHS",
                    "contributing_months": 6,
                },
                "raw_candidate_population_n": len(assessed),
            }
        )
    nav_frame = pd.DataFrame(nav_rows)
    portfolios: list[dict[str, Any]] = []
    for rung in RUNGS:
        if rung == "FULL_SYSTEM":
            portfolios.append(
                {"rung": rung, "status": "NOT_RUN", "reason": "CONTROLLER_GENERATION_NOT_ACCEPTED"}
            )
            continue
        part = nav_frame.loc[nav_frame["rung"].eq(rung)]
        portfolios.append(
            {
                "rung": rung,
                "status": "RUN",
                "initial_nav": 1.0,
                "final_nav": float(part["nav"].iloc[-1]) if len(part) else None,
                "maximum_drawdown": float(part["drawdown"].min()) if len(part) else None,
                "known_turnover": None,
                "known_trading_cost": None,
                "known_borrow_cost": None,
                "limitations": ["SYNTHETIC_PREVIEW_INVENTED_RETURNS"],
            }
        )
    summary: dict[str, Any] = {
        "experiment_id": f"SYNTHETIC_PREVIEW_backtest_h{horizon}",
        "horizon": horizon,
        "event_count": len(assessed),
        "headline": {
            "key": "SYNTHETIC",
            "threshold": threshold,
            "role": "HEADLINE",
            "execution_config_version": "SYNTHETIC",
        },
        "combinations": [],
        "rungs": rung_rows,
        "cost_grid": costs,
        "comparisons": comparisons,
        "portfolios": portfolios,
        "limitations": ["SYNTHETIC PREVIEW: every return here is invented"],
        "label_coverage": {},
        "calendar_months": sorted({str(d)[:7] for d in assessed["event_date"]}),
        "full_system": "NOT_RUN",
        "post_hoc_development": True,
        "final_test_read": False,
    }
    return summary, nav_frame, trades
