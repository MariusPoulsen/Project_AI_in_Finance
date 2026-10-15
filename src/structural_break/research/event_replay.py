"""Four bounded processes for complete, target-free source-event verification.

Each child owns a fresh parser cache and applies the serial verifier's exact
per-event checks. Only the coordinator reduces results and verifies the final
population, source inventory and feature frame. Nothing here mints a proof.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from multiprocessing import get_context
from multiprocessing.process import BaseProcess
from pathlib import Path
from queue import Empty
from typing import Any

import pandas as pd
from threadpoolctl import threadpool_limits  # type: ignore[import-untyped]


@dataclass(frozen=True)
class EventReplayTask:
    slot: int
    indices: tuple[int, ...]
    canonical_rows: list[dict[str, Any]]
    records: list[dict[str, Any]]
    file_hashes: dict[str, str]
    directory: Path
    cache_root: Path
    filings: pd.DataFrame
    coverage: dict[str, Any]
    inputs: dict[str, Any]
    catalyst_ids: set[str]


def source_partitions(
    canonical_rows: list[dict[str, Any]], pairs: pd.DataFrame
) -> list[tuple[int, ...]]:
    """Keep business peers together; balance event counts without outcomes.

    Issuers belong to frozen business groups, so group ownership avoids parsing
    an issuer's same filings independently in several process caches.
    """
    groups = (
        pairs.set_index("pair_id")["business_group"].to_dict() if "business_group" in pairs else {}
    )
    members: dict[str, list[int]] = {}
    for index, row in enumerate(canonical_rows):
        group = str(groups.get(row["pair_id"], row["pair_id"]))
        members.setdefault(group, []).append(index)
    bins: list[list[int]] = [[] for _ in range(4)]
    for _, indices in sorted(members.items(), key=lambda item: (-len(item[1]), item[0])):
        slot = min(range(4), key=lambda value: (len(bins[value]), value))
        bins[slot].extend(indices)
    return [tuple(sorted(indices)) for indices in bins]


def _event_worker(task: EventReplayTask, messages: Any) -> None:
    from structural_break.config.paths import ProjectPaths
    from structural_break.research.intelligence import _replay_source_partition

    def emit(kind: str, payload: dict[str, Any]) -> None:
        messages.put({"kind": kind, "slot": task.slot, "pid": os.getpid(), **payload})

    try:
        emit("started", {})
        with threadpool_limits(limits=1):
            result = _replay_source_partition(
                task.directory,
                task.records,
                task.canonical_rows,
                task.indices,
                task.file_hashes,
                ProjectPaths(Path(__file__).resolve().parents[3], task.cache_root),
                task.filings,
                task.coverage,
                task.inputs,
                task.catalyst_ids,
                hot_frames=16,
                progress=lambda row: emit("progress", row),
            )
        emit("result", {"result": result})
    except BaseException as error:
        emit("error", {"error_type": type(error).__name__, "message": str(error)[:500]})
        raise


def _stop_processes(processes: list[BaseProcess]) -> None:
    for process in processes:
        if process.is_alive():
            process.terminate()
    for process in processes:
        process.join(timeout=10)
        if process.is_alive():
            process.kill()
            process.join(timeout=5)
        process.close()


def parallel_source_replay(
    tasks: list[EventReplayTask], progress: Callable[[dict[str, Any]], None]
) -> dict[str, Any]:
    """Run exactly four owned children; terminate all on any failure."""
    if len(tasks) != 4 or [task.slot for task in tasks] != list(range(4)):
        raise ValueError("Complete source replay requires exactly four explicit worker slots")
    expected_indices = [index for task in tasks for index in task.indices]
    if sorted(expected_indices) != list(range(len(expected_indices))):
        raise ValueError("Parallel source assignments must cover every canonical index once")
    context = get_context("spawn")
    messages = context.Queue(maxsize=16)
    processes: list[BaseProcess] = []
    states: list[dict[str, Any]] = [
        {
            "slot": task.slot,
            "pid": None,
            "verified_source_events": 0,
            "total_source_events": len(task.indices),
            "parsed_inventories": 0,
        }
        for task in tasks
    ]
    results: dict[int, dict[str, Any]] = {}

    def report() -> None:
        progress(
            {
                "verified_source_events": sum(row["verified_source_events"] for row in states),
                "parsed_inventories": sum(row["parsed_inventories"] for row in states),
                "worker_pids": [row["pid"] for row in states if row["pid"] is not None],
                "worker_progress": [dict(row) for row in states],
            }
        )

    # Spawn imports NumPy before the target function. Bound numerical libraries
    # in the child environment as well as with threadpoolctl inside the target.
    names = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")
    prior_environment = {name: os.environ.get(name) for name in names}
    try:
        for name in names:
            os.environ[name] = "1"
        try:
            for task in tasks:
                process: BaseProcess = context.Process(
                    target=_event_worker, args=(task, messages), name=f"sec-source-{task.slot}"
                )
                process.start()
                processes.append(process)
        finally:
            for name, prior in prior_environment.items():
                if prior is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = prior
        while len(results) < 4:
            try:
                message = messages.get(timeout=0.5)
            except Empty:
                if any(process.exitcode not in (None, 0) for process in processes):
                    raise ValueError(
                        "Parallel source worker exited without a complete result"
                    ) from None
                if any(
                    process.exitcode == 0 and slot not in results
                    for slot, process in enumerate(processes)
                ):
                    raise ValueError(
                        "Parallel source worker exited successfully without its result"
                    ) from None
                continue
            slot = message["slot"]
            if slot not in range(4) or message["pid"] != processes[slot].pid:
                raise ValueError("Parallel source message worker identity differs")
            state = states[slot]
            state["pid"] = message["pid"]
            if message["kind"] == "error":
                raise ValueError(
                    f"Parallel source worker failed: {message['error_type']}: {message['message']}"
                )
            if message["kind"] == "progress":
                completed = message["verified_source_events"]
                if not state["verified_source_events"] <= completed <= state["total_source_events"]:
                    raise ValueError("Parallel source progress exceeds its assigned population")
                state.update(
                    verified_source_events=completed,
                    parsed_inventories=message["parsed_inventories"],
                )
            elif message["kind"] == "result":
                result = message["result"]
                if slot in results or tuple(result["indices"]) != tasks[slot].indices:
                    raise ValueError("Parallel source result identities differ or are duplicated")
                for key in ("extractions", "tones", "metadata_rows", "audits"):
                    if len(result[key]) != len(tasks[slot].indices):
                        raise ValueError("Parallel source result population differs")
                results[slot] = result
                state.update(
                    verified_source_events=len(tasks[slot].indices),
                    parsed_inventories=result["parsed_inventories"],
                )
            elif message["kind"] != "started":
                raise ValueError("Unknown parallel source message")
            report()
        for process in processes:
            process.join(timeout=10)
            if process.exitcode != 0:
                raise ValueError("Parallel source process did not exit successfully")
        order: dict[int, tuple[int, int]] = {}
        for slot, result in results.items():
            for offset, index in enumerate(result["indices"]):
                if index in order:
                    raise ValueError("Duplicate canonical event in parallel source results")
                order[index] = slot, offset
        if sorted(order) != list(range(len(expected_indices))):
            raise ValueError("Parallel source results omit canonical events")
        combined: dict[str, Any] = {
            key: [results[order[index][0]][key][order[index][1]] for index in sorted(order)]
            for key in ("extractions", "tones", "metadata_rows", "audits")
        }
        combined["selected_filing_ids"] = set().union(
            *(result["selected_filing_ids"] for result in results.values())
        )
        return combined
    finally:
        _stop_processes(processes)
        messages.close()
        messages.join_thread()
