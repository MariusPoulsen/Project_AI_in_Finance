"""Read the exact SEC submission preamble without loading embedded documents."""

from __future__ import annotations

from pathlib import Path

_READ_SIZE = 64 * 1024
_DOCUMENT_MARKER = b"<document>"


def read_submission_preamble(path: str | Path) -> bytes:
    """Return bytes before the first case-insensitive exact ``<DOCUMENT>`` tag.

    Reads have bounded size and stop in the chunk containing the first marker.
    Retaining the final nine bytes catches markers spanning chunk boundaries.
    With no marker, the full file is the preamble and must be read through EOF.
    """
    preamble = bytearray()
    pending = b""
    overlap = len(_DOCUMENT_MARKER) - 1
    with Path(path).open("rb") as stream:
        while chunk := stream.read(_READ_SIZE):
            window = pending + chunk
            marker_at = window.lower().find(_DOCUMENT_MARKER)
            if marker_at >= 0:
                preamble.extend(window[:marker_at])
                return bytes(preamble)
            retained_at = max(0, len(window) - overlap)
            preamble.extend(window[:retained_at])
            pending = window[retained_at:]
    preamble.extend(pending)
    return bytes(preamble)
