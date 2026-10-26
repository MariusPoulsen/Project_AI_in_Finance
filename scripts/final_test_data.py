"""Decision 118: build the final-test research workspace, step by step (resumable).

Run from a fresh checkout of the frozen commit whose ``data/team`` is a copy of the frozen
workspace (plus the raw market files and the SEC metadata from the research archive):

    python scripts/final_test_data.py market     --archive PATH/TO/data/research_v2
    python scripts/final_test_data.py sec        (needs SB_SEC_USER_AGENT)
    python scripts/final_test_data.py registry   --workers 4
    python scripts/final_test_data.py intelligence --archive PATH/TO/data/research_v2
    python scripts/final_test_data.py evaluation
    python scripts/final_test_data.py check

Every step refuses to read or capture 2024-2025 data until the owner's unlock record exists
(``periods``); ``--rehearsal`` runs the same steps with the development end instead.
"""

import argparse
import json
import os
import shutil
from datetime import date
from pathlib import Path

from structural_break import periods
from structural_break.config.paths import ProjectPaths

WORKSPACE = Path("data/team")
FROZEN_EVALUATION = "research_evaluation_16a431c4fea73ffd35f56062"  # the accepted h20 evaluation
STATE = WORKSPACE / "final_test_state.json"
SPLICE_CUT = date(2023, 12, 29)  # last frozen session
NEW_EVENTS = date(2024, 1, 1)


def _state() -> dict[str, str]:
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def _save(**values: str) -> None:
    state = _state() | values
    STATE.write_text(json.dumps(state, indent=1))


def _protocol(rehearsal: bool) -> Path:
    return Path("configs/final_test_rehearsal.yaml" if rehearsal else "configs/final_test.yaml")


def _require_unlock(rehearsal: bool) -> None:
    if not rehearsal and not periods.final_years_open():
        raise SystemExit(
            "The final test is locked: no owner unlock record cites the freeze manifest"
        )


def market(archive: Path, rehearsal: bool) -> None:
    """Splice capture into market/source_v1 (the frozen capture moves to market/frozen_v1)."""
    from structural_break.research.final_test import splice_downloader
    from structural_break.research.market import collect_market
    from structural_break.research.protocol import load_protocol

    _require_unlock(rehearsal)
    protocol = load_protocol(_protocol(rehearsal))
    frozen = WORKSPACE / "market/frozen_v1"
    if not frozen.exists():
        shutil.copytree(WORKSPACE / "market/source_v1", frozen)
        if not (frozen / "raw").exists():
            shutil.copytree(archive / "market/source_v1/raw", frozen / "raw")
        shutil.rmtree(WORKSPACE / "market/source_v1")
    manifest = collect_market(
        WORKSPACE / "universe/source_v1",
        WORKSPACE / "market/source_v1",
        protocol.data_start,
        protocol.development_end,
        downloader=splice_downloader(frozen / "raw", SPLICE_CUT),
    )
    _save(market=str(manifest["data_snapshot_id"]))
    print("market", manifest["data_snapshot_id"], manifest["price_rows"], "rows")


def sec(rehearsal: bool) -> None:
    """SEC filing metadata through the protocol end (existing collect-sec job)."""
    from structural_break.research.intelligence import collect_sec_metadata
    from structural_break.research.protocol import load_protocol

    _require_unlock(rehearsal)
    protocol = load_protocol(_protocol(rehearsal))
    out = WORKSPACE / "sec_metadata/final_test_v1"
    manifest = collect_sec_metadata(
        WORKSPACE / "universe/source_v1",
        out,
        protocol.data_start,
        protocol.development_end,
        sec_user_agent=os.environ.get("SB_SEC_USER_AGENT"),
    )
    _save(sec=str(out))
    print("sec metadata", out, manifest.get("inputs", {}).get("end"))


def registry(workers: int, rehearsal: bool) -> None:
    from structural_break.research.runner import build_research_registry

    _require_unlock(rehearsal)
    paths = ProjectPaths.resolve(Path.cwd(), WORKSPACE)
    manifest = build_research_registry(
        paths,
        _protocol(rehearsal),
        WORKSPACE / "universe/source_v1",
        WORKSPACE / "market/source_v1",
        workers=workers,
    )
    _save(registry=str(manifest["research_version"]))
    print("registry", manifest["research_version"])


def intelligence(archive: Path, rehearsal: bool, since: date) -> None:
    from structural_break.research.final_test import build_new_intelligence

    _require_unlock(rehearsal)
    paths = ProjectPaths.resolve(Path.cwd(), WORKSPACE)
    state = _state()
    sec_dir = Path(state.get("sec", str(WORKSPACE / "sec_metadata/source_v3")))
    out = WORKSPACE / "intelligence/final_test"
    build_new_intelligence(
        paths,
        state["registry"],
        since,
        out,
        sec_metadata_dir=sec_dir,
        cache_workspace=WORKSPACE / "cache",
        finbert_cache=Path.home() / ".cache/huggingface/hub",
        offline=rehearsal,
        sec_user_agent=os.environ.get("SB_SEC_USER_AGENT"),
    )
    _save(intelligence=str(out))
    print("intelligence", out)


def evaluation(since: date) -> None:
    from structural_break.research.final_test import extend_evaluation, write_binding

    paths = ProjectPaths.resolve(Path.cwd(), WORKSPACE)
    state = _state()
    manifest = extend_evaluation(
        paths,
        WORKSPACE / "artifacts/research" / FROZEN_EVALUATION,
        state["registry"],
        Path(state["intelligence"]),
        since,
    )
    version = str(manifest["research_version"])
    write_binding(paths, version)
    _save(evaluation=version)
    print("evaluation", version, "| binding written")


def check() -> None:
    """Open the bound sources and report the event years the book will see."""
    import pandas as pd

    from structural_break.pipeline.sources import _sources, load_frame

    sources = _sources(WORKSPACE)
    frame, _ = load_frame(WORKSPACE, sources.binding.evaluation.version)
    years = pd.to_datetime(frame["event_date"]).dt.year.value_counts().sort_index()
    print(
        "binding",
        sources.binding.evaluation.version,
        "| development end",
        sources.binding.development_end,
    )
    print(years.tail(6).to_string())


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "step", choices=("market", "sec", "registry", "intelligence", "evaluation", "check")
    )
    parser.add_argument(
        "--archive", type=Path, help="the research archive workspace (raw market files, SEC cache)"
    )
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument(
        "--rehearsal", action="store_true", help="development end 2023-12-31 instead"
    )
    parser.add_argument("--since", type=date.fromisoformat, default=NEW_EVENTS)
    args = parser.parse_args()
    if args.step == "market":
        market(args.archive, args.rehearsal)
    elif args.step == "sec":
        sec(args.rehearsal)
    elif args.step == "registry":
        registry(args.workers, args.rehearsal)
    elif args.step == "intelligence":
        intelligence(args.archive, args.rehearsal, args.since)
    elif args.step == "evaluation":
        evaluation(args.since)
    else:
        check()


if __name__ == "__main__":
    main()
