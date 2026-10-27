import hashlib
import json
from typing import Any

import numpy as np
import pandas as pd

from structural_break.intelligence import catalysts as cv
from structural_break.intelligence import recent_news as rn

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
HEADLINE = (
    "Acme Corp announces agreement to acquire Widget Inc for $2 billion. The deal closes in May."
)


def _filing(security: str, filing_id: str, accepted: str, form: str = "8-K") -> dict[str, Any]:
    stamp = pd.Timestamp(accepted, tz="UTC")
    return {
        "security_id": security,
        "filing_id": filing_id,
        "form": form,
        "acceptance_datetime_utc": stamp,
        "acceptance_lower_bound_utc": stamp,
    }


def _events(move_a: float = -0.05, move_b: float = 0.01) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "event_id": "e1",
                "event_timestamp": "2015-03-03T21:00:00+00:00",
                "leg_a_security_id": "US:A",
                "leg_b_security_id": "US:B",
                "abnormal_return_A_1d": move_a,
                "abnormal_return_B_1d": move_b,
            }
        ]
    )


def test_windows_keep_the_latest_two_8ks_from_the_last_three_sessions() -> None:
    filings = pd.DataFrame(
        [
            _filing("US:A", "f1", "2015-03-03 12:00"),
            _filing("US:A", "f2", "2015-03-02 12:00"),
            _filing("US:A", "f3", "2015-02-27 12:00"),
            _filing("US:A", "old", "2015-02-20 12:00"),
            _filing("US:A", "late", "2015-03-03 22:00"),
            _filing("US:B", "q", "2015-03-03 12:00", form="10-Q"),
        ]
    )
    windows = rn.leg_windows(_events(), filings, {"US:A": KNOWN, "US:B": KNOWN}, CLOSES)
    a, b = windows.iloc[0], windows.iloc[1]
    assert a["filing_ids"] == ["f1", "f2"] and a["eight_k_count"] == 3 and a["leg_key"]
    assert b["known"] and b["filing_ids"] == [] and b["leg_key"] is None
    unknown = rn.leg_windows(
        _events(), filings, {"US:A": {"status": "PARTIAL"}, "US:B": KNOWN}, CLOSES
    )
    assert not unknown.iloc[0]["known"] and unknown.iloc[0]["leg_key"] is None


def _chunk(
    filing: str, doc: str, order: int, text: str, section: str = "DOCUMENT"
) -> dict[str, Any]:
    return {
        "status": "OK",
        "filing_id": filing,
        "document_type": doc,
        "document_filename": f"{doc}.htm",
        "chunk_order": order,
        "chunk_id": f"{filing}-{doc}-{order}",
        "section_label": section,
        "chunk_text": text,
        "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        "acceptance_datetime_utc": pd.Timestamp("2015-03-03 12:00", tz="UTC"),
    }


def test_chunk_choice_prefers_item_text_and_the_exhibit_headline() -> None:
    chunks = pd.DataFrame(
        [
            _chunk("f1", "8-K", 0, "UNITED STATES SECURITIES AND EXCHANGE COMMISSION cover page"),
            _chunk("f1", "8-K", 1, "Item 8.01 Other Events. The company issued a press release."),
            _chunk("f1", "EX-99.1", 0, HEADLINE),
            _chunk("f1", "EX-99.1", 1, "Financial tables 1 2 3"),
        ]
    )
    picked = rn.select_chunks(chunks, ["f1"])
    assert [c["chunk_id"] for c in picked] == ["f1-8-K-1", "f1-EX-99.1-0"]


def _pack() -> dict[str, Any]:
    chunks = pd.DataFrame([_chunk("f1", "EX-99.1", 0, HEADLINE)])
    return {"security_id": "US:A", "filing_ids": ["f1"], "chunks": rn.select_chunks(chunks, ["f1"])}


def _ok(text: str) -> tuple[int, Any]:
    return 200, {
        "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": text}]}}],
        "usageMetadata": {"promptTokenCount": 800, "candidatesTokenCount": 30},
    }


