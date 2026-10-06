"""Sentiment boundaries/coverage/replay use the production interface without weights."""

import copy
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from structural_break.config.paths import ProjectPaths
from structural_break.intelligence.evidence import (
    build_evidence_pack,
    cache_filing,
    parse_documents,
    select_event_filings,
)
from structural_break.intelligence.fixtures import make_evidence_fixture
from structural_break.intelligence.sentiment import (
    FINBERT_MODEL,
    FINBERT_REVISION,
    SENTIMENT_FEATURE_COLUMNS,
    FinBERTPolicy,
    HuggingFaceFinBERT,
    SentimentFailure,
    score_sentiment_pack,
    validate_sentiment_result,
)


class MockBackend:
    model_name = FINBERT_MODEL
    model_revision = FINBERT_REVISION
    runtime = {"synthetic": "true"}

    def __init__(self) -> None:
        self.texts: list[str] = []
        self.windows: list[list[int]] = []
        self.calls = 0

    def token_ids(self, text: str) -> Sequence[int]:
        self.texts.append(text)
        return list(range(1, len(text.split()) + 1))

    def predict(self, windows: Sequence[Sequence[int]]) -> Sequence[Mapping[str, float]]:
        self.calls += 1
        self.windows.extend(map(list, windows))
        return [{"positive": 0.7, "negative": 0.2, "neutral": 0.1} for _ in windows]


def pack() -> dict[str, Any]:
    text = "Earnings increased. Sales grew substantially."
    return {
        "event_id": "evt_1",
        "pair_id": "KO__PEP",
        "event_timestamp": "2022-04-01T20:00:00+00:00",
        "evidence_cutoff": "2022-04-01T20:00:00+00:00",
        "coverage": {
            "A": {"security_id": "KO", "status": "COMPLETE"},
            "B": {"security_id": "PEP", "status": "COMPLETE"},
        },
        "chunks": [
            {
                "chunk_id": f"chunk_{leg}",
                "filing_id": f"filing_{leg}",
                "leg": leg,
                "security_id": ticker,
                "acceptance_datetime_utc": "2022-03-30T10:00:00+00:00",
                "chunk_text": text,
                "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                "sha256": "a" * 64,
                "source_url": "https://www.sec.gov/Archives/edgar/data/1/filing/report.htm",
                "status": "OK",
            }
            for leg, ticker in (("A", "KO"), ("B", "PEP"))
        ],
    }


