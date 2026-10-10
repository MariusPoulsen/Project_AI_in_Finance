"""Offline engineering resume checks never replace independent evidence replay."""

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import yaml

from structural_break.config.models import ProjectConfig
from structural_break.data.http import FetchedResponse
from structural_break.intelligence.sentiment import (
    FINBERT_ASSETS_SHA256,
    FINBERT_MODEL,
    FINBERT_REVISION,
    QUALITY_PREPROCESSING_VERSION,
    FinBERTPolicy,
)
from structural_break.research import intelligence
from structural_break.research.checkpoints import (
    prepare_checkpoint_audit,
    verify_checkpoint_audit,
)
from structural_break.research.universe import freeze_universe, json_bytes
from structural_break.storage.files import sha256_file


class Tone:
    model_name, model_revision = FINBERT_MODEL, FINBERT_REVISION
    runtime = {"model_assets_sha256": dict(FINBERT_ASSETS_SHA256)}

    def token_ids(self, text: str) -> list[int]:
        return list(range(1, len(text.split()) + 1))

    def predict(self, windows: list[list[int]]) -> list[dict[str, float]]:
        return [{"positive": 0.7, "negative": 0.1, "neutral": 0.2} for _ in windows]


@pytest.fixture
def batch(tmp_path: Path, project_root: Path, config: ProjectConfig) -> dict[str, Any]:
    roster = yaml.safe_load((project_root / "configs/research_v2_universe.yaml").read_bytes())
    roster["groups"] = [roster["groups"][0]]
    roster["groups"][0]["tickers"] = ["KO", "PEP", "KDP"]
    roster["issuer_rules"] = {}
    roster_path = tmp_path / "roster.yaml"
    roster_path.write_text(yaml.safe_dump(roster), encoding="utf-8")
    settings = config.model_dump(mode="json")
    settings["universe"]["pairs"] = settings["universe"]["pairs"][:1]
    directory = json.dumps(
        {
            str(i): {"ticker": ticker, "cik_str": 9000000 + i, "title": ticker}
            for i, ticker in enumerate(("KO", "PEP", "KDP"))
        }
    ).encode()
    universe = tmp_path / "universe"
    freeze_universe(roster_path, ProjectConfig.model_validate(settings), directory, universe)

    def get(url: str) -> FetchedResponse:
        if "submissions/" in url:
            cik = url.split("CIK")[1][:10]
            body = json.dumps(
                {
                    "cik": int(cik),
                    "filings": {
                        "recent": {
                            "accessionNumber": [f"{cik}-22-000001"],
                            "form": ["10-K"],
                            "filingDate": ["2022-03-08"],
                            "reportDate": ["2021-12-31"],
                            "acceptanceDateTime": ["2022-03-08T16:30:00-05:00"],
                            "primaryDocument": ["report.htm"],
                        },
                        "files": [],
                    },
                }
            ).encode()
        elif url.endswith("index.json"):
            body = b'{"directory":{"item":[{"name":"report.htm","type":"file"}]}}'
        elif url.endswith(".txt"):
            body = (
                b"<ACCEPTANCE-DATETIME>20220308163000\n<DOCUMENT>\n<TYPE>10-K\n"
                b"<SEQUENCE>1\n<FILENAME>report.htm\n<TEXT><p>Sales grew substantially.</p>"
                b"</TEXT>\n</DOCUMENT>"
            )
        else:
            body = b"<html><body><p>Sales grew substantially.</p></body></html>"
        return FetchedResponse(body, url, 200, datetime(2026, 10, 6, tzinfo=UTC))

    metadata = tmp_path / "metadata"
    intelligence.collect_sec_metadata(universe, metadata, get=get)
    events = pd.DataFrame(
        [
            {"event_id": "one", "pair_id": "KO__PEP", "event_timestamp": "2022-03-10T21:00Z"},
            {"event_id": "two", "pair_id": "KO__PEP", "event_timestamp": "2022-03-11T21:00Z"},
        ]
    )
    old = tmp_path / "old"
    workspace = tmp_path / "workspace"
    manifest = intelligence.build_event_intelligence(
        events,
        universe,
        metadata,
        old,
        provider=None,
        sentiment_backend=Tone(),
        sentiment_policy=FinBERTPolicy(preprocessing_version=QUALITY_PREPROCESSING_VERSION),
        catalyst_max_events=1,
        event_registry_id="frozen-registry-fixture",
        cache_workspace=workspace,
        get=get,
    )
    (old / "manifest.json").unlink()
    baseline = tmp_path / "preserved.json"
    baseline.write_bytes(
        json_bytes(
            {
                "recorded_processes_absent": True,
                "checkpoint_count": 2,
                "inputs_sha256": sha256_file(old / "inputs.json"),
                "catalyst_schedule_sha256": sha256_file(old / "catalyst_schedule.json"),
                "checkpoint_inventory": [
                    {
                        "filename": path.name,
                        "sha256": sha256_file(path),
                        "size_bytes": path.stat().st_size,
                    }
                    for path in sorted((old / "events").iterdir())
                ],
            }
        )
    )
    new = tmp_path / "new"
    shutil.copytree(old / "events", new / "events")
    inputs = dict(manifest["inputs"], code_sha256="a" * 64)
    return {
        "source_dir": old,
        "events": events,
        "expected_inputs": inputs,
        "expected_schedule": json.loads((old / "catalyst_schedule.json").read_bytes()),
        "frozen_universe_dir": universe,
        "sec_metadata_dir": metadata,
        "cache_workspace": workspace,
        "target_dir": new,
        "baseline_receipt_path": baseline,
        "baseline_receipt_sha256": sha256_file(baseline),
        "receipt_path": tmp_path / "audit.json",
    }


