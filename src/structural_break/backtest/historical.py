"""Generation-bound adapters from registered v2 outputs to the shared ladder.

Every file is read through its manifest checksum, starting from one evaluation
manifest and following its registry and market parents. Nothing is downloaded,
fitted or sent to a provider. Selection never reads forward prices or labels;
labels are a separate reporting input. Historical execution requires an accepted
binding and an explicitly frozen production policy, so a DRAFT policy can build
an outcome-free selection inventory but cannot produce a return.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, cast

import pandas as pd

from structural_break.backtest.contracts import (
    ExecutionConfig,
    MarketSession,
    PairPrices,
    PairTradeRequest,
    PriceLineage,
    RelationshipSnapshot,
    canonical_sessions,
    utc,
)
from structural_break.backtest.historical_contracts import (
    PRICE_ADJUSTMENT_POLICY,
    Acceptance,
    GenerationBinding,
    HistoricalInventory,
    HistoricalSpec,
    InventoryRow,
    ManifestBinding,
    Partition,
    SuppressedCrossing,
)
from structural_break.backtest.ladder import _check_prediction, _select_validated_event
from structural_break.backtest.ladder_contracts import (
    RUNG_ORDER,
    EvaluationLabel,
    LadderEvent,
    LadderPolicy,
    LadderRow,
    LadderState,
    PreviousClose,
    RungSelection,
    StoredPrediction,
)
from structural_break.backtest.simulator import sha256, simulate_pair_trade
from structural_break.config.paths import ProjectPaths, confined_path
from structural_break.research.primary import (
    checked_file,
    checked_json,
    load_primary,
    registered_manifest,
)
from structural_break.storage.files import sha256_file

ADAPTER_VERSION = "historical-ladder-adapter-v1"
_ROLE_COLUMNS = {
    "A": "A",
    "B-metadata": "B_metadata",
    "B-tone": "B_tone",
    "B-catalyst": "B_catalyst",
    "B-both": "B_both",
}
_TOLERANCE = 1e-9


def _portable(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _one(items: Iterable[Mapping[str, Any]], role: str) -> Mapping[str, Any]:
    matches = [item for item in items if item.get("role") == role]
    if len(matches) != 1:
        raise ValueError(f"Generation chain requires exactly one {role} parent")
    return matches[0]


def _chain(
    root: Path,
    evaluation_path: str,
    evaluation_sha256: str,
    *,
    acceptance: Acceptance,
    primary_version: str | None,
) -> GenerationBinding:
    """Follow the checksum chain evaluation -> registry -> market; never list folders."""
    evaluation_file = confined_path(root, evaluation_path)
    evaluation = checked_json(evaluation_file, evaluation_sha256)
    if evaluation.get("stage") != "evaluation" or evaluation.get("final_test_read") is not False:
        raise ValueError("Bound evaluation must be a development-only evaluation generation")
    inputs = evaluation["identity_inputs"]
    registry_parent = _one(evaluation["parents"], "registry")
    if registry_parent["sha256"] != inputs["registry_manifest_sha256"]:
        raise ValueError("Evaluation parent and identity registry checksums differ")
    registry_file = confined_path(root, registry_parent["path"])
    registry = checked_json(registry_file, registry_parent["sha256"])
    protocol = evaluation["protocol"]
    if (
        registry.get("stage") != "registry"
        or registry.get("final_test_read") is not False
        or registry.get("research_version") != inputs["registry_version"]
        or registry.get("protocol") != protocol
        or registry.get("protocol_hash") != evaluation.get("protocol_hash")
        or protocol.get("final_test_locked") is not True
    ):
        raise ValueError("Registry generation differs from its evaluation protocol or lock")
    market_parent = _one(registry["inputs"], "market")
    market_file = confined_path(root, market_parent["path"])
    market = checked_json(market_file, market_parent["sha256"])
    if market.get("final_test_prices_collected") is not False:
        raise ValueError("Market generation must not contain final-test prices")
    files = market["files"]
    return GenerationBinding(
        acceptance=acceptance,
        primary_version=primary_version,
        horizon_sessions=inputs["horizon"],
        evaluation=ManifestBinding(
            role="evaluation",
            version=evaluation["research_version"],
            path=evaluation_path,
            sha256=evaluation_sha256,
        ),
        registry=ManifestBinding(
            role="registry",
            version=registry["research_version"],
            path=registry_parent["path"],
            sha256=registry_parent["sha256"],
        ),
        market=ManifestBinding(
            role="market",
            version=market["data_snapshot_id"],
            path=market_parent["path"],
            sha256=market_parent["sha256"],
        ),
        prices_sha256=files["prices.parquet"],
        pair_universe_sha256=files["pair_universe.parquet"],
        protocol_hash=evaluation["protocol_hash"],
        development_end=date.fromisoformat(protocol["development_end"]),
        assessment_start=date.fromisoformat(protocol["assessment_start"]),
        assessment_end=date.fromisoformat(protocol["assessment_end"]),
        candidate_threshold=float(protocol["candidate_threshold"]),
    )


def bind_unaccepted(
    workspace_root: Path, evaluation_manifest: str, evaluation_sha256: str
) -> GenerationBinding:
    """Explicit path+checksum binding for engineering checks on an unaccepted pack."""
    return _chain(
        workspace_root,
        evaluation_manifest,
        evaluation_sha256,
        acceptance="UNACCEPTED_ENGINEERING",
        primary_version=None,
    )


def bind_accepted(
    paths: ProjectPaths, horizon: int, *, primary_version: str | None = None
) -> GenerationBinding:
    """Derive the binding only from the verified primary readiness publication."""
    primary = load_primary(paths, primary_version)
    inputs = primary["identity_inputs"]
    selected = inputs["evaluations"].get(str(horizon))
    if selected is None:
        raise ValueError("The primary publication has no evaluation for this horizon")
    path, _ = registered_manifest(paths, selected["research_version"], "evaluation")
    binding = _chain(
        paths.workspace_root,
        _portable(paths.workspace_root, path),
        sha256_file(path),
        acceptance="ACCEPTED",
        primary_version=primary["primary_version"],
    )
    if (
        binding.registry.version != inputs["registry_version"]
        or binding.evaluation.version != selected["research_version"]
        or binding.horizon_sessions != horizon
    ):
        raise ValueError("Accepted binding differs from the primary publication")
    return binding


class HistoricalSources:
    """Checksum-bound read access to one binding; open() re-derives the binding."""

    def __init__(self, root: Path, binding: GenerationBinding) -> None:
        self.root = root
        self.binding = binding
        self.evaluation_file = confined_path(root, binding.evaluation.path)
        self.registry_file = confined_path(root, binding.registry.path)
        self.market_file = confined_path(root, binding.market.path)
        self.evaluation = checked_json(self.evaluation_file, binding.evaluation.sha256)
        self.registry = checked_json(self.registry_file, binding.registry.sha256)
        self.market = checked_json(self.market_file, binding.market.sha256)
        self._pairs: dict[str, tuple[Path, dict[str, Any]]] = {}

    @classmethod
    def open(
        cls, root: Path, binding: GenerationBinding, *, paths: ProjectPaths | None = None
    ) -> HistoricalSources:
        if binding.acceptance == "ACCEPTED":
            if paths is None or paths.workspace_root.resolve() != root.resolve():
                raise ValueError("Accepted sources require the project workspace paths")
            derived = bind_accepted(
                paths, binding.horizon_sessions, primary_version=binding.primary_version
            )
        else:
            derived = _chain(
                root,
                binding.evaluation.path,
                binding.evaluation.sha256,
                acceptance="UNACCEPTED_ENGINEERING",
                primary_version=None,
            )
        if derived != binding:
            raise ValueError("Generation binding does not reproduce from its bound manifests")
        return cls(root, binding)

    def registry_frame(self, name: str, columns: Sequence[str] | None = None) -> pd.DataFrame:
        path = checked_file(self.registry_file.parent, self.registry, name)
        return pd.read_parquet(path, columns=list(columns) if columns else None)

    def predictions(self) -> pd.DataFrame:
        return pd.read_parquet(
            checked_file(self.evaluation_file.parent, self.evaluation, "predictions")
        )

    def model_sha256(self, name: str) -> str:
        entries = [item for item in self.evaluation["model_files"] if item["name"] == name]
        if len(entries) != 1:
            raise ValueError("Evaluation model inventory must contain the declared bundle once")
        path = confined_path(self.evaluation_file.parent, entries[0]["path"])
        if sha256_file(path) != entries[0]["sha256"]:
            raise ValueError("Saved native model checksum differs")
        return str(entries[0]["sha256"])

    def _market_file(self, name: str, digest: str) -> Path:
        path = confined_path(self.market_file.parent, name)
        if self.market["files"].get(name) != digest or sha256_file(path) != digest:
            raise ValueError("Bound market file checksum differs")
        return path

    def prices(self, start: date, end: date) -> pd.DataFrame:
        path = self._market_file("prices.parquet", self.binding.prices_sha256)
        columns = ["ticker", "trading_date", "open", "close", "adj_close", "quality_flag"]
        frame = pd.read_parquet(path, columns=columns)
        dates = pd.to_datetime(frame["trading_date"]).dt.date
        if dates.gt(self.binding.development_end).any():
            raise ValueError("Bound prices extend past the development period")
        return frame.loc[dates.ge(start) & dates.le(end)].copy()

    def pair_universe(self) -> pd.DataFrame:
        path = self._market_file("pair_universe.parquet", self.binding.pair_universe_sha256)
        return pd.read_parquet(path)

    def pair_frame(
        self, pair_id: str, name: str, columns: Sequence[str] | None = None
    ) -> pd.DataFrame:
        if pair_id not in self._pairs:
            matches = [
                item for item in self.registry["pair_manifests"] if item["pair_id"] == pair_id
            ]
            if len(matches) != 1:
                raise ValueError("Select one frozen pair identity")
            path = confined_path(self.registry_file.parent / "pairs", pair_id + "/manifest.json")
            manifest = checked_json(path, matches[0]["sha256"])
            if manifest.get("pair_id") != pair_id:
                raise ValueError("Frozen pair manifest identity differs")
            self._pairs[pair_id] = (path.parent, manifest)
        directory, manifest = self._pairs[pair_id]
        file = checked_file(directory, manifest, name)
        return pd.read_parquet(file, columns=list(columns) if columns else None)


def _flags(value: object) -> frozenset[str]:
    return frozenset(value.split("|")) if isinstance(value, str) and value else frozenset()


@dataclass(frozen=True)
class PriceBook:
    """Adjusted open/close on one capture: open_adj = open * adj_close / close."""

    lineage: PriceLineage
    bars: Mapping[tuple[str, date], tuple[float | None, float | None]]

    @classmethod
    def build(cls, frame: pd.DataFrame, spec: HistoricalSpec) -> PriceBook:
        if frame.duplicated(["ticker", "trading_date"]).any():
            raise ValueError("Price capture must have one row per ticker and session")
        fills, closes = set(spec.fill_quality_flags), set(spec.close_quality_flags)
        bars: dict[tuple[str, date], tuple[float | None, float | None]] = {}
        for ticker, day, raw_open, raw_close, adjusted, flag in frame[
            ["ticker", "trading_date", "open", "close", "adj_close", "quality_flag"]
        ].itertuples(index=False, name=None):
            values = (float(raw_open), float(raw_close), float(adjusted))
            flags = _flags(flag)
            if not all(math.isfinite(value) and value > 0 for value in values) or not flags:
                bars[(str(ticker), _date(day))] = (None, None)
                continue
            close = values[2] if flags <= closes else None
            opening = values[0] * values[2] / values[1] if flags <= fills else None
            bars[(str(ticker), _date(day))] = (opening, close)
        lineage = PriceLineage(
            source_snapshot_id=spec.binding.market.version,
            source_sha256=spec.binding.prices_sha256,
            price_basis="ADJUSTED_OPEN_CLOSE",
            adjustment_policy=PRICE_ADJUSTMENT_POLICY,
        )
        return cls(lineage=lineage, bars=bars)

    def close(self, ticker: str, day: date) -> float | None:
        return self.bars.get((ticker, day), (None, None))[1]

    def pair_bars(
        self, leg_a: str, leg_b: str, sessions: Sequence[MarketSession]
    ) -> tuple[PairPrices, ...]:
        rows = []
        for session in sessions:
            open_a, close_a = self.bars.get((leg_a, session.session_date), (None, None))
            open_b, close_b = self.bars.get((leg_b, session.session_date), (None, None))
            rows.append(
                PairPrices(
                    session_date=session.session_date,
                    open_a=open_a,
                    open_b=open_b,
                    close_a=close_a,
                    close_b=close_b,
                )
            )
        return tuple(rows)


def _date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.Timestamp(cast(Any, value)).date()


def _timestamp(value: object) -> datetime:
    stamp = pd.Timestamp(cast(Any, value))
    if stamp.tzinfo is None:
        raise ValueError("Historical clocks must be timezone-aware")
    return stamp.to_pydatetime()


def _close(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=_TOLERANCE, abs_tol=_TOLERANCE)


def historical_policy(
    sources: HistoricalSources,
    *,
    status: Literal["DRAFT", "FROZEN"] = "DRAFT",
    model_family: Literal["logistic", "xgboost"] = "logistic",
    model_b_variant: Literal["B-metadata", "B-tone", "B-catalyst", "B-both"] = "B-both",
) -> LadderPolicy:
    """Headline: calibrated logistic A vs B-both at the matched v2 threshold."""
    binding = sources.binding
    labels = sources.registry_frame(
        f"h{binding.horizon_sessions}_events", ["label_policy_version"]
    )["label_policy_version"].unique()
    if len(labels) != 1:
        raise ValueError("Horizon events must bind one label policy")
    model_a = sources.model_sha256(f"{model_family}_A")
    model_b = sources.model_sha256(f"{model_family}_{_ROLE_COLUMNS[model_b_variant]}")
    return LadderPolicy(
        version=f"{ADAPTER_VERSION}:{binding.evaluation.version}",
        population_id=f"{binding.evaluation.version}:{binding.registry.version}",
        status=status,
        horizon_sessions=binding.horizon_sessions,
        candidate_threshold=binding.candidate_threshold,
        model_family=model_family,
        model_a_bundle_id=model_a,
        model_a_calibrator_id="embedded-in-bundle:" + model_a,
        model_b_bundle_id=model_b,
        model_b_calibrator_id="embedded-in-bundle:" + model_b,
        model_b_variant=model_b_variant,
        controller_policy_version="NOT_RUN",
        label_policy_version=str(labels[0]),
        full_system="NOT_RUN",
    )


def default_spec(
    sources: HistoricalSources, *, status: Literal["DRAFT", "FROZEN"] = "DRAFT"
) -> HistoricalSpec:
    """Assessment window only, for all five rungs (stored earlier scores are in-sample)."""
    binding = sources.binding
    return HistoricalSpec(
        binding=binding,
        ladder=historical_policy(sources, status=status),
        window_start=binding.assessment_start,
        window_end=binding.assessment_end,
    )


def _prediction(
    row: Mapping[str, Any] | None,
    policy: LadderPolicy,
    role: str,
    cutoff: datetime,
    admitted: Sequence[Partition],
) -> StoredPrediction | None:
    if row is None:
        return None
    if row["research_partition"] not in admitted:
        raise ValueError("Stored prediction partition is outside the declared window")
    column = f"{policy.model_family}_{_ROLE_COLUMNS[role]}_calibrated"
    value = float(row[column])
    if not math.isfinite(value):
        raise ValueError("Stored calibrated probability must be finite")
    return StoredPrediction(
        model_role=cast(Any, role),
        model_family=policy.model_family,
        horizon_sessions=policy.horizon_sessions,
        model_bundle_id=policy.model_a_bundle_id if role == "A" else policy.model_b_bundle_id,
        calibrator_id=(
            policy.model_a_calibrator_id if role == "A" else policy.model_b_calibrator_id
        ),
        information_cutoff=cutoff,
        probability=value,
    )


def _lifecycle(pair: Mapping[str, Any], development_end: date) -> date | None:
    """First session no longer admissible, mirroring the relationship engine's rule."""
    candidates = []
    manual = pair.get("manual_terminal_date")
    if manual is not None and not pd.isna(manual):
        candidates.append(_date(manual))
    active_to = pair.get("active_to")
    if active_to is not None and not pd.isna(active_to):
        candidates.append(_date(active_to) + timedelta(days=1))
    termination = min(candidates) if candidates else None
    return termination if termination is not None and termination <= development_end else None


