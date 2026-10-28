"""Re-key the development agent-desk answers to the final-test registry's event ids (120a).

    python scripts/final_test_desk_rekey.py

The final-test registry has new event ids (they derive from the spliced market snapshot).
The development entry and monitor answers, copied into ``outputs/agent_desk``, are found by
file name: entry results by event id, monitor results by ``sha256("<event id>:<date>")[:40]``.
Each answer is rewritten under its new name with the old id replaced by the new one, so only
2024-2025 cases are sent to the language models. The answers themselves are unchanged.
"""

import hashlib
import json
from pathlib import Path

import pandas as pd

from structural_break.research.final_test import _registry_ids

WORKSPACE = Path("data/team")
DESK = Path("outputs/agent_desk")
FROZEN = WORKSPACE / "artifacts/research/research_evaluation_16a431c4fea73ffd35f56062"


def main() -> None:
    state = json.loads((WORKSPACE / "final_test_state.json").read_text())
    registry = WORKSPACE / "artifacts/research" / state["registry"]
    frozen = pd.read_parquet(
        FROZEN / "model_inputs.parquet", columns=["event_id", "pair_id", "event_timestamp"]
    )
    renamed = _registry_ids(frozen, registry / "h20_events.parquet")
    counts = {"entry": 0, "monitor": 0, "unmatched": 0, "already": 0}
    for path in sorted((DESK / "entry_results").glob("evt_*.json")):
        old = path.stem
        new = renamed.get(old)
        if new is None:
            counts["already" if old in renamed.values() else "unmatched"] += 1
            continue
        target = path.with_name(f"{new}.json")
        if target.exists():
            raise SystemExit(f"Refusing to overwrite {target}")
        target.write_text(path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
        path.unlink()
        counts["entry"] += 1
    for path in sorted((DESK / "monitor_results").glob("*.json")):
        text = path.read_text(encoding="utf-8")
        check_id = json.loads(text)["check_id"]
        old, day = check_id.split(":", 1)
        new = renamed.get(old)
        if new is None:
            counts["already" if old in renamed.values() else "unmatched"] += 1
            continue
        name = hashlib.sha256(f"{new}:{day}".encode()).hexdigest()[:40]
        target = path.with_name(f"{name}.json")
        if target.exists():
            raise SystemExit(f"Refusing to overwrite {target}")
        target.write_text(text.replace(old, new), encoding="utf-8")
        path.unlink()
        counts["monitor"] += 1
    print(json.dumps(counts))


if __name__ == "__main__":
    main()
