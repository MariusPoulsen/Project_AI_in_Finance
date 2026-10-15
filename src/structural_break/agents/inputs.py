"""Immutable prepared-input boundary and lazy, checksum-checked batch loading.

This first adapter prepares mock projections. It cannot certify a genuine v2
generation; native-model/source acceptance remains a separate future adapter.
"""

import hashlib
import json
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Literal, overload

from pydantic import Field, model_validator

from structural_break.agents.contracts import SHA256, AgentInput, FrozenModel, Identifier
from structural_break.agents.pipeline import canonical_json, digest
from structural_break.storage.files import write_bytes

BUNDLE_VERSION = "phase5-prepared-inputs-v1"


class InputEntry(FrozenModel):
    event_id: Identifier
    pair_id: Identifier
    event_timestamp: str
    path: str
    sha256: SHA256

    @model_validator(mode="after")
    def content_addressed_path(self) -> "InputEntry":
        if self.path != f"inputs/{self.sha256}.json":
            raise ValueError("Prepared input path must be portable and content addressed")
        return self


class InputManifest(FrozenModel):
    schema_version: Literal["phase5-prepared-inputs-v1"] = "phase5-prepared-inputs-v1"
    mode: Literal["mock"] = "mock"
    generation_id: Identifier
    bundle_id: SHA256
    entries: tuple[InputEntry, ...] = Field(min_length=1, max_length=100_000)

    @model_validator(mode="after")
    def unique_frozen_rows(self) -> "InputManifest":
        if len({entry.event_id for entry in self.entries}) != len(self.entries):
            raise ValueError("Prepared input event IDs must be unique")
        expected = digest(
            {
                "schema_version": self.schema_version,
                "mode": self.mode,
                "generation_id": self.generation_id,
                "entries": [entry.model_dump(mode="json") for entry in self.entries],
            }
        )
        if self.bundle_id != expected:
            raise ValueError("Prepared input manifest identity mismatch")
        return self


def prepare_mock_inputs(
    events: Sequence[AgentInput], output_dir: Path, *, generation_id: str
) -> Path:
    """Publish explicit synthetic projections without a genuine acceptance claim."""
    if not events or len({event.event_id for event in events}) != len(events):
        raise ValueError("A nonempty unique event population is required")
    entries: list[InputEntry] = []
    for event in events:
        raw = (canonical_json(event.model_dump(mode="json")) + "\n").encode()
        checksum = hashlib.sha256(raw).hexdigest()
        entry = InputEntry(
            event_id=event.event_id,
            pair_id=event.pair_id,
            event_timestamp=event.event_timestamp.isoformat(),
            path=f"inputs/{checksum}.json",
            sha256=checksum,
        )
        write_bytes(output_dir / entry.path, raw)
        entries.append(entry)
    identity = {
        "schema_version": BUNDLE_VERSION,
        "mode": "mock",
        "generation_id": generation_id,
        "entries": [entry.model_dump(mode="json") for entry in entries],
    }
    manifest = InputManifest.model_validate_json(
        canonical_json(
            {
                **identity,
                "bundle_id": digest(identity),
            }
        )
    )
    return write_bytes(
        output_dir / "manifest.json",
        (canonical_json(manifest.model_dump(mode="json")) + "\n").encode(),
    )


class PreparedInputs(Sequence[AgentInput]):
    """Load one bounded event at a time, retaining every scheduled denominator."""

    def __init__(self, manifest_path: Path, *, expected_sha256: str | None = None) -> None:
        if manifest_path.stat().st_size > 64_000_000:
            raise ValueError("Prepared input manifest exceeds the bounded inventory size")
        self.manifest_path = manifest_path.resolve()
        raw = self.manifest_path.read_bytes()
        self.sha256 = hashlib.sha256(raw).hexdigest()
        if expected_sha256 is not None and self.sha256 != expected_sha256:
            raise ValueError("Prepared input manifest checksum mismatch")
        self.manifest = InputManifest.model_validate_json(raw)

    def __len__(self) -> int:
        return len(self.manifest.entries)

    @property
    def event_ids(self) -> tuple[str, ...]:
        """Read-only inventory indexes; each used event is still checksum validated."""
        return tuple(entry.event_id for entry in self.manifest.entries)

    @overload
    def __getitem__(self, index: int) -> AgentInput: ...

    @overload
    def __getitem__(self, index: slice) -> list[AgentInput]: ...

    def __getitem__(self, index: int | slice) -> AgentInput | list[AgentInput]:
        if isinstance(index, slice):
            return [self[item] for item in range(*index.indices(len(self)))]
        entry = self.manifest.entries[index]
        path = (self.manifest_path.parent / entry.path).resolve()
        if not path.is_relative_to(self.manifest_path.parent):
            raise ValueError("Prepared input escapes its generation")
        if path.stat().st_size > 1_000_000:
            raise ValueError("Prepared input file checksum/bound mismatch")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry.sha256:
            raise ValueError("Prepared input file checksum/bound mismatch")
        event = AgentInput.model_validate_json(raw)
        if (event.event_id, event.pair_id, event.event_timestamp.isoformat()) != (
            entry.event_id,
            entry.pair_id,
            entry.event_timestamp,
        ):
            raise ValueError("Prepared input inventory identity mismatch")
        return event

    def __iter__(self) -> Iterator[AgentInput]:
        for index in range(len(self)):
            yield self[index]


def batch_fixture_events(fixture_path: Path) -> tuple[AgentInput, ...]:
    """Four invented cases exercise investigated and deterministically skipped rows."""
    original = AgentInput.model_validate_json(fixture_path.read_bytes())
    events: list[AgentInput] = []
    for suffix in ("eligible", "watch", "low", "missing"):
        payload = original.model_dump(mode="json")
        payload["event_id"] = f"fixture-batch-{suffix}"
        if suffix == "watch":
            payload["pair_status"] = "WATCH"
        elif suffix == "low":
            payload["quant"]["model_b_probability"] = 0.1
        elif suffix == "missing":
            payload["gates"]["market_data_ok"] = False
        events.append(AgentInput.model_validate_json(json.dumps(payload)))
    return tuple(events)