def _sessions(signal: date, horizon: int, development_end: date) -> tuple[MarketSession, ...]:
    # Signal close, horizon monitored closes and the following exit open; any
    # session after the development end is never constructed (truncated path).
    end = min(signal + timedelta(days=3 * (horizon + 2) + 14), development_end)
    sessions = canonical_sessions(signal, end)[: horizon + 2]
    if not sessions or sessions[0][0] != signal:
        raise ValueError("Signal date must be an actual XNYS session")
    return tuple(
        MarketSession(session_date=day, open_at=opening, close_at=closing)
        for day, opening, closing in sessions
    )


def build_event(
    event: Mapping[str, Any],
    crossing: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    pair: Mapping[str, Any],
    prediction: Mapping[str, Any] | None,
    prices: PriceBook,
    spec: HistoricalSpec,
) -> LadderEvent:
    """Reconcile stored registry values to prices; any mismatch stops the run."""
    binding, policy = spec.binding, spec.ladder
    pair_id = str(event["pair_id"])
    leg_a, leg_b = str(pair["leg_a"]), str(pair["leg_b"])
    if pair["pair_id"] != pair_id or crossing["pair_id"] != pair_id:
        raise ValueError("Event, crossing and roster pair identities differ")
    signal_date = _date(event["event_date"])
    sessions = _sessions(signal_date, binding.horizon_sessions, binding.development_end)
    signal_at = sessions[0].close_at
    for name in ("event_timestamp", "feature_cutoff_timestamp"):
        if utc(_timestamp(event[name])) != utc(signal_at):
            raise ValueError("Stored event clock must equal the exact XNYS signal close")
    snapshot_id = str(event["relationship_snapshot_id"])
    if snapshot["relationship_snapshot_id"] != snapshot_id or snapshot["pair_id"] != pair_id:
        raise ValueError("Relationship snapshot identity differs from the event")
    parameters = ("alpha", "beta", "spread_mean", "spread_std")
    if any(float(event[name]) != float(snapshot[name]) for name in parameters):
        raise ValueError("Event relationship parameters differ from the frozen snapshot")
    frozen = RelationshipSnapshot(
        snapshot_id=snapshot_id,
        available_at=_timestamp(snapshot["effective_start_at"]),
        formation_end=_date(snapshot["window_end"]),
        alpha=float(snapshot["alpha"]),
        beta=float(snapshot["beta"]),
        spread_mean=float(snapshot["spread_mean"]),
        spread_std=float(snapshot["spread_std"]),
    )
    prior = canonical_sessions(signal_date - timedelta(days=14), signal_date)
    previous_date = prior[-2][0]
    previous_a, previous_b = prices.close(leg_a, previous_date), prices.close(leg_b, previous_date)
    stored_previous = crossing["previous_z_score"]
    if previous_a is None or previous_b is None or stored_previous is None:
        raise ValueError("A stored fresh crossing requires its previous adjusted closes")
    previous_z = frozen.z(previous_a, previous_b)
    if not _close(previous_z, float(stored_previous)):
        raise ValueError("Previous z does not reconcile to adjusted closes and the snapshot")
    signal_z = float(event["entry_z"])
    if not _close(signal_z, float(crossing["z_entry"])):
        raise ValueError("Event and raw-crossing signal z differ")
    request = PairTradeRequest(
        data_kind="DEVELOPMENT_CAPTURE",
        event_id=str(event["event_id"]),
        pair_id=pair_id,
        leg_a=leg_a,
        leg_b=leg_b,
        signal_at=signal_at,
        signal_z=signal_z,
        snapshot=frozen,
        price_lineage=prices.lineage,
        sessions=sessions,
        prices=prices.pair_bars(leg_a, leg_b, sessions),
        lifecycle_termination=_lifecycle(pair, binding.development_end),
    )
    status = crossing["pair_status"]
    state = LadderState(
        event_id=str(event["event_id"]),
        pair_id=pair_id,
        signal_at=signal_at,
        snapshot_id=snapshot_id,
        previous=PreviousClose(
            session_date=previous_date,
            close_a=previous_a,
            close_b=previous_b,
            z=previous_z,
            snapshot_id=snapshot_id,
        ),
        pair_status=status if status in ("ACTIVE", "WATCH", "RETIRED") else "UNKNOWN",
        model_a=_prediction(prediction, policy, "A", signal_at, spec.admitted_partitions),
        model_b=_prediction(
            prediction, policy, policy.model_b_variant, signal_at, spec.admitted_partitions
        ),
        sector=str(pair["sector"]) if pair.get("sector") else "UNKNOWN",
    )
    return LadderEvent(state=state, request=request)