def verify(batch: dict[str, Any]):
    return verify_checkpoint_audit(
        batch["receipt_path"],
        batch["target_dir"],
        batch["expected_inputs"],
        batch["events"],
        batch["expected_schedule"],
        frozen_universe_dir=batch["frozen_universe_dir"],
        sec_metadata_dir=batch["sec_metadata_dir"],
        cache_workspace=batch["cache_workspace"],
        expected_audit_sha256=sha256_file(batch["receipt_path"]),
    )


def test_builder_fast_recovery_keeps_independent_raw_verification(
    batch: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    batch["expected_inputs"]["code_sha256"] = sha256_file(Path(intelligence.__file__))
    prepare_checkpoint_audit(**batch)
    original_pack = intelligence._event_pack
    original_tone_validation = intelligence.validate_sentiment_result

    def forbidden(*args, **kwargs):
        pytest.fail("Audited builder prefix must not reparse or revalidate stored tone")

    monkeypatch.setattr(intelligence, "_event_pack", forbidden)
    monkeypatch.setattr(intelligence, "validate_sentiment_result", forbidden)
    result = intelligence.build_event_intelligence(
        batch["events"],
        batch["frozen_universe_dir"],
        batch["sec_metadata_dir"],
        batch["target_dir"],
        provider=None,
        sentiment_backend=Tone(),
        sentiment_policy=FinBERTPolicy(preprocessing_version=QUALITY_PREPROCESSING_VERSION),
        catalyst_max_events=1,
        event_registry_id="frozen-registry-fixture",
        cache_workspace=batch["cache_workspace"],
        get=forbidden,
        resume_audit=batch["receipt_path"],
        resume_audit_sha256=sha256_file(batch["receipt_path"]),
    )
    assert result["event_count"] == 2 and result["all_events_retained"] is True
    assert result["checkpoint_recovery"]["independent_full_raw_verification_complete"] is False
    calls = []

    def fresh_pack(*args, **kwargs):
        calls.append(args[0]["event_id"])
        return original_pack(*args, **kwargs)

    monkeypatch.setattr(intelligence, "_event_pack", fresh_pack)
    monkeypatch.setattr(intelligence, "validate_sentiment_result", original_tone_validation)
    assert (
        intelligence.verify_event_intelligence(
            batch["target_dir"],
            batch["frozen_universe_dir"],
            batch["sec_metadata_dir"],
            cache_workspace=batch["cache_workspace"],
        )
        == result
    )
    assert calls == ["one", "two"]


def test_resume_validates_once_without_parsing_provider_or_neural_calls(
    batch: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args, **kwargs):
        pytest.fail("Resume audit cannot parse raw HTML or invoke inference/provider")

    monkeypatch.setattr(intelligence, "_event_pack", forbidden)
    monkeypatch.setattr(intelligence, "parse_documents", forbidden)
    monkeypatch.setattr(intelligence, "extract_pack", forbidden)
    monkeypatch.setattr(intelligence, "score_sentiment_pack", forbidden)
    original = {path.name: path.read_bytes() for path in (batch["source_dir"] / "events").iterdir()}
    receipt = prepare_checkpoint_audit(**batch)
    assert receipt["checkpoint_count"] == receipt["event_count"] == 2
    assert receipt["raw_text_reconstructed"] is False
    assert receipt["independent_verification_accepted"] is False
    assert receipt["final_test_outcomes_inspected"] is False
    assert receipt["neural_or_provider_calls"] == 0
    assert (
        len([name for name in receipt["source_files"] if name.endswith("response_manifest.json")])
        == 2
    )
    monkeypatch.setattr(
        "structural_break.research.checkpoints.validate_sentiment_result", forbidden
    )
    audited = verify(batch)
    for filename in audited.checkpoints:
        record = audited.load_record(filename)
        assert audited.tone_features(filename) == record["tone"]["features"]
    assert original == {
        path.name: path.read_bytes() for path in (batch["source_dir"] / "events").iterdir()
    }


@pytest.mark.parametrize("change", ["policy", "registry", "population", "schedule", "provider"])
def test_frozen_scientific_input_changes_cannot_reuse_checkpoint_audit(
    batch: dict[str, Any], change: str
) -> None:
    inputs = batch["expected_inputs"]
    if change == "policy":
        inputs["sentiment_policy"] = dict(inputs["sentiment_policy"], max_windows_per_chunk=2)
    elif change == "registry":
        inputs["event_registry_id"] = "other-registry"
    elif change == "population":
        inputs["max_events"] = 1
    elif change == "schedule":
        inputs["catalyst_max_events"] = 2
    else:
        inputs["model"] = "other-provider-model"
    with pytest.raises(ValueError, match="scientific batch input"):
        prepare_checkpoint_audit(**batch)


def test_preserved_baseline_detects_checkpoint_tampering_before_audit(
    batch: dict[str, Any],
) -> None:
    path = next((batch["source_dir"] / "events").iterdir())
    path.write_bytes(path.read_bytes().replace(b"Sales grew", b"Sales fell"))
    with pytest.raises(ValueError, match="Preserved checkpoint"):
        prepare_checkpoint_audit(**batch)


def test_source_tampering_rejected_before_audit(batch: dict[str, Any]) -> None:
    path = next((batch["cache_workspace"] / "data/raw/sec/filings").rglob("primary_document.html"))
    path.write_bytes(b"changed raw filing")
    with pytest.raises(ValueError, match="response hash mismatch"):
        prepare_checkpoint_audit(**batch)


@pytest.mark.parametrize("changed", ["copied_checkpoint", "source", "parent"])
def test_changed_bytes_rejected_when_loading_preflight_audit(
    batch: dict[str, Any], changed: str
) -> None:
    receipt = prepare_checkpoint_audit(**batch)
    if changed == "copied_checkpoint":
        path = next((batch["target_dir"] / "events").iterdir())
    elif changed == "source":
        path = batch["cache_workspace"] / next(iter(receipt["source_files"]))
    else:
        path = batch["frozen_universe_dir"] / "roster.yaml"
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="checksum differs"):
        verify(batch)


