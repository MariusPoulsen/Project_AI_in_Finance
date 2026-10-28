"""Decision 118: extend a frozen research workspace with the final-test events.

The development rows stay byte-identical. The final-test registry is rebuilt with the
frozen code under ``configs/final_test.yaml`` (verified equal to the frozen registry on
2006-2023 in the rehearsal); this module then

1. computes the SEC event intelligence (filing metadata, pinned FinBERT tone; catalysts
   stay UNKNOWN, as they are inert for the selection model) for the events after ``since``
   only, with the frozen research code;
2. builds their model-input rows with the research job's own join and appends them to the
   frozen model inputs; the frozen research predictions stay unchanged (final-test events are
   excluded rows, which the research models never score);
3. publishes a final-test evaluation whose parents are the final-test registry and both
   intelligence generations, with the frozen models and report.

``write_binding`` points the book's data binding at that evaluation. While the final test
is locked only a rehearsal (development end 2023-12-31) can be built.
"""

from __future__ import annotations

import json
import shutil
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from structural_break import periods
from structural_break.config.loader import load_config
from structural_break.config.models import Pair, UniverseConfig
from structural_break.config.paths import ProjectPaths
from structural_break.intelligence.event_features import EVENT_FEATURE_NAMES
from structural_break.intelligence.sentiment import SENTIMENT_FEATURE_COLUMNS
from structural_break.research.protocol import (
    canonical_bytes,
    experiment_config,
    identity,
    protocol_model,
)
from structural_break.research.runner import _registered_manifest, publish_research
from structural_break.storage.files import sha256_file, write_bytes

BINDING = "final_test_binding.json"


def new_evidence_events(paths: ProjectPaths, registry_version: str, since: date) -> pd.DataFrame:
    """Evidence events (pair and UTC cutoff) of the registry dated on or after ``since``."""
    from structural_break.research.cli import evidence_events

    events, _, _ = evidence_events(paths, registry_version)
    stamps = pd.to_datetime(events["event_timestamp"], utc=True)
    return events.loc[stamps.dt.date.ge(since)].reset_index(drop=True)


def build_new_intelligence(
    paths: ProjectPaths,
    registry_version: str,
    since: date,
    output_dir: Path,
    *,
    sec_metadata_dir: Path,
    cache_workspace: Path,
    finbert_cache: Path,
    preprocessing: str = "sec-sentence-quality-wordpiece-v2",
    offline: bool = False,
    sec_user_agent: str | None = None,
) -> dict[str, Any]:
    """Frozen-code intelligence for the new events only (no catalyst provider)."""
    from structural_break.intelligence.sentiment import FinBERTPolicy, HuggingFaceFinBERT
    from structural_break.research.intelligence import build_event_intelligence

    parent = _registered_manifest(paths, registry_version)
    if parent is None:
        raise ValueError("The final-test registry must be registered first")
    protocol = protocol_model(parent["protocol"])
    events = new_evidence_events(paths, registry_version, since)
    policy = FinBERTPolicy(
        model_name=protocol.sentiment_model,
        model_revision=protocol.sentiment_revision,
        preprocessing_version=preprocessing,
    )
    backend = HuggingFaceFinBERT(finbert_cache, policy, local_files_only=True)
    return build_event_intelligence(
        events,
        paths.workspace_root / "universe/source_v1",
        sec_metadata_dir,
        output_dir,
        provider=None,
        model_name=protocol.extraction_model,
        provider_config={"max_tokens": 1600, "seed": protocol.seed},
        sentiment_backend=backend,
        sentiment_policy=policy,
        cache_workspace=cache_workspace,
        catalyst_max_events=1,
        max_retries=protocol.extraction_retries,
        sec_user_agent=sec_user_agent,
        offline=offline,
        event_registry_id=registry_version,
        market_manifest_sha256=next(i["sha256"] for i in parent["inputs"] if i["role"] == "market"),
    )


