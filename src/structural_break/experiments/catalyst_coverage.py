"""Resumable full-coverage catalyst batch over the v2 evidence packs (DECISIONS 47).

``index`` reads every stored v2 event checkpoint once and records its pack key.
``run`` extracts each distinct pack once, h20 model-population packs first,
in the fixed pseudo-random order of ``catalyst_v3.processing_order``. Each pack
writes one cache record, so the job can stop and resume at any point; a
daily quota pause waits for the reset instead of failing. ``status`` summarises
progress and ``features`` expands the cache into the unchanged 31-column
catalyst block per model event, prefixed ``full_``.

The v2 checkpoints are read only. Credentials come from the environment (or
an explicit ``--env-file`` read into this process) and are never written.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import sys
import threading
import time
from collections import Counter
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from structural_break.intelligence import catalyst_v3 as cv
from structural_break.intelligence.event_features import (
    EVENT_FEATURE_NAMES,
    build_event_feature_frame,
)

FINAL_STATUSES = {"SUCCESS", "NONE"}
RETRY_REASONS = {"PROVIDER_UNAVAILABLE", "INVALID_PROVIDER_PROTOCOL"}


def _replace(path: Path, body: bytes) -> None:
    """Atomic overwrite for mutable progress files and retried pack records."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_bytes(body)
    os.replace(temporary, path)


def _record_path(output: Path, key: str) -> Path:
    return output / "cache" / key[:2] / f"{key}.json"


def load_record(output: Path, key: str) -> dict[str, Any] | None:
    path = _record_path(output, key)
    return json.loads(path.read_bytes()) if path.exists() else None


def needs_work(record: dict[str, Any] | None, *, retry_invalid: bool = False) -> bool:
    if record is None or record.get("adapter_version") != cv.ADAPTER_VERSION:
        return True
    if record["status"] in FINAL_STATUSES:
        return False
    reasons = set(record.get("reasons", []))
    if reasons & RETRY_REASONS:
        return True
    return retry_invalid and "INVALID_OR_UNGROUNDED_PROVIDER_RESPONSE" in reasons


def build_index(checkpoints: Path, output: Path, workers: int = 8) -> pd.DataFrame:
    """One row per stored event checkpoint: event, pair, pack key and chunk count."""
    files = sorted(checkpoints.glob("*.json"))

    def one(path: Path) -> dict[str, Any]:
        record = json.loads(path.read_bytes())
        pack = record["pack"]
        return {
            "file": path.name,
            "event_id": record["event"]["event_id"],
            "pair_id": record["event"]["pair_id"],
            "event_timestamp": record["event"]["event_timestamp"],
            "pack_key": cv.pack_key(pack),
            "n_chunks": len(pack.get("chunks", [])),
        }

    with ThreadPoolExecutor(workers) as pool:
        index = pd.DataFrame(list(pool.map(one, files, chunksize=64)))
    if index["event_id"].duplicated().any():
        raise ValueError("Duplicate event identities in the checkpoint directory")
    output.mkdir(parents=True, exist_ok=True)
    index.to_parquet(output / "index.parquet", index=False)
    return index


def work_queue(index: pd.DataFrame, priority_events: set[str]) -> pd.DataFrame:
    """Distinct packs with one representative checkpoint, in processing order."""
    packs = (
        index.assign(priority=index["event_id"].isin(priority_events))
        .sort_values(["pack_key", "file"])
        .groupby("pack_key", sort=False)
        .agg(file=("file", "first"), priority=("priority", "any"), events=("event_id", "size"))
        .reset_index()
    )
    packs["order"] = packs["pack_key"].map(cv.processing_order)
    return packs.sort_values(["priority", "order"], ascending=[False, True]).reset_index(drop=True)


def load_env_file(path: Path) -> None:
    """Set SB_LLM_API_KEY for this process from a dotenv file, without echoing it."""
    for line in path.read_text(encoding="utf-8").splitlines():
        name, _, value = line.partition("=")
        if name.strip() in {"SB_LLM_API_KEY", "GEMINI_API_KEY"} and value.strip():
            os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