def test_checkpoint_is_rechecked_at_actual_reuse(batch: dict[str, Any]) -> None:
    prepare_checkpoint_audit(**batch)
    audited = verify(batch)
    filename = next(iter(audited.checkpoints))
    path = batch["target_dir"] / filename
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="changed before reuse"):
        audited.load_record(filename)


def test_changed_audit_receipt_cannot_pass_bound_launch_digest(batch: dict[str, Any]) -> None:
    prepare_checkpoint_audit(**batch)
    digest = sha256_file(batch["receipt_path"])
    receipt = json.loads(batch["receipt_path"].read_bytes())
    entry = next(iter(receipt["checkpoints"].values()))
    entry["tone_features"]["sentiment_a_positive"] = 0.9
    batch["receipt_path"].write_bytes(json_bytes(receipt))
    with pytest.raises(ValueError, match="receipt checksum differs"):
        verify_checkpoint_audit(
            batch["receipt_path"],
            batch["target_dir"],
            batch["expected_inputs"],
            batch["events"],
            batch["expected_schedule"],
            frozen_universe_dir=batch["frozen_universe_dir"],
            sec_metadata_dir=batch["sec_metadata_dir"],
            cache_workspace=batch["cache_workspace"],
            expected_audit_sha256=digest,
        )


def test_forged_event_identity_fails_even_with_recaptured_baseline(batch: dict[str, Any]) -> None:
    path = next((batch["source_dir"] / "events").iterdir())
    record = json.loads(path.read_bytes())
    record["event"]["event_timestamp"] = "2025-01-01T21:00:00+00:00"
    path.write_bytes(json_bytes(record))
    baseline = json.loads(batch["baseline_receipt_path"].read_bytes())
    entry = next(row for row in baseline["checkpoint_inventory"] if row["filename"] == path.name)
    entry.update(sha256=sha256_file(path), size_bytes=path.stat().st_size)
    batch["baseline_receipt_path"].write_bytes(json_bytes(baseline))
    batch["baseline_receipt_sha256"] = sha256_file(batch["baseline_receipt_path"])
    with pytest.raises(ValueError, match="event identity"):
        prepare_checkpoint_audit(**batch)


