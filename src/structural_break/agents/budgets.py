"""Durable, conservative attempt accounting and explicit exclusive batch leases.

A reservation is published before transport and is never refunded, including a
timeout, process death or an unknown request outcome. This ledger controls this
job's allocation, not unobserved use elsewhere in the provider project.
"""

import hashlib
import json
import os
import re
import threading
import uuid
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal, Self, cast
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator

from structural_break.agents.contracts import SHA256, FrozenModel, Identifier
from structural_break.intelligence.extraction import ProviderFailure
from structural_break.storage.files import write_bytes

BUDGET_VERSION: Literal["phase5-durable-attempt-budget-v1"] = "phase5-durable-attempt-budget-v1"
Cap = Annotated[int, Field(ge=0, le=10_000_000)]


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def fingerprint(value: object) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def write_envelope(path: Path, payload: dict[str, object], *, replace: bool = False) -> None:
    write_bytes(
        path,
        (canonical({"sha256": fingerprint(payload), "payload": payload}) + "\n").encode(),
        replace=replace,
    )


def read_envelope(path: Path) -> dict[str, object]:
    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate persisted JSON key")
            result[key] = value
        return result

    value: object = json.loads(path.read_bytes(), object_pairs_hook=unique)
    if not isinstance(value, dict) or set(value) != {"sha256", "payload"}:
        raise ValueError("Invalid persisted envelope")
    payload = value["payload"]
    if not isinstance(payload, dict) or fingerprint(payload) != value["sha256"]:
        raise ValueError("Persisted checksum mismatch")
    return cast(dict[str, object], payload)


class ExclusiveLease:
    """Portable fail-closed O_EXCL lease; an abandoned file is never auto-unlocked."""

    def __init__(self, path: Path, *, purpose: str) -> None:
        self.path = path
        self.purpose = purpose
        self.token = uuid.uuid4().hex
        self._owned = False

    def __enter__(self) -> Self:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": "phase5-exclusive-lease-v1",
            "token": self.token,
            "pid": os.getpid(),
            "purpose": self.purpose,
            "started_at": datetime.now(UTC).isoformat(),
        }
        try:
            descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            raise RuntimeError(
                "Phase 5 lease already exists; inspect it and use explicit audited recovery"
            ) from None
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical(payload).encode())
            stream.flush()
            os.fsync(stream.fileno())
        self._owned = True
        return self

    def __exit__(self, *_: object) -> None:
        if self._owned:
            payload: object = json.loads(self.path.read_bytes())
            if not isinstance(payload, dict) or payload.get("token") != self.token:
                raise RuntimeError("Exclusive lease ownership changed")
            self.path.unlink()
            self._owned = False


def recover_lease(
    path: Path,
    *,
    expected_token: str,
    reason: str,
    owner_confirmed_stopped: bool,
) -> Path:
    """Explicit operator attestation, never an inference from a missing/unknown PID.

    The exact lock token and a nonempty reason are required. The audit receipt is
    written before removing the lock; a partial/corrupt lock fails closed.
    """
    if owner_confirmed_stopped is not True or not reason.strip() or len(reason) > 500:
        raise ValueError("Recovery requires an explicit stopped-owner attestation and reason")
    value: object = json.loads(path.read_bytes())
    if (
        not isinstance(value, dict)
        or set(value) != {"version", "token", "pid", "purpose", "started_at"}
        or value["version"] != "phase5-exclusive-lease-v1"
        or re.fullmatch(r"[0-9a-f]{32}", expected_token) is None
        or value["token"] != expected_token
    ):
        raise ValueError("Recovery token or lock contract mismatch")
    receipt = path.parent / "lock_recoveries" / f"{expected_token}.json"
    write_envelope(
        receipt,
        {
            "lock": value,
            "reason": reason,
            "owner_confirmed_stopped": True,
            "recovered_at": datetime.now(UTC).isoformat(),
        },
    )
    # Recheck the bytes before unlinking. The operator must ensure the old owner
    # cannot continue; no attempt is made to silently reclaim a possibly live run.
    if json.loads(path.read_bytes()) != value:
        raise RuntimeError("Lease changed during recovery")
    path.unlink()
    return receipt


class ModelCap(FrozenModel):
    model: Identifier
    total: Cap
    daily: Cap | None = None


class BudgetPolicy(FrozenModel):
    version: Literal["phase5-durable-attempt-budget-v1"] = BUDGET_VERSION
    allocation_id: Identifier
    global_cap: Cap
    model_caps: tuple[ModelCap, ...] = Field(min_length=1, max_length=10)
    daily_global_cap: Cap | None = None
    day_timezone: str = "America/Los_Angeles"

    @model_validator(mode="after")
    def valid_models_and_timezone(self) -> Self:
        if len({cap.model for cap in self.model_caps}) != len(self.model_caps):
            raise ValueError("Budget model names must be unique")
        ZoneInfo(self.day_timezone)
        return self


class Reservation(FrozenModel):
    sequence: Annotated[int, Field(ge=1)]
    previous_sha256: SHA256
    budget_sha256: SHA256
    model: Identifier
    role: Identifier
    request_sha256: SHA256
    reserved_at: datetime
    provider_day: str

    @model_validator(mode="after")
    def utc_reservation(self) -> Self:
        offset = self.reserved_at.utcoffset()
        if offset is None or offset.total_seconds():
            raise ValueError("Reservation timestamps must be UTC")
        return self


