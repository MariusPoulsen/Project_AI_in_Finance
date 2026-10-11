"""Explicit development-only event simulation; no downloads, fitting or portfolio run."""

import argparse
import hashlib
import json
from pathlib import Path

from structural_break.backtest.contracts import ExecutionConfig, PairTradeRequest
from structural_break.backtest.fixtures import synthetic_trade_request
from structural_break.backtest.simulator import canonical_bytes, fixture_config, simulate_pair_trade
from structural_break.storage.files import write_bytes


def _read(path: Path) -> str:
    if path.stat().st_size > 200_000:
        raise ValueError("Execution input/config files must be bounded")
    return path.read_text(encoding="utf-8")


def main() -> None:
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
