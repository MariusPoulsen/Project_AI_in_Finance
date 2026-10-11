"""Frozen input integrity and source-blind human review without quality inflation."""

import hashlib
import json
from pathlib import Path

import pytest

from structural_break.agents.contracts import AgentInput
from structural_break.agents.inputs import PreparedInputs, batch_fixture_events, prepare_mock_inputs
from structural_break.agents.pipeline import canonical_json, digest
from structural_break.agents.review import export_review, validate_review

FIXTURE = Path(__file__).resolve().parent / "fixtures/phase5/input.json"


def prepared(tmp_path, events=None):
    events = batch_fixture_events(FIXTURE) if events is None else events
    return PreparedInputs(prepare_mock_inputs(events, tmp_path / "inputs", generation_id="mock-v1"))


def completed(review_dir):
    payload = json.loads((review_dir / "annotations.blank.json").read_bytes())
    payload.update(
        reviewer_id="fixture-human", reviewed_at="2026-10-11T00:00:00Z", human_review_attested=True
    )
    for row in payload["annotations"]:
        row.update(
            source_completeness="COMPLETE",
            catalyst={
                "event_type": "NONE",
                "affected_leg": "NONE",
                "direction": "UNKNOWN",
                "materiality": "UNKNOWN",
                "relationship_relevance": "NONE",
                "citations": [],
            },
            source_support="SUPPORTED",
        )
    return payload


def save_annotations(review_dir, payload):
    path = review_dir / "completed.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_prepared_lazy_load_and_exact_manifest_pin(tmp_path):
    events = batch_fixture_events(FIXTURE)
    inputs = prepared(tmp_path, events)
    assert tuple(inputs) == events
    assert inputs[1:3] == list(events[1:3])
    assert PreparedInputs(inputs.manifest_path, expected_sha256=inputs.sha256)[-1] == events[-1]
    with pytest.raises(ValueError, match="manifest checksum"):
        PreparedInputs(inputs.manifest_path, expected_sha256="0" * 64)
    # Inventory loads without eagerly retaining all source packs; reading a
    # damaged row still fails before that row reaches any provider.
    damaged = inputs.manifest_path.parent / inputs.manifest.entries[1].path
    damaged.write_bytes(b"{}")
    reloaded = PreparedInputs(inputs.manifest_path)
    assert reloaded[0] == events[0]
    with pytest.raises(ValueError, match="checksum"):
        _ = reloaded[1]


@pytest.mark.parametrize("kind", ["mode", "path", "identity", "duplicate"])
def test_manifest_cannot_claim_live_or_substitute_inventory(tmp_path, kind):
    inputs = prepared(tmp_path)
    payload = inputs.manifest.model_dump(mode="json")
    if kind == "mode":
        payload["mode"] = "live"
    elif kind == "path":
        payload["entries"][0]["path"] = "../outside.json"
    elif kind == "identity":
        payload["generation_id"] = "changed"
    else:
        payload["entries"].append(payload["entries"][0])
    inputs.manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        PreparedInputs(inputs.manifest_path)


