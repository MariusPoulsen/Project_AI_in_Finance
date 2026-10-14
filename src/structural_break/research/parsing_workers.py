"""Bounded, verifier-owned processes for already validated SEC inventories."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from concurrent.futures import Future, ProcessPoolExecutor
from multiprocessing import get_context
from threading import get_ident
from types import TracebackType
from typing import Self

import pandas as pd

from structural_break.intelligence.evidence import EvidencePolicy, parse_documents


def _parse_inventory(documents: list[dict[str, object]], policy: EvidencePolicy) -> pd.DataFrame:
    # Keep the original parser's own raw hash and alias/provenance checks.
    return parse_documents(documents, policy)


class VerificationParsingPool:
    """Own exactly two spawned workers and at most two outstanding inventories.

    Only the caller validates event/SGML admissibility and owns the fresh parsing
    cache. Workers perform the unchanged parser and return frames to the caller;
    they never write caches, call providers or perform neural inference.
    """

    def __init__(self, workers: int = 2) -> None:
        if type(workers) is not int or workers != 2:
            raise ValueError("Independent verification permits exactly two parsing workers")
        self._owner = get_ident()
        self._executor = ProcessPoolExecutor(max_workers=workers, mp_context=get_context("spawn"))
        self._pending: set[Future[pd.DataFrame]] = set()
        self._closed = False

    def _check_owner(self) -> None:
        if get_ident() != self._owner:
            raise RuntimeError("Parsing worker pool must be owned by the verifier coordinator")

    def _open(self) -> None:
        self._check_owner()
        if self._closed:
            raise RuntimeError("Independent parsing worker pool is closed")

    def submit(
        self, documents: Sequence[Mapping[str, object]], policy: EvidencePolicy
    ) -> Future[pd.DataFrame]:
        self._open()
        if len(self._pending) >= 2:
            raise RuntimeError("Independent parsing permits at most two outstanding inventories")
        future = self._executor.submit(_parse_inventory, [dict(row) for row in documents], policy)
        self._pending.add(future)
        return future

    def result(self, future: Future[pd.DataFrame]) -> pd.DataFrame:
        self._open()
        if future not in self._pending:
            raise ValueError("Parsing result does not belong to this verifier operation")
        try:
            return future.result()
        finally:
            self._pending.remove(future)

    def cancel_pending(self) -> None:
        self._open()
        for future in self._pending:
            future.cancel()

    def close(self) -> None:
        self._check_owner()
        if not self._closed:
            self._closed = True
            for future in self._pending:
                future.cancel()
            self._executor.shutdown(wait=True, cancel_futures=True)
            self._pending.clear()

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
