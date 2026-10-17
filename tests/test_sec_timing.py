import numpy as np
import pandas as pd

from structural_break.experiments.p6_sec_features import variants
from structural_break.intelligence.event_features import EVENT_FEATURE_NAMES
from structural_break.intelligence.timing import TIMING_FEATURE_COLUMNS, filing_timing_features

CLOSES = pd.DatetimeIndex(
    pd.to_datetime(
        [
            "2015-02-25 21:00",
            "2015-02-26 21:00",
            "2015-02-27 21:00",
            "2015-03-02 21:00",
            "2015-03-03 21:00",
        ],
        utc=True,
    )
)
KNOWN = {
    "status": "OK",
    "missing_acceptance_count": 0,
    "earliest_observed_acceptance": "2004-01-01T00:00:00+00:00",
}


def _filing(
    security: str, form: str, accepted: str, items: str | None = None, lower: str | None = None
) -> dict:
    stamp = pd.Timestamp(accepted, tz="UTC")
    return {
        "security_id": security,
        "form": form,
        "items": items,
        "acceptance_datetime_utc": stamp,
        "acceptance_lower_bound_utc": pd.Timestamp(lower, tz="UTC") if lower else stamp,
    }


def _event(**moves: float) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "event_id": "e1",
                "event_timestamp": "2015-03-03T21:00:00+00:00",
                "leg_a_security_id": "US:A",
                "leg_b_security_id": "US:B",
                "abnormal_return_A_1d": moves.get("a", 0.05),
                "abnormal_return_B_1d": moves.get("b", 0.0),
            }
        ]
    )


def test_session_windows_count_only_admissible_filings() -> None:
    filings = pd.DataFrame(
        [
            _filing("US:A", "8-K", "2015-03-03 13:00", "2.02"),  # since previous close
            _filing("US:B", "8-K", "2015-02-27 14:00"),  # within three sessions only
            _filing("US:B", "8-K", "2015-03-03 22:00"),  # after the signal close
        ]
    )
    row = filing_timing_features(_event(), filings, {"US:A": KNOWN, "US:B": KNOWN}, CLOSES).iloc[0]
    assert row["sec_a_8k_1s"] == 1 and row["sec_a_earnings_3s"] == 1
    assert row["sec_b_8k_1s"] == 0 and row["sec_b_8k_3s"] == 1
    assert row["sec_one_sided_8k_1s"] == 1 and row["sec_one_sided_8k_3s"] == 0
    assert row["sec_mover_filed_1s"] == 1


def test_mover_is_the_leg_with_the_larger_abnormal_return() -> None:
    filings = pd.DataFrame([_filing("US:A", "10-Q", "2015-03-03 12:00")])
    coverage = {"US:A": KNOWN, "US:B": KNOWN}
    moved_b = filing_timing_features(_event(a=0.01, b=-0.04), filings, coverage, CLOSES).iloc[0]
    assert moved_b["sec_mover_filed_1s"] == 0 and moved_b["sec_a_earnings_3s"] == 1
    no_return = _event()
    no_return["abnormal_return_B_1d"] = np.nan
    assert pd.isna(
        filing_timing_features(no_return, filings, coverage, CLOSES).iloc[0]["sec_mover_filed_1s"]
    )


def test_unknown_coverage_or_straddling_clock_is_null_not_zero() -> None:
    filings = pd.DataFrame([_filing("US:B", "8-K", "2015-03-03 23:00", lower="2015-03-03 13:00")])
    row = filing_timing_features(
        _event(), filings, {"US:A": {"status": "PARTIAL"}, "US:B": KNOWN}, CLOSES
    ).iloc[0]
    assert (
        row[[c for c in TIMING_FEATURE_COLUMNS if c.startswith(("sec_a_", "sec_b_"))]].isna().all()
    )
    assert pd.isna(row["sec_one_sided_8k_1s"])


def test_variants_add_or_replace_blocks_without_touching_base() -> None:
    base = ("abs_z", *EVENT_FEATURE_NAMES[:3], "sec_one_sided_recent_8k")
    available = [*TIMING_FEATURE_COLUMNS, *("full_" + name for name in EVENT_FEATURE_NAMES)]
    result = variants(base, available)
    assert result["B_timing"] == (*base, *TIMING_FEATURE_COLUMNS)
    assert result["B_full_catalyst"][1] == "full_" + EVENT_FEATURE_NAMES[0]
    assert set(result) == {"B_timing", "B_full_catalyst", "B_full_catalyst_timing"}
    assert variants(base, list(TIMING_FEATURE_COLUMNS)).keys() == {"B_timing"}


def test_walk_forward_scores_variants_and_applies_the_pass_rule() -> None:
    from structural_break.experiments import p6_sec_features as sf

    rng = np.random.default_rng(0)
    rows = []
    for year in range(2006, 2024):
        for i in range(120):
            signal = rng.normal()
            informative = float(signal > 0.8)
            rows.append(
                {
                    "event_date": f"{year}-{1 + i % 12:02d}-15",
                    "horizon_end_date": f"{year}-{1 + i % 12:02d}-28",
                    "supervised_eligible": True,
                    "y_revert_success": float(rng.random() < 0.1 + 0.5 * informative),
                    "noise": rng.normal(),
                    "news": informative,
                    "frozen|status": "COMPLETE",
                    "frozen|net": 0.01 * informative - 0.002,
                }
            )
    frame = pd.DataFrame(rows)
    result = sf.run(frame, {"B": ("noise",), "B_timing": ("noise", "news")})
    variant = result["families"]["logistic"]["variants"]["B_timing"]
    assert variant["brier_difference_vs_B"]["estimate"] < 0
    assert variant["years_better"] >= 8 and result["verdicts"] == {"B_timing": True}
    assert variant["top20_allocation_difference_vs_B"]["estimate"] > 0
