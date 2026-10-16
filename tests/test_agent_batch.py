"""Frozen target-blind population, cheap resume and denominator-safe budget failure."""

import json
from pathlib import Path

import pytest

from structural_break.agents import pipeline
from structural_break.agents.batch import freeze_schedule, run_batch
from structural_break.agents.budgets import (
    BudgetPolicy,
    DurableAttemptJournal,
    ExclusiveLease,
    ModelCap,
    read_envelope,
    write_envelope,
)
from structural_break.agents.contracts import AgentInput, AgentPolicy
from structural_break.agents.providers import ScriptedProvider

FIXTURES = Path(__file__).resolve().parent / "fixtures/phase5"


def fixtures():
    event = AgentInput.model_validate_json((FIXTURES / "input.json").read_text())
    policy = AgentPolicy.model_validate_json((FIXTURES / "policy.json").read_text())
    responses = json.loads((FIXTURES / "responses.json").read_text())
    return event, policy, responses


def changed(event, **changes):
    payload = event.model_dump(mode="json")
    payload.update(changes)
    return type(event).model_validate_json(json.dumps(payload))


def population():
    event, policy, responses = fixtures()
    watch = changed(event, event_id="watch", pair_status="WATCH")
    low = changed(
        event,
        event_id="low",
        quant={**event.quant.model_dump(mode="json"), "model_b_probability": 0.1},
    )
    missing = changed(
        event,
        event_id="missing",
        gates={**event.gates.model_dump(mode="json"), "market_data_ok": False},
    )
    return (event, watch, low, missing), policy, responses


def test_population_is_retained_with_no_cost_for_ineligible_events(tmp_path):
    events, policy, responses = population()
    schedule = freeze_schedule(events, policy)
    provider = ScriptedProvider(responses)
    progress = run_batch(schedule, events, policy, provider, tmp_path)
    assert progress.complete
    assert progress.total_count == progress.completed_count == 4
    assert progress.eligible_count == progress.selected_count == 1
    assert progress.status_counts == {"CANDIDATE": 1, "REVIEW": 1, "NO TRADE": 1, "ABSTAIN": 1}
    assert progress.disposition_counts == {"PREFLIGHT_SKIP": 3, "INVESTIGATED": 1}
    assert progress.new_provider_calls == provider.calls == 6
    manifest = read_envelope(Path(progress.manifest_path))
    assert manifest["complete"] is True
    assert manifest["quality_evidence"] is False
    assert manifest["scientific_acceptance"] is False
    assert len(manifest["checkpoints"]) == 4


def test_order_and_sample_selection_are_target_blind_and_input_order_independent():
    event, policy, _ = fixtures()
    events = tuple(changed(event, event_id=f"eligible-{index}") for index in range(12))
    first = freeze_schedule(events, policy, max_investigations=4)
    reverse = freeze_schedule(tuple(reversed(events)), policy, max_investigations=4)
    assert reverse == first
    changed_scores = tuple(
        changed(row, quant={**row.quant.model_dump(mode="json"), "model_b_probability": 0.91})
        for row in events
    )
    second = freeze_schedule(changed_scores, policy, max_investigations=4)
    assert [(row.event_id, row.selected) for row in second.rows] == [
        (row.event_id, row.selected) for row in first.rows
    ]
    assert second.schedule_id != first.schedule_id  # Exact inputs are still bound.
    assert first.eligible_count == 12 and first.selected_count == 4


def test_unselected_eligible_rows_are_explicit_abstentions(tmp_path):
    events, policy, responses = population()
    schedule = freeze_schedule(events, policy, max_investigations=0)
    provider = ScriptedProvider(responses)
    progress = run_batch(schedule, events, policy, provider, tmp_path)
    assert progress.complete and provider.calls == 0
    assert progress.eligible_count == 1 and progress.selected_count == 0
    assert progress.disposition_counts["NOT_SCHEDULED"] == 1
    records = [
        read_envelope(path) for path in Path(progress.batch_dir).joinpath("events").glob("*.json")
    ]
    omitted = next(row for row in records if row["disposition"] == "NOT_SCHEDULED")
    assert omitted["decision"]["status"] == "ABSTAIN"
    assert omitted["decision"]["reason_codes"] == ["INVESTIGATION_NOT_SCHEDULED"]


