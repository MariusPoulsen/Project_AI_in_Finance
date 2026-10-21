"""Multi-agent layer v2 on the Decision 100 design candidates (DECISIONS 109).

``build`` writes one immutable case file per debated candidate and an inventory
that keeps every candidate in the denominator with its reason. ``run`` debates
the cases in a fixed target-blind order with durable call caps, pausing at
daily quotas and resuming where it stopped. ``status`` reports progress. No
label or return is read before ``evaluate``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import sys
import threading
import time
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from structural_break.agents import debate_v2 as dv
from structural_break.agents.budgets import BudgetPolicy, DurableAttemptJournal, ModelCap
from structural_break.agents.contracts import (
    AgentInput,
    DataGates,
    Lineage,
    QuantState,
    SourceChunk,
)
from structural_break.experiments import catalyst_coverage as cc
from structural_break.experiments import news_coverage as nc
from structural_break.experiments.p6_improvement import _sources
from structural_break.intelligence import catalyst_v3 as cv
from structural_break.intelligence.extraction import ProviderFailure

OUTPUT = Path("outputs/p6_agents")
NEWS = Path("outputs/news_v1")
SCORES = Path("outputs/p6_boosting2/scores.parquet")
BUDGET = BudgetPolicy(
    allocation_id="p6-agents-v2-decision-109",
    global_cap=9_200,
    model_caps=(
        ModelCap(model=dv.ADVOCATE_MODEL, total=6_000, daily=9_000),
        ModelCap(model=dv.SYNTHESIS_MODEL, total=1_600, daily=450),
        ModelCap(model=dv.VALIDATION_MODEL, total=1_600, daily=450),
    ),
)
MIN_INTERVAL = {dv.SYNTHESIS_MODEL: 5.0, dv.VALIDATION_MODEL: 5.0}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def design_candidates(workspace: Path) -> list[str]:
    """Decision 100 candidates: R0 top 20 % per test year after the r1, cross and cost filters."""
    from structural_break.experiments import p6_boosting as pb
    from structural_break.experiments import p6_quant_portfolio as qp

    frame, _ = pb.load_data(
        workspace, Path("outputs/p6_improvement/walkforward/simulation_frozen_exit.parquet")
    )
    year = pd.to_datetime(frame.set_index("event_id").event_date).dt.year
    scores = pd.read_parquet(SCORES)
    scores = scores[scores.variant.eq("R0_xgb_fixed")]
    r1 = set(pd.read_parquet("outputs/p6_quant/r1_events.parquet").event_id)
    cross = pd.read_parquet("outputs/p6_quant/features.parquet").set_index("event_id")[
        "state_days_since_zero_cross"
    ]
    costs = pd.read_parquet("outputs/p6_quant/cost_model_nets.parquet").set_index("event_id")
    rate = 2 * costs["rate_10m"]
    rate_year = year.reindex(rate.index)
    cost_cut = {y: np.nanquantile(rate[rate_year.eq(y - 1)], 0.8) for y in range(2010, 2024)}
    chosen: list[str] = []
    for y, group in scores.groupby("year"):
        cut = float(np.quantile(group.loc[group.role.eq("threshold"), "score"], 0.8))
        chosen += list(group[group.role.eq("test") & (group.score >= cut)].event_id)
    cache = qp.load_cache(Path("outputs/p6_quant/requests.pkl"))
    return [
        e
        for e in chosen
        if e not in r1
        and not (cross.get(e, 0) > 120)
        and not (rate.get(e, np.inf) >= cost_cut.get(year.get(e), np.inf))
        and e in cache
    ]


def _describe_news(known: bool, leg_key: Any, record: dict[str, Any] | None, pack: Any) -> str:
    if not known:
        return "coverage unknown"
    if not isinstance(leg_key, str):
        return "no 8-K in the last three sessions"
    if pack is None or not pack.get("chunks"):
        return "an 8-K was filed but its text could not be parsed"
    if record is None or record.get("status") == "UNKNOWN":
        return "8-K filed; the extraction model could not classify it"
    if record["status"] == "NONE":
        return "8-K filed; classified as routine with no material news"
    response = record["response"]
    return (
        f"8-K filed; classified as {response['event_type']}, {response['direction']}, "
        f"{response['materiality']} materiality"
    )


def build(workspace: Path, output: Path = OUTPUT) -> dict[str, Any]:
    candidates = design_candidates(workspace)
    version = _sources(workspace).binding.evaluation.version
    inputs = pd.read_parquet(workspace / "artifacts/research" / version / "model_inputs.parquet")
    inputs = inputs.set_index("event_id").loc[candidates]
    pairs = pd.read_parquet(workspace / "universe/source_v1/pair_universe.parquet").set_index("pair_id")
    master = pd.read_parquet(workspace / "universe/source_v1/security_master.parquet").set_index(
        "security_id"
    )
    scores = pd.read_parquet(SCORES)
    scores = scores[scores.variant.eq("R0_xgb_fixed") & scores.role.eq("test")].set_index("event_id")
    windows = pd.read_parquet(NEWS / "windows.parquet")
    windows = windows[windows.event_id.isin(candidates)].set_index(["event_id", "leg"])
    scores_sha = hashlib.sha256(SCORES.read_bytes()).hexdigest()
    (output / "cases").mkdir(parents=True, exist_ok=True)
    rows = []
    for event_id in candidates:
        row = inputs.loc[event_id]
        pair = pairs.loc[row["pair_id"]]
        legs = {"A": windows.loc[(event_id, "a")], "B": windows.loc[(event_id, "b")]}
        securities = {"A": pair["leg_a_security_id"], "B": pair["leg_b_security_id"]}
        companies = {
            leg: (str(master.loc[sec, "issuer_name"]), str(master.loc[sec, "ticker"]))
            for leg, sec in securities.items()
        }
        known = all(bool(w["known"]) for w in legs.values())
        packs, records, tones = {}, {}, {}
        for leg, w in legs.items():
            key = w["leg_key"]
            if isinstance(key, str):
                path = NEWS / "packs" / f"{key}.json"
                packs[leg] = json.loads(path.read_bytes())["pack"] if path.exists() else None
                records[leg] = cc.load_record(NEWS, key)
                tones[leg] = nc.load_tone(NEWS, key)
        with_text = [leg for leg, pack in packs.items() if pack and pack.get("chunks")]
        record = {"event_id": event_id, "year": int(pd.Timestamp(row["event_date"]).year)}
        if not known:
            rows.append(record | {"status": "UNKNOWN_COVERAGE"})
            continue
        if not with_text:
            reason = "NEWS_UNPARSEABLE" if packs else "NO_RECENT_NEWS"
            rows.append(record | {"status": reason})
            continue
        complete = all(pack is not None and pack.get("parse_complete") for pack in packs.values())
        stamp = pd.Timestamp(row["event_timestamp"]).to_pydatetime()
        evidence, described, timestamps_ok = [], {}, True
        for leg in ("A", "B"):
            for chunk in (packs.get(leg) or {}).get("chunks", []):
                text = dv.mask_text(chunk["chunk_text"], companies)
                accepted = pd.Timestamp(chunk["acceptance_datetime_utc"]).to_pydatetime()
                if accepted > stamp:
                    timestamps_ok = False
                    continue
                if len(text) > 8000 or sum(c.leg == leg for c in evidence) >= 8:
                    complete = False
                    continue
                evidence.append(
                    SourceChunk(
                        chunk_id=chunk["chunk_id"],
                        leg=leg,  # type: ignore[arg-type]
                        security_id=securities[leg],
                        filing_id=chunk["filing_id"],
                        # Hash of the masked text the agents read; the chunk ID links to the original.
                        document_sha256=hashlib.sha256(text.encode()).hexdigest(),
                        start_offset=0,
                        end_offset=len(text),
                        source_timestamp=accepted,
                        text=text,
                    )
                )
                label = chunk.get("section_label") or ""
                described[chunk["chunk_id"]] = f"{chunk['document_type']} {label}".strip()
        while sum(len(c.text) for c in evidence) > 32_000:
            evidence.pop()
            complete = False

        def finite(value: Any, positive: bool = False) -> float | None:
            if value is None or not np.isfinite(value) or (positive and value <= 0):
                return None
            return float(value)

        manifest = hashlib.sha256(
            json.dumps(sorted(c.document_sha256 for c in evidence)).encode()
        ).hexdigest()
        event = AgentInput(
            event_id=event_id,
            pair_id=str(row["pair_id"]),
            event_timestamp=stamp,
            leg_a_security_id=securities["A"],
            leg_b_security_id=securities["B"],
            pair_status="ACTIVE",
            quant=QuantState(
                model_b_probability=float(scores.loc[event_id, "score"]),
                z_score=finite(row["z_signed"]),
                half_life_sessions=finite(row["half_life"], positive=True),
                beta_drift=finite(abs(row["beta_drift_pct"])) if np.isfinite(row["beta_drift_pct"]) else None,
                cointegration_pvalue=finite(row["coint_pvalue"]),
            ),
            gates=DataGates(
                market_data_ok=True,
                model_inputs_ok=True,
                source_timestamps_ok=timestamps_ok,
                source_coverage="COMPLETE" if complete else "PARTIAL",
                liquidity_ok=True,
                implementation_ok=True,
            ),
            lineage=Lineage(
                registry_id="p6-decision-100-design",
                model_bundle_id="R0_xgb_fixed",
                model_version=scores_sha[:16],
                calibrator_version="raw-walk-forward-score",
                relationship_version=str(row["relationship_version"]),
                evidence_policy_version="sec-recent-news-v1+mask-v1",
                source_manifest_sha256=manifest,
            ),
            evidence=tuple(evidence),
        )

        def pct(value: Any) -> str:
            return f"{100 * value:+.1f} %" if value is not None and np.isfinite(value) else "unknown"

        def tone(leg: str) -> str:
            t = tones.get(leg)
            if not t or t.get("status") != "OK":
                return "not scored"
            return f"{t['positive'] - t['negative']:+.2f}"

        context = {
            "sub_industry": dv.mask_text(str(pair["sub_industry"]), companies),
            "rationale": dv.mask_text(str(pair["economic_rationale"]), companies),
            "legs": {
                leg: {
                    "abnormal_return": pct(row[f"abnormal_return_{leg}_1d"]),
                    "news": _describe_news(True, legs[leg]["leg_key"], records.get(leg), packs.get(leg)),
                    "tone": tone(leg) if leg in with_text else "no excerpts",
                }
                for leg in ("A", "B")
            },
            "chunks": described,
        }
        case = dv.Case(event, context)
        dv.render_case(case)  # fails here, not mid-run, if a prompt would carry outcomes
        dv.cv_write(output / "cases" / f"{event_id}.json", case.to_json())
        rows.append(
            record
            | {
                "status": "DEBATE",
                "coverage": event.gates.source_coverage,
                "chunks": len(evidence),
                "prompt_chars": len(dv.build_prompt("mean_reversion_opening", case, {})),
                "case_sha256": case.digest,
            }
        )
    inventory = pd.DataFrame(rows)
    inventory["order"] = inventory.event_id.map(cv.processing_order)
    inventory = inventory.sort_values("order").reset_index(drop=True)
    inventory.to_parquet(output / "inventory.parquet", index=False)
    return {
        "candidates": len(candidates),
        "by_status": inventory.status.value_counts().to_dict(),
        "debate_by_coverage": inventory.loc[inventory.status.eq("DEBATE"), "coverage"]
        .value_counts()
        .to_dict(),
        "opening_prompt_chars_median": float(inventory.prompt_chars.median()),
    }


# --------------------------------------------------------------------------- #
# Run
# --------------------------------------------------------------------------- #


def _result_path(output: Path, event_id: str) -> Path:
    return output / "results" / f"{event_id}.json"


def load_result(output: Path, event_id: str) -> dict[str, Any] | None:
    path = _result_path(output, event_id)
    return json.loads(path.read_bytes()) if path.exists() else None


def _state(output: Path, **fields: Any) -> None:
    path = output / "state.json"
    state = json.loads(path.read_bytes()) if path.exists() else {}
    state.update(fields, pid=os.getpid(), updated=_now())
    dv.cv_write(path, state)


def run(
    output: Path = OUTPUT,
    *,
    limit: int | None = None,
    workers: int = 3,
    say: Any = print,
    clients: dict[str, cv.ModelClient] | None = None,
    journal: DurableAttemptJournal | None = None,
    pause: Any = None,
    passes: int = 3,
    pass_delay: float = 600.0,
) -> Counter[str]:
    """Debate every scheduled case once (resumable); retry provider outages in later passes."""
    inventory = pd.read_parquet(output / "inventory.parquet")
    scheduled = list(inventory.loc[inventory.status.eq("DEBATE"), "event_id"])
    if limit is not None:
        scheduled = scheduled[:limit]
    own_journal = journal is None and clients is None
    if own_journal:
        journal = DurableAttemptJournal(output / "journal", BUDGET).__enter__()
    try:
        if clients is None:
            guard = dv.Guard(journal, MIN_INTERVAL)
            clients = dv.make_clients(cc._credential, guard)
        counts: Counter[str] = Counter()
        for number in range(passes + 1):
            todo = [e for e in scheduled if load_result(output, e) is None]
            if not todo:
                break
            if number:
                say(f"retry pass {number}: {len(todo)} events left after provider outages; waiting")
                time.sleep(pass_delay)
            counts += _pass(output, todo, clients, workers, say, journal, pause)
            if counts.get("STOPPED_BUDGET"):
                break
        _state(output, phase="finished" if not counts.get("STOPPED_BUDGET") else "budget-exhausted")
        return counts
    finally:
        if own_journal and journal is not None:
            journal.__exit__()


def _pass(
    output: Path,
    todo: Sequence[str],
    clients: dict[str, cv.ModelClient],
    workers: int,
    say: Any,
    journal: DurableAttemptJournal | None,
    pause: Any,
) -> Counter[str]:
    work: queue.Queue[str] = queue.Queue()
    for event_id in todo:
        work.put(event_id)
    counts: Counter[str] = Counter()
    lock = threading.Lock()
    stop = threading.Event()
    started = time.monotonic()
    say(f"{len(todo)} events to debate")
    _state(output, phase="running", queued=len(todo), paused_until=None)

    def sleep_until(moment: datetime) -> None:
        while not stop.is_set() and (left := (moment - datetime.now(UTC)).total_seconds()) > 0:
            time.sleep(min(left, 300))

    wait = pause or sleep_until

    def worker() -> None:
        while not stop.is_set():
            try:
                event_id = work.get_nowait()
            except queue.Empty:
                return
            case = dv.Case.from_json(json.loads((output / "cases" / f"{event_id}.json").read_bytes()))
            while not stop.is_set():
                try:
                    result = dv.run_debate(case, clients, output / "roles")
                    dv.cv_write(_result_path(output, event_id), result)
                    label = result["decision"]["status"]
                    break
                except dv.PauseRequired as error:
                    reset = cv.next_quota_reset()
                    say(f"{error}: daily quota reached; pausing until {reset.isoformat()}")
                    _state(output, paused_until=reset.isoformat())
                    wait(reset)
                    _state(output, paused_until=None)
                except cv.ProviderDown:
                    label = "PROVIDER_UNAVAILABLE"  # left without a result; a later pass retries
                    break
                except ProviderFailure as error:
                    if error.reason == "REQUEST_BUDGET_EXHAUSTED":
                        say("total call budget exhausted; stopping")
                        stop.set()
                        label = "STOPPED_BUDGET"
                        break
                    say(f"{event_id}: provider failure {error.reason}; left for a later pass")
                    label = "PROVIDER_FAILURE"
                    break
                except Exception as error:  # never let one event kill a worker silently
                    say(f"{event_id}: {type(error).__name__}; left for a later pass")
                    label = "ERROR"
                    break
            else:
                return
            with lock:
                counts[label] += 1
                done = sum(counts.values())
                if done % 10 == 0 or done == len(todo):
                    rate = done / max(time.monotonic() - started, 1) * 3600
                    http = {m: dict(c.statuses) for m, c in clients.items()}
                    used = journal.counts["by_model"] if journal is not None else {}
                    say(f"{done}/{len(todo)} events {dict(counts)}, {rate:.0f}/hour, http {http}, calls {used}")
                    _state(output, done_this_pass=done, rate_per_hour=round(rate))

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return counts


def status(output: Path = OUTPUT) -> str:
    inventory = pd.read_parquet(output / "inventory.parquet")
    debate = inventory.loc[inventory.status.eq("DEBATE"), "event_id"]
    decisions: Counter[str] = Counter()
    failures: Counter[str] = Counter()
    done = 0
    for event_id in debate:
        result = load_result(output, event_id)
        if result is None:
            continue
        done += 1
        decisions[result["decision"]["status"]] += 1
        for stage in result["stages"]:
            if stage["status"] != "VALID":
                failures[f"{stage['role']}:{stage.get('error')}"] += 1
    state_path = output / "state.json"
    state = json.loads(state_path.read_bytes()) if state_path.exists() else {}
    rate = state.get("rate_per_hour")
    left = len(debate) - done
    lines = [
        f"Debated: {done:,} / {len(debate):,} ({100 * done / max(len(debate), 1):.1f} %); "
        f"not debated: {inventory.status.ne('DEBATE').sum():,} {inventory.status.value_counts().drop('DEBATE', errors='ignore').to_dict()}",
        f"Controller: {dict(decisions)}",
        f"Failed roles: {dict(failures.most_common(8))}",
        f"Rate {rate or '-'} events/hour, ETA {f'{left / rate:.1f} h' if rate else 'unknown'} "
        f"(excluding quota pauses); state {state.get('phase', 'not started')}, "
        f"updated {state.get('updated', 'never')}, paused until {state.get('paused_until')}",
    ]
    journal = output / "journal" / "attempts"
    if journal.exists():
        counts: Counter[str] = Counter()
        today: Counter[str] = Counter()
        day = datetime.now(UTC).astimezone(cv._PACIFIC).date().isoformat()
        for path in journal.glob("*.json"):
            payload = json.loads(path.read_bytes())["payload"]
            counts[payload["model"]] += 1
            today[payload["model"]] += payload["provider_day"] == day
        lines.append(f"Calls charged: {dict(counts)}; today (Pacific {day}): {dict(today)}")
    log = output / "run.log"
    if log.exists():
        lines += ["Log:", *(f"  {line}" for line in log.read_text(errors="replace").splitlines()[-3:])]
    return "\n".join(lines)


def main(arguments: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build")
    b.add_argument("--workspace-root", type=Path, default=Path("data/team"))
    r = sub.add_parser("run")
    r.add_argument("--env-file", type=Path, required=True)
    r.add_argument("--limit", type=int)
    r.add_argument("--workers", type=int, default=3)
    sub.add_parser("status")
    args = parser.parse_args(arguments)

    def say(message: str) -> None:
        print(f"{_now()} {message}", flush=True)

    if args.command == "build":
        say(json.dumps(build(args.workspace_root), default=str))
    elif args.command == "run":
        cc.load_env_file(args.env_file)
        if not cc._credential():
            sys.exit("No API key in the environment")
        say(f"finished: {dict(run(limit=args.limit, workers=args.workers, say=say))}")
    else:
        print(status())


if __name__ == "__main__":
    main()
