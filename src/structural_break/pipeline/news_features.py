"""Recent-news extraction batch for the h20 model events (DECISIONS 50).

``build`` finds each event leg's 8-Ks from the last three sessions, parses the
distinct filing sets from the stored SEC archive (read only) and writes one
pack per company and filing set. ``run`` extracts every pack once with the
shared resumable batch runner; ``status`` reports progress. ``tone`` scores
the same packs with the pinned local FinBERT (DECISIONS 51) and
``tone-status`` reports its progress. ``features`` writes the thirteen news
features and, once scored, the seven tone features per model event.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from structural_break.config.paths import ProjectPaths
from structural_break.intelligence import catalysts as cv
from structural_break.intelligence import recent_news as rn
from structural_break.intelligence import recent_tone as rt
from structural_break.intelligence.timing import session_closes
from structural_break.pipeline import catalysts as cc
from structural_break.pipeline.sources import _sources
from structural_break.research.intelligence import _coverage_bounds


def model_events(workspace: Path) -> pd.DataFrame:
    """Accepted h20 model events with fixed leg identities and 1-day abnormal returns."""
    version = _sources(workspace).binding.evaluation.version
    inputs = pd.read_parquet(workspace / "artifacts/research" / version / "model_inputs.parquet")
    pairs = pd.read_parquet(workspace / "universe/source_v1/pair_universe.parquet")
    columns = [
        "event_id",
        "pair_id",
        "event_timestamp",
        "abnormal_return_A_1d",
        "abnormal_return_B_1d",
    ]
    return inputs.loc[:, columns].merge(
        pairs.loc[:, ["pair_id", "leg_a_security_id", "leg_b_security_id"]],
        on="pair_id",
        validate="many_to_one",
    )


def build(
    workspace: Path, sec_metadata: Path, sec_cache: Path, output: Path, workers: int = 4
) -> dict[str, Any]:
    events = model_events(workspace)
    filings = pd.read_parquet(sec_metadata / "filings.parquet")
    coverage = _coverage_bounds(json.loads((sec_metadata / "coverage.json").read_bytes()), filings)
    stamps = pd.to_datetime(events["event_timestamp"], utc=True)
    closes = session_closes(date(stamps.min().year - 1, 11, 1), stamps.max().date())
    windows = rn.leg_windows(events, filings, coverage, closes)
    output.mkdir(parents=True, exist_ok=True)
    windows.to_parquet(output / "windows.parquet", index=False)
    legs = windows.dropna(subset=["leg_key"]).drop_duplicates("leg_key")
    paths = ProjectPaths(Path(__file__).resolve().parents[3], sec_cache.resolve())
    packs = output / "packs"

    def one(row: dict[str, Any]) -> tuple[str, bool]:
        target = packs / f"{row['leg_key']}.json"
        if target.exists():
            try:
                return row["leg_key"], bool(json.loads(target.read_bytes())["pack"]["chunks"])
            except (ValueError, KeyError):
                pass  # a pack truncated by an interrupted earlier build is rebuilt
        pack = rn.build_leg_pack(paths, filings, row["security_id"], list(row["filing_ids"]))
        rn.write_json(target, {"pack": pack})
        return row["leg_key"], bool(pack["chunks"])

    with ThreadPoolExecutor(workers) as pool:
        built = dict(pool.map(one, legs.to_dict("records")))
    queue = pd.DataFrame({"pack_key": list(built)})
    queue["file"] = queue["pack_key"] + ".json"
    queue["priority"] = True
    queue["order"] = queue["pack_key"].map(cv.processing_order)
    queue = queue.sort_values("order").reset_index(drop=True)
    queue.to_parquet(output / "queue.parquet", index=False)
    queue.loc[:, ["pack_key"]].to_parquet(output / "index.parquet", index=False)
    return {
        "events": int(len(events)),
        "event_legs": int(len(windows)),
        "legs_known": int(windows["known"].sum()),
        "legs_with_recent_8k": int(windows["leg_key"].notna().sum()),
        "distinct_packs": int(len(built)),
        "packs_with_text": int(sum(built.values())),
    }


def _tone_path(output: Path, key: str) -> Path:
    return output / "tone" / key[:2] / f"{key}.json"


def load_tone(output: Path, key: str) -> dict[str, Any] | None:
    path = _tone_path(output, key)
    return json.loads(path.read_bytes()) if path.exists() else None


def tone(output: Path, cache_dir: Path, say: Any = print) -> int:
    """Score every recent-news pack with the pinned FinBERT; resumable."""
    from structural_break.intelligence.sentiment import HuggingFaceFinBERT

    os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
    backend = HuggingFaceFinBERT(cache_dir, rt.TONE_POLICY, local_files_only=True)
    keys = [str(key) for key in pd.read_parquet(output / "queue.parquet")["pack_key"]]
    todo = [key for key in keys if load_tone(output, key) is None]
    started, state = time.monotonic(), output / "tone_state.json"
    rn.write_json(
        state,
        {
            "phase": "running",
            "total": len(keys),
            "queued": len(todo),
            "started": cc._now(),
            "updated": cc._now(),
            "pid": os.getpid(),
        },
    )
    say(f"{len(todo)} of {len(keys)} packs to score with {rt.TONE_POLICY.model_name}")
    for number, key in enumerate(todo, start=1):
        pack = json.loads((output / "packs" / f"{key}.json").read_bytes())["pack"]
        record = rt.score_pack(pack, backend) | {"pack_key": key, "scored_at": cc._now()}
        if number == 1:
            record["runtime"] = backend.runtime
        rn.write_json(_tone_path(output, key), record)
        if number % 100 == 0 or number == len(todo):
            rate = number / max(time.monotonic() - started, 1) * 3600
            say(f"{number}/{len(todo)} packs scored, {rate:.0f} per hour")
            rn.write_json(
                state,
                json.loads(state.read_bytes())
                | {"done_this_run": number, "updated": cc._now(), "rate_per_hour": round(rate)},
            )
    rn.write_json(
        state, json.loads(state.read_bytes()) | {"phase": "finished", "updated": cc._now()}
    )
    return len(todo)


def tone_status(output: Path) -> str:
    keys = [str(key) for key in pd.read_parquet(output / "queue.parquet")["pack_key"]]
    done = sum(_tone_path(output, key).exists() for key in keys)
    state_path = output / "tone_state.json"
    state = json.loads(state_path.read_bytes()) if state_path.exists() else {}
    rate = state.get("rate_per_hour")
    eta = f"{(len(keys) - done) / rate:.1f} hours" if rate else "unknown"
    lines = [
        f"FinBERT tone: {done:,} / {len(keys):,} packs ({100 * done / max(len(keys), 1):.1f} %)",
        f"  rate: {rate or '-'} per hour, ETA {eta if done < len(keys) else 'done'}",
        f"  last update: {state.get('updated', 'never')} ({state.get('phase', 'not started')})",
    ]
    log = output / "tone.log"
    if log.exists():
        lines += [
            "  log:",
            *(f"    {line}" for line in log.read_text(errors="replace").splitlines()[-2:]),
        ]
    return "\n".join(lines)


def features(workspace: Path, output: Path) -> Path:
    events = model_events(workspace)
    windows = pd.read_parquet(output / "windows.parquet")
    windows["filing_ids"] = windows["filing_ids"].map(list)
    block = rn.news_features(events, windows, lambda key: cc.load_record(output, key))
    path = output / "news_features.parquet"
    block.to_parquet(path, index=False)
    if (output / "tone").exists():
        tones = rt.tone_features(events, windows, lambda key: load_tone(output, key))
        tones.to_parquet(output / "tone_features.parquet", index=False)
    return path


def main(arguments: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("build", "run", "status", "features", "tone", "tone-status"):
        command = sub.add_parser(name)
        command.add_argument("--output", type=Path, required=True)
        if name in {"build", "features"}:
            command.add_argument("--workspace-root", type=Path, required=True)
        if name == "build":
            command.add_argument("--sec-metadata", type=Path, required=True)
            command.add_argument("--sec-cache", type=Path, required=True)
        if name == "run":
            command.add_argument("--env-file", type=Path)
            command.add_argument("--models", nargs="+", default=list(cv.MODELS))
            command.add_argument("--limit", type=int)
        if name == "status":
            command.add_argument("--json", action="store_true")
        if name == "tone":
            command.add_argument(
                "--model-cache", type=Path, default=Path.home() / ".cache/huggingface/hub"
            )
    args = parser.parse_args(arguments)

    def say(message: str) -> None:
        print(f"{cc._now()} {message}", flush=True)

    if args.command == "build":
        say(json.dumps(build(args.workspace_root, args.sec_metadata, args.sec_cache, args.output)))
    elif args.command == "run":
        if args.env_file:
            cc.load_env_file(args.env_file)
        if not (os.environ.get("GEMINI_API_KEY") or os.environ.get("SB_LLM_API_KEY")):
            sys.exit("No API key in the environment")
        packs = pd.read_parquet(args.output / "queue.parquet")
        counts = cc.run_batch(
            args.output / "packs",
            args.output,
            packs,
            args.models,
            limit=args.limit,
            say=say,
            extract=rn.extract_leg,
            version=rn.ADAPTER_VERSION,
        )
        say(f"finished: {dict(counts)}")
    elif args.command == "status":
        summary = cc.status(args.output, version=rn.ADAPTER_VERSION)
        if args.json:
            print(json.dumps(summary, indent=2, sort_keys=True))
        else:
            print(cc.format_status(summary, args.output / "run.log").replace("h20 priority", "h20"))
    elif args.command == "tone":
        say(f"finished: {tone(args.output, args.model_cache, say)} packs scored")
    elif args.command == "tone-status":
        print(tone_status(args.output))
    else:
        say(f"wrote {features(args.workspace_root, args.output)}")


if __name__ == "__main__":
    main()
