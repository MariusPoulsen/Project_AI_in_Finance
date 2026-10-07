"""A private parsing spill must preserve frames and never trust replacement bytes."""

import gc
import hashlib
import pickle
import weakref
from pathlib import Path

import pandas as pd
import pytest

from structural_break.research import parsing_cache
from structural_break.research.parsing_cache import OperationParsingCache


def source_frame() -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "chunk_id": pd.Series(["second", "first", None], dtype="object"),
            "tokens": pd.Series([4, pd.NA, 0], dtype="Int64"),
            "eligible": pd.Series([True, pd.NA, False], dtype="boolean"),
            "text": pd.Series(["Sales fell.", pd.NA, ""], dtype="string"),
            "accepted": pd.to_datetime(
                ["2006-01-03T21:00:00Z", None, "2005-12-31T15:30:00Z"], utc=True
            ),
            "kind": pd.Categorical(
                ["SUBMISSION", "PRIMARY", None], categories=["PRIMARY", "SUBMISSION"], ordered=True
            ),
            "null": pd.Series([None, pd.NA, pd.NaT], dtype="object"),
        }
    )
    frame.index = pd.Index([9, 3, 7], name="source_order")
    frame.columns.name = "parsed_schema"
    frame.attrs = {"source": "verified-public-body", "offsets": [15, 2, 0]}
    return frame


def test_evicted_frames_restore_exact_dtype_null_timestamp_index_order_and_attrs() -> None:
    expected = source_frame()
    with OperationParsingCache(max_hot_frames=1) as cache:
        cache["first"] = expected
        cache["second"] = expected.iloc[0:0]
        assert cache.entry_count == 2 and cache.hot_frame_count == 1
        restored = cache["first"]
        pd.testing.assert_frame_equal(restored, expected, check_exact=True)
        assert restored.attrs == expected.attrs
        assert restored.loc[9, "null"] is None
        assert restored.loc[3, "null"] is pd.NA
        assert restored.loc[7, "null"] is pd.NaT
        pd.testing.assert_frame_equal(cache["second"], expected.iloc[0:0], check_exact=True)


def test_incoming_and_returned_mutations_cannot_change_hot_or_spilled_frames() -> None:
    incoming = source_frame()
    expected = incoming.copy(deep=True)
    with OperationParsingCache(max_hot_frames=1) as cache:
        cache["a"] = incoming
        incoming.loc[9, "text"] = "Different source."
        first = cache["a"]
        first.loc[9, "text"] = "Different returned frame."
        first.attrs["offsets"][0] = 999
        pd.testing.assert_frame_equal(cache["a"], expected, check_exact=True)
        assert cache["a"].attrs == expected.attrs
        cache["b"] = expected
        pd.testing.assert_frame_equal(cache["a"], expected, check_exact=True)


def test_eviction_releases_owned_frames_and_never_enlarges_128_frame_bound() -> None:
    with OperationParsingCache() as cache:
        cache["first"] = source_frame()
        reference = weakref.ref(cache._hot["first"])
        for index in range(131):
            cache[f"key-{index}"] = source_frame()
            assert cache.hot_frame_count <= 128
        gc.collect()
        assert reference() is None
        assert cache.entry_count == 132 and cache.hot_frame_count == 128
        pd.testing.assert_frame_equal(cache["first"], source_frame(), check_exact=True)
        assert cache.hot_frame_count == 128
        with pytest.raises(AttributeError):
            cache.max_hot_frames = 999  # type: ignore[misc]


def test_replacement_with_its_own_disk_digest_is_rejected_before_deserialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with OperationParsingCache(max_hot_frames=1) as cache:
        cache["source"] = source_frame()
        cache["eviction"] = source_frame()
        path = cache._path("source")
        replacement = pickle.dumps(pd.DataFrame({"forged": [1]}))
        path.write_bytes(replacement)
        # A forger cannot replace the operation's RAM-held digest with a sidecar.
        path.with_suffix(".sha256").write_text(hashlib.sha256(replacement).hexdigest())
        monkeypatch.setattr(
            parsing_cache.pickle,
            "loads",
            lambda _: pytest.fail("Replacement bytes must not reach pickle.loads"),
        )
        with pytest.raises(ValueError, match="checksum mismatch"):
            cache["source"]


def test_missing_spill_fails_closed_without_dropping_or_rebuilding_source_entry() -> None:
    with OperationParsingCache(max_hot_frames=1) as cache:
        cache["a"] = source_frame()
        cache["b"] = source_frame()
        cache._path("a").unlink()
        with pytest.raises(ValueError, match="spill is missing"):
            cache["a"]
        assert "a" in cache and cache.entry_count == 2
        with pytest.raises(ValueError, match="immutable"):
            cache["a"] = source_frame()


@pytest.mark.parametrize("failure", ["none", "operation", "serialization"])
def test_context_cleans_directory_and_owned_frames_on_success_or_failure(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    cache = OperationParsingCache(max_hot_frames=1)
    directory = cache._directory
    references: list[weakref.ReferenceType[pd.DataFrame]] = []

    def run() -> None:
        with cache:
            cache["first"] = source_frame()
            references.append(weakref.ref(cache._hot["first"]))
            cache["second"] = source_frame()
            references.append(weakref.ref(cache._hot["second"]))
            if failure == "serialization":

                def fail_pickle(*_: object, **__: object) -> bytes:
                    raise RuntimeError("serialization failed")

                monkeypatch.setattr(parsing_cache.pickle, "dumps", fail_pickle)
                cache["third"] = source_frame()
            if failure == "operation":
                raise RuntimeError("operation failed")

    if failure == "none":
        run()
    else:
        with pytest.raises(RuntimeError, match="failed"):
            run()
    gc.collect()
    assert not directory.exists() and all(reference() is None for reference in references)
    assert cache._digests == {} and cache._hot == {}
    cache.close()
    with pytest.raises(RuntimeError, match="closed"):
        cache["first"]
    with pytest.raises(RuntimeError, match="closed"):
        cache["new"] = source_frame()
    with pytest.raises(RuntimeError, match="closed"):
        assert "first" in cache
    with pytest.raises(RuntimeError, match="closed"):
        cache.__enter__()


def test_new_operation_is_empty_and_does_not_load_other_operations_spill() -> None:
    with OperationParsingCache() as first, OperationParsingCache() as second:
        assert first._directory != second._directory
        first["same-source"] = source_frame()
        assert "same-source" not in second and second.entry_count == 0
        with pytest.raises(KeyError):
            second["same-source"]
        # Even a copied spill cannot acquire a scientific identity in a fresh cache.
        second._path("same-source").write_bytes(first._path("same-source").read_bytes())
        with pytest.raises(KeyError):
            second["same-source"]


@pytest.mark.parametrize("limit", [0, -1, 129, True, 1.5, "128"])
def test_invalid_or_unbounded_hot_limits_are_rejected(limit: object) -> None:
    with pytest.raises(ValueError, match="between 1 and 128"):
        OperationParsingCache(max_hot_frames=limit)  # type: ignore[arg-type]


def test_source_keys_remain_immutable_and_cannot_escape_private_directory() -> None:
    with OperationParsingCache() as cache:
        cache["../../untrusted-key"] = source_frame()
        assert cache._path("../../untrusted-key").parent == cache._directory
        with pytest.raises(ValueError, match="immutable"):
            cache["../../untrusted-key"] = source_frame()
        with pytest.raises(ValueError, match="nonempty"):
            cache[""] = source_frame()
        with pytest.raises(ValueError, match="pandas frame"):
            cache["invalid"] = Path("not-a-frame")  # type: ignore[assignment]
