"""Pre-registered P6 improvement experiment: decision rules on small deterministic data."""

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from structural_break.backtest.contracts import ExecutionConfig
from structural_break.backtest.production_policy import load_headline
from structural_break.pipeline.sources import (
    paired_block_bootstrap,
)

CONFIGS = Path(__file__).resolve().parents[1] / "configs"


def test_production_modes_cannot_change_the_exit_or_freeze_research() -> None:
    base = load_headline(CONFIGS).model_dump(mode="json")
    with pytest.raises(ValidationError, match="Only research exit variants"):
        ExecutionConfig.model_validate_json(json.dumps(base | {"adverse_boundary": 4.0}))
    with pytest.raises(ValidationError, match="cannot be frozen"):
        ExecutionConfig.model_validate_json(
            json.dumps(base | {"mode": "RESEARCH", "convergence_band": 0.25})
        )


def _simulated(rows: list[tuple[int, bool, dict[str, float]]]) -> pd.DataFrame:
    records = []
    for index, (year, active, nets) in enumerate(rows):
        record: dict[str, object] = {
            "event_id": f"E{index}",
            "event_date": date(year, 6, 1),
            "active": active,
        }
        for name, net in nets.items():
            record[f"{name}|status"] = "COMPLETE"
            record[f"{name}|net"] = net
        records.append(record)
    return pd.DataFrame(records)


def test_paired_block_bootstrap_is_deterministic_and_needs_twelve_blocks() -> None:
    blocks = np.repeat([f"2022-{month:02d}" for month in range(1, 13)], 3)
    left = np.zeros(len(blocks))
    right = np.linspace(-0.01, 0.02, len(blocks))
    first = paired_block_bootstrap(left, right, blocks)
    assert first == paired_block_bootstrap(left, right, blocks)
    assert first["blocks_n"] == 12 and first["interval_95"] is not None
    assert first["estimate"] == pytest.approx(right.mean())
    few = paired_block_bootstrap(left[:6], right[:6], blocks[:6])
    assert few["interval_95"] is None
