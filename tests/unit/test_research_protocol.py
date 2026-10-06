from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from structural_break.research.protocol import ResearchProtocol, load_protocol, partition_rows


def test_complete_horizon_purges_calibration_tail() -> None:
    protocol = load_protocol(Path("configs/research_v2.yaml"))
    rows = pd.DataFrame(
        {
            "event_date": [date(2021, 12, 1), date(2021, 12, 20), date(2022, 1, 3)],
            "horizon_end_date": [date(2021, 12, 29), date(2022, 1, 20), date(2022, 2, 1)],
        }
    )
    assert partition_rows(rows, protocol)["research_partition"].tolist() == [
        "calibration",
        "excluded",
        "assessment",
    ]


def test_protocol_and_evaluation_reject_final_test() -> None:
    protocol = load_protocol(Path("configs/research_v2.yaml"))
    values = protocol.model_dump()
    values["development_end"] = date(2024, 1, 1)
    with pytest.raises(ValueError, match="locked final"):
        ResearchProtocol.model_validate(values)
    with pytest.raises(ValueError, match="final-test"):
        partition_rows(
            pd.DataFrame(
                {"event_date": [date(2024, 1, 1)], "horizon_end_date": [date(2024, 2, 1)]}
            ),
            protocol,
        )
