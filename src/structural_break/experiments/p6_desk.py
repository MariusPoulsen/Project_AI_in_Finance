"""Pairs desk v3 experiment (DECISIONS 110): build, run, status, evaluate.

``build-entry`` writes a case for every top-40 % test event with fresh news
(FNSPID headlines and/or 8-K excerpts) and an inventory for all region events.
``build-monitor`` writes one check per design trade and session with new company
headlines while the trade is open. ``run`` scores them with the desk under
durable caps (resumable). ``evaluate`` runs the pre-registered tuning grid on
2010-2017 and opens 2018-2023 once.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import queue
import sys
import threading
import time
from collections import Counter
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from structural_break.agents import debate_v2 as dv
from structural_break.agents import desk_v3 as dk
from structural_break.agents.budgets import BudgetPolicy, DurableAttemptJournal, ModelCap
from structural_break.agents.contracts import AgentInput, DataGates, Lineage, QuantState, SourceChunk
from structural_break.experiments import catalyst_coverage as cc
from structural_break.experiments import news_coverage as nc
from structural_break.experiments import p6_agents as pa
from structural_break.experiments.p6_improvement import _sources
from structural_break.intelligence import catalyst_v3 as cv

OUTPUT = Path("outputs/p6_desk")
HEADLINES = Path("data/external/fnspid/headlines.parquet")
MAX_HEADLINES = 12
# Decision 110b: the book can select with the original Model B (R0) or the best forecaster.
SELECTORS = ("R0", "B+rule+ou__recent-bag5")
# Goal 1 bases for the agent features: R0, the pre-registered best forecaster (verdict), +track (reported).
BASES = {"R0": None, "B+rule+ou": "B+rule+ou__recent-bag5", "B+rule+ou+track": "B+rule+ou+track__recent-bag5"}
# Decision 112b: the adopted exit. Take profit |z| <= 1.0, no disaster stop, news exit, and a time
# stop of clip(ceil(1.5 x half-life), 10, 40) sessions (20 when the half-life is unknown).
LONG_CACHE = Path("outputs/p6_quant/requests_long.pkl")
TAKE_PROFIT, NO_STOP, HALF_LIFE_MULTIPLE = 1.0, 99.0, 1.5


def time_stops(workspace: Path) -> dict[str, int]:
    version = _sources(workspace).binding.evaluation.version
    hl = pd.read_parquet(workspace / "artifacts/research" / version / "model_inputs.parquet",
                         columns=["event_id", "half_life"]).set_index("event_id")["half_life"]
    return {e: int(min(max(np.ceil(HALF_LIFE_MULTIPLE * h), 10), 40)) if np.isfinite(h) and h > 0 else 20
            for e, h in hl.items()}


def design_trades(
    workspace: Path,
    selector: str = "R0",
    chosen_events: list[str] | None = None,
    fractions: dict[str, float] | None = None,
    exclude: set[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """The design under the adopted exit: (allocations, trade results, long-path cache)."""
    from structural_break.experiments import p6_quant_costs as qc
    from structural_break.experiments import p6_quant_portfolio as qp

    cache = qp.load_cache(LONG_CACHE)
    chosen = [e for e in pa.design_candidates(workspace, selector, chosen_events) if e not in (exclude or set())]
    sectors = _sources(workspace).security_sectors()
    prices = pd.read_parquet(workspace / "market/source_v1/prices.parquet",
                             columns=["ticker", "trading_date", "open", "high", "low", "close", "adj_close", "volume"])
    stops = time_stops(workspace)
    design = qp.run_design(cache, chosen, (TAKE_PROFIT, NO_STOP, {e: stops.get(e, 20) for e in chosen}, True),
                           Path("configs"), 0.075, sectors, qc.lookup(qc.stock_inputs(prices)), 1e7,
                           fractions=fractions or None)
    return design["allocations"], design["results"], cache
BUDGET = BudgetPolicy(
    allocation_id="p6-desk-v3-decision-110",
    global_cap=40_000,
    model_caps=(
        ModelCap(model=dv.ADVOCATE_MODEL, total=36_000, daily=9_000),
        ModelCap(model=dv.SYNTHESIS_MODEL, total=10, daily=10),
        ModelCap(model=dv.VALIDATION_MODEL, total=3_000, daily=450),
    ),
)


# Decision 112b: the longer holding window raises the monitor to about 21,000 checks, so the
# monitor run has its own journal; the entry journal's identity and caps stay unchanged.
MONITOR_BUDGET = BudgetPolicy(
    allocation_id="p6-desk-v3-monitor-decision-112b",
    global_cap=30_000,
    model_caps=(
        ModelCap(model=dv.ADVOCATE_MODEL, total=30_000, daily=9_000),
        ModelCap(model=dv.SYNTHESIS_MODEL, total=0, daily=0),
        ModelCap(model=dv.VALIDATION_MODEL, total=0, daily=0),
    ),
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _pct(value: Any) -> str:
    return f"{100 * value:+.1f} %" if value is not None and np.isfinite(value) else "unknown"


def _chunk(chunk_id: str, leg: str, security: str, filing: str, stamp: Any, text: str) -> SourceChunk:
    return SourceChunk(
        chunk_id=chunk_id,
        leg=leg,  # type: ignore[arg-type]
        security_id=security,
        filing_id=filing,
        document_sha256=hashlib.sha256(text.encode()).hexdigest(),
        start_offset=0,
        end_offset=len(text),
        source_timestamp=stamp,
        text=text,
    )


def _headline_text(rows: pd.DataFrame, companies: dict[str, tuple[str, str]]) -> str:
    lines = []
    for row in rows.tail(MAX_HEADLINES).itertuples(index=False):
        line = f"{pd.Timestamp(row.session).date().isoformat()} headline: {row.title.strip()}"
        if isinstance(row.summary, str) and row.summary.strip():
            line += f". Summary: {row.summary.strip()}"
        lines.append(dv.mask_text(line, companies))
    return "\n".join(lines)


class Sources:
    """Shared inputs for entry and monitor cases (all read-only, point in time)."""

    def __init__(self, workspace: Path) -> None:
        version = _sources(workspace).binding.evaluation.version
        self.inputs = pd.read_parquet(workspace / "artifacts/research" / version / "model_inputs.parquet").set_index("event_id")
        self.pairs = pd.read_parquet(workspace / "universe/source_v1/pair_universe.parquet").set_index("pair_id")
        self.master = pd.read_parquet(workspace / "universe/source_v1/security_master.parquet").set_index("security_id")
        scores = pd.read_parquet(pa.SCORES)
        self.scores = scores[scores.variant.eq("R0_xgb_fixed")]
        self.headlines = pd.read_parquet(HEADLINES)
        self.headlines = self.headlines[self.headlines.specific & self.headlines.session.notna()]
        self.by_security = {s: g.sort_values(["session", "stamp"]) for s, g in self.headlines.groupby("security_id")}
        prices = pd.read_parquet(workspace / "market/source_v1/prices.parquet", columns=["trading_date"])
        self.sessions = pd.DatetimeIndex(sorted(pd.to_datetime(prices["trading_date"].unique())))
        self.windows = pd.read_parquet(pa.NEWS / "windows.parquet").set_index(["event_id", "leg"])

    def companies(self, pair_id: str) -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
        pair = self.pairs.loc[pair_id]
        securities = {"A": pair["leg_a_security_id"], "B": pair["leg_b_security_id"]}
        companies = {
            leg: (str(self.master.loc[s, "issuer_name"]), str(self.master.loc[s, "ticker"])) for leg, s in securities.items()
        }
        return securities, companies

    def headlines_between(self, security: str, first: pd.Timestamp, last: pd.Timestamp) -> pd.DataFrame:
        group = self.by_security.get(security)
        if group is None:
            return self.headlines.iloc[0:0]
        return group[group.session.between(first, last)]


def region_events(src: Sources) -> pd.DataFrame:
    """Top-40 % test events per year by the R0 threshold-role scores (the learning region)."""
    rows = []
    for year, group in src.scores.groupby("year"):
        cut = float(np.quantile(group.loc[group.role.eq("threshold"), "score"], 0.6))
        test = group[group.role.eq("test") & (group.score >= cut)]
        rows.append(test.loc[:, ["event_id", "score", "year"]])
    return pd.concat(rows, ignore_index=True)


def build_entry(workspace: Path, output: Path = OUTPUT) -> dict[str, Any]:
    src = Sources(workspace)
    region = region_events(src)
    candidates: set[str] = set()
    for selector in SELECTORS:
        candidates |= set(pa.design_candidates(workspace, selector))
    test = src.scores[src.scores.role.eq("test")].set_index("event_id")
    extra = sorted(candidates - set(region.event_id))
    region = pd.concat(
        [region, pd.DataFrame({"event_id": extra, "score": test.loc[extra, "score"].to_numpy(),
                               "year": test.loc[extra, "year"].to_numpy()})],
        ignore_index=True,
    )
    (output / "entry_cases").mkdir(parents=True, exist_ok=True)
    rows = []
    for event in region.itertuples(index=False):
        row = src.inputs.loc[event.event_id]
        securities, companies = src.companies(row["pair_id"])
        signal = pd.Timestamp(row["event_date"]).normalize()
        position = src.sessions.searchsorted(signal)
        first = src.sessions[max(position - 2, 0)]
        stamp = pd.Timestamp(row["event_timestamp"]).to_pydatetime()
        evidence, described, counts = [], {}, {}
        packs = {}
        for leg in ("A", "B"):
            w = src.windows.loc[(event.event_id, leg.lower())] if (event.event_id, leg.lower()) in src.windows.index else None
            key = None if w is None else w["leg_key"]
            if isinstance(key, str):
                path = pa.NEWS / "packs" / f"{key}.json"
                packs[leg] = (json.loads(path.read_bytes())["pack"] if path.exists() else None, key)
            heads = src.headlines_between(securities[leg], first, signal)
            counts[leg] = int(len(heads))
            if len(heads):
                text = _headline_text(heads, companies)
                cid = f"headlines:{event.event_id}:{leg}"
                evidence.append(_chunk(cid, leg, securities[leg], dk.HEADLINE_FILING, stamp, text))
                described[cid] = "news headlines (FNSPID), last three sessions"
            pack = packs.get(leg, (None, None))[0]
            for chunk in (pack or {}).get("chunks", [])[:3]:
                accepted = pd.Timestamp(chunk["acceptance_datetime_utc"]).to_pydatetime()
                if accepted > stamp:
                    continue
                text = dv.mask_text(chunk["chunk_text"], companies)[:4000]
                evidence.append(_chunk(chunk["chunk_id"], leg, securities[leg], chunk["filing_id"], accepted, text))
                described[chunk["chunk_id"]] = f"{chunk['document_type']} {chunk.get('section_label') or ''}".strip()
        has_news = bool(evidence)
        record = {
            "event_id": event.event_id,
            "year": int(event.year),
            "score": float(event.score),
            "candidate": event.event_id in candidates,
            "headlines_a": counts["A"],
            "headlines_b": counts["B"],
            "eight_k": any(p[0] and p[0].get("chunks") for p in packs.values()),
        }
        if not has_news:
            rows.append(record | {"status": "NO_NEWS"})
            continue
        while sum(len(c.text) for c in evidence) > 29_000:
            evidence.pop()
        for leg in ("B", "A"):
            label = None
            if leg in packs:
                label = pa._describe_news(True, packs[leg][1], cc.load_record(pa.NEWS, packs[leg][1]), packs[leg][0])
            tone = nc.load_tone(pa.NEWS, packs[leg][1]) if leg in packs else None
            tone_text = f"{tone['positive'] - tone['negative']:+.2f}" if tone and tone.get("status") == "OK" else "not available"
            text = "\n".join(
                [
                    f"Company {leg}'s 1-day abnormal return at the signal was {_pct(row[f'abnormal_return_{leg}_1d'])}.",
                    f"Company {leg} had {counts[leg]} company headlines in the last three sessions.",
                    f"Company {leg}'s recent 8-K news was {(label or 'no 8-K in the last three sessions').replace(';', ',')}.",
                    f"FinBERT net tone of Company {leg}'s 8-K excerpts was {tone_text}.",
                ]
            )
            evidence.insert(0, _chunk(f"context:{event.event_id}:{leg}", leg, securities[leg], dv.CONTEXT_FILING, stamp, text))

        def finite(value: Any, positive: bool = False) -> float | None:
            if value is None or not np.isfinite(value) or (positive and value <= 0):
                return None
            return float(value)

        case = dv.Case(
            AgentInput(
                event_id=event.event_id,
                pair_id=str(row["pair_id"]),
                event_timestamp=stamp,
                leg_a_security_id=securities["A"],
                leg_b_security_id=securities["B"],
                pair_status="ACTIVE",
                quant=QuantState(
                    model_b_probability=float(event.score),
                    z_score=finite(row["z_signed"]),
                    half_life_sessions=finite(row["half_life"], positive=True),
                    beta_drift=finite(abs(row["beta_drift_pct"])) if np.isfinite(row["beta_drift_pct"]) else None,
                    cointegration_pvalue=finite(row["coint_pvalue"]),
                ),
                gates=DataGates(
                    market_data_ok=True, model_inputs_ok=True, source_timestamps_ok=True,
                    source_coverage="PARTIAL", liquidity_ok=True, implementation_ok=True,
                ),
                lineage=Lineage(
                    registry_id="p6-decision-110-desk", model_bundle_id="R0_xgb_fixed", model_version="walk-forward",
                    calibrator_version="raw-walk-forward-score", relationship_version=str(row["relationship_version"]),
                    evidence_policy_version="fnspid-headlines-v1+sec-recent-news-v1+mask-v1",
                    source_manifest_sha256=hashlib.sha256(json.dumps(sorted(c.document_sha256 for c in evidence)).encode()).hexdigest(),
                ),
                evidence=tuple(evidence),
            ),
            {
                "sub_industry": dv.mask_text(str(src.pairs.loc[row["pair_id"], "sub_industry"]), companies),
                "rationale": dv.mask_text(str(src.pairs.loc[row["pair_id"], "economic_rationale"]), companies),
                "chunks": described,
                "signal_line": (
                    f"SIGNAL: the pair's price spread diverged at the close of {signal.date().isoformat()}; "
                    "a statistical-arbitrage model ranks this divergence among the top 40 % of its year "
                    "as a mean-reversion candidate."
                ),
            },
        )
        dv.cv_write(output / "entry_cases" / f"{event.event_id}.json", case.to_json())
        rows.append(record | {"status": "CASE", "prompt_chars": len(dk.analyst_prompt(case))})
    inventory = pd.DataFrame(rows)
    inventory["order"] = inventory.event_id.map(cv.processing_order)
    inventory = inventory.sort_values(["candidate", "order"], ascending=[False, True]).reset_index(drop=True)
    inventory.to_parquet(output / "entry_inventory.parquet", index=False)
    return {
        "region_events": len(inventory),
        "with_case": int(inventory.status.eq("CASE").sum()),
        "candidates_with_case": int((inventory.status.eq("CASE") & inventory.candidate).sum()),
        "by_year_case_share": inventory.groupby("year")["status"].apply(lambda s: round(float(s.eq("CASE").mean()), 3)).to_dict(),
        "prompt_chars_median": float(inventory.prompt_chars.median()),
    }


def build_monitor(workspace: Path, output: Path = OUTPUT) -> dict[str, Any]:
    """One check per open design trade and session with new company headlines."""
    from structural_break.experiments import p6_quant_portfolio as qp

    src = Sources(workspace)
    results: dict[str, Any] = {}
    stops = time_stops(workspace)
    for selector in SELECTORS:  # trades of either selection; the same event gives the same trade
        _, trades, cache = design_trades(workspace, selector)
        results.update(trades)
    (output / "monitor_cases").mkdir(parents=True, exist_ok=True)
    rows = []
    for event_id, result in results.items():
        if result.exit is None or result.position is None:
            continue
        request = cache[event_id][0]
        row = src.inputs.loc[event_id]
        securities, companies = src.companies(request.pair_id)
        days = [x.session_date for x in request.sessions]
        trigger = days[days.index(result.exit.session_date) - 1]
        closes = {p.session_date: (p.close_a, p.close_b) for p in request.prices}
        entry_close = closes[days[0]]
        position = result.position
        long_leg = "A" if position.weight_a > 0 else "B"
        for k, day in enumerate(days[1 : days.index(trigger) + 1], start=1):
            stamp_day = pd.Timestamp(day)
            heads = {leg: src.headlines_between(securities[leg], stamp_day, stamp_day) for leg in ("A", "B")}
            if not any(len(h) for h in heads.values()):
                continue
            session = request.sessions[days.index(day)]
            stamp = session.close_at
            ca, cb = closes[day]
            pnl = position.weight_a * (ca / entry_close[0] - 1) + position.weight_b * (cb / entry_close[1] - 1)
            check_id = f"{event_id}:{day.isoformat()}"
            evidence = []
            for leg in ("A", "B"):
                if len(heads[leg]):
                    cid = f"headlines:{check_id}:{leg}"
                    evidence.append(_chunk(cid, leg, securities[leg], dk.HEADLINE_FILING, stamp, _headline_text(heads[leg], companies)))
            short_leg = "B" if long_leg == "A" else "A"
            z_now = request.snapshot.z(ca, cb)
            context = "\n".join(
                [
                    f"The position is long Company {long_leg} and short Company {short_leg}, betting that the spread converges.",
                    f"It was entered at the close {k} sessions ago at a spread z-score of {request.signal_z:.2f}.",
                    f"The spread z-score at this close is {z_now:.2f}.",
                    "The desk's fixed exits are take profit at absolute z of 1.0 or less and a time stop after "
                    f"{stops.get(event_id, 20)} sessions ({max(stops.get(event_id, 20) - k, 0)} sessions left); "
                    "there is no stop-loss on the z-score.",
                    f"Its profit or loss since entry is {_pct(pnl)} of gross exposure.",
                    f"Company A moved {_pct(ca / entry_close[0] - 1)} and Company B moved {_pct(cb / entry_close[1] - 1)} since entry.",
                ]
            )
            evidence.insert(0, _chunk(f"context:{check_id}:A", "A", securities["A"], dv.CONTEXT_FILING, stamp, context))
            case = dv.Case(
                AgentInput(
                    event_id=check_id[:200],
                    pair_id=request.pair_id,
                    event_timestamp=stamp,
                    leg_a_security_id=securities["A"],
                    leg_b_security_id=securities["B"],
                    pair_status="ACTIVE",
                    quant=QuantState(model_b_probability=None, z_score=float(request.signal_z)),
                    gates=DataGates(
                        market_data_ok=True, model_inputs_ok=True, source_timestamps_ok=True,
                        source_coverage="PARTIAL", liquidity_ok=True, implementation_ok=True,
                    ),
                    lineage=Lineage(
                        registry_id="p6-decision-110-monitor", model_bundle_id="R0_xgb_fixed", model_version="walk-forward",
                        calibrator_version="none", relationship_version=str(row["relationship_version"]),
                        evidence_policy_version="fnspid-headlines-v1+mask-v1",
                        source_manifest_sha256=hashlib.sha256(json.dumps(sorted(c.document_sha256 for c in evidence)).encode()).hexdigest(),
                    ),
                    evidence=tuple(evidence),
                ),
                {
                    "sub_industry": dv.mask_text(str(src.pairs.loc[request.pair_id, "sub_industry"]), companies),
                    "rationale": dv.mask_text(str(src.pairs.loc[request.pair_id, "economic_rationale"]), companies),
                    "chunks": {c.chunk_id: "news headlines (FNSPID), this session" for c in evidence if c.filing_id == dk.HEADLINE_FILING},
                    "signal_line": (
                        f"CHECK: an open pairs position on {day.isoformat()}, {k} sessions after entry. "
                        "New company headlines became available at this close (A0 describes the position)."
                    ),
                },
            )
            name = hashlib.sha256(check_id.encode()).hexdigest()[:40]
            dv.cv_write(output / "monitor_cases" / f"{name}.json", case.to_json())
            rows.append({"check_id": check_id, "file": name, "event_id": event_id, "session": pd.Timestamp(day),
                         "held": k, "year": pd.Timestamp(day).year})
    inventory = pd.DataFrame(rows)
    inventory["order"] = inventory.check_id.map(cv.processing_order)
    inventory = inventory.sort_values("order").reset_index(drop=True)
    inventory.to_parquet(output / "monitor_inventory.parquet", index=False)
    return {"checks": len(inventory), "trades_with_checks": int(inventory.event_id.nunique()), "trades": len(results),
            "by_year": inventory.groupby("year").size().to_dict()}


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #


def _result_path(output: Path, kind: str, name: str) -> Path:
    return output / f"{kind}_results" / f"{name}.json"


def load_result(output: Path, kind: str, name: str) -> dict[str, Any] | None:
    path = _result_path(output, kind, name)
    if not path.exists():
        return None
    result = json.loads(path.read_bytes())
    version = dk.MONITOR_PROMPT_VERSION if kind == "monitor" else dk.PROMPT_VERSION
    return result if result.get("prompt_version") == version else None


def run(
    output: Path = OUTPUT,
    *,
    kind: str = "entry",
    limit: int | None = None,
    workers: int = 4,
    say: Callable[[str], None] = print,
    clients: dict[str, cv.ModelClient] | None = None,
    journal: DurableAttemptJournal | None = None,
    passes: int = 3,
    pass_delay: float = 600.0,
) -> Counter[str]:
    """Score every case of ``kind`` once (resumable); outages are retried in later passes."""
    if kind == "entry":
        inv = pd.read_parquet(output / "entry_inventory.parquet")
        names = list(inv.loc[inv.status.eq("CASE"), "event_id"])
        candidates = set(inv.loc[inv.candidate, "event_id"])
        case_dir = output / "entry_cases"
    else:
        inv = pd.read_parquet(output / "monitor_inventory.parquet")
        names, candidates, case_dir = list(inv["file"]), set(), output / "monitor_cases"
    if limit is not None:
        names = names[:limit]
    own = journal is None and clients is None
    if own:
        journal = (
            DurableAttemptJournal(output / "journal", BUDGET)
            if kind == "entry"
            else DurableAttemptJournal(output / "journal_monitor", MONITOR_BUDGET)
        ).__enter__()
    try:
        if clients is None:
            clients = dv.make_clients(cc._credential, dv.Guard(journal, {dv.VALIDATION_MODEL: 5.0}))
        counts: Counter[str] = Counter()
        for number in range(passes + 1):
            todo = [n for n in names if load_result(output, kind, n) is None]
            if not todo:
                break
            if number:
                say(f"retry pass {number}: {len(todo)} left after outages; waiting")
                time.sleep(pass_delay)

            def task(name: str) -> dict[str, Any]:
                case = dv.Case.from_json(json.loads((case_dir / f"{name}.json").read_bytes()))
                if kind == "entry":
                    candidate = name in candidates
                    return dk.run_entry(case, clients, output / "roles", debate=candidate, judge=candidate)
                return dk.run_monitor(case, clients, output / "roles")

            counts += _pass(output, kind, todo, task, clients, workers, say, journal)
            if counts.get("STOPPED_BUDGET"):
                break
        return counts
    finally:
        if own and journal is not None:
            journal.__exit__()


def _pass(output, kind, todo, task, clients, workers, say, journal) -> Counter[str]:  # type: ignore[no-untyped-def]
    work: queue.Queue[str] = queue.Queue()
    for name in todo:
        work.put(name)
    counts: Counter[str] = Counter()
    lock, stop, started = threading.Lock(), threading.Event(), time.monotonic()
    say(f"{len(todo)} {kind} cases to score")

    def worker() -> None:
        while not stop.is_set():
            try:
                name = work.get_nowait()
            except queue.Empty:
                return
            while True:
                try:
                    result = task(name)
                    dv.cv_write(_result_path(output, kind, name), result)
                    label = result["status"]
                    break
                except dv.PauseRequired as error:
                    reset = cv.next_quota_reset()
                    say(f"{error}: daily quota reached; pausing until {reset.isoformat()}")
                    while (left := (reset - datetime.now(UTC)).total_seconds()) > 0 and not stop.is_set():
                        time.sleep(min(left, 300))
                except cv.ProviderDown:
                    label = "PROVIDER_UNAVAILABLE"
                    break
                except Exception as error:  # noqa: BLE001 - one case never kills a worker
                    reason = getattr(error, "reason", type(error).__name__)
                    if reason == "REQUEST_BUDGET_EXHAUSTED":
                        say("total call budget exhausted; stopping")
                        stop.set()
                        label = "STOPPED_BUDGET"
                    else:
                        say(f"{name}: {reason}; left for a later pass")
                        label = "ERROR"
                    break
            with lock:
                counts[label] += 1
                done = sum(counts.values())
                if done % 25 == 0 or done == len(todo):
                    rate = done / max(time.monotonic() - started, 1) * 3600
                    used = journal.counts["by_model"] if journal is not None else {}
                    say(f"{done}/{len(todo)} {kind} {dict(counts)}, {rate:.0f}/hour, calls {used}")

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return counts


def status(output: Path = OUTPUT) -> str:
    lines = []
    for kind, column in (("entry", "event_id"), ("monitor", "file")):
        path = output / f"{kind}_inventory.parquet"
        if not path.exists():
            continue
        inv = pd.read_parquet(path)
        names = inv.loc[inv.status.eq("CASE"), column] if kind == "entry" else inv[column]
        statuses: Counter[str] = Counter()
        for name in names:
            result = load_result(output, kind, name)
            statuses[result["status"] if result else "PENDING"] += 1
        lines.append(f"{kind}: {dict(statuses)} of {len(names)}")
    log = output / "run.log"
    if log.exists():
        lines += [f"  {line}" for line in log.read_text(errors="replace").splitlines()[-3:]]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Evaluation and tuning (labels are read only here)
# --------------------------------------------------------------------------- #

ENTRY_GRID = [(None, False), (None, True)] + [(q, s) for q in (0.1, 0.2, 0.3) for s in (False, True)]
MONITOR_GRID = [None, (3, 3), (4, 3), (4, 4), (5, 4), (5, 5)]
FEATURES = ("no_news", "abstain", "explains_move", "persistence", "relationship_change", "persistence_x_explains")


def entry_features(output: Path, variant: str) -> pd.DataFrame:
    """Region events with agent features; ``variant`` "analyst" (B') or "desk" (C, debate where run)."""
    inv = pd.read_parquet(output / "entry_inventory.parquet")
    rows = []
    for record in inv.to_dict("records"):
        values = dict.fromkeys(FEATURES, 0.0)
        if record["status"] == "NO_NEWS":
            values["no_news"] = 1.0
        else:
            result = load_result(output, "entry", record["event_id"])
            scores = None
            if result is not None:
                scores = result["analyst_scores"] if variant == "analyst" else result["scores"]
            if scores is None:
                values["abstain"] = 1.0
            else:
                for name in ("explains_move", "persistence", "relationship_change"):
                    values[name] = float(scores[name])
                values["persistence_x_explains"] = values["persistence"] * values["explains_move"]
        rows.append({"event_id": record["event_id"], "year": record["year"], "score": record["score"],
                     "candidate": record["candidate"], **values})
    return pd.DataFrame(rows)


def base_scores(base: str | None, events: pd.Series, r0: pd.Series) -> np.ndarray:
    """The base forecaster's probability per event: R0's raw score or a stored bag5 probability."""
    if base is None:
        return r0.to_numpy(float)
    stored = pd.read_parquet(f"outputs/p6_quant/scores__{base}.parquet").set_index("event_id")["probability"]
    return stored.reindex(events).to_numpy(float)


def walk_forward(table: pd.DataFrame, with_agents: bool, column: str = "score") -> pd.Series:
    from sklearn.linear_model import LogisticRegression

    score = np.clip(table[column].to_numpy(float), 1e-6, 1 - 1e-6)
    columns = [np.log(score / (1 - score))]
    if with_agents:
        columns += [table[name].to_numpy(float) for name in FEATURES]
    x, y = np.column_stack(columns), table["y"].to_numpy(int)
    out = pd.Series(np.nan, index=table.index)
    for year in sorted(table.year.unique()):
        train = (table.year < year).to_numpy()
        if train.sum() < 200 or len(set(y[train])) < 2:
            continue
        test = (table.year == year).to_numpy()
        mean, std = x[train].mean(0), x[train].std(0) + 1e-9
        model = LogisticRegression(C=1.0, max_iter=2000).fit((x[train] - mean) / std, y[train])
        out[test] = model.predict_proba((x[test] - mean) / std)[:, 1]
    return out


def _metrics(y: pd.Series, p: pd.Series) -> dict[str, float]:
    from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

    return {"auc": float(roc_auc_score(y, p)), "log_loss": float(log_loss(y, p)), "brier": float(brier_score_loss(y, p)), "n": int(len(y))}


def _block_bootstrap(diff: pd.Series, months: pd.Series, seed: int = 5557) -> list[float]:
    rng = np.random.default_rng(seed)
    groups = {m: diff[months == m].to_numpy() for m in months.unique()}
    keys = np.array(list(groups))
    draws = [np.concatenate([groups[k] for k in rng.choice(keys, len(keys))]).mean() for _ in range(2000)]
    return [float(np.quantile(draws, 0.025)), float(np.quantile(draws, 0.975))]


def desk_book(
    workspace: Path,
    fractions: dict[str, float],
    exclude: set[str],
    exits: dict[str, Any],
    selector: str = "R0",
    chosen_events: list[str] | None = None,
) -> list[Any]:
    """Close-timing legs of the design under the adopted exit (Decision 112b), with per-event
    sizes, vetoes and earlier monitor exits."""
    from structural_break.experiments import p6_resid as pr

    allocations, results, cache = design_trades(workspace, selector, chosen_events, fractions, exclude)
    legs = []
    for event_id, fraction in allocations.items():
        result = results[event_id]
        if result.exit is None:
            continue
        request = cache[event_id][0]
        days = [x.session_date for x in request.sessions]
        trigger = days[days.index(result.exit.session_date) - 1]
        if event_id in exits and exits[event_id] < trigger:
            trigger = exits[event_id]
        for ticker, units, price in ((request.leg_a, result.position.units_a, result.entry.price_a),
                                     (request.leg_b, result.position.units_b, result.entry.price_b)):
            legs.append(pr.Leg(str(ticker), pd.Timestamp(days[0]), pd.Timestamp(trigger), fraction * units * price))
    return legs


def evaluate(workspace: Path = Path("data/team"), output: Path = OUTPUT, holdout: bool = False) -> dict[str, Any]:
    """Decision 110/110b. Goal 1: agent features on three base forecasters (verdict on B+rule+ou,
    desk variant). Goal 2: for each selection, the entry grid and then the monitor grid; the
    highest 2010-2017 Sharpe wins; 2018-2023 is opened once."""
    from structural_break.experiments import p6_resid as pr

    src_inputs = pd.read_parquet(
        workspace / "artifacts/research" / _sources(workspace).binding.evaluation.version / "model_inputs.parquet",
        columns=["event_id", "y_revert_success", "event_date"],
    ).set_index("event_id")
    spans = [("2011-2017", (2011, 2017))] + ([("2018-2023", (2018, 2023))] if holdout else [])
    report: dict[str, Any] = {"forecast": {}}
    tables: dict[tuple[str, str], pd.DataFrame] = {}
    for variant in ("analyst", "desk"):
        raw = entry_features(output, variant)
        raw["y"] = src_inputs.loc[raw.event_id, "y_revert_success"].to_numpy()
        raw["month"] = pd.to_datetime(src_inputs.loc[raw.event_id, "event_date"]).dt.to_period("M").astype(str).to_numpy()
        raw = raw.dropna(subset=["y"]).reset_index(drop=True)
        raw["y"] = raw.y.astype(int)
        for base_name, base in BASES.items():
            table = raw.assign(base_score=base_scores(base, raw.event_id, raw.score)).dropna(subset=["base_score"])
            table = table.reset_index(drop=True)
            table["p_base"] = walk_forward(table, False, "base_score")
            table["p_agent"] = walk_forward(table, True, "base_score")
            tables[(variant, base_name)] = table
            scored = table.dropna(subset=["p_base", "p_agent"])
            out = {}
            for label, (a, b) in spans:
                part = scored[scored.year.between(a, b)]
                diff = (part.p_agent - part.y) ** 2 - (part.p_base - part.y) ** 2
                interval = _block_bootstrap(diff, part.month)
                cand = part[part.candidate]
                out[label] = {
                    "base": _metrics(part.y, part.p_base),
                    "agents": _metrics(part.y, part.p_agent),
                    "brier_difference": float(diff.mean()),
                    "brier_95": interval,
                    "passes": bool(interval[1] < 0),
                    "candidates": {"base": _metrics(cand.y, cand.p_base), "agents": _metrics(cand.y, cand.p_agent)},
                }
            report["forecast"][f"{variant}|{base_name}"] = out
    report["goal1_verdict"] = report["forecast"]["desk|B+rule+ou"]["2011-2017"]["passes"]

    sectors = _sources(workspace).security_sectors()
    prices = pd.read_parquet(workspace / "market/source_v1/prices.parquet",
                             columns=["ticker", "trading_date", "open", "high", "low", "close", "adj_close", "volume"])
    panels = pr.load_panels(prices, sectors)
    rf = pr.tbill(Path("data/external/irx_13w_tbill.csv"))
    w = np.load("outputs/p6_quant/stage_q/targets_pca_continuous.npy") * 0.25

    def book(legs: list[Any]) -> pd.DataFrame:
        return pr.run_book(panels, w, legs, pd.Timestamp("2010-01-01"), pd.Timestamp("2023-12-31"), capital=1e7, rf=rf,
                           speed=0.10, vol_target=0.04, vol_window=60, timing="close", max_gross=2.0)

    monitor_rows = []
    if (output / "monitor_inventory.parquet").exists():
        for record in pd.read_parquet(output / "monitor_inventory.parquet").to_dict("records"):
            result = load_result(output, "monitor", record["file"])
            if result and result["scores"]:
                monitor_rows.append({**record, **{k: result["scores"][k] for k in ("adverse", "persistence")}})
    checks = pd.DataFrame(monitor_rows)
    base_for = {"R0": "R0", "B+rule+ou__recent-bag5": "B+rule+ou"}
    trials, books = [], {}
    for selector in SELECTORS:
        table = tables[("desk", base_for[selector])].set_index("event_id")
        members = set(pa.design_candidates(workspace, selector))
        cands = table[table.index.isin(members)].copy()
        cands["ratio"] = (cands.p_agent / cands.p_base).fillna(1.0)

        def entry_rule(q: float | None, size: bool) -> tuple[dict[str, float], set[str]]:
            exclude: set[str] = set()
            if q is not None:
                for year, part in cands.groupby("year"):
                    prior = cands[cands.year < year].ratio
                    if len(prior) >= 50:
                        exclude |= set(part.index[part.ratio < prior.quantile(q)])
            fractions = {e: 0.075 * float(np.clip(r, 0.5, 1.5)) for e, r in cands.ratio.items()} if size else {}
            return fractions, exclude

        entry = []
        for q, size in ENTRY_GRID:
            fractions, exclude = entry_rule(q, size)
            b = book(desk_book(workspace, fractions, exclude, {}, selector))
            entry.append({"selector": selector, "q": q, "size": size, "vetoed": len(exclude), "2010-2017": pr.stats(b, 2010, 2017)})
            books[(selector, q, size, None)] = b
        best = max(entry, key=lambda g: g["2010-2017"]["sharpe"])
        fractions, exclude = entry_rule(best["q"], best["size"])
        monitor = []
        for rule in MONITOR_GRID[1:]:
            hit = checks[(checks.adverse >= rule[0]) & (checks.persistence >= rule[1])] if len(checks) else checks
            exits = hit.sort_values("session").groupby("event_id").session.first().dt.date.to_dict() if len(hit) else {}
            b = book(desk_book(workspace, fractions, exclude, exits, selector))
            monitor.append({"selector": selector, "q": best["q"], "size": best["size"], "rule": rule,
                            "exits": len(exits), "2010-2017": pr.stats(b, 2010, 2017)})
            books[(selector, best["q"], best["size"], rule)] = b
        trials += entry + monitor
    # Decision 110c, the full model as selector: rank the region by the agent-adjusted forecast
    # (desk scores on the B+rule+ou base) and take as many events per year as the best model's
    # top 20 %, with the cut from the previous year. Years without an agent forecast fall back
    # to the best model's own selection.
    full = tables[("desk", "B+rule+ou")]
    flags = pd.read_parquet("outputs/p6_quant/scores__B+rule+ou__recent-bag5.parquet")
    per_year = flags.groupby("year").top20.sum()
    best_top = flags.loc[flags.top20.astype(bool)]
    chosen_full: list[str] = []
    for year in sorted(flags.year.unique()):
        now = full[(full.year == year) & full.p_agent.notna()]
        prior = full[(full.year == year - 1) & full.p_agent.notna()]
        if len(now) == 0 or len(prior) < 50:
            chosen_full += list(best_top.loc[best_top.year == year, "event_id"])
            continue
        share = min(1.0, float(per_year.get(year - 1, 0)) / len(prior))
        chosen_full += list(now.event_id[now.p_agent >= prior.p_agent.quantile(1 - share)])
    full_members = set(pa.design_candidates(workspace, "FULL", chosen_full))
    fcands = full.set_index("event_id")
    fcands = fcands[fcands.index.isin(full_members)].copy()
    fcands["ratio"] = (fcands.p_agent / fcands.p_base).fillna(1.0)
    full_trials = []
    for size in (False, True):
        fractions = {e: 0.075 * float(np.clip(r, 0.5, 1.5)) for e, r in fcands.ratio.items()} if size else {}
        b = book(desk_book(workspace, fractions, set(), {}, "FULL", chosen_full))
        full_trials.append({"selector": "FULL", "q": None, "size": size, "vetoed": 0, "2010-2017": pr.stats(b, 2010, 2017)})
        books[("FULL", None, size, None)] = b
    fbest = max(full_trials, key=lambda g: g["2010-2017"]["sharpe"])
    ffractions = (
        {e: 0.075 * float(np.clip(r, 0.5, 1.5)) for e, r in fcands.ratio.items()} if fbest["size"] else {}
    )
    for rule in MONITOR_GRID[1:]:
        hit = checks[(checks.adverse >= rule[0]) & (checks.persistence >= rule[1])] if len(checks) else checks
        exits = hit.sort_values("session").groupby("event_id").session.first().dt.date.to_dict() if len(hit) else {}
        b = book(desk_book(workspace, ffractions, set(), exits, "FULL", chosen_full))
        full_trials.append({"selector": "FULL", "q": None, "size": fbest["size"], "rule": rule,
                            "exits": len(exits), "2010-2017": pr.stats(b, 2010, 2017)})
        books[("FULL", None, fbest["size"], rule)] = b
    trials += full_trials
    report["full_selection"] = {"events": len(chosen_full), "candidates_after_filters": len(full_members),
                                "with_monitor_checks": int(len(set(checks.event_id) & full_members)) if len(checks) else 0}
    report["trials"] = trials
    report["trial_count"] = len(trials)
    winner = max(trials, key=lambda g: g["2010-2017"]["sharpe"])
    report["chosen"] = {k: winner.get(k) for k in ("selector", "q", "size", "rule")}
    if holdout:
        chosen_book = books[(winner["selector"], winner["q"], winner["size"], winner.get("rule"))]
        named = {
            "current book (R0, no agents)": books[("R0", None, False, None)],
            "best model, no agents": books[("B+rule+ou__recent-bag5", None, False, None)],
            "chosen": chosen_book,
        }
        report["holdout"] = {
            name: {label: pr.stats(b, *span) for label, span in
                   (("2010-2017", (2010, 2017)), ("2018-2023", (2018, 2023)), ("2010-2023", (2010, 2023)))}
            for name, b in named.items()
        }
    dv.cv_write(output / ("evaluation_holdout.json" if holdout else "evaluation.json"), report)
    return report


def main(arguments: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("build-entry", "build-monitor"):
        sub.add_parser(name).add_argument("--workspace-root", type=Path, default=Path("data/team"))
    r = sub.add_parser("run")
    r.add_argument("--env-file", type=Path, required=True)
    r.add_argument("--kind", choices=("entry", "monitor"), default="entry")
    r.add_argument("--limit", type=int)
    r.add_argument("--workers", type=int, default=4)
    sub.add_parser("status")
    sub.add_parser("evaluate").add_argument("--holdout", action="store_true")
    args = parser.parse_args(arguments)

    def say(message: str) -> None:
        print(f"{_now()} {message}", flush=True)

    if args.command == "build-entry":
        say(json.dumps(build_entry(args.workspace_root), default=str))
    elif args.command == "build-monitor":
        say(json.dumps(build_monitor(args.workspace_root), default=str))
    elif args.command == "run":
        cc.load_env_file(args.env_file)
        if not cc._credential():
            sys.exit("No API key in the environment")
        say(f"finished: {dict(run(kind=args.kind, limit=args.limit, workers=args.workers, say=say))}")
    elif args.command == "evaluate":
        print(json.dumps(evaluate(holdout=args.holdout), indent=1, default=str))
    else:
        print(status())


if __name__ == "__main__":
    main()