def select_historical_event(
    event: LadderEvent, spec: HistoricalSpec
) -> tuple[bool | None, tuple[RungSelection, ...]]:
    """Outcome-free selection for captured inputs; no simulator or label access."""
    if event.request.data_kind != "DEVELOPMENT_CAPTURE":
        raise ValueError("Historical selection requires captured development inputs")
    if event.request.price_lineage.source_sha256 != spec.binding.prices_sha256:
        raise ValueError("Event prices do not bind the declared market capture")
    _check_prediction(event.state.model_a, spec.ladder, role="A")
    _check_prediction(event.state.model_b, spec.ladder, role="B")
    return _select_validated_event(event, spec.ladder)


def _rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    return cast(list[dict[str, Any]], frame.to_dict("records"))


def _records(frame: pd.DataFrame, key: str) -> dict[str, dict[str, Any]]:
    if frame[key].duplicated().any():
        raise ValueError(f"Stored {key} identities must be unique")
    return {str(row[key]): row for row in _rows(frame)}


def build_historical_events(
    sources: HistoricalSources, spec: HistoricalSpec
) -> tuple[tuple[LadderEvent, ...], tuple[str | None, ...], tuple[SuppressedCrossing, ...]]:
    """All horizon episode events in the window, plus omitted raw crossings."""
    if spec.binding != sources.binding:
        raise ValueError("Specification and sources bind different generations")
    horizon = spec.binding.horizon_sessions
    events = sources.registry_frame(f"h{horizon}_events")
    dates = pd.to_datetime(events["event_date"]).dt.date
    events = events.loc[dates.ge(spec.window_start) & dates.le(spec.window_end)]
    events = events.sort_values(["event_date", "pair_id", "event_id"], kind="mergesort")
    predictions = _records(sources.predictions(), "event_id")
    universe = _records(sources.pair_universe(), "pair_id")
    prices = PriceBook.build(
        sources.prices(spec.window_start - timedelta(days=21), spec.binding.development_end),
        spec,
    )
    by_pair: dict[str, list[dict[str, Any]]] = {}
    for row in _rows(events):
        by_pair.setdefault(str(row["pair_id"]), []).append(row)
    built: dict[str, tuple[LadderEvent, str | None]] = {}
    suppressed: list[SuppressedCrossing] = []
    for pair_id in sorted(universe):
        crossings = sources.pair_frame(pair_id, "raw_crossings")
        crossing_dates = pd.to_datetime(crossings["event_date"]).dt.date
        crossings = crossings.loc[
            crossing_dates.ge(spec.window_start) & crossing_dates.le(spec.window_end)
        ]
        keyed = {
            (_date(row["event_date"]), str(row["relationship_snapshot_id"])): row
            for row in _rows(crossings)
        }
        if len(keyed) != len(crossings):
            raise ValueError("Raw crossings must be unique per session and snapshot")
        matched: set[tuple[date, str]] = set()
        pair_events = by_pair.get(pair_id, [])
        if pair_events:
            snapshots = _records(
                sources.pair_frame(pair_id, "relationship_snapshots"), "relationship_snapshot_id"
            )
            for row in pair_events:
                key = (_date(row["event_date"]), str(row["relationship_snapshot_id"]))
                if key not in keyed:
                    raise ValueError("Every horizon event must be a stored raw crossing")
                matched.add(key)
                prediction = predictions.get(str(row["event_id"]))
                event = build_event(
                    row, keyed[key], snapshots[key[1]], universe[pair_id], prediction, prices, spec
                )
                partition = prediction["research_partition"] if prediction else None
                built[str(row["event_id"])] = (event, partition)
        for key, row in keyed.items():
            if key not in matched:
                suppressed.append(
                    SuppressedCrossing(
                        crossing_id=str(row["crossing_id"]), pair_id=pair_id, event_date=key[0]
                    )
                )
    if set(built) != set(events["event_id"].astype(str)):
        raise ValueError("Every horizon event must belong to the frozen pair roster")
    ordered = [built[str(event_id)] for event_id in events["event_id"]]
    return (
        tuple(item[0] for item in ordered),
        tuple(item[1] for item in ordered),
        tuple(sorted(suppressed, key=lambda row: (row.event_date, row.pair_id, row.crossing_id))),
    )