def score(tmp_path: Path, evidence: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
    return score_sentiment_pack(
        evidence or pack(),
        kwargs.pop("backend", MockBackend()),
        tmp_path,
        leg_security_ids=("KO", "PEP"),
        **kwargs,
    )


def test_compact_features_and_exact_window_provenance(tmp_path: Path) -> None:
    result = score(tmp_path)
    assert tuple(result["features"]) == SENTIMENT_FEATURE_COLUMNS
    assert len(SENTIMENT_FEATURE_COLUMNS) == 17
    assert result["features"]["sentiment_a_positive"] == pytest.approx(0.7)
    assert result["features"]["sentiment_a_net"] == pytest.approx(0.5)
    assert result["features"]["sentiment_net_contrast"] == 0
    assert result["features"]["sentiment_both_known"] == 1
    assert result["retrospective_pretrained_extractor"] is True
    assert result["pretrained_model_available_from"] == "2020-12-24"
    row = result["chunks"][0]
    assert row["security_id"] == "KO"
    assert row["sentence_count"] == row["fully_scored_sentence_count"] == 2
    assert row["window_count"] == row["scored_window_count"] == 2
    assert row["token_coverage"] == 1
    text = pack()["chunks"][0]["chunk_text"]
    for window in row["windows"]:
        assert text[window["sentence_char_start"] : window["sentence_char_end"]] in (
            "Earnings increased.",
            "Sales grew substantially.",
        )


def test_identical_text_cache_reuses_inference_but_reattaches_issuer_identity(
    tmp_path: Path,
) -> None:
    backend = MockBackend()
    first = score(tmp_path, backend=backend)
    second = score(tmp_path, backend=backend)
    assert first == second
    assert backend.calls == 1  # Same exact text on two distinct issuer legs.
    assert first["chunks"][0]["cache_key"] == first["chunks"][1]["cache_key"]
    assert first["chunks"][0]["security_id"] != first["chunks"][1]["security_id"]
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_long_sentence_splits_tokens_without_truncation(tmp_path: Path) -> None:
    evidence = pack()
    text = " ".join(f"word{index}" for index in range(23))
    evidence["chunks"][0].update(
        chunk_text=text, text_sha256=hashlib.sha256(text.encode()).hexdigest()
    )
    evidence["chunks"] = evidence["chunks"][:1]
    backend = MockBackend()
    result = score(tmp_path, evidence, backend=backend, policy=FinBERTPolicy(max_tokens=8))
    row = result["chunks"][0]
    assert [len(ids) for ids in backend.windows] == [6, 6, 6, 5]
    assert [value for ids in backend.windows for value in ids] == list(range(1, 24))
    assert row["token_count"] == row["scored_token_count"] == 23
    assert row["window_count"] == 4
    assert row["fully_scored_sentence_count"] == 1
    assert row["status"] == "SUCCESS"


def test_window_budget_records_omissions_and_partial_sentence(tmp_path: Path) -> None:
    evidence = pack()
    text = " ".join(f"word{index}" for index in range(23))
    evidence["chunks"][0].update(
        chunk_text=text, text_sha256=hashlib.sha256(text.encode()).hexdigest()
    )
    evidence["chunks"] = evidence["chunks"][:1]
    result = score(tmp_path, evidence, policy=FinBERTPolicy(max_tokens=8, max_windows_per_chunk=2))
    row = result["chunks"][0]
    assert row["status"] == "PARTIAL"
    assert row["reason"] == "EXPLICIT_WINDOW_BUDGET"
    assert row["window_count"] == 4
    assert row["scored_window_count"] == 2
    assert row["fully_scored_sentence_count"] == 0
    assert row["token_coverage"] == pytest.approx(12 / 23)
    assert result["legs"]["A"]["status"] == "PARTIAL"


def test_missing_evidence_is_unknown_not_neutral(tmp_path: Path) -> None:
    evidence = pack()
    evidence["chunks"] = []
    evidence["coverage"]["A"]["status"] = "UNKNOWN"
    backend = MockBackend()
    result = score(tmp_path, evidence, backend=backend)
    assert backend.calls == 0
    for leg in ("a", "b"):
        assert result["features"][f"sentiment_{leg}_neutral"] is None
        assert result["features"][f"sentiment_{leg}_unknown"] == 1
        assert result["features"][f"sentiment_{leg}_token_coverage"] == 0
    assert result["features"]["sentiment_net_contrast"] is None


def test_partial_source_coverage_remains_distinct_from_model_tone(tmp_path: Path) -> None:
    evidence = pack()
    evidence["coverage"]["A"]["status"] = "PARTIAL"
    result = score(tmp_path, evidence)
    assert result["legs"]["A"]["status"] == "PARTIAL"
    assert result["legs"]["A"]["source_coverage_status"] == "PARTIAL"
    assert result["features"]["sentiment_a_positive"] is not None


def test_failed_runtime_unknown_is_retryable_not_immutably_cached(tmp_path: Path) -> None:
    class FailingBackend(MockBackend):
        def predict(self, windows: Sequence[Sequence[int]]) -> Sequence[Mapping[str, float]]:
            raise SentimentFailure("LOCAL_INFERENCE_FAILED")

    failure = score(tmp_path, backend=FailingBackend())
    assert failure["chunks"][0]["status"] == "UNKNOWN"
    assert failure["features"]["sentiment_a_neutral"] is None
    assert not list(tmp_path.glob("*.json"))
    success = score(tmp_path)
    assert success["chunks"][0]["status"] == "SUCCESS"


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("acceptance_datetime_utc", "2022-04-01T20:00:00.000001+00:00", "Future SEC"),
        ("acceptance_datetime_utc", None, "timezone-aware"),
        ("acceptance_datetime_utc", "2022-03-30T10:00:00", "timezone-aware"),
        ("security_id", "other_issuer", "identity mismatch"),
        ("leg", "C", "identity mismatch"),
        ("text_sha256", "b" * 64, "text hash"),
        ("sha256", "not-a-hash", "provenance"),
        ("source_url", "https://example.com/future.html", "provenance"),
        ("point_in_time_eligible", False, "Inadmissible"),
    ],
)
def test_admissibility_rejections_happen_before_inference(
    tmp_path: Path, field: str, value: object, reason: str
) -> None:
    evidence, backend = pack(), MockBackend()
    evidence["chunks"][0][field] = value
    with pytest.raises(ValueError, match=reason):
        score(tmp_path, evidence, backend=backend)
    assert backend.calls == 0
    assert backend.texts == []