def test_rehashed_inventory_still_must_match_event_identity(tmp_path):
    inputs = prepared(tmp_path)
    payload = inputs.manifest.model_dump(mode="json")
    payload["entries"][0]["pair_id"] = "different-pair"
    payload["bundle_id"] = digest(
        {key: value for key, value in payload.items() if key != "bundle_id"}
    )
    inputs.manifest_path.write_text(canonical_json(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="inventory identity"):
        _ = PreparedInputs(inputs.manifest_path)[0]


def test_publication_is_immutable_and_population_unique(tmp_path):
    events = batch_fixture_events(FIXTURE)
    inputs = prepared(tmp_path, events)
    assert prepare_mock_inputs(events, inputs.manifest_path.parent, generation_id="mock-v1")
    with pytest.raises(FileExistsError):
        prepare_mock_inputs(events, inputs.manifest_path.parent, generation_id="different")
    with pytest.raises(ValueError, match="unique"):
        prepare_mock_inputs((events[0], events[0]), tmp_path / "duplicate", generation_id="mock")


def test_review_omits_probabilities_labels_outcomes_and_never_silently_shrinks(tmp_path):
    inputs = prepared(tmp_path)
    review_dir = tmp_path / "review"
    manifest = json.loads(export_review(inputs, review_dir, count=4).read_bytes())
    assert manifest["selected_count"] == manifest["available_count"] == 4
    for case in manifest["cases"]:
        source = json.loads((review_dir / case["source_file"]).read_bytes())
        assert set(source) == {
            "event_id",
            "pair_id",
            "event_timestamp",
            "leg_a_security_id",
            "leg_b_security_id",
            "declared_source_coverage",
            "evidence_policy_version",
            "evidence",
        }
        assert source["evidence"][0]["text"]
    with pytest.raises(ValueError, match="exceeds available"):
        export_review(inputs, tmp_path / "too-many", count=50)
    with pytest.raises(FileExistsError):
        export_review(inputs, review_dir, count=2)


def test_review_selection_is_independent_of_model_scores(tmp_path):
    events = batch_fixture_events(FIXTURE)
    changed = []
    for event in events:
        payload = event.model_dump(mode="json")
        payload["quant"]["model_b_probability"] = 0.31
        changed.append(AgentInput.model_validate_json(json.dumps(payload)))
    first = prepared(tmp_path / "first", events)
    second = prepared(tmp_path / "second", changed)
    manifests = [
        json.loads(export_review(inputs, tmp_path / name, count=2).read_bytes())
        for name, inputs in (("review-first", first), ("review-second", second))
    ]
    assert [row["event_id"] for row in manifests[0]["cases"]] == [
        row["event_id"] for row in manifests[1]["cases"]
    ]
    assert manifests[0]["cases"][0]["source_sha256"] == manifests[1]["cases"][0]["source_sha256"]


def test_completed_review_validates_provenance_without_claiming_measured_quality(tmp_path):
    inputs = prepared(tmp_path)
    review_dir = tmp_path / "review"
    export_review(inputs, review_dir, count=4)
    with pytest.raises(ValueError):
        validate_review(inputs, review_dir, review_dir / "annotations.blank.json")
    result = validate_review(
        inputs, review_dir, save_annotations(review_dir, completed(review_dir))
    )
    assert result["completed_count"] == 4
    assert result["genuine_quality_gate_passed"] is False
    assert result["semantic_accuracy_measured"] is False


@pytest.mark.parametrize("kind", ["binding", "missing", "duplicate", "quote", "source", "attest"])
def test_invalid_human_provenance_is_rejected(tmp_path, kind):
    inputs = prepared(tmp_path)
    review_dir = tmp_path / "review"
    manifest_path = export_review(inputs, review_dir, count=2)
    payload = completed(review_dir)
    if kind == "binding":
        payload["review_manifest_sha256"] = "0" * 64
    elif kind == "missing":
        payload["annotations"].pop()
    elif kind == "duplicate":
        payload["annotations"][1] = payload["annotations"][0]
    elif kind == "attest":
        payload["human_review_attested"] = False
    elif kind == "source":
        case = json.loads(manifest_path.read_bytes())["cases"][0]
        (review_dir / case["source_file"]).write_bytes(b"{}")
    else:
        payload["annotations"][0]["catalyst"] = {
            "event_type": "GUIDANCE",
            "affected_leg": "A",
            "direction": "POSITIVE",
            "materiality": "LOW",
            "relationship_relevance": "INDIRECT",
            "citations": [{"chunk_id": "fixture-A-chunk", "leg": "A", "quote": "invented quote"}],
        }
    with pytest.raises(ValueError):
        validate_review(inputs, review_dir, save_annotations(review_dir, payload))


def test_human_cannot_upgrade_incomplete_acquisition(tmp_path):
    event = batch_fixture_events(FIXTURE)[0]
    payload = event.model_dump(mode="json")
    payload["gates"]["source_coverage"] = "PARTIAL"
    payload["catalysts"] = []
    inputs = prepared(tmp_path, [AgentInput.model_validate_json(json.dumps(payload))])
    review_dir = tmp_path / "review"
    export_review(inputs, review_dir, count=1)
    annotations = completed(review_dir)
    with pytest.raises(ValueError, match="cannot upgrade"):
        validate_review(inputs, review_dir, save_annotations(review_dir, annotations))
    annotations["annotations"][0].update(
        source_completeness="PARTIAL",
        source_support="INSUFFICIENT",
        catalyst={
            "event_type": "UNKNOWN",
            "affected_leg": "UNKNOWN",
            "direction": "UNKNOWN",
            "materiality": "UNKNOWN",
            "relationship_relevance": "UNKNOWN",
            "citations": [],
        },
    )
    assert validate_review(inputs, review_dir, save_annotations(review_dir, annotations))


def test_review_manifest_and_annotation_are_byte_bound(tmp_path):
    inputs = prepared(tmp_path)
    review_dir = tmp_path / "review"
    path = export_review(inputs, review_dir, count=1)
    annotations = save_annotations(review_dir, completed(review_dir))
    original = path.read_bytes()
    assert (
        hashlib.sha256(original).hexdigest()
        == json.loads(annotations.read_bytes())["review_manifest_sha256"]
    )
    path.write_bytes(original + b"\n")
    with pytest.raises(ValueError, match="exact review manifest"):
        validate_review(inputs, review_dir, annotations)


@pytest.mark.parametrize("kind", ["ordering", "denominator"])
def test_rehashed_review_cannot_replace_target_blind_selection(tmp_path, kind):
    inputs = prepared(tmp_path)
    review_dir = tmp_path / "review"
    path = export_review(inputs, review_dir, count=4)
    manifest = json.loads(path.read_bytes())
    if kind == "ordering":
        manifest["cases"].reverse()
    else:
        manifest["available_count"] += 1
    path.write_text(json.dumps(manifest), encoding="utf-8")
    payload = completed(review_dir)
    payload["review_manifest_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="target-blind selection"):
        validate_review(inputs, review_dir, save_annotations(review_dir, payload))


@pytest.mark.parametrize("affected", ["B", "BOTH"])
def test_catalyst_affected_legs_require_matching_exact_citations(affected):
    event = batch_fixture_events(FIXTURE)[0]
    payload = event.model_dump(mode="json")
    payload["catalysts"] = [
        {
            "event_type": "GUIDANCE",
            "affected_leg": affected,
            "direction": "POSITIVE",
            "materiality": "LOW",
            "relationship_relevance": "INDIRECT",
            "citations": [
                {"chunk_id": "fixture-A-chunk", "leg": "A", "quote": "unchanged operating guidance"}
            ],
        }
    ]
    with pytest.raises(ValueError, match="claimed affected legs"):
        AgentInput.model_validate_json(json.dumps(payload))


def test_final_period_cannot_be_hidden_with_timestamp_offset():
    payload = batch_fixture_events(FIXTURE)[0].model_dump(mode="json")
    payload["event_timestamp"] = "2023-12-31T23:30:00-02:00"
    with pytest.raises(ValueError, match="locked final-test"):
        AgentInput.model_validate_json(json.dumps(payload))
