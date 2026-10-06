"""Target-free, point-in-time SEC tone features for the separate research-v2 study.

FinBERT classifies financial tone, not catalysts or reversion probabilities. Its
fixed modern weights are a retrospective feature extractor: they were not
available to signals before December 2020. SEC acceptance still governs text
admissibility. Nothing here changes the registered Phase 4 experiment.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

from structural_break.storage.files import sha256_file, write_bytes

FINBERT_MODEL = "ProsusAI/finbert"
FINBERT_REVISION = "4556d13015211d73dccd3fdd39d39232506f3e43"
FINBERT_WEIGHTS_SHA256 = "e15a7b5738df7f17553399b6d94c6e2ff69c89245d066e8e5d183f5803a554e3"
# Pinned official HF files; small-file content also matched the model API Git blobs.
FINBERT_ASSETS_SHA256 = {
    "pytorch_model.bin": FINBERT_WEIGHTS_SHA256,
    "config.json": "f6449ddda85eb726207a40be59c0cd3bd4b142ccb27298d5e45f9ae3396b1abe",
    "vocab.txt": "07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3",
    "tokenizer_config.json": "ffc7913f6084b138dad68de5a0c2f0ee25ac983709260901e01f53be5796b9d9",
    "special_tokens_map.json": "303df45a03609e4ead04bc3dc1536d0ab19b5358db685b6f3da123d05ec200e3",
}
SENTIMENT_SCHEMA_VERSION = "sec-finbert-research-v2.1"
_LABELS = ("positive", "negative", "neutral")
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+|\n+")
SENTIMENT_FEATURE_COLUMNS = tuple(
    f"sentiment_{leg}_{name}"
    for leg in ("a", "b")
    for name in ("positive", "negative", "neutral", "net", "token_coverage", "unknown")
) + (
    "sentiment_net_contrast",
    "sentiment_net_asymmetry",
    "sentiment_both_known",
    "sentiment_window_count",
    "sentiment_chunk_count",
)


@dataclass(frozen=True)
class FinBERTPolicy:
    """Prespecified inference/preprocessing; two special BERT tokens are reserved."""

    model_name: str = FINBERT_MODEL
    model_revision: str = FINBERT_REVISION
    max_tokens: int = 512
    max_windows_per_chunk: int = 64
    batch_size: int = 8
    max_chunk_chars: int = 100_000
    preprocessing_version: str = "exact-sentence-nonoverlap-wordpiece-v1"

    def __post_init__(self) -> None:
        if (
            not self.model_name
            or not re.fullmatch(r"[0-9a-f]{40}", self.model_revision)
            or not 3 <= self.max_tokens <= 512
            or not 1 <= self.max_windows_per_chunk <= 1024
            or not 1 <= self.batch_size <= 256
            or not 1 <= self.max_chunk_chars <= 1_000_000
            or self.preprocessing_version != "exact-sentence-nonoverlap-wordpiece-v1"
        ):
            raise ValueError("Invalid pinned FinBERT inference policy")


class SentimentBackend(Protocol):
    """Mocks and the local adapter expose exactly the same target-free interface."""

    model_name: str
    model_revision: str

    def token_ids(self, text: str) -> Sequence[int]: ...

    def predict(self, windows: Sequence[Sequence[int]]) -> Sequence[Mapping[str, float]]: ...


class SentimentFailure(RuntimeError):
    """Redacted recoverable runtime failure; missing inference is never neutral."""

    def __init__(self, reason: str) -> None:
        if not re.fullmatch(r"[A-Z][A-Z0-9_]+", reason):
            raise ValueError("Sentiment failure needs a machine-readable reason")
        self.reason = reason
        super().__init__(reason)


class HuggingFaceFinBERT:
    """Lazy optional local PyTorch adapter; CPU works in Windows and Colab.

    The default is offline loading. A batch job explicitly sets
    ``local_files_only=False`` once to acquire the pinned public weights. Remote
    Python code is disabled; inference is evaluation-only and uses no LLM API.
    """

    def __init__(
        self,
        cache_dir: Path,
        policy: FinBERTPolicy | None = None,
        *,
        device: str = "cpu",
        local_files_only: bool = True,
    ) -> None:
        self.policy = policy or FinBERTPolicy()
        self.model_name = self.policy.model_name
        self.model_revision = self.policy.model_revision
        if device not in {"cpu", "cuda"}:
            raise ValueError("FinBERT device must be cpu or cuda")
        self.cache_dir = cache_dir
        self.device = device
        self.local_files_only = local_files_only
        self._torch: Any = None
        self._tokenizer: Any = None
        self._model: Any = None
        self._labels: dict[int, str] = {}
        self.runtime: dict[str, Any] = {}

    def _load(self) -> None:
        if self._model is not None:
            return
        try:
            torch = importlib.import_module("torch")
            transformers = importlib.import_module("transformers")
        except ImportError:
            raise SentimentFailure("NLP_DEPENDENCY_UNAVAILABLE") from None
        if self.device == "cuda" and not torch.cuda.is_available():
            raise SentimentFailure("CUDA_UNAVAILABLE")
        options = {
            "revision": self.model_revision,
            "cache_dir": str(self.cache_dir),
            "local_files_only": self.local_files_only,
            "trust_remote_code": False,
        }
        try:
            tokenizer = transformers.AutoTokenizer.from_pretrained(self.model_name, **options)
            model = transformers.AutoModelForSequenceClassification.from_pretrained(
                self.model_name, **options, weights_only=True, use_safetensors=False
            )
            labels = {int(key): str(value).lower() for key, value in model.config.id2label.items()}
            if set(labels.values()) != set(_LABELS) or len(labels) != 3:
                raise ValueError("Pinned sentiment model must expose three named financial tones")
            if (
                tokenizer.num_special_tokens_to_add(pair=False) != 2
                or int(model.config.max_position_embeddings) < self.policy.max_tokens
            ):
                raise ValueError("FinBERT tokenizer/model window contract mismatch")
            model.to(self.device)
            model.eval()
        except OSError:
            raise SentimentFailure("PINNED_MODEL_UNAVAILABLE") from None
        self._torch, self._tokenizer, self._model, self._labels = torch, tokenizer, model, labels
        self.runtime = {
            "torch_version": str(torch.__version__),
            "transformers_version": str(transformers.__version__),
            "device": self.device,
            "model_available_from": "2020-12-24",
        }
        hub = importlib.import_module("huggingface_hub")
        assets: dict[str, str] = {}
        for name in (
            "config.json",
            "vocab.txt",
            "tokenizer_config.json",
            "special_tokens_map.json",
            "pytorch_model.bin",
            "model.safetensors",
        ):
            filename = hub.try_to_load_from_cache(
                self.model_name,
                name,
                revision=self.model_revision,
                cache_dir=str(self.cache_dir),
            )
            if isinstance(filename, str):
                assets[name] = sha256_file(Path(filename))
        if (
            self.model_name == FINBERT_MODEL
            and self.model_revision == FINBERT_REVISION
            and any(assets.get(name) != digest for name, digest in FINBERT_ASSETS_SHA256.items())
        ):
            self._torch, self._tokenizer, self._model, self._labels = None, None, None, {}
            raise ValueError("Pinned FinBERT assets do not match their official immutable SHA-256")
        self.runtime["model_assets_sha256"] = assets

    def token_ids(self, text: str) -> Sequence[int]:
        self._load()
        return [
            int(value)
            for value in self._tokenizer.encode(text, add_special_tokens=False, truncation=False)
        ]

    def predict(self, windows: Sequence[Sequence[int]]) -> Sequence[Mapping[str, float]]:
        self._load()
        result: list[dict[str, float]] = []
        for start in range(0, len(windows), self.policy.batch_size):
            batch = windows[start : start + self.policy.batch_size]
            if any(not ids or len(ids) > self.policy.max_tokens - 2 for ids in batch):
                raise ValueError("FinBERT received an empty or oversized token window")
            ids = [self._tokenizer.build_inputs_with_special_tokens(list(row)) for row in batch]
            width = max(map(len, ids))
            padded = [row + [self._tokenizer.pad_token_id] * (width - len(row)) for row in ids]
            masks = [[1] * len(row) + [0] * (width - len(row)) for row in ids]
            try:
                with self._torch.inference_mode():
                    logits = self._model(
                        input_ids=self._torch.tensor(padded, device=self.device),
                        attention_mask=self._torch.tensor(masks, device=self.device),
                    ).logits
                    probabilities = self._torch.softmax(logits, dim=-1).cpu().tolist()
            except RuntimeError:
                raise SentimentFailure("LOCAL_INFERENCE_FAILED") from None
            for row in probabilities:
                result.append(
                    {self._labels[index]: float(value) for index, value in enumerate(row)}
                )
        return result


def _json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _sha(value: object) -> str:
    return hashlib.sha256(_json(value)).hexdigest()


def _utc(value: object, name: str) -> datetime:
    if not isinstance(value, str | datetime):
        raise ValueError(f"{name} must be a timezone-aware timestamp")
    try:
        stamp = (
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            if isinstance(value, str)
            else value
        )
    except ValueError:
        raise ValueError(f"{name} must be a timezone-aware timestamp") from None
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError(f"{name} must be a timezone-aware timestamp")
    return stamp.astimezone(UTC)


def _probabilities(value: Mapping[str, object]) -> dict[str, float]:
    if set(value) != set(_LABELS):
        raise ValueError("Sentiment probabilities need exact positive/negative/neutral labels")
    result: dict[str, float] = {}
    for name in _LABELS:
        probability = value[name]
        if (
            not isinstance(probability, int | float)
            or isinstance(probability, bool)
            or not math.isfinite(float(probability))
            or not 0 <= probability <= 1
        ):
            raise ValueError("Invalid sentiment class probability")
        result[name] = float(probability)
    if not math.isclose(sum(result.values()), 1, rel_tol=0, abs_tol=1e-6):
        raise ValueError("Sentiment class probabilities must sum to one")
    return result


def _window_plan(
    text: str, backend: SentimentBackend, policy: FinBERTPolicy
) -> tuple[list[dict[str, Any]], list[list[int]], dict[str, int]]:
    """Keep every nonempty sentence's exact character and nonoverlap token spans.

    A sentence longer than the tokenizer limit is explicitly divided. The global
    chunk budget scores the first windows in source order, recording all omitted
    windows/tokens and incomplete sentences rather than claiming full coverage.
    """
    metadata: list[dict[str, Any]] = []
    windows: list[list[int]] = []
    cursor, sentence_count, token_count = 0, 0, 0
    bounds = [(match.start(), match.end()) for match in _SENTENCE_BOUNDARY.finditer(text)]
    bounds.append((len(text), len(text)))
    for boundary, following in bounds:
        segment = text[cursor:boundary]
        leading = len(segment) - len(segment.lstrip())
        trailing = len(segment.rstrip())
        begin, end = cursor + leading, cursor + trailing
        cursor = following
        if begin >= end:
            continue
        token_ids = list(backend.token_ids(text[begin:end]))
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in token_ids
        ):
            raise ValueError("Sentiment tokenizer must return nonnegative integer token IDs")
        if not token_ids:
            continue
        token_count += len(token_ids)
        sentence_id = sentence_count
        sentence_count += 1
        for offset in range(0, len(token_ids), policy.max_tokens - 2):
            ids = token_ids[offset : offset + policy.max_tokens - 2]
            metadata.append(
                {
                    "window_index": len(metadata),
                    "sentence_index": sentence_id,
                    "sentence_char_start": begin,
                    "sentence_char_end": end,
                    "sentence_token_count": len(token_ids),
                    "token_start": offset,
                    "token_end": offset + len(ids),
                    "token_count": len(ids),
                    "token_ids_sha256": _sha(ids),
                }
            )
            windows.append(ids)
    return (
        metadata,
        windows,
        {
            "sentence_count": sentence_count,
            "window_count": len(windows),
            "token_count": token_count,
        },
    )


def _chunk_scores(
    text: str, backend: SentimentBackend, cache_dir: Path, policy: FinBERTPolicy
) -> dict[str, Any]:
    text_hash = hashlib.sha256(text.encode()).hexdigest()
    identity = {
        "text_sha256": text_hash,
        "policy": asdict(policy),
        "schema_version": SENTIMENT_SCHEMA_VERSION,
    }
    cache_key = _sha(identity)
    cache_path = cache_dir / f"{cache_key}.json"
    plan, windows, counts = _window_plan(text, backend, policy)
    selected_plan = plan[: policy.max_windows_per_chunk]
    selected_windows = windows[: policy.max_windows_per_chunk]
    if cache_path.exists():
        stored = json.loads(cache_path.read_bytes())
        if (
            not isinstance(stored, dict)
            or stored.get("identity") != identity
            or stored.get("cache_key") != cache_key
            or stored.get("result_sha256") != _sha(stored.get("result"))
        ):
            raise ValueError("Immutable sentiment cache identity/content mismatch")
        result = stored["result"]
        _validate_chunk_result(result, selected_plan, counts)
        return dict(result, cache_key=cache_key)
    if not selected_windows:
        return dict(
            counts, status="UNKNOWN", reason="NO_USABLE_TOKENS", windows=[], cache_key=cache_key
        )
    try:
        probabilities = list(backend.predict(selected_windows))
    except SentimentFailure as error:
        return dict(counts, status="UNKNOWN", reason=error.reason, windows=[], cache_key=cache_key)
    if len(probabilities) != len(selected_windows):
        raise ValueError("Sentiment inference must preserve every requested window")
    scored = [
        dict(row, probabilities=_probabilities(probability))
        for row, probability in zip(selected_plan, probabilities, strict=True)
    ]
    result = dict(
        counts,
        status="SUCCESS" if len(scored) == counts["window_count"] else "PARTIAL",
        reason="ALL_CHUNK_WINDOWS_SCORED"
        if len(scored) == counts["window_count"]
        else "EXPLICIT_WINDOW_BUDGET",
        windows=scored,
        runtime=dict(getattr(backend, "runtime", {})),
    )
    _validate_chunk_result(result, selected_plan, counts)
    write_bytes(
        cache_path,
        _json(
            {
                "identity": identity,
                "cache_key": cache_key,
                "result": result,
                "result_sha256": _sha(result),
            }
        ),
    )
    return dict(result, cache_key=cache_key)


def _validate_chunk_result(
    result: object, selected_plan: list[dict[str, Any]], counts: dict[str, int]
) -> None:
    if not isinstance(result, dict):
        raise ValueError("Invalid stored sentiment result")
    expected_status = "SUCCESS" if len(selected_plan) == counts["window_count"] else "PARTIAL"
    if result.get("status") != expected_status or any(
        result.get(name) != count for name, count in counts.items()
    ):
        raise ValueError("Stored sentiment window coverage mismatch")
    rows = result.get("windows")
    if not isinstance(rows, list) or len(rows) != len(selected_plan):
        raise ValueError("Stored sentiment window inventory mismatch")
    for row, expected in zip(rows, selected_plan, strict=True):
        if not isinstance(row, dict) or {key: row.get(key) for key in expected} != expected:
            raise ValueError("Stored sentiment window provenance mismatch")
        probabilities = row.get("probabilities")
        if not isinstance(probabilities, dict):
            raise ValueError("Stored sentiment probabilities missing")
        _probabilities(probabilities)


def _admitted_input(
    pack: Mapping[str, object],
    leg_security_ids: Sequence[str],
    rules: FinBERTPolicy,
) -> tuple[datetime, datetime, str, str, dict[str, str], list[dict[str, Any]], str]:
    """Normalize the exact allowlisted scientific inputs before any inference."""
    if len(leg_security_ids) != 2 or len(set(leg_security_ids)) != 2 or not all(leg_security_ids):
        raise ValueError("Sentiment needs two distinct oriented security identities")
    timestamp = _utc(
        pack.get("event_timestamp", pack.get("event_timestamp_utc")), "event timestamp"
    )
    cutoff = _utc(pack.get("evidence_cutoff", timestamp), "evidence cutoff")
    if cutoff > timestamp:
        raise ValueError("Sentiment evidence cutoff cannot follow the event timestamp")
    event_id, pair_id = pack.get("event_id"), pack.get("pair_id")
    if not isinstance(event_id, str) or not event_id or not isinstance(pair_id, str) or not pair_id:
        raise ValueError("Sentiment pack requires event and pair identities")
    raw_chunks, coverage = pack.get("chunks"), pack.get("coverage")
    if not isinstance(raw_chunks, list) or not isinstance(coverage, dict):
        raise ValueError("Sentiment requires explicit selected chunks and leg coverage")
    identities = dict(zip(("A", "B"), leg_security_ids, strict=True))
    source_coverage: dict[str, str] = {}
    for leg, security in identities.items():
        info = coverage.get(leg)
        if not isinstance(info, dict) or info.get("status") not in {
            "COMPLETE",
            "PARTIAL",
            "UNKNOWN",
        }:
            raise ValueError("Sentiment requires explicit source coverage per leg")
        if info.get("security_id", security) != security:
            raise ValueError("Sentiment coverage security identity mismatch")
        source_coverage[leg] = str(info["status"])
    admitted: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_chunks:
        if not isinstance(raw, dict):
            raise ValueError("Invalid sentiment chunk")
        chunk_id, raw_leg = raw.get("chunk_id"), raw.get("leg")
        if not isinstance(chunk_id, str) or not chunk_id or chunk_id in seen:
            raise ValueError("Sentiment chunks require unique stable IDs")
        seen.add(chunk_id)
        if raw_leg not in identities or raw.get("security_id") != identities[str(raw_leg)]:
            raise ValueError("Sentiment chunk leg/security identity mismatch")
        chunk_leg = str(raw_leg)
        accepted = _utc(raw.get("acceptance_datetime_utc"), "SEC acceptance")
        if accepted > cutoff:
            raise ValueError("Future SEC text is not an admissible sentiment predictor")
        if raw.get("point_in_time_eligible", True) is not True:
            raise ValueError("Inadmissible SEC chunk cannot enter sentiment")
        text = raw.get("chunk_text")
        text_hash = raw.get("text_sha256")
        if not isinstance(text, str):
            raise ValueError("Sentiment chunk text must be explicit, including missing empty text")
        if len(text) > rules.max_chunk_chars:
            raise ValueError("Sentiment chunk exceeds the declared character bound")
        if text and text_hash != hashlib.sha256(text.encode()).hexdigest():
            raise ValueError("Sentiment SEC text hash mismatch")
        url = urlparse(str(raw.get("source_url", "")))
        if (
            url.scheme != "https"
            or url.hostname not in {"www.sec.gov", "data.sec.gov"}
            or url.username
            or url.password
            or url.port not in (None, 443)
            or not url.path.startswith("/Archives/edgar/data/")
            or not re.fullmatch(r"[0-9a-f]{64}", str(raw.get("sha256", "")))
            or not isinstance(raw.get("filing_id"), str)
            or not raw["filing_id"]
        ):
            raise ValueError("Sentiment needs immutable official SEC source provenance")
        admitted.append(
            {
                "chunk_id": chunk_id,
                "leg": chunk_leg,
                "security_id": identities[chunk_leg],
                "filing_id": raw["filing_id"],
                "acceptance_datetime_utc": accepted.isoformat(),
                "source_url": raw["source_url"],
                "sha256": raw["sha256"],
                "text_sha256": text_hash,
                "chunk_text": text,
                "source_status": str(raw.get("status", "OK")),
            }
        )
    admitted.sort(key=lambda row: (row["leg"], row["acceptance_datetime_utc"], row["chunk_id"]))
    input_hash = _sha(
        {
            "event_id": event_id,
            "pair_id": pair_id,
            "event_timestamp": timestamp.isoformat(),
            "evidence_cutoff": cutoff.isoformat(),
            "source_coverage": source_coverage,
            "chunks": admitted,
            "policy": asdict(rules),
        }
    )
    return timestamp, cutoff, event_id, pair_id, source_coverage, admitted, input_hash


def score_sentiment_pack(
    pack: Mapping[str, object],
    backend: SentimentBackend,
    cache_dir: Path,
    *,
    leg_security_ids: Sequence[str],
    policy: FinBERTPolicy | None = None,
) -> dict[str, Any]:
    """Score an already selected/verified P4 pack and retain every supplied chunk.

    Only text reaches the backend. Identity, acceptance, source/text hashes and
    character/token spans remain in the result. Event targets/scores and other
    pack fields are not model inputs or cache inputs. Empty/failed evidence yields
    explicit UNKNOWN, null class probabilities and fixed missingness indicators.
    """
    rules = policy or FinBERTPolicy()
    if (backend.model_name, backend.model_revision) != (rules.model_name, rules.model_revision):
        raise ValueError("Sentiment backend must match the pinned model policy")
    timestamp, cutoff, event_id, pair_id, source_coverage, admitted, input_hash = _admitted_input(
        pack, leg_security_ids, rules
    )
    identities = dict(zip(("A", "B"), leg_security_ids, strict=True))
    scored_chunks: list[dict[str, Any]] = []
    for row in admitted:
        provenance = {key: value for key, value in row.items() if key != "chunk_text"}
        if row["source_status"] != "OK" or not row["chunk_text"].strip():
            scores: dict[str, Any] = {
                "status": "UNKNOWN",
                "reason": "SOURCE_TEXT_UNAVAILABLE",
                "sentence_count": 0,
                "window_count": 0,
                "token_count": 0,
                "windows": [],
                "cache_key": None,
            }
        else:
            try:
                scores = _chunk_scores(row["chunk_text"], backend, cache_dir, rules)
            except SentimentFailure as error:
                scores = {
                    "status": "UNKNOWN",
                    "reason": error.reason,
                    "sentence_count": 0,
                    "window_count": 0,
                    "token_count": 0,
                    "windows": [],
                    "cache_key": None,
                }
        scores.update(_chunk_summary(scores))
        scored_chunks.append(dict(provenance, **scores))
    legs, features = _aggregate_scores(scored_chunks, identities, source_coverage)
    return {
        "schema_version": SENTIMENT_SCHEMA_VERSION,
        "event_id": event_id,
        "pair_id": pair_id,
        "event_timestamp": timestamp.isoformat(),
        "evidence_cutoff": cutoff.isoformat(),
        "input_sha256": input_hash,
        "policy": asdict(rules),
        "pretrained_model_available_from": "2020-12-24",
        "retrospective_pretrained_extractor": True,
        "chunks": scored_chunks,
        "legs": legs,
        "features": features,
    }


def _chunk_summary(scores: Mapping[str, Any]) -> dict[str, Any]:
    scored_tokens = sum(window["token_count"] for window in scores["windows"])
    full_sentences = {
        window["sentence_index"]
        for window in scores["windows"]
        if window["token_end"] == window["sentence_token_count"]
    }
    return dict(
        scored_token_count=scored_tokens,
        scored_window_count=len(scores["windows"]),
        omitted_window_count=scores["window_count"] - len(scores["windows"]),
        fully_scored_sentence_count=len(full_sentences),
        sentence_coverage=len(full_sentences) / scores["sentence_count"]
        if scores["sentence_count"]
        else 0.0,
        window_coverage=len(scores["windows"]) / scores["window_count"]
        if scores["window_count"]
        else 0.0,
        token_coverage=scored_tokens / scores["token_count"] if scores["token_count"] else 0.0,
        probabilities={
            label: sum(
                window["probabilities"][label] * window["token_count"]
                for window in scores["windows"]
            )
            / scored_tokens
            if scored_tokens
            else None
            for label in _LABELS
        },
    )


def _aggregate_scores(
    scored_chunks: list[dict[str, Any]], identities: dict[str, str], source_coverage: dict[str, str]
) -> tuple[dict[str, Any], dict[str, float | None]]:
    legs: dict[str, Any] = {}
    features: dict[str, float | None] = {}
    for leg, security_id in identities.items():
        rows = [row for row in scored_chunks if row["leg"] == leg]
        windows = [window for row in rows for window in row["windows"]]
        token_count = sum(row["token_count"] for row in rows)
        scored_count = sum(window["token_count"] for window in windows)
        means = {
            label: sum(window["probabilities"][label] * window["token_count"] for window in windows)
            / scored_count
            if scored_count
            else None
            for label in _LABELS
        }
        positive, negative = means["positive"], means["negative"]
        net = positive - negative if positive is not None and negative is not None else None
        ratio = scored_count / token_count if token_count else 0.0
        status = (
            "UNKNOWN"
            if not scored_count
            else "SUCCESS"
            if source_coverage[leg] == "COMPLETE"
            and all(row["status"] == "SUCCESS" for row in rows)
            else "PARTIAL"
        )
        legs[leg] = {
            "security_id": security_id,
            "status": status,
            "source_coverage_status": source_coverage[leg],
            "probabilities": means,
            "net": net,
            "token_coverage": ratio,
            "scored_token_count": scored_count,
            "token_count": token_count,
            "chunk_count": len(rows),
            "unknown_chunk_count": sum(row["status"] == "UNKNOWN" for row in rows),
            "scored_window_count": len(windows),
        }
        for label, probability in means.items():
            features[f"sentiment_{leg.lower()}_{label}"] = probability
        features.update(
            {
                f"sentiment_{leg.lower()}_net": net,
                f"sentiment_{leg.lower()}_token_coverage": ratio,
                f"sentiment_{leg.lower()}_unknown": float(not scored_count),
            }
        )
    both = legs["A"]["net"] is not None and legs["B"]["net"] is not None
    contrast = legs["A"]["net"] - legs["B"]["net"] if both else None
    features.update(
        sentiment_net_contrast=contrast,
        sentiment_net_asymmetry=abs(contrast) if contrast is not None else None,
        sentiment_both_known=float(both),
        sentiment_window_count=float(sum(row["scored_window_count"] for row in scored_chunks)),
        sentiment_chunk_count=float(len(scored_chunks)),
    )
    return legs, {name: features[name] for name in SENTIMENT_FEATURE_COLUMNS}


def _sentence_spans(text: str) -> set[tuple[int, int]]:
    """Exact deterministic character spans, without importing a tokenizer."""
    spans: set[tuple[int, int]] = set()
    cursor = 0
    bounds = [(match.start(), match.end()) for match in _SENTENCE_BOUNDARY.finditer(text)]
    bounds.append((len(text), len(text)))
    for boundary, following in bounds:
        segment = text[cursor:boundary]
        begin = cursor + len(segment) - len(segment.lstrip())
        end = cursor + len(segment.rstrip())
        cursor = following
        if begin < end:
            spans.add((begin, end))
    return spans


def _validate_stored_windows(
    row: dict[str, Any], source: dict[str, Any], rules: FinBERTPolicy
) -> None:
    """Validate recorded token spans; exact tokenizer IDs remain immutable outputs."""
    for name in ("sentence_count", "window_count", "token_count"):
        value = row.get(name)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError("Stored sentiment counts are invalid")
    windows, status = row.get("windows"), row.get("status")
    if not isinstance(windows, list) or status not in {"SUCCESS", "PARTIAL", "UNKNOWN"}:
        raise ValueError("Stored sentiment window inventory/status is invalid")
    if not isinstance(row.get("reason"), str) or not re.fullmatch(
        r"[A-Z][A-Z0-9_]+", row["reason"]
    ):
        raise ValueError("Stored sentiment reason must be machine-readable")
    identity = {
        "text_sha256": hashlib.sha256(source["chunk_text"].encode()).hexdigest(),
        "policy": asdict(rules),
        "schema_version": SENTIMENT_SCHEMA_VERSION,
    }
    if status == "UNKNOWN":
        if windows or row.get("cache_key") not in (None, _sha(identity)):
            raise ValueError("UNKNOWN sentiment cannot invent scored windows")
    else:
        if source["source_status"] != "OK" or not source["chunk_text"].strip():
            raise ValueError("Unavailable SEC source cannot have sentiment scores")
        if row.get("cache_key") != _sha(identity):
            raise ValueError("Stored sentiment cache key disagrees with exact text/model/policy")
        if not windows or len(windows) != min(row["window_count"], rules.max_windows_per_chunk):
            raise ValueError("Stored sentiment does not retain the declared window prefix")
        expected_status = "SUCCESS" if len(windows) == row["window_count"] else "PARTIAL"
        expected_reason = (
            "ALL_CHUNK_WINDOWS_SCORED" if expected_status == "SUCCESS" else "EXPLICIT_WINDOW_BUDGET"
        )
        if status != expected_status or row["reason"] != expected_reason:
            raise ValueError("Stored sentiment truncation status/reason mismatch")
    spans = _sentence_spans(source["chunk_text"])
    previous: dict[str, Any] | None = None
    observed_sentences: dict[int, int] = {}
    observed_tokens = 0
    keys = {
        "window_index",
        "sentence_index",
        "sentence_char_start",
        "sentence_char_end",
        "sentence_token_count",
        "token_start",
        "token_end",
        "token_count",
        "token_ids_sha256",
        "probabilities",
    }
    for index, window in enumerate(windows):
        if not isinstance(window, dict) or set(window) != keys:
            raise ValueError("Stored sentiment window schema mismatch")
        if any(
            not isinstance(window[name], int) or isinstance(window[name], bool) or window[name] < 0
            for name in keys - {"token_ids_sha256", "probabilities"}
        ):
            raise ValueError("Stored sentiment window coordinates are invalid")
        if (
            window["window_index"] != index
            or (window["sentence_char_start"], window["sentence_char_end"]) not in spans
            or not 0 < window["token_count"] <= rules.max_tokens - 2
            or window["token_end"] - window["token_start"] != window["token_count"]
            or not window["token_end"] <= window["sentence_token_count"]
            or window["sentence_index"] >= row["sentence_count"]
            or not re.fullmatch(r"[0-9a-f]{64}", str(window["token_ids_sha256"]))
        ):
            raise ValueError("Stored sentiment window provenance/ranges mismatch")
        if (
            window["token_end"] < window["sentence_token_count"]
            and window["token_count"] != rules.max_tokens - 2
        ):
            raise ValueError("Stored sentiment split must fill nonfinal sentence windows")
        if previous is None or window["sentence_index"] != previous["sentence_index"]:
            if (
                window["token_start"] != 0
                or window["sentence_index"] != len(observed_sentences)
                or previous is not None
                and (
                    previous["token_end"] != previous["sentence_token_count"]
                    or window["sentence_char_start"] < previous["sentence_char_end"]
                )
            ):
                raise ValueError("Stored sentiment sentences must follow source order")
            observed_sentences[window["sentence_index"]] = window["sentence_token_count"]
        elif (
            window["token_start"] != previous["token_end"]
            or window["sentence_token_count"] != previous["sentence_token_count"]
            or window["sentence_char_start"] != previous["sentence_char_start"]
            or window["sentence_char_end"] != previous["sentence_char_end"]
        ):
            raise ValueError("Stored sentiment token windows must be contiguous and nonoverlapping")
        if not isinstance(window["probabilities"], dict):
            raise ValueError("Stored sentiment probability vector missing")
        _probabilities(window["probabilities"])
        observed_tokens += window["token_count"]
        previous = window
    if observed_tokens > row["token_count"] or len(observed_sentences) > row["sentence_count"]:
        raise ValueError("Stored sentiment coverage totals are impossible")
    if status == "SUCCESS" and (
        observed_tokens != row["token_count"]
        or len(observed_sentences) != row["sentence_count"]
        or previous is not None
        and previous["token_end"] != previous["sentence_token_count"]
    ):
        raise ValueError("SUCCESS sentiment requires complete recorded token/sentence coverage")
    summary = _chunk_summary(row)
    if any(_json(row.get(name)) != _json(value) for name, value in summary.items()):
        raise ValueError("Stored sentiment chunk probabilities/coverage disagree with windows")


def validate_sentiment_result(
    pack: Mapping[str, object],
    result: Mapping[str, object],
    *,
    leg_security_ids: Sequence[str],
    policy: FinBERTPolicy | None = None,
) -> dict[str, float | None]:
    """Rebuild all 17 features from stored windows without model/tokenizer calls.

    Recheck the exact admissible SEC inputs, probability schema, source sentence
    spans, contiguous token windows and coverage totals. Native WordPiece IDs and
    model probabilities are recorded inference outputs bound by immutable artifact
    hashes; this verifier does not claim to re-run the pretrained classifier.
    """
    rules = policy or FinBERTPolicy()
    timestamp, cutoff, event_id, pair_id, coverage, admitted, input_hash = _admitted_input(
        pack, leg_security_ids, rules
    )
    expected = {
        "schema_version": SENTIMENT_SCHEMA_VERSION,
        "event_id": event_id,
        "pair_id": pair_id,
        "event_timestamp": timestamp.isoformat(),
        "evidence_cutoff": cutoff.isoformat(),
        "input_sha256": input_hash,
        "policy": asdict(rules),
        "pretrained_model_available_from": "2020-12-24",
        "retrospective_pretrained_extractor": True,
    }
    if any(_json(result.get(name)) != _json(value) for name, value in expected.items()):
        raise ValueError("Stored sentiment identity/input/model policy mismatch")
    chunks = result.get("chunks")
    if not isinstance(chunks, list) or len(chunks) != len(admitted):
        raise ValueError("Stored sentiment must retain the exact selected SEC chunk inventory")
    for row, source in zip(chunks, admitted, strict=True):
        provenance = {name: value for name, value in source.items() if name != "chunk_text"}
        if not isinstance(row, dict) or any(
            row.get(name) != value for name, value in provenance.items()
        ):
            raise ValueError("Stored sentiment chunk identity/timestamp/source hash mismatch")
        _validate_stored_windows(row, source, rules)
    identities = dict(zip(("A", "B"), leg_security_ids, strict=True))
    legs, features = _aggregate_scores(chunks, identities, coverage)
    if _json(result.get("legs")) != _json(legs) or _json(result.get("features")) != _json(features):
        raise ValueError("Stored sentiment leg/features disagree with window reconstruction")
    return features