def test_missing_checkpoint_is_not_a_complete_population_claim(batch: dict[str, Any]) -> None:
    path = next((batch["source_dir"] / "events").iterdir())
    path.unlink()
    (batch["target_dir"] / "events" / path.name).unlink()
    baseline = json.loads(batch["baseline_receipt_path"].read_bytes())
    baseline["checkpoint_inventory"] = [
        row for row in baseline["checkpoint_inventory"] if row["filename"] != path.name
    ]
    baseline["checkpoint_count"] = 1
    batch["baseline_receipt_path"].write_bytes(json_bytes(baseline))
    batch["baseline_receipt_sha256"] = sha256_file(batch["baseline_receipt_path"])
    receipt = prepare_checkpoint_audit(**batch)
    assert receipt["checkpoint_count"] == 1 and receipt["event_count"] == 2
    assert len(verify(batch).checkpoints) == 1


def test_sgml_clock_is_checked_even_if_changed_response_hashes_are_consistent(
    batch: dict[str, Any],
) -> None:
    from hashlib import sha256

    path = next(
        (batch["cache_workspace"] / "data/raw/sec/filings").rglob("complete_submission.txt")
    )
    path.write_bytes(path.read_bytes().replace(b"20220308163000", b"20250308163000"))
    digest = sha256(path.read_bytes()).hexdigest()
    sidecar = path.with_name(path.name + ".response.json")
    response = json.loads(sidecar.read_bytes())
    response["sha256"] = digest
    sidecar.write_bytes(json_bytes(response))
    manifest_path = path.parent / "response_manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    row = next(row for row in manifest["documents"] if row["document_type"] == "SUBMISSION")
    row["sha256"] = digest
    manifest_path.write_bytes(json_bytes(manifest))
    with pytest.raises(ValueError, match="submission acceptance contradicts"):
        prepare_checkpoint_audit(**batch)


def test_stored_inference_must_retain_pinned_asset_identity(batch: dict[str, Any]) -> None:
    path = next((batch["source_dir"] / "events").iterdir())
    record = json.loads(path.read_bytes())
    record["tone"]["chunks"][0]["runtime"]["model_assets_sha256"]["vocab.txt"] = "0" * 64
    path.write_bytes(json_bytes(record))
    baseline = json.loads(batch["baseline_receipt_path"].read_bytes())
    entry = next(row for row in baseline["checkpoint_inventory"] if row["filename"] == path.name)
    entry.update(sha256=sha256_file(path), size_bytes=path.stat().st_size)
    batch["baseline_receipt_path"].write_bytes(json_bytes(baseline))
    batch["baseline_receipt_sha256"] = sha256_file(batch["baseline_receipt_path"])
    with pytest.raises(ValueError, match="pinned model assets"):
        prepare_checkpoint_audit(**batch)
