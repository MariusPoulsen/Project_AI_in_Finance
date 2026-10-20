"""Pre-registered literature entry filters and volatility sizing (DECISIONS 71).

Population: the R0 (fixed Decision 45 XGBoost Model B) top-20 % walk-forward
selections traded with the E3 news exit, the best combination so far. Baseline
0 (every event, E3 exit) is reported alongside. Thresholds are point-in-time:
each event is compared with quantiles of the previous calendar year's events.

Entry filters (skip the trade when the rule holds; a skipped trade earns 0):
F1 one-sided volume shock (single-stock information; Engelberg, Gao and
Jagannathan), F2 quiet common market (no common news), F3 the moving stock
rose (positive residual shocks reverse slowly; Baldi-Lanfranchi, Collin-Dufresne
and Daniel), F4 few same-day signals (low market-wide distraction; Jacobs and
Weber), F5 slow divergence, F6 expanding spread volatility (regime change),
F7 low VIX (liquidity provision pays less in calm markets; Nagel).

Volatility sizing (weight on each trade, normalised by the previous year's mean
weight): Z1v inverse spread volatility (equal risk per trade), Z2v inverse
market volatility (Moreira and Muir), Z3v proportional to VIX (Nagel).

``explore`` scores 2010-2015 and fixes the best filter and the best sizing rule;
``confirm`` tests both on 2016-2021 with Holm over the two and reports
2022-2023. The 2024-2025 final test is not read.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from structural_break.experiments import p6_boosting as pb

PLAN_VERSION = "p6-entry-volatility-v1"
EXPLORE, CONFIRM, REPLICATE = (2010, 2015), (2016, 2021), (2022, 2023)
MIN_CONFIRM_YEARS = 4
WEIGHT_BOUNDS = (0.25, 4.0)


def prior_year_quantile(frame: pd.DataFrame, values: pd.Series, q: float) -> pd.Series:
    """For each event, the q-quantile of ``values`` over all events signalled in the prior year."""
    year = pd.to_datetime(frame["event_date"]).dt.year
    table = values.groupby(year).quantile(q)
    return year.map(lambda y: table.get(y - 1, np.nan)).astype(float)


def derived(frame: pd.DataFrame) -> pd.DataFrame:
    """Mover, same-day activity and the prior-year reference levels used by the rules."""
    out = frame.copy()
    a, b = out["abnormal_return_A_1d"].astype(float), out["abnormal_return_B_1d"].astype(float)
    mover_a = a.abs() >= b.abs()
    out["mover_return"] = np.where(mover_a, a, b)
    out["mover_volume_z"] = np.where(mover_a, out["volume_z_A_20"], out["volume_z_B_20"])
    out["other_volume_z"] = np.where(mover_a, out["volume_z_B_20"], out["volume_z_A_20"])
    out["same_day_signals"] = out.groupby("event_date")["event_id"].transform("count")
    out["abs_market_1d"] = out["market_return_1d"].abs()
    out["abs_sector_1d"] = out["sector_return_1d"].abs()
    for column in ("abs_market_1d", "abs_sector_1d", "same_day_signals", "adverse_z_velocity_1d"):
        out[f"{column}_p50"] = prior_year_quantile(out, out[column].astype(float), 0.5)
    out["vix_p33"] = prior_year_quantile(out, out["vix_level"].astype(float), 1 / 3)
    for column in ("spread_vol_20", "market_rv20", "vix_level"):
        out[f"{column}_p50"] = prior_year_quantile(out, out[column].astype(float), 0.5)
    return out


FILTERS: dict[str, Callable[[pd.DataFrame], pd.Series]] = {
    "F1_one_sided_volume_shock": lambda f: (
        f["mover_volume_z"].ge(2.0) & f["other_volume_z"].lt(1.0)
    ),
    "F2_quiet_common_market": lambda f: (
        f["abs_market_1d"].lt(f["abs_market_1d_p50"])
        & f["abs_sector_1d"].lt(f["abs_sector_1d_p50"])
    ),
    "F3_mover_rose": lambda f: pd.Series(f["mover_return"] > 0, index=f.index),
    "F4_few_same_day_signals": lambda f: f["same_day_signals"].lt(f["same_day_signals_p50"]),
    "F5_slow_divergence": lambda f: f["adverse_z_velocity_1d"].lt(f["adverse_z_velocity_1d_p50"]),
    "F6_expanding_spread_vol": lambda f: f["spread_vol_ratio_20_60"].ge(1.5),
    "F7_low_vix": lambda f: f["vix_level"].lt(f["vix_p33"]),
}


def _clip(values: pd.Series) -> pd.Series:
    return values.clip(*WEIGHT_BOUNDS).fillna(1.0)


SIZING: dict[str, Callable[[pd.DataFrame], pd.Series]] = {
    "Z1v_inverse_spread_vol": lambda f: _clip(f["spread_vol_20_p50"] / f["spread_vol_20"]),
    "Z2v_inverse_market_vol": lambda f: _clip(f["market_rv20_p50"] / f["market_rv20"]),
    "Z3v_vix_proportional": lambda f: _clip(f["vix_level"] / f["vix_level_p50"]),
}


def normalised(frame: pd.DataFrame, weights: pd.Series) -> pd.Series:
    """Divide by the previous year's mean weight over all events (known before trading)."""
    year = pd.to_datetime(frame["event_date"]).dt.year
    means = weights.groupby(year).mean()
    return weights / year.map(lambda y: means.get(y - 1, np.nan)).astype(float)


