"""Frozen, target-blind source review exports; human annotations remain external."""

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from structural_break.agents.contracts import (
    SHA256,
    AgentInput,
    CatalystState,
    Coverage,
    FrozenModel,
    Identifier,
)
from structural_break.agents.inputs import PreparedInputs
from structural_break.agents.pipeline import canonical_json, digest
from structural_break.storage.files import write_bytes

REVIEW_VERSION = "phase5-blind-source-review-v1"


class ReviewCase(FrozenModel):
    event_id: Identifier
    input_sha256: SHA256
    source_file: str
    source_sha256: SHA256


class ReviewManifest(FrozenModel):
    schema_version: Literal["phase5-blind-source-review-v1"] = "phase5-blind-source-review-v1"
    mode: Literal["mock"] = "mock"
    bundle_sha256: SHA256
    seed: Identifier
    selection_policy: Literal["event-identity-sha256-v1"] = "event-identity-sha256-v1"
    available_count: int = Field(ge=1)
    selected_count: int = Field(ge=1, le=100)
    cases: tuple[ReviewCase, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_cases(self) -> "ReviewManifest":
        if self.selected_count != len(self.cases) or self.selected_count > self.available_count:
            raise ValueError("Review selection denominators do not match")
        if len({case.event_id for case in self.cases}) != len(self.cases):
            raise ValueError("Review selection event identities must be unique")
        if any(case.source_file != f"sources/{case.source_sha256}.json" for case in self.cases):
            raise ValueError("Review source paths must be content addressed")
        return self


class HumanAnnotation(FrozenModel):
    event_id: Identifier
    source_completeness: Coverage
    catalyst: CatalystState
    source_support: Literal["SUPPORTED", "UNSUPPORTED", "INSUFFICIENT"]
    notes: str = Field(max_length=2000)


class CompletedReview(FrozenModel):
    review_manifest_sha256: SHA256
    reviewer_id: Identifier
    reviewed_at: datetime
    human_review_attested: Literal[True]
    annotations: tuple[HumanAnnotation, ...] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def clock_and_ids(self) -> "CompletedReview":
        if self.reviewed_at.utcoffset() is None:
            raise ValueError("Human review must have an explicit timestamp timezone")
        if len({row.event_id for row in self.annotations}) != len(self.annotations):
            raise ValueError("Human annotations must have unique event IDs")
        return self


def _source_projection(event: AgentInput) -> dict[str, object]:
    # No model probabilities, proposed extraction labels or realized outcomes.
    return {
        "event_id": event.event_id,
        "pair_id": event.pair_id,
        "event_timestamp": event.event_timestamp.isoformat(),
        "leg_a_security_id": event.leg_a_security_id,
        "leg_b_security_id": event.leg_b_security_id,
        "declared_source_coverage": event.gates.source_coverage,
        "evidence_policy_version": event.lineage.evidence_policy_version,
        "evidence": [source.model_dump(mode="json") for source in event.evidence],
    }


def export_review(
    inputs: PreparedInputs, output_dir: Path, *, count: int = 50, seed: str = "phase5-review-v1"
) -> Path:
    """Freeze a deterministic source-only human review selection without outcomes."""
    if type(count) is not int or not 1 <= count <= 100 or not seed or len(seed) > 200:
        raise ValueError("Review count must be 1..100 and have a bounded explicit seed")
    if count > len(inputs):
        raise ValueError("Requested review size exceeds available events; no silent downsampling")
    ranked = sorted(
        inputs.manifest.entries,
        key=lambda entry: digest(
            {
                "event_id": entry.event_id,
                "pair_id": entry.pair_id,
                "event_timestamp": entry.event_timestamp,
                "seed": seed,
            }
        ),
    )[:count]
    by_event = {entry.event_id: index for index, entry in enumerate(inputs.manifest.entries)}
    cases: list[ReviewCase] = []
    for entry in ranked:
        event = inputs[by_event[entry.event_id]]
        raw = (canonical_json(_source_projection(event)) + "\n").encode()
        checksum = hashlib.sha256(raw).hexdigest()
        case = ReviewCase(
            event_id=event.event_id,
            input_sha256=entry.sha256,
            source_file=f"sources/{checksum}.json",
            source_sha256=checksum,
        )
        write_bytes(output_dir / case.source_file, raw)
        cases.append(case)
    manifest = ReviewManifest(
        bundle_sha256=inputs.sha256,
        seed=seed,
        available_count=len(inputs),
        selected_count=count,
        cases=tuple(cases),
    )
    raw_manifest = (canonical_json(manifest.model_dump(mode="json")) + "\n").encode()
    manifest_path = write_bytes(output_dir / "manifest.json", raw_manifest)
    blank = {
        "review_manifest_sha256": hashlib.sha256(raw_manifest).hexdigest(),
        "reviewer_id": None,
        "reviewed_at": None,
        "human_review_attested": False,
        "annotations": [
            {
                "event_id": case.event_id,
                "source_completeness": None,
                "catalyst": None,
                "source_support": None,
                "notes": "",
            }
            for case in cases
        ],
    }
    write_bytes(
        output_dir / "annotations.blank.json", (json.dumps(blank, indent=2) + "\n").encode()
    )
    guide = (
        "# Blind historical source review\n\n"
        "This export contains synthetic mock inputs. "
        "It cannot satisfy genuine quality acceptance.\n\n"
        "Read each source JSON in the frozen manifest. Review the bounded historical evidence; "
        "model scores, suggested catalyst labels and realized outcomes are omitted. Copy "
        "`annotations.blank.json` to a separate completed file, then fill the reviewer identity, "
        "timezone-aware review time, human attestation and every selected event.\n\n"
        "For each event supply source completeness, a structured catalyst, exact supporting "
        "citations, source support (SUPPORTED/UNSUPPORTED/INSUFFICIENT), and notes. UNKNOWN "
        "retains insufficient evidence. NONE requires complete selected-source coverage and "
        "means no supported catalyst within that bounded set, not absence of any real event.\n\n"
        "Known catalyst fields: event_type, affected_leg, direction, materiality, "
        "relationship_relevance, citations. Citation fields: chunk_id, leg, quote. "
        "A genuine review will require at least 50 historical events, aiming for 100. "
        "This export prepares the workflow only; no model quality is measured.\n"
    )
    write_bytes(output_dir / "README.md", guide.encode())
    return manifest_path


def validate_review(
    inputs: PreparedInputs, review_dir: Path, annotations_path: Path
) -> dict[str, object]:
    """Verify human-returned provenance/categories, without judging the human's meaning."""
    raw_manifest = (review_dir / "manifest.json").read_bytes()
    manifest = ReviewManifest.model_validate_json(raw_manifest)
    if manifest.bundle_sha256 != inputs.sha256:
        raise ValueError("Human review uses a different frozen input bundle")
    ranked = sorted(
        inputs.manifest.entries,
        key=lambda entry: digest(
            {
                "event_id": entry.event_id,
                "pair_id": entry.pair_id,
                "event_timestamp": entry.event_timestamp,
                "seed": manifest.seed,
            }
        ),
    )[: manifest.selected_count]
    if manifest.available_count != len(inputs) or [case.event_id for case in manifest.cases] != [
        entry.event_id for entry in ranked
    ]:
        raise ValueError("Human review differs from its frozen target-blind selection")
    if annotations_path.stat().st_size > 2_000_000:
        raise ValueError("Review annotations exceed the bounded response size")
    review = CompletedReview.model_validate_json(annotations_path.read_bytes())
    if review.review_manifest_sha256 != hashlib.sha256(raw_manifest).hexdigest():
        raise ValueError("Human annotations do not bind the exact review manifest")
    if {row.event_id for row in review.annotations} != {case.event_id for case in manifest.cases}:
        raise ValueError("Every selected case must have exactly one human annotation")
    by_event = {entry.event_id: index for index, entry in enumerate(inputs.manifest.entries)}
    by_annotation = {row.event_id: row for row in review.annotations}
    for case in manifest.cases:
        source_path = (review_dir / case.source_file).resolve()
        if not source_path.is_relative_to(review_dir.resolve()):
            raise ValueError("Human review source escapes its inventory")
        raw = source_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != case.source_sha256:
            raise ValueError("Human review source checksum mismatch")
        event = inputs[by_event[case.event_id]]
        if inputs.manifest.entries[by_event[case.event_id]].sha256 != case.input_sha256:
            raise ValueError("Human review input binding mismatch")
        if raw != (canonical_json(_source_projection(event)) + "\n").encode():
            raise ValueError("Human review source projection differs from the frozen event")
        annotation = by_annotation[case.event_id]
        # Reuse clock/issuer/quote and NONE-vs-coverage rules without trusting prose.
        payload = event.model_dump(mode="json")
        payload["catalysts"] = [annotation.catalyst.model_dump(mode="json")]
        payload["gates"]["source_coverage"] = annotation.source_completeness
        AgentInput.model_validate_json(canonical_json(payload))
        if (
            annotation.source_completeness == "COMPLETE"
            and event.gates.source_coverage != "COMPLETE"
        ):
            raise ValueError("Human annotation cannot upgrade incomplete source acquisition")
    return {
        "status": "ANNOTATION_FORMAT_AND_PROVENANCE_VALID",
        "mode": manifest.mode,
        "selected_count": manifest.selected_count,
        "completed_count": len(review.annotations),
        "reviewer_id": review.reviewer_id,
        "genuine_quality_gate_passed": False,
        "semantic_accuracy_measured": False,
    }