class DurableAttemptJournal:
    """Exclusive immutable reservation chain with restart-stable budget identity."""

    def __init__(
        self,
        path: Path,
        policy: BudgetPolicy,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.path = path
        self.policy = policy
        self._clock = clock or (lambda: datetime.now(UTC))
        self._mutex = threading.Lock()
        self._lease: ExclusiveLease | None = None
        self._records: list[Reservation] = []
        self._last_hash = "0" * 64
        self._totals: Counter[str] = Counter()
        self._daily: Counter[tuple[str, str]] = Counter()

    @property
    def identity(self) -> dict[str, object]:
        return {
            "policy": self.policy.model_dump(mode="json"),
            "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        }

    def __enter__(self) -> Self:
        if self._lease is not None:
            raise RuntimeError("Journal is already open")
        lease = ExclusiveLease(self.path / "journal.lock", purpose="durable-attempt-journal")
        lease.__enter__()
        self._lease = lease
        try:
            identity_file = self.path / "identity.json"
            head_file = self.path / "head.json"
            if identity_file.exists():
                if read_envelope(identity_file) != self.identity:
                    raise ValueError("Durable budget policy/implementation identity mismatch")
            else:
                # No ledger may be adopted without its original policy identity.
                if list((self.path / "attempts").glob("*.json")):
                    raise ValueError("Attempt records exist without budget identity")
                write_envelope(identity_file, self.identity)
                write_envelope(head_file, {"count": 0, "last_sha256": "0" * 64})
            head = read_envelope(head_file)
            head_count = head.get("count")
            if (
                set(head) != {"count", "last_sha256"}
                or type(head_count) is not int
                or head_count < 0
            ):
                raise ValueError("Invalid durable attempt head")
            self._records = []
            self._last_hash = "0" * 64
            self._totals.clear()
            self._daily.clear()
            for index, file in enumerate(sorted((self.path / "attempts").glob("*.json")), 1):
                if file.name != f"{index:09d}.json":
                    raise ValueError("Durable attempt sequence has a gap or unknown file")
                payload = read_envelope(file)
                record = Reservation.model_validate_json(canonical(payload))
                self._validate_reservation(record, index)
                self._accept(record, fingerprint(payload))
                if index == head_count and self._last_hash != head["last_sha256"]:
                    raise ValueError("Durable attempt head checksum mismatch")
            if len(self._records) < head_count or (
                head_count == 0 and head["last_sha256"] != "0" * 64
            ):
                raise ValueError("Durable attempt records were truncated")
            # A crash after publishing a reservation but before advancing its
            # head is conservatively charged on resume, even before any HTTP.
            if len(self._records) > head_count:
                self._write_head()
            return self
        except BaseException:
            self.__exit__()
            raise

    def __exit__(self, *_: object) -> None:
        if self._lease is not None:
            lease, self._lease = self._lease, None
            lease.__exit__()

    def _validate_reservation(self, record: Reservation, sequence: int) -> None:
        if (
            record.sequence != sequence
            or record.previous_sha256 != self._last_hash
            or record.budget_sha256 != fingerprint(self.identity)
            or record.provider_day
            != record.reserved_at.astimezone(ZoneInfo(self.policy.day_timezone)).date().isoformat()
        ):
            raise ValueError("Durable attempt chain or policy binding mismatch")
        self._check_capacity(record.model, record.provider_day)

    def _accept(self, record: Reservation, checksum: str) -> None:
        self._records.append(record)
        self._last_hash = checksum
        self._totals[record.model] += 1
        self._daily[record.provider_day, record.model] += 1

    def _write_head(self) -> None:
        write_envelope(
            self.path / "head.json",
            {"count": len(self._records), "last_sha256": self._last_hash},
            replace=True,
        )

    def _check_capacity(self, model: str, provider_day: str) -> None:
        cap = next((value for value in self.policy.model_caps if value.model == model), None)
        if cap is None:
            raise ProviderFailure("UNREGISTERED_BUDGET_MODEL", retriable=False)
        if len(self._records) >= self.policy.global_cap or self._totals[model] >= cap.total:
            raise ProviderFailure("REQUEST_BUDGET_EXHAUSTED", retriable=False)
        daily_total = sum(count for (day, _), count in self._daily.items() if day == provider_day)
        if (
            self.policy.daily_global_cap is not None and daily_total >= self.policy.daily_global_cap
        ) or (cap.daily is not None and self._daily[provider_day, model] >= cap.daily):
            raise ProviderFailure("DURABLE_DAY_BUDGET_EXHAUSTED", retriable=False)

    @property
    def counts(self) -> dict[str, object]:
        with self._mutex:
            return {
                "total_reserved_attempts": len(self._records),
                "by_model": dict(self._totals),
                "by_provider_day_model": {
                    f"{day}/{model}": count for (day, model), count in sorted(self._daily.items())
                },
            }

    def reserve(self, *, model: str, role: str, request_sha256: str) -> Reservation:
        """Durably charge exactly one prospective transport attempt before HTTP."""
        with self._mutex:
            if self._lease is None:
                raise RuntimeError("Durable attempt journal must be exclusively open")
            now = self._clock()
            if now.utcoffset() is None:
                raise ValueError("Budget clock must be timezone-aware")
            now = now.astimezone(UTC)
            provider_day = now.astimezone(ZoneInfo(self.policy.day_timezone)).date().isoformat()
            self._check_capacity(model, provider_day)
            record = Reservation(
                sequence=len(self._records) + 1,
                previous_sha256=self._last_hash,
                budget_sha256=fingerprint(self.identity),
                model=model,
                role=role,
                request_sha256=request_sha256,
                reserved_at=now,
                provider_day=provider_day,
            )
            payload = record.model_dump(mode="json")
            write_envelope(self.path / "attempts" / f"{record.sequence:09d}.json", payload)
            self._accept(record, fingerprint(payload))
            self._write_head()
            return record