def population(
    frame: pd.DataFrame, selected: pd.Series | None, span: tuple[int, int]
) -> pd.DataFrame:
    """Priced candidates in ``span``: all of Baseline 0, or the R0 selections only."""
    year = pd.to_datetime(frame["event_date"]).dt.year
    rows = (
        frame["frozen_status"].eq("COMPLETE")
        & frame["exit|status"].eq("COMPLETE")
        & year.between(*span)
    )
    if selected is not None:
        rows &= selected.reindex(frame.index, fill_value=False)
    return frame.loc[rows]


def _summary(
    data: pd.DataFrame, difference: pd.Series, base: pd.Series, new: pd.Series
) -> dict[str, Any]:
    months = pd.to_datetime(data["event_date"]).dt.strftime("%Y-%m")
    stats = pb.bootstrap(difference.to_numpy(float), months.to_numpy())
    year = pd.to_datetime(data["event_date"]).dt.year
    per_year = difference.groupby(year).mean() * 1e4
    sd = float(np.std(difference)) / math.sqrt(max(len(difference), 1))

    def sharpe(series: pd.Series) -> float:
        monthly = series.groupby(months).mean()
        spread = float(monthly.std(ddof=1))
        return float(monthly.mean() / spread * math.sqrt(12)) if spread > 0 else math.nan

    return stats | {
        "estimate_bps": stats["estimate"] * 1e4,
        "interval_95_bps": [v * 1e4 for v in stats["interval_95"]],
        "t": stats["estimate"] / sd if sd > 0 else 0.0,
        "per_year_bps": {int(str(k)): float(v) for k, v in per_year.items()},
        "years_positive": int((per_year > 0).sum()),
        "base_per_trade_bps": float(base.mean() * 1e4),
        "new_per_trade_bps": float(new.mean() * 1e4),
        "base_sharpe": sharpe(base),
        "new_sharpe": sharpe(new),
    }


def contrast(data: pd.DataFrame, family: str, name: str) -> dict[str, Any]:
    net = data["exit|net"].astype(float)
    if family == "filter":
        skip = FILTERS[name](data).fillna(False).astype(bool)
        new = net.where(~skip, 0.0)
        extra = {
            "skipped_share": float(skip.mean()),
            "skipped_mean_net_bps": float(net[skip].mean() * 1e4) if skip.any() else None,
            "kept_mean_net_bps": float(net[~skip].mean() * 1e4) if (~skip).any() else None,
        }
    else:
        weights = data["weight_" + name]
        new = net * weights
        extra = {"mean_weight": float(weights.mean())}
    return _summary(data, new - net, net, new) | extra


