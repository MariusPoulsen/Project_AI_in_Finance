"""Independent model jobs coordinate short DB access, without stale PID locks."""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from structural_break.storage.database import DuckDBConnectionFactory
from structural_break.storage.process_lock import database_process_lock


def start(code: str, *arguments: str) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-c", code, *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=dict(os.environ),
    )


def stop(children: list[subprocess.Popen[str]]) -> None:
    for child in children:
        if child.poll() is None:
            child.terminate()
        child.communicate(timeout=10)


def test_concurrent_reads_and_writes_preserve_every_transaction(tmp_path: Path) -> None:
    database = tmp_path / "models.duckdb"
    factory = DuckDBConnectionFactory(database, coordinated=True)
    with factory.connect(read_only=False) as connection:
        connection.execute("CREATE TABLE records(worker INTEGER, value INTEGER)")
    code = """
import sys
from pathlib import Path
from structural_break.storage.database import DuckDBConnectionFactory
factory = DuckDBConnectionFactory(Path(sys.argv[1]), coordinated=True)
for index in range(8):
    with factory.connect(read_only=False) as connection:
        connection.execute('INSERT INTO records VALUES (?,?)', [int(sys.argv[2]),index])
    with factory.connect() as connection:
        assert connection.execute('SELECT COUNT(*) FROM records').fetchone()[0] > 0
"""
    children = [start(code, str(database), str(index)) for index in range(3)]
    try:
        for child in children:
            output, errors = child.communicate(timeout=30)
            assert child.returncode == 0, output + errors
        with factory.connect() as connection:
            assert connection.execute(
                "SELECT COUNT(*), COUNT(DISTINCT (worker,value)) FROM records"
            ).fetchone() == (24, 24)
    finally:
        stop(children)


def test_timeout_and_crash_release_ownership_without_changing_database(tmp_path: Path) -> None:
    database, ready = tmp_path / "models.duckdb", tmp_path / "ready"
    code = """
import sys, time
from pathlib import Path
from structural_break.storage.process_lock import database_process_lock
with database_process_lock(Path(sys.argv[1])):
    Path(sys.argv[2]).write_text('OWNED')
    time.sleep(30)
"""
    child = start(code, str(database), str(ready))
    try:
        deadline = time.monotonic() + 10
        while not ready.exists():
            assert child.poll() is None
            assert time.monotonic() < deadline
            time.sleep(0.02)
        with pytest.raises(TimeoutError, match="bounded"):
            with database_process_lock(database, timeout=0):
                pytest.fail("Another process owns the lock")
        child.terminate()
        child.communicate(timeout=10)
        with database_process_lock(database, timeout=1):
            assert not database.exists()
    finally:
        stop([child])


def test_ordinary_read_only_factory_creates_no_operational_files(tmp_path: Path) -> None:
    database = tmp_path / "models.duckdb"
    factory = DuckDBConnectionFactory(database)
    with factory.connect(read_only=False) as connection:
        connection.execute("CREATE TABLE t(x INTEGER)")
    before = {path.name for path in tmp_path.iterdir()}
    with factory.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM t").fetchone() == (0,)
    assert {path.name for path in tmp_path.iterdir()} == before
