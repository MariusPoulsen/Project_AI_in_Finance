"""Final-test outcome labels (Decision 120b): the frozen label rule on 2024-2025 events.

    python scripts/final_test_labels.py [--workers 4]

The dataset builder never materialises final-test labels (its ``final_test`` partition is
locked by design). After the owner's unlock this script calls the same frozen
``ml.dataset.build_event_dataset`` per pair, with the registry's own inputs (prices,
securities, market context and the pair's cached relationship tables), on a configuration
whose labelled period runs to 2025-12-31. It then checks that

- the rebuilt events are exactly the registry's events (same ids), and
- every label of an event resolved before the old partition boundary equals the registry's,

and writes the 2024-2025 labels to ``data/team/final_test_labels.parquet``. Development
labels are never replaced.
"""

import argparse
import json
from concurrent.futures import ProcessPoolExecutor
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from structural_break import periods
from structural_break.config.loader import load_config
from structural_break.config.models import Pair, ProjectConfig, UniverseConfig
from structural_break.ml.dataset import build_event_dataset
from structural_break.research.protocol import experiment_config, load_protocol

WORKSPACE = Path("data/team").resolve()
STATE = WORKSPACE / "final_test_state.json"
OUT = WORKSPACE / "final_test_labels.parquet"
COLUMNS = [
    "event_id",
    "y_revert_success",
    "outcome_type",
    "resolution_date",
    "time_to_resolution",
    "max_adverse_z",
    "max_favourable_z",
    "horizon_end_date",
    "label_eligible",
    "censor_reason",
]
_MARKET: dict[str, pd.DataFrame] = {}


def _config(horizon: int) -> ProjectConfig:
    protocol = load_protocol(Path("configs/final_test.yaml"))
    pairs = pd.read_parquet(WORKSPACE / "market/source_v1/pair_universe.parquet")
    universe = UniverseConfig(
        version="research-v2-survivor-peers",
        orientation="leg_a_is_y",
        pairs=tuple(
            Pair(leg_a=r["leg_a"], leg_b=r["leg_b"], peer_group=r["peer_group"])
            for r in pairs.to_dict("records")
        ),
    )
    config = experiment_config(load_config(Path("configs")), protocol, universe, horizon)
    values = config.model_dump(mode="python")
    # The labelled period runs through the final-test end; the locked partition moves past it.
    values["ml"]["validation"]["end"] = periods.FINAL_TEST_END
    values["ml"]["final_test"] = {"start": date(2026, 1, 1), "end": date(2026, 12, 31)}
    values["data"]["end"] = date(2026, 12, 31)  # covers the moved partition; prices end 2025
    return ProjectConfig.model_validate(values)


def _init() -> None:
    market = WORKSPACE / "market/source_v1"
    for name in ("prices", "security_master", "market_context"):
        _MARKET[name] = pd.read_parquet(market / f"{name}.parquet")


def _pair(arguments: dict[str, Any]) -> dict[str, Any]:
    if not _MARKET:
        _init()
    config = ProjectConfig.model_validate(arguments["config"])
    pair = pd.DataFrame([arguments["pair"]])
    cache = Path(arguments["cache"])
    manifest = json.loads((cache / "manifest.json").read_bytes())
    key = manifest["identity"]
    tickers = (arguments["pair"]["leg_a"], arguments["pair"]["leg_b"])
    prices = _MARKET["prices"]
    prices = prices.loc[prices["ticker"].isin(tickers)].copy()
    prices = prices.loc[pd.to_datetime(prices["trading_date"]).dt.date.le(periods.FINAL_TEST_END)]
    securities = _MARKET["security_master"]
    securities = securities.loc[securities["ticker"].isin(tickers)].copy()
    context = _MARKET["market_context"]
    context = context.loc[context["sector_etf"].isin(securities["sector_etf"])]
    dataset = build_event_dataset(
        prices,
        pair,
        securities,
        context,
        pd.read_parquet(cache / "relationship_snapshots.parquet"),
        pd.read_parquet(cache / "daily_pair_state.parquet"),
        pd.read_parquet(cache / "raw_crossings.parquet"),
        config,
        data_snapshot_id=arguments["data_snapshot_id"],
        relationship_version=f"research_relationships_{key[:24]}",
        dataset_version=f"research_events_{key[:24]}_h{arguments['horizon']}",
        population=arguments["population"],
    )
    frozen_events = pd.read_parquet(cache / f"h{arguments['horizon']}_events.parquet")
    frozen_targets = pd.read_parquet(cache / f"h{arguments['horizon']}_targets.parquet")
    same_events = list(dataset.events["event_id"]) == list(frozen_events["event_id"])
    targets = dataset.targets.merge(
        frozen_targets[["event_id", "y_revert_success", "outcome_type"]],
        on="event_id",
        suffixes=("", "_frozen"),
    )
    old = targets["outcome_type_frozen"].ne("LOCKED") & targets["outcome_type_frozen"].ne(
        "CENSORED"
    )
    mismatched = int(
        (
            targets.loc[old, "y_revert_success"].fillna(-1)
            != targets.loc[old, "y_revert_success_frozen"].fillna(-1)
        ).sum()
    )
    final = targets.loc[targets["outcome_type_frozen"].eq("LOCKED"), COLUMNS]
    return {
        "pair_id": arguments["pair"]["pair_id"],
        "same_events": same_events,
        "checked": int(old.sum()),
        "mismatched": mismatched,
        "final": final.to_dict("records"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--horizon", type=int, default=20)
    args = parser.parse_args()
    if not periods.final_years_open():
        raise SystemExit("The final test is locked")
    state = json.loads(STATE.read_text())
    registry = WORKSPACE / "artifacts/research" / state["registry"]
    market_manifest = json.loads((WORKSPACE / "market/source_v1/manifest.json").read_text())
    protocol = load_protocol(Path("configs/final_test.yaml"))
    config = _config(args.horizon).model_dump(mode="json")
    pairs = pd.read_parquet(WORKSPACE / "market/source_v1/pair_universe.parquet")
    jobs = [
        {
            "config": config,
            "pair": row,
            "cache": str(registry / "pairs" / row["pair_id"]),
            "data_snapshot_id": market_manifest["data_snapshot_id"],
            "horizon": args.horizon,
            "population": protocol.population,
        }
        for row in pairs.sort_values("pair_id").to_dict("records")
    ]
    results = []
    with ProcessPoolExecutor(max_workers=args.workers, initializer=_init) as pool:
        for n, result in enumerate(pool.map(_pair, jobs), 1):
            results.append(result)
            if n % 50 == 0:
                print(f"{n}/{len(jobs)} pairs", flush=True)
    bad_events = [r["pair_id"] for r in results if not r["same_events"]]
    mismatched = sum(r["mismatched"] for r in results)
    checked = sum(r["checked"] for r in results)
    print(f"checked {checked} development labels: {mismatched} differ; event lists differ for "
          f"{len(bad_events)} pairs {bad_events[:5]}")
    if bad_events or mismatched:
        raise SystemExit("The rebuilt events or labels differ from the registry; nothing written")
    labels = pd.DataFrame([row for r in results for row in r["final"]], columns=COLUMNS)
    labels.to_parquet(OUT, index=False)
    print(
        f"wrote {OUT}: {len(labels)} final-test events, "
        f"{int(labels['y_revert_success'].notna().sum())} labelled, "
        f"{int(labels['y_revert_success'].fillna(0).sum())} reverted"
    )


if __name__ == "__main__":
    main()