def test_event_cutoff_and_unique_ids_are_blocking(tmp_path: Path) -> None:
    evidence = pack()
    evidence["evidence_cutoff"] = "2022-04-01T20:00:01+00:00"
    with pytest.raises(ValueError, match="cannot follow"):
        score(tmp_path, evidence)
    evidence = pack()
    evidence["chunks"][1]["chunk_id"] = evidence["chunks"][0]["chunk_id"]
    with pytest.raises(ValueError, match="unique"):
        score(tmp_path, evidence)


def test_future_empty_or_failed_chunk_does_not_bypass_time_check(tmp_path: Path) -> None:
    evidence = pack()
    evidence["chunks"][0].update(
        chunk_text="", status="FAILED", acceptance_datetime_utc="2023-01-01T10:00:00+00:00"
    )
    with pytest.raises(ValueError, match="Future SEC"):
        score(tmp_path, evidence)


def test_targets_scores_and_irrelevant_fields_never_reach_backend_or_identity(
    tmp_path: Path,
) -> None:
    clean = pack()
    extra = copy.deepcopy(clean)
    extra.update(y_revert_success=1, raw_probability=0.99, final_outcome="SUCCESS")
    extra["chunks"][0].update(y_revert_success=0, calibrated_probability=0.1)
    backend = MockBackend()
    first = score(tmp_path, clean, backend=backend)
    second = score(tmp_path, extra, backend=backend)
    assert first == second
    assert all(text in clean["chunks"][0]["chunk_text"] for text in backend.texts)
    assert not any(word in json.dumps(first) for word in ("y_revert_success", "raw_probability"))


def test_cache_is_keyed_by_exact_text_revision_and_preprocessing(tmp_path: Path) -> None:
    backend = MockBackend()
    first = score(tmp_path, backend=backend)
    modified = pack()
    text = modified["chunks"][0]["chunk_text"] + " "
    modified["chunks"][0].update(
        chunk_text=text, text_sha256=hashlib.sha256(text.encode()).hexdigest()
    )
    second = score(tmp_path, modified, backend=backend)
    third = score(tmp_path, backend=backend, policy=FinBERTPolicy(max_tokens=256))
    assert backend.calls == 3
    assert first["chunks"][0]["cache_key"] != second["chunks"][0]["cache_key"]
    assert first["chunks"][0]["cache_key"] != third["chunks"][0]["cache_key"]
    backend.model_revision = "f" * 40
    with pytest.raises(ValueError, match="pinned"):
        score(tmp_path, backend=backend)
    fourth = score(
        tmp_path,
        backend=backend,
        policy=replace(FinBERTPolicy(), model_revision=backend.model_revision),
    )
    assert fourth["chunks"][0]["cache_key"] != first["chunks"][0]["cache_key"]


def test_cache_tampering_is_blocking_not_silently_recomputed(tmp_path: Path) -> None:
    score(tmp_path)
    cache = next(tmp_path.glob("*.json"))
    stored = json.loads(cache.read_bytes())
    stored["result"]["windows"][0]["probabilities"]["positive"] = 0.1
    cache.write_text(json.dumps(stored))
    with pytest.raises(ValueError, match="cache identity/content"):
        score(tmp_path)