def model_input_rows(
    frames: dict[str, pd.DataFrame], pairs: pd.DataFrame, intelligence_dir: Path
) -> pd.DataFrame:
    """The research job's model-input join (``model_job.train_research_models``), unchanged."""
    from structural_break.research.intelligence import METADATA_FEATURE_COLUMNS

    rows = frames["events"].merge(
        frames["features"], on="event_id", validate="one_to_one", suffixes=("", "_feature")
    )
    rows = rows.merge(
        frames["targets"][["event_id", "y_revert_success"]], on="event_id", validate="one_to_one"
    )
    rows = rows.merge(
        frames["partitions"][["event_id", "supervised_eligible"]],
        on="event_id",
        validate="one_to_one",
    )
    rows = rows.merge(
        pairs[["pair_id", "leg_a", "leg_b", "business_group"]], on="pair_id", validate="many_to_one"
    )
    mappings = pd.read_parquet(intelligence_dir / "event_mapping.parquet")
    key_columns = ["pair_id", "event_timestamp"]
    mappings["event_timestamp"] = pd.to_datetime(mappings["event_timestamp"], utc=True)
    rows["event_timestamp"] = pd.to_datetime(rows["event_timestamp"], utc=True)
    mappings = mappings.rename(columns={"event_id": "evidence_event_id"})
    rows = rows.merge(
        mappings[key_columns + ["evidence_event_id"]],
        on=key_columns,
        how="left",
        validate="many_to_one",
    )
    if rows["evidence_event_id"].isna().any():
        raise ValueError("Every new quantitative event requires an explicit text/UNKNOWN row")
    features = pd.read_parquet(intelligence_dir / "features.parquet").rename(
        columns={"event_id": "evidence_event_id"}
    )
    text_columns = (*EVENT_FEATURE_NAMES, *SENTIMENT_FEATURE_COLUMNS, *METADATA_FEATURE_COLUMNS)
    rows = rows.merge(
        features[["evidence_event_id", *text_columns]],
        on="evidence_event_id",
        how="left",
        validate="many_to_one",
    )
    rows["tone_aligned_contrast"] = rows["divergence_sign"] * rows["sentiment_net_contrast"]
    # No final-test event is catalyst-extracted (no provider). The scheduler must still select at
    # least one event, which would carry evidence_available = 1; it gets the value of every other
    # unscheduled event instead (the only column that differs, verified in the rehearsal).
    schedule = intelligence_dir / "catalyst_schedule.json"
    if schedule.exists():
        selected = set(json.loads(schedule.read_bytes()).get("selected_event_ids", []))
        rows.loc[rows["evidence_event_id"].isin(selected), "evidence_available"] = 0.0
    return rows


def _registry_ids(frozen: pd.DataFrame, registry_events: Path) -> dict[str, str]:
    """Frozen event id -> final-test registry event id, matched by pair and event timestamp."""
    events = pd.read_parquet(registry_events, columns=["event_id", "pair_id", "event_timestamp"])

    def keys(frame: pd.DataFrame) -> pd.Series:
        stamps = pd.to_datetime(frame["event_timestamp"], utc=True)
        return pd.Series(list(zip(frame["pair_id"], stamps, strict=True)), index=frame.index)

    registry_keys = keys(events)
    if registry_keys.duplicated().any():
        raise ValueError("Registry events are not unique by pair and timestamp")
    lookup = dict(zip(registry_keys, events["event_id"], strict=True))
    mapped = keys(frozen).map(lookup)
    if mapped.isna().any() or mapped.duplicated().any():
        raise ValueError("Frozen model inputs do not match the registry one to one")
    return dict(zip(frozen["event_id"], mapped, strict=True))


