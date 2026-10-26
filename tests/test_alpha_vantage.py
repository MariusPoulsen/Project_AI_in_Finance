import hashlib
from datetime import date
from pathlib import Path

import pytest

from structural_break import periods
from structural_break.intelligence import alpha_vantage as av


def _payload(n: int = 2) -> dict:
    feed = [
        {
            "title": "Acme Corp raises guidance",
            "time_published": "20230103T143000",
            "summary": "Acme raised its outlook.",
            "source": "Wire",
            "url": "https://example.com/1",
            "ticker_sentiment": [{"ticker": "ACME", "relevance_score": "0.9"}],
        },
        {
            "title": "Stocks to watch this week",
            "time_published": "20230104T000000",
            "ticker_sentiment": [{"ticker": "ACME", "relevance_score": "0.1"}],
        },
    ]
    return {"items": str(n), "feed": feed[:n]}


def test_normalise_matches_the_fnspid_layout_and_rules() -> None:
    frame = av.normalise(_payload(), "ACME", "US:ACME", "Acme Corp")
    assert list(frame.specific) == [True, False]
    assert list(frame.same_day) == [True, False]  # 14:30 counts that day; a date-only stamp waits
    assert frame.relevance.tolist() == [0.9, 0.1]
    assert (frame.source == "alpha_vantage").all()


def test_fetch_caches_reserves_and_respects_the_daily_limit(tmp_path: Path) -> None:
    calls = []

    def transport(url: str) -> dict:
        calls.append(url)
        return _payload()

    kwargs = {
        "raw": tmp_path / "raw",
        "counter": tmp_path / "count.json",
        "limit": 1,
        "transport": transport,
    }
    first = av.fetch("ACME", date(2023, 1, 1), date(2023, 6, 30), "k", **kwargs)
    again = av.fetch("ACME", date(2023, 1, 1), date(2023, 6, 30), "k", **kwargs)
    assert first == again and len(calls) == 1  # the second read comes from the cache
    with pytest.raises(av.QuotaReached):
        av.fetch("OTHER", date(2023, 1, 1), date(2023, 6, 30), "k", **kwargs)
    assert "apikey=k" in calls[0] and "time_to=20230630T2359" in calls[0]


def test_rate_limit_answer_is_not_cached(tmp_path: Path) -> None:
    def transport(url: str) -> dict:
        return {"Information": "Our standard API rate limit is 25 requests per day."}

    with pytest.raises(av.QuotaReached, match="rate limit"):
        av.fetch(
            "ACME",
            date(2023, 1, 1),
            date(2023, 6, 30),
            "k",
            raw=tmp_path / "raw",
            counter=tmp_path / "c.json",
            transport=transport,
        )
    assert not (tmp_path / "raw").exists()


def test_final_test_years_are_refused_until_the_owner_unlocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_bytes(b'{"status": "DRAFT"}')
    decisions = tmp_path / "DECISIONS.md"
    decisions.write_text(
        "# Decisions\n\n## 116. Something else\n\nNo unlock here.\n", encoding="utf-8"
    )
    monkeypatch.setattr(periods, "DECISIONS", decisions)
    monkeypatch.setattr(periods, "MANIFEST", manifest)
    with pytest.raises(PermissionError):
        av.fetch(
            "ACME",
            date(2024, 1, 1),
            date(2024, 6, 30),
            "k",
            raw=tmp_path / "raw",
            counter=tmp_path / "c.json",
            transport=lambda url: _payload(),
        )
    assert periods.data_end(decisions, manifest) == periods.DEVELOPMENT_END
    sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
    # A record that cites a different manifest does not unlock.
    decisions.write_text(
        f"## 118. Owner final-test unlock record\n\nThe owner unlocks {'0' * 64}.\n",
        encoding="utf-8",
    )
    assert periods.unlock_record(decisions, manifest) is None
    decisions.write_text(
        f"## 118. Owner final-test unlock record\n\nThe owner unlocks manifest {sha}.\n",
        encoding="utf-8",
    )
    assert periods.unlock_record(decisions, manifest) == "118. Owner final-test unlock record"
    assert periods.data_end(decisions, manifest) == periods.FINAL_TEST_END