def load(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.Series]:
    from structural_break.experiments.p6_sec_explore3 import EXIT, load_exits

    frame, _ = pb.load_data(args.workspace_root, args.simulation)
    exits = load_exits(args.exits_dir).rename(
        columns={f"{EXIT}|status": "exit|status", f"{EXIT}|net": "exit|net"}
    )
    frame = derived(frame).merge(exits, on="event_id", how="left", validate="one_to_one")
    for name, rule in SIZING.items():
        frame["weight_" + name] = normalised(frame, rule(frame))
    scores = pd.read_parquet(args.scores)
    scores = scores.loc[scores["variant"].eq("R0_xgb_fixed")].copy()
    scores["selected"] = pb.selections(scores)
    chosen = scores.loc[scores["role"].eq("test") & scores["selected"], "event_id"]
    selected = frame["event_id"].isin(set(chosen))
    return frame, selected


def score_all(frame: pd.DataFrame, selected: pd.Series, span: tuple[int, int]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for label, chosen in (("model", selected), ("baseline0", None)):
        data = population(frame, chosen, span)
        result[label] = {
            **{n: contrast(data, "filter", n) for n in FILTERS},
            **{n: contrast(data, "sizing", n) for n in SIZING},
            "n": len(data),
        }
    return result


def _save(path: Path, value: dict[str, Any]) -> None:
    body = value | {"plan_version": PLAN_VERSION, "run_date": date.today().isoformat()}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body, indent=2, sort_keys=True, default=str) + "\n")


def main(arguments: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("explore", "confirm"))
    parser.add_argument("--workspace-root", type=Path, default=Path("data/team"))
    parser.add_argument(
        "--simulation",
        type=Path,
        default=Path("outputs/p6_improvement/walkforward/simulation_frozen_exit.parquet"),
    )
    parser.add_argument("--exits-dir", type=Path, default=Path("outputs/p6_sec_explore2"))
    parser.add_argument("--scores", type=Path, default=Path("outputs/p6_boosting2/scores.parquet"))
    parser.add_argument("--output", type=Path, default=Path("outputs/p6_entry_vol"))
    args = parser.parse_args(arguments)
    frame, selected = load(args)
    out = args.output
    if args.stage == "explore":
        rows = score_all(frame, selected, EXPLORE)
        model = rows["model"]

        def best(names: Sequence[str]) -> str:
            positive = [n for n in names if model[n]["estimate"] > 0]
            pool = positive or list(names)
            return max(pool, key=lambda n: model[n]["t"])

        choice = {"filter": best(list(FILTERS)), "sizing": best(list(SIZING))}
        _save(out / "exploration.json", {"years": EXPLORE, "results": rows, "choice": choice})
        raw = (json.dumps(choice, indent=2, sort_keys=True) + "\n").encode()
        (out / "choices.json").write_bytes(raw)
        print(json.dumps({"choice": choice, "sha256": hashlib.sha256(raw).hexdigest()}))
        for name in (*FILTERS, *SIZING):
            r = model[name]
            print(
                f"{name:28s} model {r['estimate_bps']:+6.2f} bps t {r['t']:+.2f}"
                f" | baseline0 {rows['baseline0'][name]['estimate_bps']:+6.2f} bps"
            )
        return
    raw = (out / "choices.json").read_bytes()
    choice = json.loads(raw)
    confirm = score_all(frame, selected, CONFIRM)
    replicate = score_all(frame, selected, REPLICATE)
    chosen = {family: confirm["model"][name] for family, name in choice.items()}
    adjusted = pb.holm({family: stats["p_one_sided"] for family, stats in chosen.items()})
    verdicts = {}
    for family, stats in chosen.items():
        verdicts[family] = {
            "name": choice[family],
            "estimate_bps": stats["estimate_bps"],
            "interval_95_bps": stats["interval_95_bps"],
            "p_one_sided": stats["p_one_sided"],
            "p_holm": adjusted[family],
            "years_positive": stats["years_positive"],
            "replicate_bps": replicate["model"][choice[family]]["estimate_bps"],
            "passes": bool(
                stats["estimate"] > 0
                and adjusted[family] < pb.ALPHA
                and stats["years_positive"] >= MIN_CONFIRM_YEARS
            ),
        }
    _save(
        out / "confirmation.json",
        {
            "choice": choice,
            "choices_sha256": hashlib.sha256(raw).hexdigest(),
            "confirm": confirm,
            "replicate": replicate,
            "verdicts": verdicts,
        },
    )
    print(json.dumps(verdicts, indent=2))


if __name__ == "__main__":
    main()