def select_inventory(
    events: Sequence[LadderEvent],
    partitions: Sequence[str | None],
    suppressed: Sequence[SuppressedCrossing],
    spec: HistoricalSpec,
) -> HistoricalInventory:
    """Selection only: valid for DRAFT policies because no return is produced."""
    if len(events) != len(partitions):
        raise ValueError("Every inventory event requires its stored partition or None")
    rows = []
    for event, partition in zip(events, partitions, strict=True):
        raw_fresh, selections = select_historical_event(event, spec)
        rows.append(
            InventoryRow(
                event_id=event.state.event_id,
                pair_id=event.state.pair_id,
                signal_at=event.state.signal_at,
                partition=cast(Partition | None, partition),
                state_sha256=sha256(event.state),
                request_sha256=sha256(event.request),
                raw_fresh=raw_fresh,
                selections=selections,
            )
        )
    return HistoricalInventory(
        spec_sha256=sha256(spec),
        acceptance=spec.binding.acceptance,
        rows=tuple(rows),
        suppressed=tuple(suppressed),
    )


def inventory_summary(inventory: HistoricalInventory) -> dict[str, Any]:
    """Counts and reasons only; no prices, returns or labels are summarized."""
    rungs: dict[str, Any] = {}
    for index, rung in enumerate(RUNG_ORDER):
        selections = [row.selections[index] for row in inventory.rows]
        rungs[rung] = {
            "disposition_counts": dict(
                sorted(Counter(item.disposition for item in selections).items())
            ),
            "reason_counts": dict(
                sorted(Counter(code for item in selections for code in item.reason_codes).items())
            ),
        }
    return {
        "schema_version": "historical-ladder-inventory-summary-v1",
        "adapter_version": ADAPTER_VERSION,
        "acceptance": inventory.acceptance,
        "spec_sha256": inventory.spec_sha256,
        "events_n": len(inventory.rows),
        "suppressed_raw_crossings_n": len(inventory.suppressed),
        "partition_counts": dict(
            sorted(Counter(str(row.partition) for row in inventory.rows).items())
        ),
        "raw_fresh_counts": dict(
            sorted(Counter(str(row.raw_fresh) for row in inventory.rows).items())
        ),
        "rungs": rungs,
        "simulated": False,
        "labels_read": False,
        "final_test_read": False,
        "economic_results": None,
    }