def test_pause_resume_and_complete_replay_do_not_replay_finished_graphs(tmp_path, monkeypatch):
    events, policy, responses = population()
    schedule = freeze_schedule(events, policy)
    first = run_batch(schedule, events, policy, ScriptedProvider(responses), tmp_path, max_events=2)
    assert first.completed_count == 2 and not first.complete and first.manifest_path is None
    assert not Path(first.batch_dir).joinpath("manifest.json").exists()
    second_provider = ScriptedProvider(responses)
    second = run_batch(schedule, events, policy, second_provider, tmp_path)
    assert second.complete
    assert first.new_provider_calls + second.new_provider_calls == 6
    monkeypatch.setattr(
        pipeline, "_build_graph", lambda *args: pytest.fail("Completed graphs must not replay")
    )
    third_provider = ScriptedProvider(responses)
    third = run_batch(schedule, tuple(reversed(events)), policy, third_provider, tmp_path)
    assert third.complete and third.new_provider_calls == third_provider.calls == 0
    assert third.batch_id == second.batch_id


def test_completed_checkpoint_is_self_contained_when_redundant_caches_are_removed(
    tmp_path, monkeypatch
):
    event, policy, responses = fixtures()
    schedule = freeze_schedule((event,), policy)
    first = run_batch(schedule, (event,), policy, ScriptedProvider(responses), tmp_path)
    for redundant in tmp_path.joinpath("investigations").rglob("*.json"):
        redundant.unlink()
    monkeypatch.setattr(
        pipeline,
        "_build_graph",
        lambda *args: pytest.fail("Must trust only verified embedded result"),
    )
    provider = ScriptedProvider(responses)
    resumed = run_batch(schedule, (event,), policy, provider, tmp_path)
    assert resumed.batch_id == first.batch_id and provider.calls == 0


def test_durable_attempt_exhaustion_preserves_all_terminal_rows(tmp_path):
    event, policy, responses = fixtures()
    events = tuple(changed(event, event_id=f"eligible-{index}") for index in range(3))
    schedule = freeze_schedule(events, policy)
    budget = BudgetPolicy(
        allocation_id="bounded-fixture",
        global_cap=2,
        model_caps=(ModelCap(model="scripted-fixture", total=2),),
    )
    with DurableAttemptJournal(tmp_path / "budget", budget) as journal:
        provider = ScriptedProvider(responses, attempt_journal=journal)
        first = run_batch(schedule, events, policy, provider, tmp_path / "outputs", max_events=1)
        assert first.status_counts == {"ABSTAIN": 1}
        assert first.new_provider_calls == 2
    with DurableAttemptJournal(tmp_path / "budget", budget) as resumed_journal:
        provider = ScriptedProvider(responses, attempt_journal=resumed_journal)
        resumed = run_batch(schedule, events, policy, provider, tmp_path / "outputs")
        assert resumed.complete and resumed.completed_count == 3
        assert resumed.new_provider_calls == provider.calls == 0
        assert resumed.disposition_counts == {"BUDGET_EXHAUSTED": 3}
        assert resumed_journal.counts["total_reserved_attempts"] == 2


