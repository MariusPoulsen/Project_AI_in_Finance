"""Explicit offline Phase 5 batch launcher; no implicit LLM calls or fitting."""

import argparse
import json
import sys
from pathlib import Path

from structural_break.agents.batch import freeze_schedule, run_batch
from structural_break.agents.budgets import (
    BudgetPolicy,
    DurableAttemptJournal,
    ModelCap,
    recover_lease,
)
from structural_break.agents.contracts import AgentInput, AgentPolicy
from structural_break.agents.inputs import PreparedInputs, batch_fixture_events, prepare_mock_inputs
from structural_break.agents.pipeline import run_investigation
from structural_break.agents.providers import ScriptedProvider
from structural_break.agents.review import export_review, validate_review


def _read(path: Path) -> str:
    if path.stat().st_size > 1_000_000:
        raise ValueError("Phase 5 input files must be bounded")
    return path.read_text(encoding="utf-8")


def _fixture_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "tests/fixtures/phase5"


def _batch(arguments: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Resume an explicit mock investigation batch")
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--fixture", action="store_true")
    inputs.add_argument("--bundle", type=Path, help="Immutable mock input manifest")
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--responses", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-events", type=int, help="Pause after this many new checkpoints")
    parser.add_argument("--max-investigations", type=int, help="Frozen target-blind selection cap")
    parser.add_argument("--call-budget", type=int, default=60, help="Durable fixture attempt cap")
    parser.add_argument("--seed", default="phase5-target-blind-v1")
    parser.add_argument("--attempt-id", default="initial")
    args = parser.parse_args(arguments)
    if args.fixture:
        if args.policy or args.responses:
            parser.error("--fixture cannot be combined with supplied policy/responses")
        fixture = _fixture_dir()
        bundle = prepare_mock_inputs(
            batch_fixture_events(fixture / "input.json"),
            args.output_dir / "prepared",
            generation_id="fixture-batch-v1",
        )
        policy_path, responses_path = fixture / "policy.json", fixture / "responses.json"
    else:
        if not args.policy or not args.responses:
            parser.error("--bundle requires --policy and --responses")
        bundle, policy_path, responses_path = args.bundle, args.policy, args.responses
    events = PreparedInputs(bundle)
    policy = AgentPolicy.model_validate_json(_read(policy_path))
    responses = json.loads(_read(responses_path))
    if not isinstance(responses, dict):
        parser.error("Responses must be an object keyed by the six stage roles")
    schedule = freeze_schedule(
        events, policy, seed=args.seed, max_investigations=args.max_investigations
    )
    budget = BudgetPolicy(
        allocation_id="phase5-cli-mock-allocation-v1",
        global_cap=args.call_budget,
        model_caps=(ModelCap(model="scripted-fixture", total=args.call_budget),),
    )
    with DurableAttemptJournal(args.output_dir / "attempt-journal", budget) as journal:
        provider = ScriptedProvider(responses, attempt_journal=journal)
        progress = run_batch(
            schedule,
            events,
            policy,
            provider,
            args.output_dir,
            attempt_id=args.attempt_id,
            max_events=args.max_events,
        )
    print(progress.model_dump_json(indent=2))


def _review(arguments: list[str], *, validate: bool) -> None:
    parser = argparse.ArgumentParser(description="Blind source review workflow (mock inputs only)")
    parser.add_argument("--bundle", type=Path, required=True)
    if validate:
        parser.add_argument("--review-dir", type=Path, required=True)
        parser.add_argument("--annotations", type=Path, required=True)
    else:
        parser.add_argument("--output-dir", type=Path, required=True)
        parser.add_argument("--count", type=int, default=50)
        parser.add_argument("--seed", default="phase5-review-v1")
    args = parser.parse_args(arguments)
    events = PreparedInputs(args.bundle)
    if validate:
        print(json.dumps(validate_review(events, args.review_dir, args.annotations), indent=2))
    else:
        manifest = export_review(events, args.output_dir, count=args.count, seed=args.seed)
        print(json.dumps({"mode": "mock", "review_manifest": str(manifest)}, indent=2))


def _recover(arguments: list[str]) -> None:
    parser = argparse.ArgumentParser(description="Explicit abandoned-lease recovery")
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--owner-confirmed-stopped", action="store_true", required=True)
    args = parser.parse_args(arguments)
    receipt = recover_lease(
        args.lock,
        expected_token=args.token,
        reason=args.reason,
        owner_confirmed_stopped=args.owner_confirmed_stopped,
    )
    print(json.dumps({"recovery_receipt": str(receipt)}, indent=2))


def main() -> None:
    if len(sys.argv) > 1:
        command = sys.argv[1]
        if command == "batch":
            _batch(sys.argv[2:])
            return
        if command in {"review-export", "review-validate"}:
            _review(sys.argv[2:], validate=command == "review-validate")
            return
        if command == "recover-lock":
            _recover(sys.argv[2:])
            return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", action="store_true", help="Run the bundled synthetic debate")
    parser.add_argument("--input", type=Path, help="Strict source-bounded event JSON")
    parser.add_argument("--policy", type=Path, help="Explicit controller policy JSON")
    parser.add_argument("--responses", type=Path, help="Deterministic per-role response JSON")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=("mock",), default="mock")
    parser.add_argument("--attempt-id", default="initial", help="Explicit retry identity")
    args = parser.parse_args()
    if args.fixture:
        if any((args.input, args.policy, args.responses)):
            parser.error("--fixture cannot be combined with supplied inputs")
        fixture = _fixture_dir()
        input_path, policy_path, responses_path = (
            fixture / "input.json",
            fixture / "policy.json",
            fixture / "responses.json",
        )
    else:
        if not all((args.input, args.policy, args.responses)):
            parser.error("Supply --input, --policy and --responses, or use --fixture")
        input_path, policy_path, responses_path = args.input, args.policy, args.responses
    event = AgentInput.model_validate_json(_read(input_path))
    policy = AgentPolicy.model_validate_json(_read(policy_path))
    responses = json.loads(_read(responses_path))
    if not isinstance(responses, dict):
        parser.error("Responses must be an object keyed by the six stage roles")
    provider = ScriptedProvider(responses)
    result = run_investigation(event, policy, provider, args.output_dir, attempt_id=args.attempt_id)
    print(
        json.dumps(
            {
                "run_id": result.run_id,
                "mode": result.mode,
                "status": result.decision.status,
                "reason_codes": result.decision.reason_codes,
                "new_provider_calls": provider.calls,
                "result": str(args.output_dir / "runs" / result.run_id / "result.json"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
