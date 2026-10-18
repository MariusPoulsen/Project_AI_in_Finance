"""FinBERT headline tone of every 8-K, 2005-11 to 2023-12 (DECISIONS 59).

``parse`` reads each 8-K of the 250 frozen issuers from the stored SEC archive
(read only, several processes) and keeps its headline chunk: the opening
chunk of its first EX-99 exhibit (usually the press release), otherwise the
8-K's first Item chunk. ``score`` runs v2's pinned FinBERT on the first three
scored sentences of each headline, as chunks become available, and ``table``
writes one row per filing with its availability time, earnings flag and tone.
``status`` reports progress. No filing after the development end is read.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import pandas as pd

from structural_break.config.paths import ProjectPaths
from structural_break.experiments.catalyst_coverage import _now
from structural_break.intelligence import recent_news as rn

VERSION = "sec-8k-headline-tone-v1"
START, END = "2005-11-01", "2023-12-31"
WINDOWS = 3
SHARD = 400
_ITEM = re.compile(r"\b\d+\.\d+\b")


def _filings(sec_metadata: Path) -> pd.DataFrame:
    filings = pd.read_parquet(sec_metadata / "filings.parquet")
    accepted = pd.to_datetime(filings["acceptance_datetime_utc"], utc=True)
    keep = (
        filings["form"].isin(rn.EIGHT_K) & accepted.ge(START) & accepted.le(f"{END} 23:59:59+00:00")
    )
    return (
        filings.loc[keep]
        .sort_values(["acceptance_datetime_utc", "filing_id"])
        .reset_index(drop=True)
    )


def _parse_batch(arguments: tuple[str, str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    root, cache, rows = arguments
    from structural_break.intelligence.evidence import cache_filing, parse_documents

    paths = ProjectPaths(Path(root), Path(cache))
    result = []
    for filing in rows:
        record = {"filing_id": filing["filing_id"], "security_id": filing["security_id"]}
        try:
            documents = cache_filing(paths, filing, rn._offline, offline=True)
            picks = rn.select_chunks(
                parse_documents(documents, rn.PARSE_POLICY), [filing["filing_id"]]
            )
        except Exception as error:  # an unreadable capture stays UNKNOWN
            result.append(record | {"status": "PARSE_FAILED", "reason": type(error).__name__})
            continue
        exhibits = [chunk for chunk in picks if chunk["document_type"].startswith("EX-99")]
        chosen = exhibits[0] if exhibits else (picks[0] if picks else None)
        if chosen is None:
            result.append(record | {"status": "NO_TEXT"})
            continue
        result.append(
            record
            | {
                "status": "OK",
                "document_type": chosen["document_type"],
                "chunk_id": chosen["chunk_id"],
                "text": chosen["chunk_text"],
            }
        )
    return result


def parse(sec_metadata: Path, sec_cache: Path, output: Path, workers: int = 4) -> int:
    filings = _filings(sec_metadata)
    folder = output / "chunks"
    folder.mkdir(parents=True, exist_ok=True)
    done: set[str] = set()
    for shard in folder.glob("part-*.parquet"):
        done.update(pd.read_parquet(shard, columns=["filing_id"])["filing_id"])
    todo = filings.loc[~filings["filing_id"].isin(done)]
    root = str(Path(__file__).resolve().parents[3])
    rows = todo.to_dict("records")
    batches = [rows[i : i + SHARD] for i in range(0, len(rows), SHARD)]
    print(
        f"{_now()} {len(todo)} of {len(filings)} 8-Ks to parse in {len(batches)} shards", flush=True
    )
    started = time.monotonic()
    with ProcessPoolExecutor(workers) as pool:
        jobs = [(root, str(sec_cache.resolve()), batch) for batch in batches]
        for number, records in enumerate(pool.map(_parse_batch, jobs), start=1):
            stamp = f"{int(time.time() * 1000)}-{number}"
            pd.DataFrame(records).to_parquet(folder / f"part-{stamp}.parquet", index=False)
            rate = number * SHARD / max(time.monotonic() - started, 1) * 3600
            print(
                f"{_now()} parsed shard {number}/{len(batches)}, {rate:.0f} filings per hour",
                flush=True,
            )
    (output / "parse_done").write_text(_now())
    return len(todo)


def score(output: Path, cache_dir: Path) -> int:
    """Score parsed headlines as they appear; stop when parsing is done and all are scored."""
    from structural_break.intelligence.recent_tone import TONE_POLICY
    from structural_break.intelligence.sentiment import HuggingFaceFinBERT, _window_plan

    os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
    backend = HuggingFaceFinBERT(cache_dir, TONE_POLICY, local_files_only=True)
    tone_folder = output / "tone"
    tone_folder.mkdir(parents=True, exist_ok=True)
    scored_total = 0
    while True:
        done: set[str] = set()
        for shard in tone_folder.glob("part-*.parquet"):
            done.update(pd.read_parquet(shard, columns=["filing_id"])["filing_id"])
        parse_finished = (output / "parse_done").exists()
        pending = []
        for shard in sorted((output / "chunks").glob("part-*.parquet")):
            frame = pd.read_parquet(shard)
            pending.append(frame.loc[~frame["filing_id"].isin(done)])
        todo = pd.concat(pending) if pending else pd.DataFrame()
        if todo.empty:
            if parse_finished:
                break
            time.sleep(60)
            continue
        rows = []
        for record in todo.head(SHARD).to_dict("records"):
            row = {"filing_id": record["filing_id"], "status": record["status"]}
            if record["status"] == "OK":
                plan, windows, _ = _window_plan(record["text"], backend, TONE_POLICY)
                plan, windows = plan[:WINDOWS], windows[:WINDOWS]
                if windows:
                    weights = [int(meta["token_count"]) for meta in plan]
                    probabilities = backend.predict(windows)
                    total = sum(weights)
                    for label in ("positive", "negative", "neutral"):
                        row[label] = (
                            sum(w * p[label] for w, p in zip(weights, probabilities, strict=True))
                            / total
                        )
                    row["tokens"] = total
                else:
                    row["status"] = "NO_SCORABLE_TEXT"
            rows.append(row)
        pd.DataFrame(rows).to_parquet(
            tone_folder / f"part-{int(time.time() * 1000)}.parquet", index=False
        )
        scored_total += len(rows)
        print(f"{_now()} scored {scored_total} headlines this run", flush=True)
    (output / "score_done").write_text(_now())
    return scored_total


def table(sec_metadata: Path, output: Path) -> Path:
    filings = _filings(sec_metadata)
    tones = pd.concat(pd.read_parquet(p) for p in (output / "tone").glob("part-*.parquet"))
    tones = tones.drop_duplicates("filing_id", keep="last")
    items = filings["items"].astype(str)
    frame = filings.loc[
        :, ["filing_id", "security_id", "acceptance_datetime_utc", "acceptance_lower_bound_utc"]
    ].assign(earnings=items.map(lambda value: "2.02" in _ITEM.findall(value)))
    frame = frame.merge(tones, on="filing_id", how="left")
    frame["net"] = frame["positive"] - frame["negative"]
    path = output / "headline_tone.parquet"
    frame.to_parquet(path, index=False)
    return path


def status(sec_metadata: Path, output: Path) -> str:
    total = len(_filings(sec_metadata))

    def count(folder: str) -> int:
        return sum(
            len(pd.read_parquet(p, columns=["filing_id"]))
            for p in (output / folder).glob("part-*.parquet")
        )

    parsed, scored = count("chunks"), count("tone")
    return (
        f"8-K headlines: parsed {parsed:,} / {total:,}, FinBERT-scored {scored:,} / {total:,}"
        f" (parse {'done' if (output / 'parse_done').exists() else 'running'},"
        f" score {'done' if (output / 'score_done').exists() else 'running'})"
    )


def main(arguments: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("parse", "score", "table", "status"))
    parser.add_argument("--sec-metadata", type=Path)
    parser.add_argument("--sec-cache", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--model-cache", type=Path, default=Path.home() / ".cache/huggingface/hub")
    args = parser.parse_args(arguments)
    if args.command == "parse":
        parsed = parse(args.sec_metadata, args.sec_cache, args.output, args.workers)
        print(f"{_now()} finished: parsed {parsed}")
    elif args.command == "score":
        print(f"{_now()} finished: scored {score(args.output, args.model_cache)}")
    elif args.command == "table":
        print(table(args.sec_metadata, args.output))
    else:
        print(status(args.sec_metadata, args.output))
    sys.stdout.flush()


if __name__ == "__main__":
    main()