def _credential() -> str | None:
    return os.environ.get("GEMINI_API_KEY") or os.environ.get("SB_LLM_API_KEY")


def run_batch(
    checkpoints: Path,
    output: Path,
    packs: pd.DataFrame,
    models: Sequence[str],
    *,
    retry_invalid: bool = False,
    limit: int | None = None,
    say: Callable[[str], None] = print,
    client_factory: Callable[[str], cv.ModelClient] | None = None,
    wait_until: Callable[[datetime], None] | None = None,
    in_flight: int = cv.MAX_IN_FLIGHT,
) -> Counter[str]:
    todo: queue.Queue[tuple[str, str]] = queue.Queue()
    queued = 0
    for key, file in zip(packs["pack_key"].astype(str), packs["file"].astype(str), strict=True):
        if limit is not None and queued >= limit:
            break
        if needs_work(load_record(output, key), retry_invalid=retry_invalid):
            todo.put((key, file))
            queued += 1
    say(f"{queued} packs to extract with {', '.join(models)}")
    _write_state(output, phase="running", queued=queued, paused_until=None)
    factory = client_factory or (lambda model: cv.ModelClient(model, credential=_credential))

    def sleep_until(moment: datetime) -> None:
        while (left := (moment - datetime.now(UTC)).total_seconds()) > 0:
            time.sleep(min(left, 300))

    pause = wait_until or sleep_until
    counts: Counter[str] = Counter()
    lock = threading.Lock()
    started = time.monotonic()

    def worker(model: str, client: cv.ModelClient) -> None:
        while True:
            try:
                key, file = todo.get_nowait()
            except queue.Empty:
                return
            pack = json.loads((checkpoints / file).read_bytes())["pack"]
            while True:
                try:
                    record = cv.extract_view(client, pack)
                    break
                except cv.DailyQuotaExhausted:
                    reset = cv.next_quota_reset()
                    say(f"{model}: daily quota reached; pausing until {reset.isoformat()}")
                    _write_state(output, paused_until=reset.isoformat())
                    pause(reset)
                    _write_state(output, paused_until=None)
            record |= {"pack_key": key, "file": file, "extracted_at": _now()}
            earlier = load_record(output, key)
            if earlier is not None:
                # A retried pack keeps its earlier failed attempts for the audit trail.
                record["previous_attempts"] = [
                    *earlier.pop("previous_attempts", []),
                    {k: earlier.get(k) for k in ("model", "reasons", "extracted_at")},
                ]
            _replace(_record_path(output, key), json.dumps(record, sort_keys=True).encode())
            with lock:
                counts[record["status"]] += 1
                done = sum(counts.values())
                _write_state(output, done_this_run=done)
                if done % 25 == 0 or done == queued:
                    rate = done / max(time.monotonic() - started, 1) * 3600
                    codes = {m: dict(c.statuses) for m, c in clients.items()}
                    say(f"{done}/{queued} packs, {dict(counts)}, {rate:.0f} per hour, http {codes}")

    clients = {model: factory(model) for model in models}
    threads = [
        threading.Thread(target=worker, args=(model, clients[model]), daemon=True)
        for model in models
        for _ in range(in_flight)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    _write_state(output, phase="finished")
    return counts


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _write_state(output: Path, **fields: Any) -> None:
    """Small heartbeat for ``status``: process, last update and any quota pause."""
    path = output / "state.json"
    state = json.loads(path.read_bytes()) if path.exists() else {}
    state.update(fields, pid=os.getpid(), updated=_now())
    _replace(path, json.dumps(state, sort_keys=True).encode())


def _label(record: dict[str, Any]) -> str:
    """SUCCESS / NONE, or why a pack is UNKNOWN: abstained, rejected or server."""
    if record["status"] != "UNKNOWN":
        return str(record["status"])
    reasons = set(record.get("reasons", []))
    if "PROVIDER_RETURNED_UNKNOWN" in reasons:
        return "UNKNOWN_ABSTAINED"
    if "INVALID_OR_UNGROUNDED_PROVIDER_RESPONSE" in reasons:
        return "UNKNOWN_REJECTED"
    return "UNKNOWN_SERVER_OR_OTHER"


def status(output: Path) -> dict[str, Any]:
    """Progress over all packs and the h20 priority packs, with rates and an ETA."""
    queue_path = output / "queue.parquet"
    packs = (
        pd.read_parquet(queue_path, columns=["pack_key", "priority"])
        if queue_path.exists()
        else pd.read_parquet(output / "index.parquet", columns=["pack_key"])
        .drop_duplicates()
        .assign(priority=False)
    )
    statuses: Counter[str] = Counter()
    priority_done = 0
    reasons: Counter[str] = Counter()
    errors: Counter[str] = Counter()
    tokens = 0
    stamps: list[datetime] = []
    for key, priority in zip(packs["pack_key"], packs["priority"], strict=True):
        record = load_record(output, str(key))
        if record is None or needs_work(record):
            statuses["PENDING" if record is None else "TO_RETRY"] += 1
            continue
        statuses[_label(record)] += 1
        priority_done += bool(priority)
        reasons.update(record.get("reasons", []))
        errors.update(message[:70] for message in record.get("validation_errors", []))
        tokens += sum(int(item.get("prompt_tokens") or 0) for item in record.get("usage", []))
        if record.get("extracted_at"):
            stamps.append(datetime.fromisoformat(record["extracted_at"]))
    now = datetime.now(UTC)
    total, priority_total = len(packs), int(packs["priority"].sum())
    done = total - statuses["PENDING"] - statuses["TO_RETRY"]
    hour = sum(now - stamp < timedelta(hours=1) for stamp in stamps)
    day = sum(now - stamp < timedelta(days=1) for stamp in stamps)
    # Rate over the last day, or over the time actually covered if shorter.
    recent = [stamp for stamp in stamps if now - stamp < timedelta(days=1)]
    span = (now - min(recent)).total_seconds() if recent else 0.0
    per_day = len(recent) / max(span, 600.0) * 86_400 if recent else 0.0
    valid = statuses["SUCCESS"] + statuses["NONE"] + statuses["UNKNOWN_ABSTAINED"]
    state_path = output / "state.json"
    state = json.loads(state_path.read_bytes()) if state_path.exists() else {}
    return {
        "packs_done": done,
        "packs_total": total,
        "percent_done": round(100 * done / total, 1) if total else 0.0,
        "priority_done": priority_done,
        "priority_total": priority_total,
        "status": dict(statuses),
        "valid_share": round(valid / done, 3) if done else None,
        "packs_last_hour": hour,
        "packs_last_24h": day,
        "eta_days_all": round((total - done) / per_day, 1) if per_day else None,
        "eta_days_priority": round((priority_total - priority_done) / per_day, 1)
        if per_day
        else None,
        "reasons": dict(reasons),
        "top_validation_errors": dict(errors.most_common(5)),
        "prompt_tokens": tokens,
        "state": state,
    }


def format_status(summary: dict[str, Any], log: Path | None = None) -> str:
    state = summary["state"]
    lines = [
        f"Catalyst extraction: {summary['packs_done']:,} / {summary['packs_total']:,} packs "
        f"({summary['percent_done']} %)",
        f"  h20 priority packs: {summary['priority_done']:,} / {summary['priority_total']:,}",
        f"  results: {summary['status']}",
        f"  valid answers (catalyst, NONE or abstained): {summary['valid_share']}",
        f"  rate: {summary['packs_last_hour']} in the last hour, "
        f"{summary['packs_last_24h']} in the last 24 h",
        f"  ETA: priority {summary['eta_days_priority']} days, all {summary['eta_days_all']} days",
        f"  last update: {state.get('updated', 'never')} (process {state.get('pid', '-')}, "
        f"{state.get('phase', 'not started')})",
    ]
    if state.get("paused_until"):
        lines.append(f"  paused for the daily quota until {state['paused_until']}")
    if summary["top_validation_errors"]:
        lines.append(f"  most common validation errors: {summary['top_validation_errors']}")
    if log is not None and log.exists():
        tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-3:]
        lines += ["  log:", *(f"    {line}" for line in tail)]
    return "\n".join(lines)