def extend_evaluation(
    paths: ProjectPaths,
    frozen_evaluation: Path,
    registry_version: str,
    intelligence_dir: Path,
    since: date,
    *,
    horizon: int = 20,
    labels: Path | None = None,
) -> dict[str, Any]:
    """Publish the final-test evaluation: frozen rows plus the new events' rows."""
    registry = _registered_manifest(paths, registry_version)
    if registry is None or registry["stage"] != "registry":
        raise ValueError("The final-test registry must be registered first")
    protocol = protocol_model(registry["protocol"])
    registry_dir = paths.artifacts / "research" / registry_version
    frames = {
        name: pd.read_parquet(registry_dir / f"h{horizon}_{name}.parquet")
        for name in ("events", "features", "targets", "partitions")
    }
    day = pd.to_datetime(frames["events"]["event_date"]).dt.date
    new_ids = set(frames["events"].loc[day.ge(since), "event_id"])
    frames = {name: frame[frame["event_id"].isin(new_ids)] for name, frame in frames.items()}
    pairs = pd.read_parquet(paths.workspace_root / "universe/source_v1/pair_universe.parquet")
    new_rows = model_input_rows(frames, pairs, intelligence_dir)
    if labels is not None:
        # Decision 120b: the frozen label rule applied after the unlock
        # (scripts/final_test_labels.py); eligibility as for every other labelled event.
        table = pd.read_parquet(labels).set_index("event_id")
        if not set(new_rows["event_id"]) <= set(table.index):
            raise ValueError("Final-test labels do not cover every new event")
        rows = table.loc[new_rows["event_id"]]
        complete = frames["features"].set_index("event_id").loc[new_rows["event_id"]]
        new_rows = new_rows.assign(
            y_revert_success=rows["y_revert_success"].to_numpy(),
            supervised_eligible=(
                rows["label_eligible"].astype(bool).to_numpy()
                & complete["feature_complete"].astype(bool).to_numpy()
            ),
        )
    frozen_inputs = pd.read_parquet(frozen_evaluation / "model_inputs.parquet")
    frozen_predictions = pd.read_parquet(frozen_evaluation / "predictions.parquet")
    # The registry's event ids derive from its market snapshot, which the splice changes, so
    # the frozen rows are re-keyed to the final-test registry's ids by pair and event
    # timestamp (Decision 120a); every frozen row must match exactly one registry event.
    renamed = _registry_ids(frozen_inputs, registry_dir / f"h{horizon}_events.parquet")
    frozen_inputs = frozen_inputs.assign(event_id=frozen_inputs["event_id"].map(renamed))
    frozen_predictions = frozen_predictions.assign(
        event_id=frozen_predictions["event_id"].map(renamed)
    )
    if frozen_predictions["event_id"].isna().any():
        raise ValueError("A frozen research prediction has no frozen model-input row")
    old_inputs = frozen_inputs[~frozen_inputs["event_id"].isin(new_ids)]
    model_inputs = pd.concat(
        [old_inputs, new_rows.loc[:, list(frozen_inputs.columns)]], ignore_index=True
    )
    # The research models score only fit, calibration and assessment rows; like every other
    # excluded event, final-test events have no research prediction row.
    predictions = frozen_predictions
    frozen_manifest = json.loads((frozen_evaluation / "manifest.json").read_bytes())
    inputs = {
        "registry_version": registry_version,
        "registry_manifest_sha256": sha256_file(registry_dir / "manifest.json"),
        "intelligence_manifest_sha256": sha256_file(intelligence_dir / "manifest.json"),
        "frozen_evaluation_manifest_sha256": sha256_file(frozen_evaluation / "manifest.json"),
        "horizon": horizon,
        "since": since.isoformat(),
        "decision": "DECISIONS 118",
        "frozen_rows_rekeyed": "pair_id+event_timestamp (DECISIONS 120a)",
        "final_test_labels_sha256": sha256_file(labels) if labels is not None else None,
    }
    generation = "research_evaluation_" + identity(inputs)[:24]
    existing = _registered_manifest(paths, generation)
    if existing is not None:
        return existing
    directory = paths.artifacts / "research" / generation
    shutil.copytree(frozen_evaluation / "models", directory / "models", dirs_exist_ok=True)
    report = write_bytes(
        directory / "report.json", (frozen_evaluation / "report.json").read_bytes()
    )
    universe = UniverseConfig(
        version="research-v2-survivor-peers",
        orientation="leg_a_is_y",
        pairs=tuple(
            Pair(leg_a=r["leg_a"], leg_b=r["leg_b"], peer_group=r["peer_group"])
            for r in pairs.to_dict("records")
        ),
    )
    config = experiment_config(
        load_config(paths.project_root / "configs"), protocol, universe, horizon
    )
    final_read = protocol.development_end > periods.DEVELOPMENT_END
    manifest: dict[str, Any] = {
        "identity_inputs": inputs,
        "model_files": frozen_manifest["model_files"],
        "report_sha256": sha256_file(report),
        "final_test_read": final_read,
        "parents": [
            {
                "role": role,
                "path": path.relative_to(paths.workspace_root).as_posix(),
                "sha256": sha256_file(path),
            }
            for role, path in (
                ("registry", registry_dir / "manifest.json"),
                ("intelligence", intelligence_dir / "manifest.json"),
                ("frozen_evaluation", frozen_evaluation / "manifest.json"),
            )
        ],
    }
    return publish_research(
        paths,
        config,
        protocol,
        "evaluation",
        generation,
        directory,
        manifest,
        {"predictions": predictions, "model_inputs": model_inputs},
    )


