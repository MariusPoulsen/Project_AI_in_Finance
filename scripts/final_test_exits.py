"""Final-test news-exit simulations (Decision 120a): the frozen rules, every span plus 2024-2025.

    python scripts/final_test_exits.py

The development stages (``pipeline.news_exit`` explore, confirm, replicate) also chose the
exit rule; that choice is frozen in ``choices.json``, copied from development. Here only the
simulation runs: once per frozen span on the final-test registry (whose event ids differ) and
once for 2024-2025, which no development stage covers. ``news_exit.load_exits`` reads the
extra ``exits_final.parquet``.
"""

import argparse
import shutil
import sys
from pathlib import Path

from structural_break import periods
from structural_break.pipeline import news_exit as ne
from structural_break.pipeline.sources import _sources

OUT = Path("outputs/news_exit")
DEVELOPMENT = Path("C:/Users/mariu/dev/Project_AI_in_Finance/outputs/news_exit")
SPANS = {
    "explore": ne.EXPLORE,
    "confirm": ne.CONFIRM,
    "replicate": ne.REPLICATE,
    "final": (periods.FINAL_TEST_YEARS[0], periods.FINAL_TEST_YEARS[-1]),
}


def main() -> None:
    if not periods.final_years_open():
        raise SystemExit("The final test is locked")
    args = argparse.Namespace(
        workspace_root=Path("data/team"),
        configs_dir=Path("configs"),
        features=[
            Path("outputs/sec_timing/timing_features.parquet"),
            Path("outputs/news_8k/news_features.parquet"),
            Path("outputs/news_8k/tone_features.parquet"),
        ],
        simulation=Path("outputs/walkforward/simulation_frozen_exit.parquet"),
        headlines=Path("outputs/headline_tone/headline_tone.parquet"),
        sec_metadata=Path("data/team/sec_metadata/final_test_v1"),
    )
    OUT.mkdir(parents=True, exist_ok=True)
    for name in ("choices.json", "exploration.json", "confirmation.json", "replication.json"):
        if (DEVELOPMENT / name).exists() and not (OUT / name).exists():
            shutil.copy2(DEVELOPMENT / name, OUT / name)
    frame, pairs, index, periodic = ne._load(args)
    sources = _sources(args.workspace_root)
    for stage, span in SPANS.items():
        target = OUT / f"exits_{stage}.parquet"
        if target.exists():
            print(stage, "exists", flush=True)
            continue
        exits = ne.simulate_exits(
            sources,
            args.configs_dir,
            frame,
            pairs,
            index,
            periodic,
            span,
            lambda message: print(message, file=sys.stderr, flush=True),
        )
        exits.to_parquet(target, index=False)
        print(stage, span, len(exits), "events", flush=True)


if __name__ == "__main__":
    main()