def build_features(checkpoints: Path, output: Path, model_inputs: Path) -> Path:
    """Full-coverage catalyst block for every model event, keyed by model event_id."""
    index = pd.read_parquet(output / "index.parquet").set_index("event_id")
    events = pd.read_parquet(model_inputs, columns=["event_id", "evidence_event_id"])
    evidence_ids = events["evidence_event_id"].dropna().unique()
    extractions, rows = [], []
    for evidence_id in evidence_ids:
        if evidence_id not in index.index:
            continue
        row = index.loc[evidence_id]
        pack = json.loads((checkpoints / row["file"]).read_bytes())["pack"]
        record = load_record(output, row["pack_key"]) or {
            "model": cv.MODELS[0],
            "response": None,
            "reasons": ["NOT_YET_EXTRACTED"],
        }
        extraction = cv.event_extraction(pack, record)
        extractions.append(extraction)
        rows.append(
            {
                "event_id": evidence_id,
                "pair_id": row["pair_id"],
                "event_timestamp": extraction["event_timestamp"],
            }
        )
    block = build_event_feature_frame(pd.DataFrame(rows), extractions, cv.ADAPTER_VERSION)
    block = block.loc[:, ["event_id", *EVENT_FEATURE_NAMES]].rename(
        columns={"event_id": "evidence_event_id"}
        | {name: "full_" + name for name in EVENT_FEATURE_NAMES}
    )
    features = events.merge(block, on="evidence_event_id", how="left").drop(
        columns="evidence_event_id"
    )
    path = output / "full_catalyst_features.parquet"
    features.to_parquet(path, index=False)
    return path