def test_rehashed_wrong_window_coordinates_still_rejected(tmp_path: Path) -> None:
    score(tmp_path)
    cache = next(tmp_path.glob("*.json"))
    stored = json.loads(cache.read_bytes())
    stored["result"]["windows"][0]["token_start"] = 9
    stored["result_sha256"] = hashlib.sha256(
        json.dumps(
            stored["result"], sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
    cache.write_text(json.dumps(stored))
    with pytest.raises(ValueError, match="window provenance"):
        score(tmp_path)


@pytest.mark.parametrize(
    "probabilities",
    [
        {"positive": 0.8, "negative": 0.8, "neutral": 0.1},
        {"positive": float("nan"), "negative": 0.2, "neutral": 0.1},
        {"positive": -0.1, "negative": 0.2, "neutral": 0.9},
        {"positive": 0.7, "negative": 0.3},
    ],
)
def test_invalid_probability_outputs_are_scientific_failures(
    tmp_path: Path, probabilities: dict[str, float]
) -> None:
    class InvalidBackend(MockBackend):
        def predict(self, windows: Sequence[Sequence[int]]) -> Sequence[Mapping[str, float]]:
            return [probabilities for _ in windows]

    with pytest.raises(ValueError, match="probabilit|labels"):
        score(tmp_path, backend=InvalidBackend())


def test_optional_adapter_is_lazy_and_dependency_failure_is_redacted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = HuggingFaceFinBERT(tmp_path)
    assert backend._model is None

    def missing(name: str) -> Any:
        raise ImportError("raw-secret-dependent trace must not appear")

    monkeypatch.setattr("structural_break.intelligence.sentiment.importlib.import_module", missing)
    result = score(tmp_path, backend=backend)
    assert result["chunks"][0]["reason"] == "NLP_DEPENDENCY_UNAVAILABLE"
    assert "raw-secret" not in json.dumps(result)


def test_actual_p4_fixture_selection_cache_parser_pack_metadata_supported(
    paths: ProjectPaths,
) -> None:
    event = {
        "event_id": "evt_fixture",
        "pair_id": "KO__PEP",
        "event_timestamp": "2022-04-01T20:00:00+00:00",
        "evidence_cutoff": "2022-04-01T20:00:00+00:00",
    }
    index, get = make_evidence_fixture(pd.DataFrame([event]), paths)
    selected, coverage = select_event_filings(event, index, ["KO", "PEP"])
    documents = [document for filing in selected for document in cache_filing(paths, filing, get)]
    chunks = parse_documents(documents)
    evidence = build_evidence_pack(event, selected, chunks, coverage)
    result = score_sentiment_pack(
        evidence, MockBackend(), paths.data / "cache/sentiment", leg_security_ids=("KO", "PEP")
    )
    assert len(result["chunks"]) == len(evidence["chunks"]) > 0
    assert result["features"]["sentiment_both_known"] == 1
    assert all(row["status"] == "SUCCESS" for row in result["chunks"])


def test_stored_result_reconstructs_without_tokenizer_or_inference(tmp_path: Path) -> None:
    evidence = pack()
    result = score(tmp_path, evidence)
    assert (
        validate_sentiment_result(evidence, result, leg_security_ids=("KO", "PEP"))
        == result["features"]
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "future_timestamp",
        "issuer",
        "window_span",
        "token_gap",
        "probability",
        "coverage",
        "feature",
    ],
)
def test_offline_reconstruction_rejects_tampered_scientific_outputs(
    tmp_path: Path, mutation: str
) -> None:
    evidence = pack()
    result = score(tmp_path, evidence)
    first = result["chunks"][0]
    if mutation == "future_timestamp":
        first["acceptance_datetime_utc"] = "2023-01-01T10:00:00+00:00"
    elif mutation == "issuer":
        first["security_id"] = "other"
    elif mutation == "window_span":
        first["windows"][0]["sentence_char_start"] += 1
    elif mutation == "token_gap":
        first["windows"][0]["token_start"] = 1
    elif mutation == "probability":
        first["windows"][0]["probabilities"]["negative"] = 0.7
    elif mutation == "coverage":
        first["scored_token_count"] += 1
    elif mutation == "feature":
        result["features"]["sentiment_a_net"] = 1.0
    with pytest.raises(ValueError, match="Stored sentiment|Sentiment class probabilities"):
        validate_sentiment_result(evidence, result, leg_security_ids=("KO", "PEP"))


def test_unknown_and_budgeted_partial_results_reconstruct_offline(tmp_path: Path) -> None:
    missing = pack()
    missing["chunks"] = []
    result = score(tmp_path, missing)
    assert (
        validate_sentiment_result(missing, result, leg_security_ids=("KO", "PEP"))
        == result["features"]
    )
    evidence = pack()
    text = " ".join(f"word{index}" for index in range(23))
    evidence["chunks"][0].update(
        chunk_text=text, text_sha256=hashlib.sha256(text.encode()).hexdigest()
    )
    rules = FinBERTPolicy(max_tokens=8, max_windows_per_chunk=2)
    result = score(tmp_path, evidence, policy=rules)
    assert (
        validate_sentiment_result(evidence, result, leg_security_ids=("KO", "PEP"), policy=rules)
        == result["features"]
    )
