"""Bounded cooperative ownership for short cross-process database operations."""

from __future__ import annotations

import errno
import importlib
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO


def _try_lock(stream: BinaryIO) -> None:
    stream.seek(0)
    if os.name == "nt":
        locking = importlib.import_module("msvcrt")
        locking.locking(stream.fileno(), locking.LK_NBLCK, 1)
    else:
        locking = importlib.import_module("fcntl")
        locking.flock(stream.fileno(), locking.LOCK_EX | locking.LOCK_NB)


def _unlock(stream: BinaryIO) -> None:
    stream.seek(0)
    if os.name == "nt":
        locking = importlib.import_module("msvcrt")
        locking.locking(stream.fileno(), locking.LK_UNLCK, 1)
    else:
        locking = importlib.import_module("fcntl")
        locking.flock(stream.fileno(), locking.LOCK_UN)


@contextmanager
def database_process_lock(path: Path, *, timeout: float = 60) -> Iterator[None]:
    """Coordinate opt-in readers/writers; fitting and source replay stay outside.

    The operating system releases ownership after a crash. The persistent lock
    file is an operational sidecar, never a scientific input or stored result.
    """
    if timeout < 0:
        raise ValueError("Database lock timeout cannot be negative")
    lock_path = path.with_name(path.name + ".process.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+b") as stream:
        if stream.seek(0, os.SEEK_END) == 0:
            stream.write(b"\0")
            stream.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                _try_lock(stream)
                break
            except OSError as error:
                if error.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                    raise
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        "Research database is busy; bounded ownership wait expired"
                    ) from None
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        try:
            yield
        finally:
            _unlock(stream)
