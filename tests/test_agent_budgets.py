"""Durable reservations, interrupted accounting and explicit lock recovery offline."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest

from structural_break.agents.budgets import (
    BudgetPolicy,
    DurableAttemptJournal,
    ExclusiveLease,
    ModelCap,
    read_envelope,
    recover_lease,
    write_envelope,
)
from structural_break.intelligence.extraction import ProviderFailure

SCHEMA = {"type": "object", "properties": {"summary": {"type": "string"}}}
REQUEST = "a" * 64
MODEL = "gemma-4-26b-a4b-it"
REVIEWER = "gemini-3.1-flash-lite"


def policy(global_cap=10, model_cap=10, daily=None, timezone="America/Los_Angeles"):
    return BudgetPolicy(
        allocation_id="fixture-batch-allocation",
        global_cap=global_cap,
        model_caps=(ModelCap(model=MODEL, total=model_cap, daily=daily),),
        day_timezone=timezone,
    )


def reserve(journal, model=MODEL):
    return journal.reserve(model=model, role="mean_reversion_opening", request_sha256=REQUEST)


def test_attempt_cap_cannot_reset_after_restart(tmp_path):
    budget = policy(global_cap=2)
    with DurableAttemptJournal(tmp_path, budget) as journal:
        reserve(journal)
        reserve(journal)
    with DurableAttemptJournal(tmp_path, budget) as resumed:
        assert resumed.counts["total_reserved_attempts"] == 2
        with pytest.raises(ProviderFailure, match="REQUEST_BUDGET_EXHAUSTED"):
            reserve(resumed)
    assert len(list((tmp_path / "attempts").glob("*.json"))) == 2


def test_model_and_global_caps_are_shared_between_roles(tmp_path):
    budget = BudgetPolicy(
        allocation_id="shared-test",
        global_cap=3,
        model_caps=(ModelCap(model=MODEL, total=1), ModelCap(model=REVIEWER, total=3)),
    )
    with DurableAttemptJournal(tmp_path, budget) as journal:
        reserve(journal)
        with pytest.raises(ProviderFailure, match="REQUEST_BUDGET_EXHAUSTED"):
            reserve(journal)
        reserve(journal, REVIEWER)
        reserve(journal, REVIEWER)
        with pytest.raises(ProviderFailure, match="REQUEST_BUDGET_EXHAUSTED"):
            reserve(journal, REVIEWER)
        assert journal.counts["by_model"] == {MODEL: 1, REVIEWER: 2}


def test_provider_day_resets_at_pacific_midnight_not_utc(tmp_path):
    now = datetime(2023, 7, 2, 6, 59, tzinfo=UTC)  # 23:59 July 1 Pacific
    with DurableAttemptJournal(tmp_path, policy(daily=1), clock=lambda: now) as journal:
        first = reserve(journal)
        assert first.provider_day == "2023-07-01"
        now = datetime(2023, 7, 2, 6, 59, 59, tzinfo=UTC)
        with pytest.raises(ProviderFailure, match="DURABLE_DAY_BUDGET_EXHAUSTED"):
            reserve(journal)
        now = datetime(2023, 7, 2, 7, 0, tzinfo=UTC)
        assert reserve(journal).provider_day == "2023-07-02"
    with DurableAttemptJournal(tmp_path, policy(daily=1), clock=lambda: now) as resumed:
        with pytest.raises(ProviderFailure, match="DURABLE_DAY_BUDGET_EXHAUSTED"):
            reserve(resumed)


def test_utc_daily_global_cap_is_shared_across_models(tmp_path):
    budget = BudgetPolicy(
        allocation_id="utc-day-test",
        global_cap=10,
        daily_global_cap=1,
        model_caps=(ModelCap(model=MODEL, total=10), ModelCap(model=REVIEWER, total=10)),
        day_timezone="UTC",
    )
    with DurableAttemptJournal(tmp_path, budget) as journal:
        reserve(journal)
        with pytest.raises(ProviderFailure, match="DURABLE_DAY_BUDGET_EXHAUSTED"):
            reserve(journal, REVIEWER)


def test_concurrent_reservations_use_unique_exact_sequence(tmp_path):
    with DurableAttemptJournal(tmp_path, policy(global_cap=40, model_cap=40)) as journal:
        identity = journal.identity
        with ThreadPoolExecutor(max_workers=4) as pool:
            sequence = sorted(
                record.sequence for record in pool.map(lambda _: reserve(journal), range(20))
            )
        assert sequence == list(range(1, 21))
        assert journal.counts["total_reserved_attempts"] == 20
        assert journal.identity == identity
    with DurableAttemptJournal(tmp_path, policy(global_cap=40, model_cap=40)) as resumed:
        assert resumed.counts["total_reserved_attempts"] == 20


def test_published_reservation_ahead_of_head_is_conservatively_recovered(tmp_path):
    with DurableAttemptJournal(tmp_path, policy()) as journal:
        reserve(journal)
    write_envelope(tmp_path / "head.json", {"count": 0, "last_sha256": "0" * 64}, replace=True)
    with DurableAttemptJournal(tmp_path, policy()) as resumed:
        assert resumed.counts["total_reserved_attempts"] == 1
        assert read_envelope(tmp_path / "head.json")["count"] == 1


@pytest.mark.parametrize("damage", ["corrupt", "truncated", "gap", "head"])
def test_damaged_attempt_history_fails_closed(tmp_path, damage):
    with DurableAttemptJournal(tmp_path, policy()) as journal:
        reserve(journal)
        reserve(journal)
    first = tmp_path / "attempts/000000001.json"
    second = tmp_path / "attempts/000000002.json"
    if damage == "corrupt":
        first.write_text(first.read_text().replace(REQUEST, "b" * 64))
    elif damage == "truncated":
        second.unlink()
    elif damage == "gap":
        first.unlink()
    else:
        write_envelope(tmp_path / "head.json", {"count": 2, "last_sha256": "b" * 64}, replace=True)
    with pytest.raises(ValueError):
        with DurableAttemptJournal(tmp_path, policy()):
            pytest.fail("Invalid accounting must not be accepted")


def test_changed_allocation_policy_cannot_adopt_old_ledger(tmp_path):
    with DurableAttemptJournal(tmp_path, policy()) as journal:
        reserve(journal)
    with pytest.raises(ValueError, match="identity mismatch"):
        with DurableAttemptJournal(tmp_path, policy(global_cap=11)):
            pytest.fail("Changed policy must not reset accounting")


def test_exclusive_lease_requires_explicit_auditable_recovery(tmp_path):
    path = tmp_path / "batch.lock"
    abandoned = ExclusiveLease(path, purpose="fixture simulated stopped process")
    abandoned.__enter__()
    with pytest.raises(RuntimeError, match="explicit audited recovery"):
        with ExclusiveLease(path, purpose="second process"):
            pytest.fail("Never infer that an existing owner is dead")
    for token, stopped, reason in [
        ("wrong", True, "operator check"),
        (abandoned.token, False, "check"),
        (abandoned.token, True, ""),
    ]:
        with pytest.raises(ValueError):
            recover_lease(
                path, expected_token=token, owner_confirmed_stopped=stopped, reason=reason
            )
    receipt = recover_lease(
        path,
        expected_token=abandoned.token,
        owner_confirmed_stopped=True,
        reason="Operator explicitly confirmed the simulated owner is stopped",
    )
    assert not path.exists()
    assert read_envelope(receipt)["owner_confirmed_stopped"] is True
    assert read_envelope(receipt)["lock"]["token"] == abandoned.token
    with ExclusiveLease(path, purpose="new process after audited recovery"):
        assert path.exists()
    assert not path.exists()


def test_closed_journal_cannot_reserve_or_concurrently_reopen(tmp_path):
    journal = DurableAttemptJournal(tmp_path, policy())
    with pytest.raises(RuntimeError, match="exclusively open"):
        reserve(journal)
    with journal:
        with pytest.raises(RuntimeError, match="already exists"):
            with DurableAttemptJournal(tmp_path, policy()):
                pytest.fail("Two processes must not share journal mutation")


def test_invalid_clock_and_unregistered_model_fail_without_charging(tmp_path):
    with DurableAttemptJournal(tmp_path, policy(), clock=lambda: datetime(2023, 1, 1)) as journal:
        with pytest.raises(ValueError, match="timezone-aware"):
            reserve(journal)
    with DurableAttemptJournal(tmp_path, policy()) as journal:
        with pytest.raises(ProviderFailure, match="UNREGISTERED_BUDGET_MODEL"):
            reserve(journal, "not-configured")
        assert journal.counts["total_reserved_attempts"] == 0