def historical_labels(
    sources: HistoricalSources, spec: HistoricalSpec, events: Sequence[LadderEvent]
) -> tuple[tuple[EvaluationLabel, ...], dict[str, int]]:
    """Separate reporting input; censored or ineligible targets stay unlabelled."""
    horizon = spec.binding.horizon_sessions
    name = f"h{horizon}_targets"
    digest = next(item["sha256"] for item in sources.registry["files"] if item["name"] == name)
    targets = _records(sources.registry_frame(name), "event_id")
    labels: list[EvaluationLabel] = []
    missing: Counter[str] = Counter()
    for event in events:
        target = targets.get(event.state.event_id)
        if target is None:
            missing["TARGET_NOT_STORED"] += 1
            continue
        value = target["y_revert_success"]
        if target["label_eligible"] is not True or value is None or not math.isfinite(value):
            missing["LABEL_NOT_ELIGIBLE"] += 1
            continue
        if target["label_policy_version"] != spec.ladder.label_policy_version:
            raise ValueError("Stored target label policy differs from the declared ladder")
        if int(value) != value or value not in (0, 1):
            raise ValueError("Stored supervised target must be binary")
        labels.append(
            EvaluationLabel(
                event_id=event.state.event_id,
                pair_id=event.state.pair_id,
                signal_at=event.state.signal_at,
                horizon_sessions=spec.ladder.horizon_sessions,
                label_policy_version=spec.ladder.label_policy_version,
                label_manifest_sha256=digest,
                complete_window_end=_date(target["horizon_end_date"]),
                label_success=cast(Literal[0, 1], int(value)),
            )
        )
    return tuple(labels), dict(sorted(missing.items()))


