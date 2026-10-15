"""Spawned complete-event replay must preserve every serial scientific check."""

import json
import os
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import yaml
from test_research_intelligence import Tone, provider, source

from structural_break.config.models import ProjectConfig
from structural_break.research import intelligence
from structural_break.research.event_replay import (
    EventReplayTask,
    parallel_source_replay,
    source_partitions,
)
from structural_break.research.intelligence import (
    build_event_intelligence,
    collect_sec_metadata,
    verify_event_intelligence,
)
from structural_break.research.universe import freeze_universe
from structural_break.storage.files import sha256_file


@pytest.fixture
def four_group_freeze(tmp_path: Path, project_root: Path, config: ProjectConfig) -> Path:
    payload = yaml.safe_load(
        (project_root / "configs/research_v2_universe.yaml").read_text(encoding="utf-8")
    )
    payload["groups"] = payload["groups"][:4]
    for group in payload["groups"]:
        group["tickers"] = group["tickers"][:2]
    payload["issuer_rules"] = {}
    tickers = [ticker for group in payload["groups"] for ticker in group["tickers"]]
    path = tmp_path / "four_groups.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    config_payload = config.model_dump(mode="json")
    config_payload["universe"]["pairs"] = config_payload["universe"]["pairs"][:1]
    small = ProjectConfig.model_validate(config_payload)
    directory = json.dumps(
        {
            str(index): {
                "ticker": ticker,
                "cik_str": 9000000 + index,
                "title": f"Fixture {ticker}",
            }
            for index, ticker in enumerate(tickers)
        }
    ).encode()
    output = tmp_path / "freeze"
    freeze_universe(path, small, directory, output)
    return output


@pytest.fixture
def event_batch(four_group_freeze: Path, tmp_path: Path) -> dict[str, Any]:
    freeze = four_group_freeze
    metadata, output = tmp_path / "metadata", tmp_path / "intelligence"
    collect_sec_metadata(freeze, metadata, get=source([], missing_acceptance=True))
    pairs = pd.read_parquet(freeze / "pair_universe.parquet")
    pair_ids = pairs["pair_id"].tolist()
    assert len(pair_ids) == pairs["business_group"].nunique() == 4
    events = pd.DataFrame(
        [
            {
                "event_id": f"fixture-{index}",
                "pair_id": pair_ids[index % 4],
                "event_timestamp": timestamp,
            }
            for index, timestamp in enumerate(
                (
                    "2022-03-12T21:00:00Z",
                    "2010-02-04T21:00:00Z",
                    "2022-03-10T21:00:00Z",
                    "2022-02-04T21:00:00Z",
                    "2010-02-05T21:00:00Z",
                    "2022-03-11T21:00:00Z",
                    "2022-02-07T21:00:00Z",
                    "2022-03-14T21:00:00Z",
                )
            )
        ]
    )
    calls: list[str] = []
    manifest = build_event_intelligence(
        events,
        freeze,
        metadata,
        output,
        provider=provider(calls),
        get=source([], missing_acceptance=True),
        sentiment_backend=Tone(),
        catalyst_max_events=2,
    )
    assert manifest["event_count"] == manifest["scheduled_event_count"] == 8
    assert manifest["catalyst_scheduled_event_count"] == len(calls) == 2
    return {"freeze": freeze, "metadata": metadata, "output": output, "manifest": manifest}


