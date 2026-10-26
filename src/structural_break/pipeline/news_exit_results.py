"""Round 3: combine the news exit with entry rules, and check it on model trades (DECISIONS 63).

The E3 adverse-tone news exit passed its confirmation (Decision 60). This
round asks two follow-up questions on data whose components have already been
seen, so its results are post-hoc evidence for the locked final test, not
independent confirmation:

* ``combine``: on top of E3, apply each entry rule that was positive but
  inconclusive in rounds 1-2 (skip filters and graded sizing). The best
  combination is chosen on 2006-2015 by its gain over E3 alone, written to
  ``choices.json`` and committed; it is then evaluated on 2016-2023.
* ``models``: compare E3 with the frozen exit on the trades that the
  Decision 45 walk-forward top-20 % rule would select for Model A and Model B.

Net returns come from the Decision 59-61 exit simulations, whose research exit
loop reproduced the frozen simulator exactly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from structural_break.pipeline import news_exit as e2
from structural_break.pipeline import news_filters as ex
from structural_break.pipeline.walkforward import (
    TOP_SHARE,
    XGB_PARAMETERS,
    allocation,
    rolling_split,
)
from structural_break.research.evaluation import _estimator
from structural_break.storage.files import write_bytes

PLAN_VERSION = "p6-sec-explore3-v1"
EXPLORE, EVALUATE = (2006, 2015), (2016, 2023)
MODEL_YEARS = tuple(range(2010, 2024))
EXIT = "E3_adverse_tone_either_leg"
MIN_EVALUATE_YEARS = 5  # of 8


def _skip(rule: Callable[[pd.DataFrame], pd.Series]) -> Callable[[pd.DataFrame], pd.Series]:
    return lambda f: pd.Series(
        np.where(rule(f).fillna(False).astype(bool), 0.0, 1.0), index=f.index
    )


def _both(*weights: Callable[[pd.DataFrame], pd.Series]) -> Callable[[pd.DataFrame], pd.Series]:
    def combined(f: pd.DataFrame) -> pd.Series:
        result = pd.Series(1.0, index=f.index)
        for weight in weights:
            result = result * weight(f)
        return result

    return combined


ENTRY_WEIGHTS: dict[str, Callable[[pd.DataFrame], pd.Series]] = {
    "C1_S5_negative_recent_tone": _skip(ex.FILTERS["S5_mover_negative_prob_0.2"][1]),
    "C2_T3_earnings_filing": _skip(ex.FILTERS["T3_mover_earnings_3s"][1]),
    "C3_R1_earnings_or_negative_tone": _skip(ex.FILTERS["R1_fresh_news_filter"][1]),
    "C4_N2_news_explains_move": _skip(ex.FILTERS["N2_mover_news_explains_move"][1]),
    "C5_H1_negative_headline_1s": _skip(e2.SKIPS["H1_mover_neg_headline_1s"]),
    "C6_H2_net_headline_1s": _skip(e2.SKIPS["H2_mover_net_headline_1s"]),
    "C7_H4_abnormal_8k_volume": _skip(e2.SKIPS["H4_abnormal_8k_volume_5s"]),
    "C8_Z1_recent_tone_weight": e2.WEIGHTS["Z1_recent_tone_weight"],
    "C9_Z3_news_type_weight": e2.WEIGHTS["Z3_news_type_weight"],
    "C10_Z4_headline_tone_weight": e2.WEIGHTS["Z4_headline_tone_weight"],
    "C11_H2_and_Z1": _both(
        _skip(e2.SKIPS["H2_mover_net_headline_1s"]), e2.WEIGHTS["Z1_recent_tone_weight"]
    ),
    "C12_T3_and_H2": _both(
        _skip(ex.FILTERS["T3_mover_earnings_3s"][1]), _skip(e2.SKIPS["H2_mover_net_headline_1s"])
    ),
}


def load_exits(output: Path) -> pd.DataFrame:
    parts = [
        pd.read_parquet(output / f"exits_{name}.parquet")
        for name in ("explore", "confirm", "replicate")
    ]
    exits = pd.concat(parts, ignore_index=True)
    if exits["event_id"].duplicated().any():
        raise ValueError("Exit simulations overlap")
    return exits.loc[
        :, ["event_id", "frozen_status", "frozen_net", f"{EXIT}|status", f"{EXIT}|net"]
    ]


def combined_frame(frame: pd.DataFrame, exits: pd.DataFrame) -> pd.DataFrame:
    data = frame.drop(columns=["frozen|status", "frozen|net"], errors="ignore").merge(
        exits, on="event_id", how="inner", validate="one_to_one"
    )
    priced = data["frozen_status"].eq("COMPLETE") & data[f"{EXIT}|status"].eq("COMPLETE")
    return data.loc[priced].reset_index(drop=True)


def combination_contrast(data: pd.DataFrame, name: str, span: tuple[int, int]) -> dict[str, Any]:
    year = pd.to_datetime(data["event_date"]).dt.year
    rows = data.loc[year.between(*span)]
    weight = ENTRY_WEIGHTS[name](rows).astype(float)
    exit_net = rows[f"{EXIT}|net"].astype(float)
    frozen = rows["frozen_net"].astype(float)
    over_exit = (weight - 1) * exit_net  # gain over E3 alone
    over_frozen = weight * exit_net - frozen  # gain over the frozen policy
    reduced = weight.lt(1)
    stamps = pd.to_datetime(rows["event_date"])
    months = stamps.dt.strftime("%Y-%m").to_numpy()
    return ex.bootstrap(over_exit.to_numpy(), months) | {
        "versus_frozen": ex.bootstrap(over_frozen.to_numpy(), months),
        "reduced_share": float(reduced.mean()),
        "reduced_mean_exit_net_bps": float(exit_net[reduced].mean() * 1e4)
        if reduced.any()
        else None,
        "per_year_bps": {
            str(y): float(g.mean() * 1e4) for y, g in over_exit.groupby(stamps.dt.year.to_numpy())
        },
    }


def model_check(
    frame: pd.DataFrame, exits: pd.DataFrame, columns: dict[str, tuple[str, ...]]
) -> dict[str, Any]:
    """E3 versus the frozen exit on walk-forward top-20 % selections of A and B."""
    data = frame.drop(columns=["frozen|status", "frozen|net"], errors="ignore").merge(
        exits, on="event_id", how="left", validate="one_to_one"
    )
    result: dict[str, Any] = {}
    for family, params in (("logistic", {"C": 0.01}), ("xgboost", XGB_PARAMETERS)):
        for model in ("A", "B"):
            frozen_alloc = pd.Series(np.nan, index=data.index)
            exit_alloc = pd.Series(np.nan, index=data.index)
            for year in MODEL_YEARS:
                train, threshold_rows, test = rolling_split(data, year)
                estimator = _estimator(family, params, 42)
                estimator.fit(
                    train.loc[:, columns[model]].astype(float), train[ex.TARGET].astype(int)
                )
                both = pd.concat([threshold_rows, test])
                scores = estimator.predict_proba(both.loc[:, columns[model]].astype(float))[:, 1]
                simulated = threshold_rows["frozen_status"].notna().to_numpy()
                cut = float(np.quantile(scores[: len(threshold_rows)][simulated], 1.0 - TOP_SHARE))
                selected = pd.Series(scores[len(threshold_rows) :] >= cut, index=test.index)
                priced = test["frozen_status"].eq("COMPLETE") & test[f"{EXIT}|status"].eq(
                    "COMPLETE"
                )
                index = test.index[priced]
                frozen_alloc.loc[index] = allocation(
                    selected[priced],
                    test.loc[priced, "frozen_status"],
                    test.loc[priced, "frozen_net"],
                )
                exit_alloc.loc[index] = allocation(
                    selected[priced],
                    test.loc[priced, f"{EXIT}|status"],
                    test.loc[priced, f"{EXIT}|net"],
                )
            known = frozen_alloc.notna() & exit_alloc.notna()
            difference = (exit_alloc - frozen_alloc)[known]
            stamps = pd.to_datetime(data.loc[known, "event_date"])
            selected_rows = known & frozen_alloc.ne(0)
            result[f"{family}|{model}"] = ex.bootstrap(
                difference.to_numpy(), stamps.dt.strftime("%Y-%m").to_numpy()
            ) | {
                "selected_trades": int(selected_rows.sum()),
                "frozen_mean_net_selected_bps": float(
                    data.loc[selected_rows, "frozen_net"].mean() * 1e4
                ),
                "exit_mean_net_selected_bps": float(
                    data.loc[selected_rows, f"{EXIT}|net"].mean() * 1e4
                ),
                "per_period_bps": {
                    label: float(difference[stamps.dt.year.between(lo, hi).to_numpy()].mean() * 1e4)
                    for label, (lo, hi) in (
                        ("2010-2015", (2010, 2015)),
                        ("2016-2021", (2016, 2021)),
                        ("2022-2023", (2022, 2023)),
                    )
                },
            }
    return result


def main(arguments: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("combine-explore", "combine-evaluate", "models"))
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--features", type=Path, action="append", required=True)
    parser.add_argument("--simulation", type=Path, required=True)
    parser.add_argument("--headlines", type=Path, required=True)
    parser.add_argument("--sec-metadata", type=Path, required=True)
    parser.add_argument("--exits-dir", type=Path, default=Path("outputs/p6_sec_explore2"))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(arguments)
    frame, _, _, _ = e2._load(args)
    exits = load_exits(args.exits_dir)
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)

    def save(name: str, value: dict[str, Any]) -> None:
        text = json.dumps(
            value | {"plan_version": PLAN_VERSION, "run_date": date.today().isoformat()},
            indent=2,
            sort_keys=True,
            default=str,
        ) + chr(10)
        write_bytes(out / name, text.encode())

    if args.stage == "models":
        _, columns = ex.load(args.workspace_root, args.features, args.simulation)
        result = model_check(frame, exits, columns)
        save("models.json", {"exit": EXIT, "years": list(MODEL_YEARS), "models": result})
        print(json.dumps({k: round(v["estimate_bps"], 2) for k, v in result.items()}))
        return
    data = combined_frame(frame, exits)
    if args.stage == "combine-explore":
        rows = {name: combination_contrast(data, name, EXPLORE) for name in ENTRY_WEIGHTS}
        positive = {k: v for k, v in rows.items() if v["estimate"] > 0}
        best = max(positive or rows, key=lambda k: (positive or rows)[k]["t"])
        choice = {
            "name": best,
            "explore_t": rows[best]["t"],
            "explore_estimate_bps": rows[best]["estimate_bps"],
        }
        save("combine_exploration.json", {"years": EXPLORE, "combinations": rows, "choice": choice})
        raw = (json.dumps(choice, indent=2, sort_keys=True) + chr(10)).encode()
        write_bytes(out / "choices.json", raw)
        print(json.dumps({"choice": choice, "sha256": hashlib.sha256(raw).hexdigest()}))
        return
    raw = (out / "choices.json").read_bytes()
    choice = json.loads(raw)
    rows = {name: combination_contrast(data, name, EVALUATE) for name in ENTRY_WEIGHTS}
    chosen = rows[choice["name"]]
    years_positive = sum(v > 0 for v in chosen["per_year_bps"].values())
    passes = bool(
        chosen["estimate"] > 0
        and chosen["p_one_sided"] < ex.ALPHA
        and years_positive >= MIN_EVALUATE_YEARS
    )
    save(
        "combine_evaluation.json",
        {
            "years": EVALUATE,
            "choice": choice,
            "choices_sha256": hashlib.sha256(raw).hexdigest(),
            "chosen": chosen,
            "years_positive": years_positive,
            "passes": passes,
            "all_combinations": rows,
        },
    )
    print(
        json.dumps(
            {
                "choice": choice["name"],
                "estimate_bps": chosen["estimate_bps"],
                "p": chosen["p_one_sided"],
                "years_positive": years_positive,
                "passes": passes,
            }
        )
    )


if __name__ == "__main__":
    main()
