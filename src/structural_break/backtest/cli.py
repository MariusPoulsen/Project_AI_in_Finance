"""Explicit development-only event simulation; no downloads, fitting or portfolio run."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

from structural_break.backtest.contracts import ExecutionConfig, PairTradeRequest
from structural_break.backtest.fixtures import synthetic_trade_request
from structural_break.backtest.simulator import canonical_bytes, fixture_config, simulate_pair_trade
from structural_break.storage.files import write_bytes


def _read(path: Path) -> str:
    if path.stat().st_size > 200_000:
        raise ValueError("Execution input/config files must be bounded")
    return path.read_text(encoding="utf-8")


def _ladder(arguments: list[str]) -> None:
    # Preserve the small single-event launcher without loading report tooling
    # until the user explicitly requests a ladder experiment.
    from structural_break.backtest.experiment import (
        LadderInputDocument,
        LadderLabelDocument,
        read_bounded,
        run_ladder_experiment,
        strict_json,
    )
    from structural_break.backtest.ladder_contracts import LadderPolicy
    from structural_break.backtest.ladder_fixtures import fixture_ladder

    parser = argparse.ArgumentParser(description="Synthetic five-rung comparison experiment")
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--fixture", action="store_true")
    inputs.add_argument("--input", type=Path)
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--labels", type=Path, help="Separate complete-window evaluation labels")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(arguments)
    if args.fixture:
        if args.policy or args.config or args.labels:
            parser.error("--fixture cannot be combined with supplied policies or labels")
        events, policy, config, labels = fixture_ladder()
    else:
        if not args.policy or not args.config:
            parser.error("--input requires --policy and --config")
        payloads = {
            name: read_bounded(path)
            for name, path in (
                ("inputs", args.input),
                ("policy", args.policy),
                ("config", args.config),
            )
        }
        for raw in payloads.values():
            strict_json(raw)
        events = LadderInputDocument.model_validate_json(payloads["inputs"]).events
        policy = LadderPolicy.model_validate_json(payloads["policy"])
        config = ExecutionConfig.model_validate_json(payloads["config"])
        labels = ()
        if args.labels:
            raw = read_bounded(args.labels)
            strict_json(raw)
            labels = LadderLabelDocument.model_validate_json(raw).labels
    manifest = run_ladder_experiment(events, policy, config, args.output_dir, labels=labels)
    print(
        json.dumps(
            {
                "mode": "SYNTHETIC_FIXTURE",
                "event_count": len(events),
                "manifest": str(manifest),
                "summary": str(manifest.parent / "summary.md"),
                "scientific_acceptance": False,
                "final_test_unlocked": False,
            },
            indent=2,
        )
    )


def _verify(arguments: list[str]) -> None:
    from structural_break.backtest.experiment import verify_ladder_experiment

    parser = argparse.ArgumentParser(description="Independently verify a synthetic ladder manifest")
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args(arguments)
    print(json.dumps(verify_ladder_experiment(args.manifest), indent=2))


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "ladder":
        _ladder(sys.argv[2:])
        return
    if len(sys.argv) > 1 and sys.argv[1] == "verify":
        _verify(sys.argv[2:])
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture", action="store_true", help="Run the synthetic 10% gross example"
    )
    parser.add_argument(
        "--input", type=Path, help="Strict supplied development execution path JSON"
    )
    parser.add_argument("--config", type=Path, help="Explicit execution policy JSON")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.fixture:
        if args.input or args.config:
            parser.error("--fixture cannot be combined with supplied input/config")
        event, config = synthetic_trade_request(), fixture_config()
    else:
        if args.input is None or args.config is None:
            parser.error("Supply both --input and --config, or use --fixture")
        event = PairTradeRequest.model_validate_json(_read(args.input))
        config = ExecutionConfig.model_validate_json(_read(args.config))
    result = simulate_pair_trade(event, config)
    output = canonical_bytes(result)
    # Content-addressed directories make reruns idempotent, not overwrites.
    run_id = hashlib.sha256(output).hexdigest()
    directory = args.output_dir / "runs" / run_id
    write_bytes(directory / "input.json", canonical_bytes(event))
    write_bytes(directory / "config.json", canonical_bytes(config))
    write_bytes(directory / "result.json", output)
    print(
        json.dumps(
            {
                "run_id": run_id,
                "data_kind": result.data_kind,
                "status": result.status,
                "reason": result.reason,
                "gross_return": result.gross_return,
                "net_return": result.net_return,
                "result": str(directory / "result.json"),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
