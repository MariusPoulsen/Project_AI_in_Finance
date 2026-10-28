"""Development and final-test periods, and the owner's unlock guard (Decisions 42, 116, 117).

Everything up to ``DEVELOPMENT_END`` is development data. The final-test years stay locked
until the decision log holds an owner-written unlock record that cites the SHA-256 of the
committed research freeze manifest. Code that reads or captures data calls ``data_end`` or
``check_end`` instead of hard-coding the last development date.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date
from pathlib import Path

DEVELOPMENT_END = date(2023, 12, 31)
FINAL_TEST_YEARS = (2024, 2025)
FINAL_TEST_END = date(2025, 12, 31)
DECISIONS = Path("docs/DECISIONS.md")
MANIFEST = Path("docs/freeze/research_freeze_manifest.json")
_HEADING = re.compile(r"^#{2,3} .*\bunlock record\b.*$", re.IGNORECASE | re.MULTILINE)


def manifest_sha256(manifest: Path = MANIFEST) -> str | None:
    if not manifest.exists():
        return None
    return hashlib.sha256(manifest.read_bytes()).hexdigest()


def _stamp(path: Path) -> tuple[int, int] | None:
    try:
        status = path.stat()
    except OSError:
        return None
    return status.st_mtime_ns, status.st_size


# Execution checks call the gate millions of times; the answer is cached per state of the
# two files, so a changed decision log or manifest is always read again.
_UNLOCK_CACHE: dict[tuple[object, ...], str | None] = {}


def unlock_record(decisions: Path = DECISIONS, manifest: Path = MANIFEST) -> str | None:
    """The unlock heading, if a decision section titled "... unlock record ..." cites the
    current manifest's SHA-256 and says the owner wrote it; otherwise None."""
    key = (str(decisions), _stamp(Path(decisions)), str(manifest), _stamp(Path(manifest)))
    if key not in _UNLOCK_CACHE:
        _UNLOCK_CACHE[key] = _read_unlock_record(Path(decisions), Path(manifest))
    return _UNLOCK_CACHE[key]


def _read_unlock_record(decisions: Path, manifest: Path) -> str | None:
    sha = manifest_sha256(manifest)
    if sha is None or not decisions.exists():
        return None
    text = decisions.read_text(encoding="utf-8")
    for match in _HEADING.finditer(text):
        following = text[match.end() :]
        nxt = re.search(r"^#{2,3} ", following, re.MULTILINE)
        body = following[: nxt.start()] if nxt else following
        if sha in body and re.search(r"\bowner\b", match.group(0) + body, re.IGNORECASE):
            return match.group(0).lstrip("# ").strip()
    return None


def data_end(decisions: Path = DECISIONS, manifest: Path = MANIFEST) -> date:
    """Last date any builder may read: the development end, or the final-test end once
    the owner's unlock record exists."""
    return FINAL_TEST_END if unlock_record(decisions, manifest) else DEVELOPMENT_END


def scored_years(first: int = 2010) -> tuple[int, ...]:
    """Test years scored walk-forward: from ``first`` to the last year of ``data_end``."""
    return tuple(range(first, data_end().year + 1))


def final_years_open() -> tuple[int, ...]:
    """The final-test years once the owner has unlocked them, otherwise none."""
    return FINAL_TEST_YEARS if unlock_record() else ()


def check_end(end: date, decisions: Path = DECISIONS, manifest: Path = MANIFEST) -> None:
    """Refuse a request for data after the development end while the final test is locked."""
    if end > DEVELOPMENT_END and unlock_record(decisions, manifest) is None:
        raise PermissionError(
            f"{end} is after the development end {DEVELOPMENT_END}; the final test is locked "
            "until an owner unlock record cites the freeze manifest's SHA-256"
        )