def write_binding(paths: ProjectPaths, evaluation_version: str) -> Path:
    """Point ``pipeline.sources._sources`` at the final-test evaluation of this workspace."""
    manifest = paths.artifacts / "research" / evaluation_version / "manifest.json"
    record = {
        "evaluation_manifest": manifest.relative_to(paths.workspace_root).as_posix(),
        "evaluation_sha256": sha256_file(manifest),
        "decision": "DECISIONS 118",
    }
    return write_bytes(paths.workspace_root / BINDING, canonical_bytes(record))


# --------------------------------------------------------------------------- #
# Price splice (Decision 118): frozen raw rows through the development cut, new rows after it
# rescaled so the cut day's close and adjusted close equal the frozen values.
# --------------------------------------------------------------------------- #

YAHOO_NAMES = {
    "open": "Open",
    "high": "High",
    "low": "Low",
    "close": "Close",
    "adj_close": "Adj Close",
    "volume": "Volume",
    "dividends": "Dividends",
    "stock_splits": "Stock Splits",
}


def _yahoo_frame(ticker: str, rows: pd.DataFrame) -> pd.DataFrame:
    """Rows in the layout ``yfinance.download(group_by="ticker")`` returns."""
    frame = rows.set_index(pd.DatetimeIndex(pd.to_datetime(rows["trading_date"])))
    frame = frame.loc[:, list(YAHOO_NAMES)].rename(columns=YAHOO_NAMES)
    frame.columns = pd.MultiIndex.from_product([[ticker], list(frame.columns)])
    return frame


def splice(frozen: pd.DataFrame, new: pd.DataFrame, cut: date) -> pd.DataFrame:
    """Frozen rows through ``cut``; new rows after it, scaled to the frozen level on ``cut``."""
    old = frozen.loc[pd.to_datetime(frozen["trading_date"]).dt.date.le(cut)]
    days = pd.to_datetime(new["trading_date"]).dt.date
    anchor_old = old.loc[pd.to_datetime(old["trading_date"]).dt.date.eq(cut)]
    anchor_new = new.loc[days.eq(cut)]
    if len(anchor_old) != 1 or len(anchor_new) != 1:
        raise ValueError(f"Both captures need the cut day {cut} to splice")
    price = float(anchor_old["close"].iloc[0]) / float(anchor_new["close"].iloc[0])
    adjusted = float(anchor_old["adj_close"].iloc[0]) / float(anchor_new["adj_close"].iloc[0])
    after = new.loc[days.gt(cut)].copy()
    for column in ("open", "high", "low", "close"):
        after[column] = after[column] * price
    after["adj_close"] = after["adj_close"] * adjusted
    after["volume"] = after["volume"] / price
    after["dividends"] = after["dividends"] * price
    return pd.concat(
        [
            old.loc[:, list(YAHOO_NAMES) + ["trading_date"]],
            after.loc[:, list(YAHOO_NAMES) + ["trading_date"]],
        ],
        ignore_index=True,
    )


def splice_downloader(frozen_raw: Path, cut: date, live: Any = None) -> Any:
    """A ``collect_market`` downloader: frozen raw rows plus spliced live rows, per ticker."""
    from structural_break.data.market import YAHOO_FIELDS

    def download(tickers: list[str], start: str, end: str, **kwargs: Any) -> pd.DataFrame:
        if len(tickers) != 1:
            raise ValueError("The splice downloader serves one ticker per request")
        ticker = tickers[0]
        frozen = pd.read_parquet(frozen_raw / f"{ticker}.parquet")
        source = live
        if source is None:
            import yfinance

            source = yfinance.download
        window_start = (pd.Timestamp(cut) - pd.Timedelta(days=60)).date().isoformat()
        batch = source([ticker], start=window_start, end=end, **kwargs)
        raw = pd.DataFrame(batch.xs(ticker, axis=1, level=0)).rename(columns=YAHOO_FIELDS)
        raw.insert(0, "trading_date", pd.DatetimeIndex(raw.index).date)
        raw = raw.reset_index(drop=True)
        return _yahoo_frame(ticker, splice(frozen, raw, cut))

    return download