@pytest.mark.parametrize("damage", ["checksum", "decision", "missing"])
def test_checkpoint_damage_fails_closed_without_new_calls(tmp_path, damage):
    event, policy, responses = fixtures()
    schedule = freeze_schedule((event,), policy)
    first = run_batch(schedule, (event,), policy, ScriptedProvider(responses), tmp_path)
    checkpoint = Path(first.batch_dir) / "events/000000000.json"
    if damage == "checksum":
        checkpoint.write_text(checkpoint.read_text().replace('"CANDIDATE"', '"NO TRADE"'))
    elif damage == "decision":
        payload = read_envelope(checkpoint)
        payload["investigation"]["decision"]["status"] = "NO TRADE"
        write_envelope(checkpoint, payload, replace=True)
    else:
        checkpoint.unlink()
    provider = ScriptedProvider(responses)
    with pytest.raises(ValueError):
        run_batch(schedule, (event,), policy, provider, tmp_path)
    assert provider.calls == 0


def test_changed_event_or_policy_cannot_reuse_frozen_schedule(tmp_path):
    event, policy, responses = fixtures()
    schedule = freeze_schedule((event,), policy)
    provider = ScriptedProvider(responses)
    with pytest.raises(ValueError, match="binding mismatch"):
        run_batch(schedule, (changed(event, pair_status="WATCH"),), policy, provider, tmp_path)
    with pytest.raises(ValueError, match="population or policy"):
        run_batch(
            schedule, (event,), changed(policy, policy_version="other-policy"), provider, tmp_path
        )
    assert provider.calls == 0


def test_changed_provider_creates_distinct_generation(tmp_path):
    event, policy, responses = fixtures()
    schedule = freeze_schedule((event,), policy)
    first = run_batch(schedule, (event,), policy, ScriptedProvider(responses), tmp_path)
    responses["validation"]["break_risk"] = "HIGH"
    second = run_batch(schedule, (event,), policy, ScriptedProvider(responses), tmp_path)
    assert second.batch_id != first.batch_id
    assert second.status_counts == {"NO TRADE": 1}
    assert second.new_provider_calls == 6


def test_batch_exclusive_lease_prevents_concurrent_launch(tmp_path):
    events, policy, responses = population()
    schedule = freeze_schedule(events, policy)
    with ExclusiveLease(tmp_path / "batch.lock", purpose="other runner"):
        provider = ScriptedProvider(responses)
        with pytest.raises(RuntimeError, match="already exists"):
            run_batch(schedule, events, policy, provider, tmp_path)
        assert provider.calls == 0


def test_schedule_rejects_duplicates_and_invalid_pause_limits(tmp_path):
    event, policy, responses = fixtures()
    with pytest.raises(ValueError, match="unique"):
        freeze_schedule((event, event), policy)
    with pytest.raises(ValueError, match="nonnegative"):
        freeze_schedule((event,), policy, max_investigations=True)
    schedule = freeze_schedule((event,), policy)
    with pytest.raises(ValueError, match="nonnegative"):
        run_batch(schedule, (event,), policy, ScriptedProvider(responses), tmp_path, max_events=-1)


def test_file_backed_inventory_avoids_an_extra_full_evidence_read(tmp_path):
    events, policy, responses = population()
    schedule = freeze_schedule(events, policy)

    class Inventory:
        event_ids = tuple(event.event_id for event in events)
        reads = 0

        def __len__(self):
            return len(events)

        def __getitem__(self, index):
            self.reads += 1
            return events[index]

        def __iter__(self):
            pytest.fail("A frozen inventory must not reread every pack to build an index")

    inventory = Inventory()
    assert run_batch(schedule, inventory, policy, ScriptedProvider(responses), tmp_path).complete
    assert inventory.reads == len(events)


def test_live_batch_rejects_an_invocation_only_budget(tmp_path):
    event, policy, responses = fixtures()
    frozen = changed(policy, status="FROZEN")
    schedule = freeze_schedule((event,), frozen)

    class UnjournaledLiveProvider(ScriptedProvider):
        mode = "live"

    provider = UnjournaledLiveProvider(responses)
    with pytest.raises(ValueError, match="durable attempt journal"):
        run_batch(schedule, (event,), frozen, provider, tmp_path)
    assert provider.calls == 0
