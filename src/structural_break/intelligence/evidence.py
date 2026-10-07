"""Point-in-time SEC selection, immutable document caching and lexical retrieval.

Retrieval is deliberately local. SEC acceptance times define admissibility;
report dates, modern web search, outcomes and downstream scores never do.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any, cast
from urllib.parse import quote, urlparse

import pandas as pd

from structural_break.config.paths import ProjectPaths, confined_path
from structural_break.data.http import FetchedResponse, SourceError, validate_redirect
from structural_break.data.sec import normalize_cik
from structural_break.storage.files import segment, sha256_file, write_bytes

_ACCESSION = re.compile(r"^\d{10}-\d{2}-\d{6}$")
_TYPE = re.compile(r"<TYPE>\s*([^\r\n<]+)", re.I)
_FILENAME = re.compile(r"<FILENAME>\s*([^\r\n<]+)", re.I)
_SEQUENCE = re.compile(r"<SEQUENCE>\s*([^\r\n<]+)", re.I)
_WORDS = re.compile(r"[a-z][a-z0-9]+")
_HEADING = re.compile(r"^(?:part\s+[ivx]+|item\s+\d+[a-z]?(?:\.\d+)?\b)", re.I)
_QUERY = frozenset(
    "earnings revenue income loss guidance outlook forecast merger acquisition disposition "
    "litigation lawsuit regulatory regulation investigation bankruptcy restructuring impairment "
    "dividend repurchase executive officer resignation appointment product recall approval "
    "demand supply margin risk material agreement uncertainty liquidity".split()
)
CHUNK_COLUMNS = (
    "chunk_id",
    "filing_id",
    "security_id",
    "leg",
    "cik",
    "form",
    "is_amendment",
    "document_type",
    "document_filename",
    "acceptance_datetime_utc",
    "section_label",
    "chunk_order",
    "chunk_text",
    "char_count",
    "token_estimate",
    "source_url",
    "raw_file_path",
    "sha256",
    "text_sha256",
    "status",
    "error_reason",
)


@dataclass(frozen=True)
class EvidencePolicy:
    recent_8k_days: int = 30
    periodic_days: int = 180
    periodic_extension_days: int = 400
    chunk_chars: int = 2200
    max_chunks_per_leg: int = 8
    max_total_chars: int = 32000
    version: str = "sec_evidence_v1"

    def __post_init__(self) -> None:
        if (
            self.recent_8k_days <= 0
            or self.periodic_days <= 0
            or self.periodic_extension_days < self.periodic_days
            or not 200 <= self.chunk_chars <= 10000
            or not 1 <= self.max_chunks_per_leg <= 100
            or self.max_total_chars < 2 * self.chunk_chars
            or not self.version
        ):
            raise ValueError("Invalid bounded SEC evidence policy")


def _utc(value: object, field: str) -> datetime:
    if not isinstance(value, str | datetime | pd.Timestamp):
        raise ValueError(f"{field} must be a timezone-aware timestamp")
    stamp = pd.Timestamp(value)
    if pd.isna(stamp) or stamp.tzinfo is None:
        raise ValueError(f"{field} must be a timezone-aware timestamp")
    return stamp.to_pydatetime().astimezone(UTC)


def _event_times(event: Mapping[str, object]) -> tuple[datetime, datetime]:
    timestamp = event.get("event_timestamp", event.get("event_timestamp_utc"))
    cutoff = event.get("evidence_cutoff", timestamp)
    moment = _utc(timestamp, "event_timestamp")
    boundary = _utc(cutoff, "evidence_cutoff")
    if boundary > moment:
        raise ValueError("Evidence cutoff cannot follow the event timestamp")
    return moment, boundary


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _missing(value: object) -> bool:
    return value is None or (not isinstance(value, list | dict) and bool(pd.isna(cast(Any, value))))


def select_event_filings(
    event: Mapping[str, object],
    filing_index: pd.DataFrame,
    leg_security_ids: Sequence[str],
    policy: EvidencePolicy | None = None,
) -> tuple[list[dict[str, object]], dict[str, dict[str, object]]]:
    """Select recent 8-Ks and the latest periodic context for both fixed legs.

    Periodic amendments supplement the latest original's same form/report date;
    they never replace it or retrospectively amend earlier information sets.
    Optional dated identity bounds are inclusive start/exclusive end.
    """
    rules = policy or EvidencePolicy()
    _, cutoff = _event_times(event)
    if len(leg_security_ids) != 2 or len(set(leg_security_ids)) != 2:
        raise ValueError("Evidence selection requires two distinct fixed security identities")
    required = {"security_id", "filing_id", "form", "acceptance_datetime_utc"}
    if not required.issubset(filing_index.columns):
        raise ValueError(
            f"SEC filing index is missing columns: {sorted(required - set(filing_index))}"
        )
    if filing_index["filing_id"].duplicated().any():
        raise ValueError("SEC filing accessions must be unique before evidence selection")
    selected: list[dict[str, object]] = []
    coverage: dict[str, dict[str, object]] = {}
    for leg, security_id in zip(("A", "B"), leg_security_ids, strict=True):
        source = filing_index.loc[filing_index["security_id"].eq(security_id)]
        admissible: list[dict[str, Any]] = []
        unknown_times = 0
        for raw in cast(list[dict[str, Any]], source.to_dict("records")):
            if _missing(raw["acceptance_datetime_utc"]):
                unknown_times += 1
                continue
            accepted = _utc(raw["acceptance_datetime_utc"], "SEC acceptance_datetime_utc")
            if accepted > cutoff or raw.get("point_in_time_eligible", True) is not True:
                continue
            identity_start = raw.get("identity_valid_from")
            identity_end = raw.get("identity_valid_to")
            if (
                not _missing(identity_start)
                and cutoff.date() < pd.Timestamp(str(identity_start)).date()
            ):
                continue
            if (
                not _missing(identity_end)
                and cutoff.date() >= pd.Timestamp(str(identity_end)).date()
            ):
                continue
            form = str(raw["form"])
            if form not in {"8-K", "8-K/A", "10-Q", "10-Q/A", "10-K", "10-K/A"}:
                continue
            raw.update(
                acceptance_datetime_utc=accepted.isoformat(),
                leg=leg,
                is_amendment=form.endswith("/A"),
                base_form=form.removesuffix("/A"),
            )
            admissible.append(raw)
        recent = [
            row
            for row in admissible
            if row["base_form"] == "8-K"
            and _utc(row["acceptance_datetime_utc"], "acceptance")
            >= cutoff - timedelta(days=rules.recent_8k_days)
        ]
        periodic = [
            row
            for row in admissible
            if row["base_form"] in {"10-Q", "10-K"}
            and not row["is_amendment"]
            and _utc(row["acceptance_datetime_utc"], "acceptance")
            >= cutoff - timedelta(days=rules.periodic_extension_days)
        ]
        context = max(
            periodic,
            key=lambda row: (str(row["acceptance_datetime_utc"]), str(row["filing_id"])),
            default=None,
        )
        chosen = recent[:]
        if context is not None:
            chosen.append(context)
            report = context.get("report_date")
            if not _missing(report):
                chosen.extend(
                    row
                    for row in admissible
                    if row["is_amendment"]
                    and row["base_form"] == context["base_form"]
                    and not _missing(row.get("report_date"))
                    and str(row["report_date"]) == str(report)
                    and _utc(row["acceptance_datetime_utc"], "acceptance")
                    >= _utc(context["acceptance_datetime_utc"], "acceptance")
                )
        chosen.sort(key=lambda row: (str(row["acceptance_datetime_utc"]), str(row["filing_id"])))
        for row in chosen:
            row["selection_reason"] = (
                "RECENT_8K"
                if row["base_form"] == "8-K"
                else "PERIODIC_AMENDMENT"
                if row["is_amendment"]
                else "LATEST_PERIODIC"
            )
        selected.extend(chosen)
        extended = (
            context is not None
            and (cutoff - _utc(context["acceptance_datetime_utc"], "acceptance")).total_seconds()
            > rules.periodic_days * 86400
        )
        coverage[leg] = {
            "security_id": security_id,
            "status": "SELECTED" if chosen else "UNKNOWN",
            "reason": "PENDING_DOCUMENT_VALIDATION" if chosen else "NO_ADMISSIBLE_FILINGS",
            "selected_filing_ids": [str(row["filing_id"]) for row in chosen],
            "periodic_filing_id": None if context is None else context["filing_id"],
            "periodic_extended": extended,
            "index_row_count": len(source),
            "missing_acceptance_count": unknown_times,
        }
    return selected, coverage


def _filename(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or len(path.parts) != 1
        or "\\" in value
        or ":" in value
        or path.name in {".", ".."}
    ):
        raise ValueError("SEC document filename must be one portable path segment")
    return value


def _embedded_documents(text: str) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for part in re.findall(r"<DOCUMENT>(.*?)</DOCUMENT>", text, flags=re.I | re.S):
        kind, filename, sequence = (
            _TYPE.search(part),
            _FILENAME.search(part),
            _SEQUENCE.search(part),
        )
        body = re.search(r"<TEXT>(.*?)(?:</TEXT>|$)", part, flags=re.I | re.S)
        if kind is not None and filename is not None and body is not None:
            result.append(
                {
                    "document_type": kind.group(1).strip().upper(),
                    "document_filename": _filename(filename.group(1).strip()),
                    "sequence": sequence.group(1).strip() if sequence else "0",
                    "text": body.group(1),
                }
            )
    return result


def _cached_filing_response(
    paths: ProjectPaths,
    target: Path,
    url: str,
    kind: str,
    original: str,
    accepted: datetime,
) -> dict[str, object] | None:
    """Validate a complete response pair without replacing its retrieval receipt."""
    sidecar = target.with_name(target.name + ".response.json")
    if not sidecar.is_file():
        if sidecar.exists() or target.exists():
            raise ValueError("SEC cached body has no complete response metadata")
        return None
    value = json.loads(sidecar.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("Invalid cached SEC response metadata")
    record = cast(dict[str, object], value)
    required = {
        "document_type",
        "document_filename",
        "source_url",
        "raw_file_path",
        "sha256",
        "http_status",
        "retrieved_at_utc",
        "status",
        "error_reason",
    }
    if set(record) not in (required, required | {"response_url"}):
        raise ValueError("Incomplete cached SEC response metadata")
    expected = {
        "document_type": kind,
        "document_filename": original,
        "source_url": url,
        "raw_file_path": target.relative_to(paths.workspace_root).as_posix(),
    }
    if any(record[field] != expected_value for field, expected_value in expected.items()):
        raise ValueError("Cached SEC response document identity mismatch")
    status = record["status"]
    http_status = record["http_status"]
    if (
        not isinstance(status, str)
        or status not in {"DOWNLOADED", "FAILED"}
        or (
            http_status is not None
            and (type(http_status) is not int or not 100 <= http_status <= 599)
        )
    ):
        raise ValueError("Invalid cached SEC response status")
    if (status == "DOWNLOADED" and record["error_reason"] is not None) or (
        status == "FAILED" and not isinstance(record["error_reason"], str)
    ):
        raise ValueError("Invalid cached SEC response failure metadata")
    digest = record["sha256"]
    if digest is None:
        # A request-level failure has no response bytes or observed retrieval time.
        if (
            status != "FAILED"
            or target.exists()
            or record["retrieved_at_utc"] is not None
            or "response_url" in record
        ):
            raise ValueError("Incomplete cached SEC response body/hash metadata")
        return record
    if (
        not isinstance(digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        or not target.is_file()
        or sha256_file(target) != digest
    ):
        raise ValueError("Immutable SEC response hash mismatch")
    response_url = record.get("response_url")
    if http_status is None or not isinstance(response_url, str):
        raise ValueError("Incomplete cached SEC response retrieval metadata")
    retrieved = _utc(record["retrieved_at_utc"], "cached SEC retrieved_at_utc")
    if retrieved < accepted:
        raise ValueError("SEC document acceptance cannot follow its cached retrieval")
    validate_redirect(url, response_url)
    empty = target.stat().st_size == 0
    if (status == "DOWNLOADED" and (http_status != 200 or empty)) or (
        status == "FAILED" and http_status == 200 and not empty
    ):
        raise ValueError("Cached SEC response status/body mismatch")
    return record


def cache_filing(
    paths: ProjectPaths,
    filing: Mapping[str, object],
    get: Callable[[str], FetchedResponse],
    offline: bool = False,
    *,
    attempt_id: str | None = None,
) -> list[dict[str, object]]:
    """Cache an accession once, including source responses and failure states.

    Ordinary reruns never recapture responses. Interrupted online captures reuse
    validated response pairs and fetch only missing documents before publishing
    the manifest. ``attempt_id`` creates another immutable capture under the
    accession, retaining failed originals. Offline misses remain read-only.
    """
    cik = normalize_cik(str(filing["cik"]))
    accession = str(filing["filing_id"])
    if not _ACCESSION.fullmatch(accession):
        raise ValueError("Invalid SEC accession number")
    accepted = _utc(filing["acceptance_datetime_utc"], "acceptance_datetime_utc")
    folder = paths.data_path(f"raw/sec/filings/{cik}/{accession}")
    if attempt_id is not None:
        folder = confined_path(folder, f"attempts/{segment(attempt_id)}")
    manifest_path = folder / "response_manifest.json"
    archive = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/"
    primary_value = filing.get("primary_document")
    primary = None if _missing(primary_value) else _filename(str(primary_value))
    requests: list[tuple[str, str, str, str]] = [
        ("index.json", archive + "index.json", "INDEX", "index.json"),
        ("complete_submission.txt", archive + accession + ".txt", "SUBMISSION", accession + ".txt"),
    ]
    if primary is not None:
        requests.insert(
            1, ("primary_document.html", archive + quote(primary), str(filing["form"]), primary)
        )
    documents: list[dict[str, object]] = []
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_bytes())
        if manifest.get("cik") != cik or manifest.get("filing_id") != accession:
            raise ValueError("Cached SEC accession identity mismatch")
        if manifest.get("acceptance_datetime_utc") != accepted.isoformat():
            raise ValueError("Cached SEC acceptance timestamp mismatch")
        if manifest.get("attempt_id") != attempt_id:
            raise ValueError("Cached SEC capture attempt identity mismatch")
        documents = cast(list[dict[str, object]], manifest["documents"])
    elif offline:
        documents = [
            {
                "document_type": kind,
                "document_filename": original,
                "source_url": url,
                "status": "MISSING",
                "error_reason": "OFFLINE_CACHE_MISS",
                "raw_file_path": None,
                "sha256": None,
                "http_status": None,
                "retrieved_at_utc": None,
            }
            for _, url, kind, original in requests
        ]
    else:
        # A crash can leave complete per-document receipts before the accession
        # manifest. Validate all existing base pairs before making any request.
        for relative, url, kind, original in requests:
            _cached_filing_response(paths, folder / relative, url, kind, original, accepted)

        def capture(relative: str, url: str, kind: str, original: str) -> dict[str, object]:
            target = folder / relative
            cached = _cached_filing_response(paths, target, url, kind, original, accepted)
            if cached is not None:
                return cached
            record: dict[str, object] = {
                "document_type": kind,
                "document_filename": original,
                "source_url": url,
                "raw_file_path": target.relative_to(paths.workspace_root).as_posix(),
                "sha256": None,
                "http_status": None,
                "retrieved_at_utc": None,
                "status": "FAILED",
                "error_reason": None,
            }
            try:
                response = get(url)
                validate_redirect(url, response.url)
                record["http_status"] = response.status_code
                retrieved = _utc(response.retrieved_at, "retrieved_at")
                if retrieved < accepted:
                    raise ValueError("SEC document acceptance cannot follow its retrieval")
                record["retrieved_at_utc"] = retrieved.isoformat()
                record["response_url"] = response.url
                write_bytes(target, response.body)
                record["sha256"] = hashlib.sha256(response.body).hexdigest()
                if response.status_code != 200 or not response.body:
                    raise SourceError(url, response.status_code)
                record["status"] = "DOWNLOADED"
            except (SourceError, TimeoutError) as exc:
                record["error_reason"] = str(exc)
                if isinstance(exc, SourceError):
                    record["http_status"] = exc.status_code
            write_bytes(target.with_name(target.name + ".response.json"), _json_bytes(record))
            return record

        for relative, url, kind, original in requests:
            documents.append(capture(relative, url, kind, original))
        index = next(row for row in documents if row["document_type"] == "INDEX")
        names: set[str] = set()
        if index["status"] == "DOWNLOADED":
            try:
                listing = json.loads(
                    confined_path(paths.workspace_root, str(index["raw_file_path"])).read_bytes()
                )
                names = {_filename(str(item["name"])) for item in listing["directory"]["item"]}
            except (KeyError, TypeError, ValueError):
                index["parse_status"] = "INVALID_INDEX"
        complete = next(row for row in documents if row["document_type"] == "SUBMISSION")
        exhibits: dict[str, tuple[str, str]] = {}
        if complete["status"] == "DOWNLOADED":
            content = confined_path(
                paths.workspace_root, str(complete["raw_file_path"])
            ).read_bytes()
            for embedded in _embedded_documents(content.decode("utf-8", errors="replace")):
                kind = embedded["document_type"]
                name = embedded["document_filename"]
                if kind.startswith("EX-99") and (not names or name in names):
                    exhibits[name] = (kind, embedded["sequence"])
        # Directory names provide a conservative fallback if submission retrieval
        # fails; no contemporaneous search or foreign URLs enter this path.
        for name in sorted(names):
            if name.lower().endswith((".htm", ".html", ".txt", ".pdf")) and re.search(
                r"(?:ex|dex)[-_]?99(?:\D|\d)", name, flags=re.I
            ):
                exhibits.setdefault(name, ("EX-99", "index"))
        for name, (kind, sequence) in sorted(exhibits.items()):
            safe_type = re.sub(r"[^a-zA-Z0-9._-]", "_", kind)
            safe_sequence = re.sub(r"[^a-zA-Z0-9._-]", "_", sequence)
            documents.append(
                capture(
                    f"exhibits/{safe_sequence}_{safe_type}_{name}",
                    archive + quote(name),
                    kind,
                    name,
                )
            )
        write_bytes(
            manifest_path,
            _json_bytes(
                {
                    "cache_version": "sec_accession_cache_v1",
                    "cik": cik,
                    "filing_id": accession,
                    "acceptance_datetime_utc": accepted.isoformat(),
                    "attempt_id": attempt_id,
                    "documents": documents,
                }
            ),
        )
    enriched: list[dict[str, object]] = []
    for stored in documents:
        record = dict(stored)
        raw_relative = record.get("raw_file_path")
        if raw_relative is not None:
            metadata_target = confined_path(paths.workspace_root, str(raw_relative))
            metadata = json.loads(
                metadata_target.with_name(metadata_target.name + ".response.json").read_bytes()
            )
            if metadata != {key: value for key, value in stored.items() if key != "parse_status"}:
                raise ValueError("Immutable SEC response metadata mismatch")
        if record.get("sha256") is not None:
            target = confined_path(paths.workspace_root, str(raw_relative))
            if not target.is_file() or sha256_file(target) != record["sha256"]:
                raise ValueError("Immutable SEC response hash mismatch")
            if record["status"] == "DOWNLOADED":
                record["local_path"] = str(target)
        elif record["status"] == "DOWNLOADED":
            raise ValueError("Successful SEC response has no raw hash")
        record.update(
            filing_id=accession,
            cik=cik,
            security_id=filing["security_id"],
            form=filing["form"],
            is_amendment=str(filing["form"]).endswith("/A"),
            acceptance_datetime_utc=accepted.isoformat(),
            leg=filing.get("leg"),
        )
        enriched.append(record)
    return enriched


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "ix:hidden", "head"}:
            self.skip += 1
        if not self.skip and tag in {"p", "div", "br", "tr", "h1", "h2", "h3", "h4", "li"}:
            self.lines.append("\n")
        if not self.skip and tag in {"td", "th"}:
            self.lines.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "ix:hidden", "head"}:
            self.skip = max(0, self.skip - 1)
        if not self.skip and tag in {"p", "div", "tr", "h1", "h2", "h3", "h4", "li"}:
            self.lines.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.lines.append(data)


def _clean_lines(text: str) -> list[str]:
    parser = _TextParser()
    parser.feed(text)
    parser.close()
    return [
        cleaned
        for line in "".join(parser.lines).splitlines()
        if (cleaned := re.sub(r"\s+", " ", line).strip())
    ]


def _sections(lines: list[str], maximum: int) -> list[tuple[str, str]]:
    chunks: list[tuple[str, str]] = []
    section, buffer = "DOCUMENT", ""
    for line in lines:
        if _HEADING.match(line) and len(line) <= 180:
            if buffer:
                chunks.append((section, buffer))
                buffer = ""
            section = line
        while len(line) > maximum:
            if buffer:
                chunks.append((section, buffer))
                buffer = ""
            position = line.rfind(" ", 0, maximum + 1)
            if position < maximum // 2:
                position = maximum
            chunks.append((section, line[:position].strip()))
            line = line[position:].strip()
        if buffer and len(buffer) + len(line) + 1 > maximum:
            chunks.append((section, buffer))
            buffer = ""
        buffer = (buffer + "\n" + line).strip()
    if buffer:
        chunks.append((section, buffer))
    return chunks


def parse_documents(
    documents: Sequence[Mapping[str, object]],
    policy: EvidencePolicy | None = None,
) -> pd.DataFrame:
    """Parse primary/exhibit text, preserving source identity and failure rows.

    An embedded document in a successful complete submission can supply the
    same source when its standalone response failed. Raw download failures are
    still retained as status rows for explicit coverage reporting.
    """
    rules = policy or EvidencePolicy()
    rows: list[dict[str, object]] = []
    available = {
        (str(doc["filing_id"]), str(doc["document_filename"]))
        for doc in documents
        if doc["status"] == "DOWNLOADED" and doc["document_type"] not in {"INDEX", "SUBMISSION"}
    }
    for document in documents:
        base = {name: document.get(name) for name in CHUNK_COLUMNS}
        if document["status"] != "DOWNLOADED":
            rows.append({**base, "status": document["status"], "chunk_id": None})
            continue
        raw_path = Path(str(document["local_path"]))
        if sha256_file(raw_path) != document["sha256"]:
            raise ValueError("SEC response changed before parsing")
        if document["document_type"] == "INDEX":
            if document.get("parse_status") == "INVALID_INDEX":
                rows.append({**base, "status": "INVALID_INDEX", "chunk_id": None})
            continue
        raw = raw_path.read_bytes()
        if raw.startswith(b"%PDF"):
            rows.append(
                {
                    **base,
                    "status": "UNSUPPORTED",
                    "chunk_id": None,
                    "error_reason": "PDF_NOT_PARSED",
                }
            )
            continue
        text = raw.decode("utf-8", errors="replace")
        sources: list[tuple[dict[str, object], str]] = []
        if document["document_type"] == "SUBMISSION":
            embedded_sources = _embedded_documents(text)
            if not embedded_sources:
                rows.append(
                    {
                        **base,
                        "status": "INVALID_SUBMISSION",
                        "chunk_id": None,
                        "error_reason": "NO_EMBEDDED_DOCUMENTS",
                    }
                )
            for embedded in embedded_sources:
                kind, filename = embedded["document_type"], embedded["document_filename"]
                if (kind == str(document["form"]) or kind.startswith("EX-99")) and (
                    str(document["filing_id"]),
                    filename,
                ) not in available:
                    sources.append(
                        (
                            {**base, "document_type": kind, "document_filename": filename},
                            embedded["text"],
                        )
                    )
        else:
            sources.append((base, text))
        for source, body in sources:
            if str(source["document_filename"]).lower().endswith(".pdf") or re.search(
                r"<PDF>", body, flags=re.I
            ):
                rows.append(
                    {
                        **source,
                        "status": "UNSUPPORTED",
                        "chunk_id": None,
                        "error_reason": "EMBEDDED_PDF_NOT_PARSED",
                    }
                )
                continue
            parsed = _sections(_clean_lines(body), rules.chunk_chars)
            if not parsed:
                rows.append(
                    {
                        **source,
                        "status": "EMPTY",
                        "chunk_id": None,
                        "error_reason": "NO_USABLE_TEXT",
                    }
                )
            for order, (section, content) in enumerate(parsed):
                digest = hashlib.sha256(content.encode()).hexdigest()
                identity = [
                    source["filing_id"],
                    source["document_filename"],
                    section,
                    order,
                    digest,
                    source["sha256"],
                ]
                rows.append(
                    {
                        **source,
                        "chunk_id": "chunk_" + hashlib.sha256(_json_bytes(identity)).hexdigest(),
                        "section_label": section,
                        "chunk_order": order,
                        "chunk_text": content,
                        "char_count": len(content),
                        "token_estimate": math.ceil(len(content) / 4),
                        "text_sha256": digest,
                        "status": "OK",
                        "error_reason": None,
                    }
                )
    result = pd.DataFrame(rows, columns=list(CHUNK_COLUMNS))
    result["acceptance_datetime_utc"] = pd.to_datetime(result["acceptance_datetime_utc"], utc=True)
    for name in ("chunk_order", "char_count", "token_estimate"):
        result[name] = result[name].astype("Int64")
    return result.reset_index(drop=True)


def _rank(chunk: Mapping[str, object], cutoff: datetime) -> float:
    words = Counter(_WORDS.findall(str(chunk["chunk_text"]).lower()))
    lexical = sum(1 + math.log(count) for word, count in words.items() if word in _QUERY)
    age = (cutoff - _utc(chunk["acceptance_datetime_utc"], "acceptance")).total_seconds() / 86400
    return lexical / math.sqrt(max(1, sum(words.values()))) + 0.05 / (1 + age / 30)


def build_evidence_pack(
    event: Mapping[str, object],
    selected_filings: Sequence[Mapping[str, object]],
    chunks: pd.DataFrame,
    coverage: Mapping[str, Mapping[str, object]],
    policy: EvidencePolicy | None = None,
) -> dict[str, object]:
    """Admissibility first, deterministic lexical rank second, bounded pack last."""
    rules = policy or EvidencePolicy()
    moment, cutoff = _event_times(event)
    selected = {str(row["filing_id"]): row for row in selected_filings}
    if len(selected) != len(selected_filings):
        raise ValueError("Selected SEC accession IDs must be unique")
    for selected_filing in selected.values():
        if _utc(selected_filing["acceptance_datetime_utc"], "filing acceptance") > cutoff:
            raise ValueError("Selected SEC filing follows the evidence cutoff")
    eligible: dict[str, list[dict[str, object]]] = {"A": [], "B": []}
    failure_ids: dict[str, set[str]] = {"A": set(), "B": set()}
    for row in cast(list[dict[str, object]], chunks.to_dict("records")):
        filing = selected.get(str(row["filing_id"]))
        if filing is None:
            continue
        leg = str(filing["leg"])
        if leg not in eligible or str(row["security_id"]) != str(filing["security_id"]):
            raise ValueError("SEC chunk security disagrees with selected filing identity")
        accepted = _utc(row["acceptance_datetime_utc"], "chunk acceptance")
        source_accepted = _utc(filing["acceptance_datetime_utc"], "filing acceptance")
        if accepted > cutoff or source_accepted > cutoff:
            continue
        if accepted != source_accepted:
            raise ValueError("SEC chunk acceptance disagrees with source filing")
        if row["status"] != "OK" or _missing(row["chunk_id"]):
            failure_ids[leg].add(str(row["filing_id"]))
            continue
        if row["document_type"] != filing["form"] and not str(row["document_type"]).startswith(
            "EX-99"
        ):
            continue
        digest = hashlib.sha256(str(row["chunk_text"]).encode()).hexdigest()
        if digest != row["text_sha256"]:
            raise ValueError("SEC chunk text hash mismatch")
        url = urlparse(str(row["source_url"]))
        if (
            url.scheme != "https"
            or url.hostname not in {"www.sec.gov", "data.sec.gov"}
            or url.username
            or url.password
            or url.port not in (None, 443)
            or not url.path.startswith("/Archives/edgar/data/")
        ):
            raise ValueError("Historical SEC evidence must retain an official HTTPS source")
        if not re.fullmatch(r"[0-9a-f]{64}", str(row["sha256"])):
            raise ValueError("SEC evidence requires an immutable raw SHA-256 hash")
        raw_relative = str(row["raw_file_path"])
        if (
            "\\" in raw_relative
            or ":" in raw_relative
            or ".." in PurePosixPath(raw_relative).parts
            or PurePosixPath(raw_relative).is_absolute()
        ):
            raise ValueError("SEC evidence raw provenance must use a portable relative path")
        row["leg"] = leg
        row["acceptance_datetime_utc"] = accepted.isoformat()
        row["relevance_score"] = _rank(row, cutoff)
        eligible[leg].append(row)
    if len({str(row["chunk_id"]) for rows in eligible.values() for row in rows}) != sum(
        len(rows) for rows in eligible.values()
    ):
        raise ValueError("SEC chunks must have unique stable IDs")
    result_coverage: dict[str, dict[str, object]] = {}
    for leg in ("A", "B"):
        info = dict(coverage[leg])
        expected = {str(value) for value in cast(list[object], info["selected_filing_ids"])}
        actual = {str(filing["filing_id"]) for filing in selected.values() if filing["leg"] == leg}
        if expected != actual or any(
            filing["security_id"] != info["security_id"]
            for filing in selected.values()
            if filing["leg"] == leg
        ):
            raise ValueError("SEC coverage identity disagrees with the selected filing set")
        present = {str(row["filing_id"]) for row in eligible[leg]}
        failed = failure_ids[leg] | (expected - present)
        if not present:
            status, reason = "UNKNOWN", "NO_USABLE_ADMISSIBLE_DOCUMENTS"
        elif (
            failed
            or _missing(info.get("periodic_filing_id"))
            or info.get("missing_acceptance_count", 0)
        ):
            status, reason = "PARTIAL", "INCOMPLETE_DOCUMENT_OR_PERIODIC_COVERAGE"
        else:
            status, reason = "COMPLETE", "SELECTED_DOCUMENTS_VALIDATED"
        info.update(
            status=status,
            reason=reason,
            available_filing_ids=sorted(present),
            failed_filing_ids=sorted(failed),
        )
        result_coverage[leg] = info
        eligible[leg].sort(
            key=lambda row: (
                -float(cast(float, row["relevance_score"])),
                str(row["filing_id"]),
                str(row["chunk_id"]),
            )
        )
    chosen: list[dict[str, object]] = []
    remaining = rules.max_total_chars
    # Round-robin gives both companies space before either exhausts the budget.
    for position in range(rules.max_chunks_per_leg):
        for leg in ("A", "B"):
            if position < len(eligible[leg]):
                row = eligible[leg][position]
                count = int(cast(int, row["char_count"]))
                if count <= remaining:
                    chosen.append(row)
                    remaining -= count
    statuses = {str(value["status"]) for value in result_coverage.values()}
    overall = (
        "COMPLETE"
        if statuses == {"COMPLETE"}
        else "UNKNOWN"
        if statuses == {"UNKNOWN"}
        else "PARTIAL"
    )
    result: dict[str, object] = {
        "event_id": str(event["event_id"]),
        "pair_id": str(event["pair_id"]),
        "event_timestamp": moment.isoformat(),
        "evidence_cutoff": cutoff.isoformat(),
        "policy_version": rules.version,
        "evidence_policy": asdict(rules),
        "coverage": result_coverage,
        "coverage_status": overall,
        "chunks": chosen,
        "selected_filing_ids": sorted(selected),
        "total_chars": rules.max_total_chars - remaining,
    }
    result["evidence_hash"] = hashlib.sha256(_json_bytes(result)).hexdigest()
    return result