def test_four_process_reconstruction_matches_serial_values_order_and_coverage(
    event_batch: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    batch = event_batch
    output = batch["output"]
    original_files = {name: sha256_file(output / name) for name in batch["manifest"]["files"]}
    stored_features = pd.read_parquet(output / "features.parquet")
    reconstructed: list[pd.DataFrame] = []
    original_assert = pd.testing.assert_frame_equal

    def compare(left, right, *args, **kwargs):
        if list(left.columns) == list(stored_features.columns):
            reconstructed.append(right.copy(deep=True))
        return original_assert(left, right, *args, **kwargs)

    def forbidden(*args, **kwargs):
        pytest.fail("Source verification must not perform provider or neural inference")

    monkeypatch.setattr(pd.testing, "assert_frame_equal", compare)
    monkeypatch.setattr(intelligence, "extract_pack", forbidden)
    monkeypatch.setattr(intelligence, "score_sentiment_pack", forbidden)
    progress: dict[int, list[dict[str, Any]]] = {}
    process_sets: list[set[int]] = []
    for workers in (0, 4, 4):
        observed: list[dict[str, Any]] = []
        progress[workers] = observed
        assert (
            verify_event_intelligence(
                output,
                batch["freeze"],
                batch["metadata"],
                event_workers=workers,
                progress=observed.append,
            )
            == batch["manifest"]
        )
        assert observed[-1]["stage"] == "SOURCE_VERIFICATION_COMPLETE"
        assert observed[-1]["verified_source_events"] == 8
        assert observed[-1]["total_source_events"] == 8
        counts = [row["verified_source_events"] for row in observed]
        assert counts == sorted(counts)
        if workers:
            process_sets.append(set(observed[-1]["worker_pids"]))
    assert len(reconstructed) == 3
    original_assert(reconstructed[0], reconstructed[1])
    original_assert(reconstructed[1], reconstructed[2])
    original_assert(stored_features, reconstructed[1], check_dtype=False)
    assert reconstructed[1]["event_id"].tolist() == stored_features["event_id"].tolist()
    assert not reconstructed[1]["event_id"].duplicated().any()
    assert set(reconstructed[1]["event_id"]) == {f"fixture-{index}" for index in range(8)}
    assert any(row["event_workers"] == 4 for row in progress[4])
    worker_pids = progress[4][-1]["worker_pids"]
    assert len(worker_pids) == len(set(worker_pids)) == 4
    assert os.getpid() not in worker_pids
    assert len(process_sets) == 2 and not process_sets[0].intersection(process_sets[1])
    worker_rows = progress[4][-1]["worker_progress"]
    assert {row["slot"] for row in worker_rows} == {0, 1, 2, 3}
    assert {row["pid"] for row in worker_rows} == set(worker_pids)
    assert sum(row["verified_source_events"] for row in worker_rows) == 8
    assert sum(row["total_source_events"] for row in worker_rows) == 8
    assert all(row["total_source_events"] == 2 for row in worker_rows)
    assert all(row["verified_source_events"] == row["total_source_events"] for row in worker_rows)
    assert {
        name: sha256_file(output / name) for name in batch["manifest"]["files"]
    } == original_files


def test_four_process_reconstruction_cannot_hide_changed_raw_source(
    event_batch: dict[str, Any],
) -> None:
    batch = event_batch
    # Raw bodies are independently checked in the workers, beyond checkpoint hashes.
    target = next((batch["output"] / "data/raw/sec/filings").glob("**/primary_document.html"))
    target.write_bytes(target.read_bytes() + b"changed source")
    observed: list[dict[str, Any]] = []
    with pytest.raises(ValueError, match="hash mismatch|checksum|provenance"):
        verify_event_intelligence(
            batch["output"],
            batch["freeze"],
            batch["metadata"],
            event_workers=4,
            progress=observed.append,
        )
    assert all(row["stage"] != "SOURCE_VERIFICATION_COMPLETE" for row in observed)


def test_four_process_replay_completes_when_three_shards_have_no_events(
    four_group_freeze: Path, tmp_path: Path
) -> None:
    metadata, output = tmp_path / "metadata", tmp_path / "one-event"
    collect_sec_metadata(four_group_freeze, metadata, get=source([]))
    pair_id = pd.read_parquet(four_group_freeze / "pair_universe.parquet")["pair_id"].iloc[0]
    events = pd.DataFrame(
        [{"event_id": "only-event", "pair_id": pair_id, "event_timestamp": "2022-03-10T21:00:00Z"}]
    )
    manifest = build_event_intelligence(
        events,
        four_group_freeze,
        metadata,
        output,
        provider=None,
        get=source([]),
        sentiment_backend=Tone(),
    )
    observed: list[dict[str, Any]] = []
    assert (
        verify_event_intelligence(
            output, four_group_freeze, metadata, event_workers=4, progress=observed.append
        )
        == manifest
    )
    final = observed[-1]
    assert final["stage"] == "SOURCE_VERIFICATION_COMPLETE"
    assert final["verified_source_events"] == final["total_source_events"] == 1
    assert len(final["worker_pids"]) == len(set(final["worker_pids"])) == 4
    assert sorted(row["total_source_events"] for row in final["worker_progress"]) == [0, 0, 0, 1]
    assert sum(row["verified_source_events"] for row in final["worker_progress"]) == 1


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "reordered"])
def test_four_process_reconstruction_rejects_incomplete_or_reordered_checkpoints(
    event_batch: dict[str, Any], mutation: str
) -> None:
    batch = event_batch
    manifest = batch["manifest"]
    records = manifest["source_identity"]["records"]
    if mutation == "missing":
        records.pop()
    elif mutation == "duplicate":
        records[-1] = records[0]
    else:
        records[0], records[-1] = records[-1], records[0]
    # Reseal only this synthetic test manifest, so rejection exercises population
    # and canonical-event checks rather than stopping at an outer identity digest.
    manifest["intelligence_version"] = (
        "research_intelligence_" + intelligence._sha(manifest["source_identity"])[:24]
    )
    (batch["output"] / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="exact event registry|event or label-blind scheduling"):
        verify_event_intelligence(
            batch["output"], batch["freeze"], batch["metadata"], event_workers=4
        )


