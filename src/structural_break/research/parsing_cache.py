"""Bounded, operation-private memoization of already verified SEC parsing.

Every build or independent verifier creates an empty cache. Its disk entries are
locally serialized frames, never a scientific source or a cache shared with a
previous operation. A digest held in memory is checked before deserializing the
private bytes. Raw-source/hash/clock validation remains the caller's obligation
before every lookup; this cache only avoids repeating the same HTML parser.
"""

from __future__ import annotations

import hashlib
import pickle
from collections import OrderedDict
from pathlib import Path
from tempfile import TemporaryDirectory
from types import TracebackType
from typing import Self

import pandas as pd


class OperationParsingCache:
    """Keep at most 128 hot frames and spill exact copies until context exit.

    Pickle preserves pandas dtype/index/null/timestamp distinctions exactly. It
    is safe here only because payloads are created by this instance from trusted
    parser outputs, within a fresh private directory, and are matched against a
    RAM-held digest before loading. No external/shared pickle is accepted.
    """

    def __init__(self, max_hot_frames: int = 128) -> None:
        if type(max_hot_frames) is not int or not 1 <= max_hot_frames <= 128:
            raise ValueError("Parsing cache must keep between 1 and 128 hot frames")
        self._max_hot_frames = max_hot_frames
        self._temporary = TemporaryDirectory(prefix="structural-break-parse-")
        self._directory = Path(self._temporary.name)
        self._hot: OrderedDict[str, pd.DataFrame] = OrderedDict()
        self._digests: dict[str, str] = {}
        self._closed = False

    def _open(self) -> None:
        if self._closed:
            raise RuntimeError("Operation parsing cache is closed")

    def _path(self, key: str) -> Path:
        if not isinstance(key, str) or not key:
            raise ValueError("Parsing cache requires a nonempty immutable source key")
        return self._directory / (hashlib.sha256(key.encode()).hexdigest() + ".pkl")

    def __contains__(self, key: str) -> bool:
        self._open()
        return key in self._digests

    @property
    def max_hot_frames(self) -> int:
        return self._max_hot_frames

    @property
    def hot_frame_count(self) -> int:
        self._open()
        return len(self._hot)

    @property
    def entry_count(self) -> int:
        self._open()
        return len(self._digests)

    def _retain(self, key: str, frame: pd.DataFrame) -> None:
        self._hot[key] = frame
        self._hot.move_to_end(key)
        if len(self._hot) > self.max_hot_frames:
            self._hot.popitem(last=False)

    def __setitem__(self, key: str, frame: pd.DataFrame) -> None:
        self._open()
        target = self._path(key)
        if key in self._digests:
            raise ValueError("Operation parsing source keys are immutable")
        if not isinstance(frame, pd.DataFrame):
            raise ValueError("Parsing cache requires a pandas frame")
        owned = frame.copy(deep=True)
        payload = pickle.dumps(owned, protocol=pickle.HIGHEST_PROTOCOL)
        with target.open("xb") as output:
            output.write(payload)
        self._digests[key] = hashlib.sha256(payload).hexdigest()
        self._retain(key, owned)

    def __getitem__(self, key: str) -> pd.DataFrame:
        self._open()
        if key not in self._digests:
            raise KeyError(key)
        if key in self._hot:
            self._hot.move_to_end(key)
            return self._hot[key].copy(deep=True)
        try:
            payload = self._path(key).read_bytes()
        except FileNotFoundError:
            raise ValueError("Operation parsing spill is missing") from None
        if hashlib.sha256(payload).hexdigest() != self._digests[key]:
            raise ValueError("Operation parsing spill checksum mismatch")
        # Only our own bytes matching the in-memory digest reach this loader.
        frame = pickle.loads(payload)
        if not isinstance(frame, pd.DataFrame):
            raise ValueError("Operation parsing spill is not a pandas frame")
        self._retain(key, frame)
        return frame.copy(deep=True)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._hot.clear()
            self._digests.clear()
            self._temporary.cleanup()

    def __enter__(self) -> Self:
        self._open()
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