def evaluate_historical_ladder(
    events: Sequence[LadderEvent], spec: HistoricalSpec, config: ExecutionConfig
) -> tuple[LadderRow, ...]:
    """Run the shared engine once per fresh event, only under accepted frozen policy."""
    if spec.binding.acceptance != "ACCEPTED":
        raise ValueError("Historical execution requires an accepted generation binding")
    if spec.ladder.status != "FROZEN":
        raise ValueError("Historical execution requires a frozen ladder policy")
    if config.mode != "DEVELOPMENT" or config.status != "FROZEN":
        raise ValueError("Historical execution requires a frozen production execution policy")
    if config.horizon_sessions != spec.ladder.horizon_sessions:
        raise ValueError("Ladder and shared execution horizon must match")
    if len({event.state.event_id for event in events}) != len(events):
        raise ValueError("Every ladder input must have a unique event identity")
    selections = [select_historical_event(event, spec) for event in events]
    rows = []
    for event, (raw_fresh, selected) in zip(events, selections, strict=True):
        execution = simulate_pair_trade(event.request, config) if raw_fresh else None
        rows.append(
            LadderRow(
                event_id=event.state.event_id,
                pair_id=event.state.pair_id,
                signal_at=event.state.signal_at,
                state_sha256=sha256(event.state),
                request_sha256=sha256(event.request),
                raw_fresh=raw_fresh,
                selections=selected,
                execution=execution,
            )
        )
    return tuple(rows)
