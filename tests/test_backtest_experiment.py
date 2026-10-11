"""Adversarial persistence/replay checks for explicitly synthetic experiments."""

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from structural_break.backtest import cli, experiment
from structural_break.backtest.experiment import (
    ARTIFACT_NAMES,
    ExperimentManifest,
    LadderInputDocument,
    checksum,
    run_ladder_experiment,
    strict_json,
    verify_ladder_experiment,
)
from structural_break.backtest.ladder_fixtures import fixture_ladder
from structural_break.backtest.simulator import canonical_bytes


def publish(output_dir: Path) -> Path:
    events, policy, execution, labels = fixture_ladder()
    return run_ladder_experiment(events, policy, execution, output_dir, labels=labels)


def rehash_output(manifest_path: Path, name: str, content: bytes) -> None:
    """Simulate an attacker changing an output AND its declared checksum."""
    (manifest_path.parent / name).write_bytes(content)
    payload = json.loads(manifest_path.read_bytes())
    for binding in payload["artifacts"]:
        if binding["path"] == name:
            binding.update(sha256=checksum(content), size_bytes=len(content))
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")


def test_publication_is_immutable_idempotent_and_replayable(tmp_path: Path) -> None:
    manifest_path = publish(tmp_path)
    before = {path.name: path.read_bytes() for path in manifest_path.parent.iterdir()}
    assert publish(tmp_path) == manifest_path
    assert before == {path.name: path.read_bytes() for path in manifest_path.parent.iterdir()}
    result = verify_ladder_experiment(manifest_path)
    assert result["status"] == "VERIFIED_SYNTHETIC_REPLAY"
    assert result["event_count"] == 14
    assert result["scientific_acceptance"] is False
    assert result["genuine_quality_evidence"] is False
    assert result["final_test_unlocked"] is False
    assert before == {path.name: path.read_bytes() for path in manifest_path.parent.iterdir()}


def test_manifest_is_published_last_and_partial_publication_resumes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = experiment.write_bytes
    published: list[str] = []

    def interrupted(path: Path, content: bytes) -> Path:
        if path.name == "rows.json":
            raise OSError("synthetic interrupted publication")
        published.append(path.name)
        return original(path, content)

    monkeypatch.setattr(experiment, "write_bytes", interrupted)
    with pytest.raises(OSError, match="interrupted publication"):
        publish(tmp_path)
    assert not list(tmp_path.rglob("manifest.json"))
    assert published == list(ARTIFACT_NAMES[:4])
    monkeypatch.setattr(experiment, "write_bytes", original)
    manifest = publish(tmp_path)
    assert verify_ladder_experiment(manifest)["event_count"] == 14


def test_existing_conflicting_output_is_never_overwritten(tmp_path: Path) -> None:
    manifest = publish(tmp_path)
    report = manifest.parent / "report.json"
    report.write_bytes(b"corrupted")
    with pytest.raises(FileExistsError, match="Immutable file already exists"):
        publish(tmp_path)
    assert report.read_bytes() == b"corrupted"


@pytest.mark.parametrize("name", ARTIFACT_NAMES)
def test_each_artifact_checksum_is_enforced(tmp_path: Path, name: str) -> None:
    manifest = publish(tmp_path)
    path = manifest.parent / name
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError, match="checksum/size mismatch"):
        verify_ladder_experiment(manifest)


def test_missing_artifact_cannot_be_verified(tmp_path: Path) -> None:
    manifest = publish(tmp_path)
    (manifest.parent / "rows.json").unlink()
    with pytest.raises(FileNotFoundError):
        verify_ladder_experiment(manifest)


@pytest.mark.parametrize("name", ["rows.json", "report.json", "summary.md"])
def test_rehashed_fabricated_output_fails_independent_replay(tmp_path: Path, name: str) -> None:
    manifest = publish(tmp_path)
    raw = (manifest.parent / name).read_bytes()
    if name == "rows.json":
        payload = json.loads(raw)
        payload["rows"][0]["selections"][2]["disposition"] = "WITHHELD"
        raw = json.dumps(payload).encode()
    elif name == "report.json":
        payload = json.loads(raw)
        payload["natural_rungs"]["MODEL_B"]["selected_n"] = 100
        raw = json.dumps(payload).encode()
    else:
        raw = b"This system is profitable.\n"
    rehash_output(manifest, name, raw)
    with pytest.raises(ValueError, match="independent deterministic replay"):
        verify_ladder_experiment(manifest)


def test_rehashed_changed_input_fails_experiment_identity(tmp_path: Path) -> None:
    manifest = publish(tmp_path)
    payload = json.loads((manifest.parent / "input.json").read_bytes())
    payload["events"][0]["state"]["sector"] = "ALTERED"
    rehash_output(manifest, "input.json", json.dumps(payload).encode())
    with pytest.raises(ValueError, match="source or runtime identity"):
        verify_ladder_experiment(manifest)


@pytest.mark.parametrize("binding", ["source_bindings", "runtime_bindings"])
def test_different_code_or_runtime_cannot_verify_old_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, binding: str
) -> None:
    manifest = publish(tmp_path)
    records = getattr(experiment, binding)()
    replacement = (
        records[0].model_copy(update={"sha256": "0" * 64})
        if binding == "source_bindings"
        else records[0].model_copy(update={"version": "999.0"})
    )
    monkeypatch.setattr(experiment, binding, lambda: (replacement, *records[1:]))
    with pytest.raises(ValueError, match="source or runtime identity"):
        verify_ladder_experiment(manifest)


