"""Exact streaming preambles and unchanged official SEC clock validation."""

import io
import re
from pathlib import Path

import pandas as pd
import pytest

from structural_break.research.intelligence import SubmissionClockState, _submission_clock_state
from structural_break.research.submission_header import _READ_SIZE, read_submission_preamble


@pytest.mark.parametrize("marker", [b"<DOCUMENT>", b"<document>", b"<dOcUmEnT>"])
@pytest.mark.parametrize("marker_bytes_in_first_chunk", range(len(b"<DOCUMENT>") + 1))
def test_every_marker_boundary_split_matches_full_read(
    tmp_path: Path, marker: bytes, marker_bytes_in_first_chunk: int
) -> None:
    prefix = b"\x00\xff<SEC-HEADER>\r\n<ACCEPTANCE-DATETIME>20220518070659\r\n"
    marker_at = _READ_SIZE - marker_bytes_in_first_chunk
    preamble = prefix + b"x" * (marker_at - len(prefix))
    body = preamble + marker + b"\nquoted <ACCEPTANCE-DATETIME>oops\n<DOCUMENT>later"
    path = tmp_path / "submission.txt"
    path.write_bytes(body)

    expected = re.split(rb"<DOCUMENT>", body, maxsplit=1, flags=re.I)[0]
    assert expected == preamble
    assert read_submission_preamble(path) == expected


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"<DOCUMENT>payload",
        b"a\x80\r\n<dOcUmEnT>first<DOCUMENT>second",
        b"<DOCUMENT >< DOCUMENT><DOCUMENT\n></DOCUMENT><DOCUMENTS><DOCUMENT",
        b"<DOCUMENT ><DOCUMENT>exact marker",
        b"x" * (3 * _READ_SIZE) + b"<DOCUMENT",
    ],
    ids=["empty", "marker_at_start", "first_mixed_case", "near_matches", "exact", "long_eof"],
)
def test_exact_marker_and_markerless_eof_match_full_read(tmp_path: Path, body: bytes) -> None:
    path = tmp_path / "submission.txt"
    path.write_bytes(body)
    assert (
        read_submission_preamble(path) == re.split(rb"<DOCUMENT>", body, maxsplit=1, flags=re.I)[0]
    )


def test_original_source_fixture_preamble_matches_full_read() -> None:
    path = Path(__file__).parents[1] / "fixtures" / "tiny_documents" / "filing.txt"
    assert (
        read_submission_preamble(path)
        == re.split(rb"<DOCUMENT>", path.read_bytes(), maxsplit=1, flags=re.I)[0]
    )


class TrackingStream(io.BytesIO):
    def __init__(self, body: bytes) -> None:
        super().__init__(body)
        self.read_sizes: list[int] = []
        self.bytes_read = 0

    def read(self, size: int = -1) -> bytes:
        assert 0 < size <= _READ_SIZE, "Submission reads must have bounded size"
        self.read_sizes.append(size)
        chunk = super().read(size)
        self.bytes_read += len(chunk)
        return chunk


def _filing() -> dict[str, pd.Timestamp]:
    accepted = pd.Timestamp("2022-05-18T11:06:59Z")
    return {
        "acceptance_lower_bound_utc": accepted,
        "acceptance_upper_bound_utc": accepted,
        "acceptance_datetime_utc": accepted,
    }


def test_clock_reader_stops_before_large_embedded_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    preamble = b"<SEC-HEADER>\n<ACCEPTANCE-DATETIME>20220518070659\n</SEC-HEADER>\n"
    body = preamble + b"<dOcUmEnT>\n<ACCEPTANCE-DATETIME>oops\n" + b"x" * (8 * 1024 * 1024)
    stream = TrackingStream(body)
    path = tmp_path / "submission.txt"

    def open_stream(self: Path, mode: str) -> TrackingStream:
        assert self == path and mode == "rb"
        return stream

    def forbidden_full_read(self: Path) -> bytes:
        raise AssertionError("Clock validation must not read the full submission")

    monkeypatch.setattr(Path, "open", open_stream)
    monkeypatch.setattr(Path, "read_bytes", forbidden_full_read)
    document = {"document_type": "SUBMISSION", "status": "DOWNLOADED", "local_path": str(path)}
    assert (
        _submission_clock_state([document], _filing(), pd.Timestamp("2023-01-01T00:00Z"))
        is SubmissionClockState.VERIFIED
    )
    assert stream.read_sizes == [_READ_SIZE]
    assert stream.bytes_read == _READ_SIZE < len(body)
    assert stream.closed


def test_markerless_reader_reads_all_bounded_chunks_through_eof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = b"x" * (3 * _READ_SIZE) + b"<DOCUMENT"
    stream = TrackingStream(body)
    path = tmp_path / "submission.txt"

    def open_stream(self: Path, mode: str) -> TrackingStream:
        assert self == path and mode == "rb"
        return stream

    monkeypatch.setattr(Path, "open", open_stream)
    assert read_submission_preamble(path) == body
    assert stream.bytes_read == len(body)
    assert stream.read_sizes == [_READ_SIZE] * 5
    assert stream.closed


@pytest.mark.parametrize("marker", [b"", b"<dOcUmEnT>\n"])
@pytest.mark.parametrize(
    ("field", "expected"),
    [
        (b"No clock\n", SubmissionClockState.ABSENT),
        (b"<ACCEPTANCE-DATETIME>20220518070659\n", SubmissionClockState.VERIFIED),
        (b"<ACCEPTANCE-DATETIME>\n", SubmissionClockState.EMPTY_ACCEPTANCE),
        (
            b"<acceptance-datetime> \t\r\n\r\n<ACCESSION-NUMBER>preserved\r\n",
            SubmissionClockState.EMPTY_ACCEPTANCE,
        ),
        (
            b"<ACCEPTANCE-DATETIME></ACCEPTANCE-DATETIME>\n",
            SubmissionClockState.EMPTY_ACCEPTANCE,
        ),
        (b"<ACCEPTANCE-DATETIME>oops\n", None),
        (b"<ACCEPTANCE-DATETIME>\n20220518070659\n", None),
        (b"<ACCEPTANCE-DATETIME>20220518070659\n" * 2, None),
        (b"<ACCEPTANCE-DATETIME> \n<ACCEPTANCE-DATETIME>\n", None),
    ],
)
def test_absent_empty_malformed_and_duplicate_clock_semantics_are_preserved(
    tmp_path: Path, field: bytes, expected: SubmissionClockState | None, marker: bytes
) -> None:
    path = tmp_path / "submission.txt"
    body = field + marker
    if marker:
        body += b"<ACCEPTANCE-DATETIME>oops\n<ACCEPTANCE-DATETIME>20220518070659\n"
    path.write_bytes(body)
    document = {"document_type": "SUBMISSION", "status": "DOWNLOADED", "local_path": str(path)}
    cutoff = pd.Timestamp("2023-01-01T00:00Z")
    if expected is None:
        with pytest.raises(ValueError, match="ambiguous or malformed"):
            _submission_clock_state([document], _filing(), cutoff)
    else:
        assert _submission_clock_state([document], _filing(), cutoff) is expected