def _client(replies: list[tuple[int, Any]]) -> cv.ModelClient:
    prompts: list[str] = []

    def transport(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: float):
        prompts.append(payload["contents"][0]["parts"][0]["text"])
        return replies.pop(0)

    client = cv.ModelClient(
        cv.MODELS[0], credential=lambda: "k", transport=transport, sleep=lambda s: None
    )
    client.prompts = prompts  # type: ignore[attr-defined]
    return client


DEAL = {
    "event_type": "M&A",
    "direction": "POSITIVE",
    "materiality": "HIGH",
    "extraction_confidence": 0.9,
    "citations": ["C1.1"],
}


def test_extraction_resolves_sentences_and_retries_with_a_specific_correction() -> None:
    wrong = {**DEAL, "event_type": "LITIGATION"}
    client = _client([_ok(json.dumps(wrong)), _ok("```json\n" + json.dumps(DEAL) + "\n```")])
    record = rn.extract_leg(client, _pack())
    assert record["status"] == "SUCCESS" and record["response"]["citations"][0]["quote"] in HEADLINE
    assert "contains a LITIGATION term" in client.prompts[1]  # type: ignore[attr-defined]
    none = {
        **DEAL,
        "event_type": "NONE",
        "direction": "UNKNOWN",
        "materiality": "UNKNOWN",
        "citations": [],
    }
    assert rn.extract_leg(_client([_ok(json.dumps(none))]), _pack())["status"] == "NONE"
    empty = rn.extract_leg(_client([]), {**_pack(), "chunks": []})
    assert empty["reasons"] == ["NO_PARSEABLE_8K_TEXT"]


def test_features_mark_mover_news_and_unknowns() -> None:
    windows = pd.DataFrame(
        [
            {"event_id": "e1", "leg": "a", "known": True, "filing_ids": ["f1"], "leg_key": "k1"},
            {"event_id": "e1", "leg": "b", "known": True, "filing_ids": [], "leg_key": None},
        ]
    )
    negative = {"status": "SUCCESS", "response": {**DEAL, "direction": "NEGATIVE"}}
    row = rn.news_features(_events(), windows, lambda key: negative).iloc[0]
    assert (
        row["news_a_material"] == 1 and row["news_a_negative"] == 1 and row["news_a_corporate"] == 1
    )
    assert row["news_b_material"] == 0 and row["news_one_sided_material"] == 1
    assert row["news_mover_material"] == 1 and row["news_mover_explains_move"] == 1
    rose = rn.news_features(_events(move_a=0.05), windows, lambda key: negative).iloc[0]
    assert rose["news_mover_explains_move"] == 0
    failed = rn.news_features(_events(), windows, lambda key: {"status": "UNKNOWN"}).iloc[0]
    assert np.isnan(failed["news_a_material"]) and np.isnan(failed["news_mover_material"])
    assert failed["news_b_material"] == 0


def test_news_vocabulary_accepts_typical_8k_wording() -> None:
    def label(kind: str, sentence: str) -> rn.LegNews:
        return rn.LegNews.model_validate(
            {
                "event_type": kind,
                "direction": "POSITIVE",
                "materiality": "MEDIUM",
                "extraction_confidence": 0.8,
                "citations": [{"chunk_id": "c", "quote": sentence}],
            }
        )

    label("EARNINGS", "BERKLEY CORPORATION REPORTS FIRST QUARTER RESULTS")
    label("FINANCING", "Delta completed its previously announced offering of senior secured notes")
    label("PRODUCT_OTHER", "Entry into a Material Definitive Agreement.")
    try:
        label("LITIGATION", "Other comprehensive income (loss):")
    except ValueError:
        pass
    else:
        raise AssertionError("table boilerplate must not support LITIGATION")
    assert "FINANCING" in rn.CORPORATE and "EARNINGS" not in rn.CORPORATE