def main(arguments: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("index", "run", "status", "features"):
        command = sub.add_parser(name)
        command.add_argument("--output", type=Path, required=True)
        if name != "status":
            command.add_argument("--checkpoints", type=Path, required=True)
        if name in {"run", "features"}:
            command.add_argument("--model-inputs", type=Path, required=True)
        if name == "status":
            command.add_argument("--json", action="store_true")
        if name == "run":
            command.add_argument("--env-file", type=Path)
            command.add_argument("--models", nargs="+", default=list(cv.MODELS))
            command.add_argument("--retry-invalid", action="store_true")
            command.add_argument("--limit", type=int)
    args = parser.parse_args(arguments)

    def say(message: str) -> None:
        print(f"{_now()} {message}", flush=True)

    if args.command == "index":
        index = build_index(args.checkpoints, args.output)
        say(f"indexed {len(index)} events, {index['pack_key'].nunique()} distinct packs")
    elif args.command == "run":
        if args.env_file:
            load_env_file(args.env_file)
        if not _credential():
            sys.exit("No API key in the environment")
        index = pd.read_parquet(args.output / "index.parquet")
        priority = set(
            pd.read_parquet(args.model_inputs, columns=["evidence_event_id"])["evidence_event_id"]
            .dropna()
            .astype(str)
        )
        packs = work_queue(index, priority)
        packs.to_parquet(args.output / "queue.parquet", index=False)
        counts = run_batch(
            args.checkpoints,
            args.output,
            packs,
            args.models,
            retry_invalid=args.retry_invalid,
            limit=args.limit,
            say=say,
        )
        say(f"finished: {dict(counts)}")
    elif args.command == "status":
        summary = status(args.output)
        if args.json:
            print(json.dumps(summary, indent=2, sort_keys=True))
        else:
            print(format_status(summary, args.output / "run.log"))
    else:
        path = build_features(args.checkpoints, args.output, args.model_inputs)
        say(f"wrote {path}")


if __name__ == "__main__":
    main()