@pytest.mark.parametrize("verifying", [False, True])
def test_source_drift_during_computation_or_verification_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, verifying: bool
) -> None:
    manifest = publish(tmp_path) if verifying else None
    records = experiment.source_bindings()
    call_count = 0

    def drifting_sources() -> tuple[experiment.SourceBinding, ...]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return records
        return (records[0].model_copy(update={"sha256": "0" * 64}), *records[1:])

    monkeypatch.setattr(experiment, "source_bindings", drifting_sources)
    with pytest.raises(ValueError, match="changed during"):
        if manifest is not None:
            verify_ladder_experiment(manifest)
        else:
            publish(tmp_path)
    if not verifying:
        assert not list(tmp_path.rglob("manifest.json"))


def test_oversized_document_is_rejected_before_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b"{} ")
    monkeypatch.setattr(experiment, "MAX_DOCUMENT_BYTES", 2)
    with pytest.raises(ValueError, match="bounded document size"):
        experiment.read_bounded(oversized)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("event_count", 1),
        ("population_id", "unrelated"),
        ("policy_version", "unrelated"),
        ("horizon_sessions", 10),
    ],
)
def test_manifest_control_metadata_is_bound_to_inputs(
    tmp_path: Path, field: str, value: Any
) -> None:
    manifest = publish(tmp_path)
    payload = json.loads(manifest.read_bytes())
    payload[field] = value
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="population/policy binding mismatch"):
        verify_ladder_experiment(manifest)


@pytest.mark.parametrize(
    "field", ["scientific_acceptance", "genuine_quality_evidence", "final_test_unlocked"]
)
def test_manifest_cannot_claim_real_acceptance(tmp_path: Path, field: str) -> None:
    manifest = publish(tmp_path)
    payload = json.loads(manifest.read_bytes())
    payload[field] = True
    with pytest.raises(ValidationError):
        ExperimentManifest.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize("path", ["../report.json", "C:/outside/report.json"])
def test_manifest_cannot_substitute_arbitrary_artifact_paths(tmp_path: Path, path: str) -> None:
    manifest = publish(tmp_path)
    payload = json.loads(manifest.read_bytes())
    payload["artifacts"][5]["path"] = path
    with pytest.raises(ValidationError, match="canonical file"):
        ExperimentManifest.model_validate_json(json.dumps(payload))


@pytest.mark.parametrize(
    "raw", [b'{"a":1,"a":2}', b'{"a":{"b":1,"b":2}}', b'{"a":NaN}', b'{"a":Infinity}']
)
def test_json_rejects_ambiguous_or_nonfinite_documents(raw: bytes) -> None:
    with pytest.raises(ValueError):
        strict_json(raw)


def test_cli_fixture_then_verify_and_explicit_saved_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        sys, "argv", ["backtest", "ladder", "--fixture", "--output-dir", str(tmp_path)]
    )
    cli.main()
    result = json.loads(capsys.readouterr().out)
    manifest = Path(result["manifest"])
    monkeypatch.setattr(sys, "argv", ["backtest", "verify", "--manifest", str(manifest)])
    cli.main()
    assert json.loads(capsys.readouterr().out)["status"] == "VERIFIED_SYNTHETIC_REPLAY"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "backtest",
            "ladder",
            "--input",
            str(manifest.parent / "input.json"),
            "--policy",
            str(manifest.parent / "policy.json"),
            "--config",
            str(manifest.parent / "execution-config.json"),
            "--labels",
            str(manifest.parent / "labels.json"),
            "--output-dir",
            str(tmp_path),
        ],
    )
    cli.main()
    assert json.loads(capsys.readouterr().out)["manifest"] == str(manifest)


def test_no_labels_still_publishes_full_event_population(tmp_path: Path) -> None:
    events, policy, execution, _labels = fixture_ladder()
    manifest = run_ladder_experiment(events, policy, execution, tmp_path)
    report = json.loads((manifest.parent / "report.json").read_bytes())
    assert report["population_n"] == 14
    assert report["natural_rungs"]["MODEL_B"]["selected_economics"]["population_n"] == 9
    assert verify_ladder_experiment(manifest)["event_count"] == 14


def test_production_data_and_duplicate_ids_are_rejected_before_publication(tmp_path: Path) -> None:
    events, _policy, _execution, _labels = fixture_ladder()
    with pytest.raises(ValidationError, match="unique"):
        LadderInputDocument(events=(events[0], events[0]))
    payload = json.loads(canonical_bytes(LadderInputDocument(events=events)))
    payload["events"][0]["request"]["data_kind"] = "DEVELOPMENT_CAPTURE"
    with pytest.raises(ValidationError, match="not implemented"):
        LadderInputDocument.model_validate_json(json.dumps(payload))
    assert not list(tmp_path.iterdir())


def test_label_changes_are_separate_from_selection_but_change_report_identity(
    tmp_path: Path,
) -> None:
    events, policy, execution, labels = fixture_ladder()
    first = run_ladder_experiment(events, policy, execution, tmp_path, labels=labels)
    flipped = tuple(
        label.model_copy(update={"label_success": 1 - label.label_success}) for label in labels
    )
    second = run_ladder_experiment(events, policy, execution, tmp_path, labels=flipped)
    assert second != first
    assert (second.parent / "rows.json").read_bytes() == (first.parent / "rows.json").read_bytes()
    assert (second.parent / "report.json").read_bytes() != (
        first.parent / "report.json"
    ).read_bytes()
    assert verify_ladder_experiment(second)["status"] == "VERIFIED_SYNTHETIC_REPLAY"
