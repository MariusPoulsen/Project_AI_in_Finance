"""Explicit offline Phase 5 batch launcher; no implicit LLM calls or fitting."""

import argparse
import json
from pathlib import Path

from structural_break.agents.contracts import AgentInput, AgentPolicy
from structural_break.agents.pipeline import run_investigation
from structural_break.agents.providers import ScriptedProvider


def _read(path: Path) -> str:
    if path.stat().st_size > 1_000_000:
        raise ValueError("Phase 5 input files must be bounded")
    return path.read_text(encoding="utf-8")


def main() -> None:
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
        fixture = Path(__file__).resolve().parents[3] / "tests/fixtures/phase5"
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
