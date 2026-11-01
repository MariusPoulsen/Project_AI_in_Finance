"""Supplement histories are pinned to the roster and checked before presentation."""

import hashlib
import json

import pandas as pd
import pytest

from structural_break.app_bundle.pair_history import PairHistory


@pytest.fixture
def history(tmp_path):
    dates = pd.to_datetime(["2023-01-03", "2023-01-04"])
    frames = {
        "state.parquet": pd.DataFrame(
            {"pair_id": ["A__B", "B__C"], "trading_date": dates, "z_score": [2.1, -2.1]}
        ),
        "prices.parquet": pd.DataFrame(
            {"ticker": ["A", "B", "C"], "trading_date": [dates[0]] * 3, "adj_close": [2, 3, 4]}
        ),
        "snapshots.parquet": pd.DataFrame(
            {"pair_id": ["A__B", "B__C"], "estimation_date": dates, "beta": [1, 1]}
        ),
        "crossings.parquet": pd.DataFrame({"pair_id": ["A__B", "B__C"], "event_date": dates}),
    }
    for name, frame in frames.items():
        frame.to_parquet(tmp_path / name, index=False)
    manifest = {
        "schema_version": "pair-history-v1",
        "registry_version": "pinned",
        "start": "2006-01-01",
        "end": "2023-12-31",
        "pairs": dict.fromkeys(["A__B", "B__C"], "state.parquet"),
        "files": {
            name: hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() for name in frames
        },
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    return tmp_path, manifest


def test_pair_history_filters_and_rejects_wrong_registry_roster_and_tampering(history):
    root, _ = history
    reader = PairHistory.open(root, "pinned", {"A__B", "B__C"})
    pair = reader.read("A__B")
    assert set(pair.prices.ticker) == {"A", "B"}
    assert pair.state.pair_id.tolist() == ["A__B"]
    assert pair.snapshots.pair_id.tolist() == ["A__B"]
    with pytest.raises(ValueError, match="registry"):
        PairHistory.open(root, "different", {"A__B", "B__C"})
    with pytest.raises(ValueError, match="roster"):
        PairHistory.open(root, "pinned", {"A__B"})
    with pytest.raises(ValueError, match="roster"):
        reader.read("A__C")
    with (root / "state.parquet").open("ab") as file:
        file.write(b"changed")
    with pytest.raises(ValueError, match="checksum"):
        reader.read("A__B")


def test_pair_history_rejects_final_test_rows_even_with_a_valid_file_hash(history):
    root, manifest = history
    path = root / "state.parquet"
    frame = pd.read_parquet(path)
    frame.loc[0, "trading_date"] = pd.Timestamp("2024-01-02")
    frame.to_parquet(path, index=False)
    manifest["files"]["state.parquet"] = hashlib.sha256(path.read_bytes()).hexdigest()
    (root / "manifest.json").write_text(json.dumps(manifest))
    reader = PairHistory.open(root, "pinned", {"A__B", "B__C"})
    with pytest.raises(ValueError, match="Final-test"):
        reader.read("A__B")