@pytest.mark.parametrize("workers", [-1, 1, 2, 3, 5, True])
def test_event_worker_count_is_explicit_and_bounded(tmp_path: Path, workers: int) -> None:
    with pytest.raises(ValueError, match="event.*worker|Event.*worker"):
        verify_event_intelligence(tmp_path, tmp_path, tmp_path, event_workers=workers)


def test_four_event_workers_cannot_nest_additional_parsing_processes(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="combine|nested|nest"):
        verify_event_intelligence(tmp_path, tmp_path, tmp_path, event_workers=4, parsing_workers=2)


def test_partitions_cover_every_index_once_and_preserve_whole_business_groups() -> None:
    pairs = pd.DataFrame(
        [
            {"pair_id": f"pair-{index}", "business_group": f"group-{index // 2}"}
            for index in range(10)
        ]
    )
    events = [
        {"event_id": f"event-{index}", "pair_id": f"pair-{index % 10}"} for index in range(33)
    ]
    partitions = source_partitions(events, pairs)
    assert len(partitions) == 4
    assert sorted(index for partition in partitions for index in partition) == list(range(33))
    assert all(list(partition) == sorted(partition) for partition in partitions)
    ownership: dict[str, set[int]] = {}
    groups = pairs.set_index("pair_id")["business_group"].to_dict()
    for slot, partition in enumerate(partitions):
        for index in partition:
            ownership.setdefault(groups[events[index]["pair_id"]], set()).add(slot)
    assert all(len(slots) == 1 for slots in ownership.values())
    assert partitions == source_partitions(events, pairs.iloc[::-1])


@pytest.mark.parametrize("indices", [((0,), (0,), (), ()), ((0,), (2,), (), ())])
def test_parallel_coordinator_rejects_duplicate_or_missing_assignment_before_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, indices: tuple[tuple[int, ...], ...]
) -> None:
    import structural_break.research.event_replay as replay

    def forbidden(*args, **kwargs):
        pytest.fail("Invalid event coverage must fail before creating processes")

    monkeypatch.setattr(replay, "get_context", forbidden)
    tasks = [
        EventReplayTask(
            slot=slot,
            indices=assigned,
            canonical_rows=[],
            records=[],
            file_hashes={},
            directory=tmp_path,
            cache_root=tmp_path,
            filings=pd.DataFrame(),
            coverage={},
            inputs={},
            catalyst_ids=set(),
        )
        for slot, assigned in enumerate(indices)
    ]
    with pytest.raises(ValueError, match="cover every canonical index once"):
        parallel_source_replay(tasks, lambda _: None)
