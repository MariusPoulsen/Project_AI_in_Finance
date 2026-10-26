"""Resumable full-coverage catalyst batch over the v2 evidence packs (DECISIONS 47).

``index`` reads every stored v2 event checkpoint once and records its pack key.
``run`` extracts each distinct pack once, h20 model-population packs first,
in the fixed pseudo-random order of ``catalysts.processing_order``. Each pack
writes one cache record, so the job can stop and resume at any point; a
daily quota pause waits for the reset instead of failing. ``status`` summarises
progress and ``features`` expands the cache into the unchanged 31-column
catalyst block per model event, prefixed ``full_``.

The v2 checkpoints are read only. Credentials come from the environment (or
an explicit ``--env-file`` read into this process) and are never written.
"""

from __future__ import annotations

import json
import os
import queue
import threading
import time
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from structural_break.intelligence import catalysts as cv

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


def needs_work(
    record: dict[str, Any] | None,
    *,
    retry_invalid: bool = False,
    version: str = cv.ADAPTER_VERSION,
) -> bool:
    if record is None or record.get("adapter_version") != version:
        return True
    if record["status"] in FINAL_STATUSES:
        return False
    reasons = set(record.get("reasons", []))
    if reasons & RETRY_REASONS:
        return True
    return retry_invalid and "INVALID_OR_UNGROUNDED_PROVIDER_RESPONSE" in reasons


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
    extra_passes: int = 3,
    pass_delay_seconds: float = 600.0,
    between_passes: Callable[[float], None] = time.sleep,
    **options: Any,
) -> Counter[str]:
    """Extract every pack, then retry server-failed packs in up to ``extra_passes``.

    A pack whose server errors outlast the client's quick retries is left
    PROVIDER_UNAVAILABLE; later passes, spaced ``pass_delay_seconds`` apart,
    send it again so a temporary outage does not leave it UNKNOWN.
    """
    say = options.get("say", print)
    version = options.get("version", cv.ADAPTER_VERSION)
    counts = _run_pass(checkpoints, output, packs, models, **options)
    options.pop("limit", None)
    for number in range(1, extra_passes + 1):
        leftover = sum(
            1
            for key in packs["pack_key"].astype(str)
            if (record := load_record(output, key)) is not None
            and record.get("adapter_version") == version
            and needs_work(record, version=version)
        )
        if not leftover:
            break
        say(f"retry pass {number}: {leftover} packs failed on server errors; waiting first")
        between_passes(pass_delay_seconds)
        counts += _run_pass(checkpoints, output, packs, models, **options)
    _write_state(output, phase="finished")
    return counts


def _run_pass(
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
    extract: Callable[[cv.ModelClient, dict[str, Any]], dict[str, Any]] = cv.extract_view,
    version: str = cv.ADAPTER_VERSION,
) -> Counter[str]:
    todo: queue.Queue[tuple[str, str]] = queue.Queue()
    queued = 0
    for key, file in zip(packs["pack_key"].astype(str), packs["file"].astype(str), strict=True):
        if limit is not None and queued >= limit:
            break
        if needs_work(load_record(output, key), retry_invalid=retry_invalid, version=version):
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
                    record = extract(client, pack)
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


def status(output: Path, version: str = cv.ADAPTER_VERSION) -> dict[str, Any]:
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
        if record is None or needs_work(record, version=version):
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
