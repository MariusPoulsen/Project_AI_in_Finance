"""Reproduction check for the adopted book (Decision 110d) and its inputs.

Rebuilds the selection, the book without the monitor exit and the final book (R0, monitor
exit at adverse >= 5 and persistence >= 5), 2010-2023, and fingerprints them: candidate
lists, daily NAV returns and 2010-2017 statistics. Reads no 2024-2025 data.

    python scripts/verify_book.py --save     # write outputs/checks/book_fingerprint.json
    python scripts/verify_book.py            # compare against the saved fingerprint
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from structural_break.experiments import p6_agents as selection
from structural_break.experiments import p6_desk as desk
from structural_break.experiments import p6_resid as book
from structural_break.experiments.p6_improvement import _sources

WORKSPACE = Path("data/team")
FINGERPRINT = Path("outputs/checks/book_fingerprint.json")


def digest(values: object) -> str:
    return hashlib.sha256(json.dumps(values, default=str).encode()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", action="store_true")
    args = parser.parse_args()
    sectors = _sources(WORKSPACE).security_sectors()
    prices = pd.read_parquet(WORKSPACE / "market/source_v1/prices.parquet",
                             columns=["ticker", "trading_date", "open", "high", "low", "close", "adj_close", "volume"])
    panels = book.load_panels(prices, sectors)
    rf = book.tbill(Path("data/external/irx_13w_tbill.csv"))
    w = np.load("outputs/p6_quant/stage_q/targets_pca_continuous.npy") * 0.25

    def run(legs: list) -> pd.DataFrame:
        return book.run_book(panels, w, legs, pd.Timestamp("2010-01-01"), pd.Timestamp("2023-12-31"), capital=1e7, rf=rf,
                             speed=0.10, vol_target=0.04, vol_window=60, timing="close", max_gross=2.0)

    checks = []
    for record in pd.read_parquet(desk.OUTPUT / "monitor_inventory.parquet").to_dict("records"):
        result = desk.load_result(desk.OUTPUT, "monitor", record["file"])
        if result and result["scores"]:
            checks.append({**record, **{k: result["scores"][k] for k in ("adverse", "persistence")}})
    hit = pd.DataFrame(checks).query("adverse >= 5 and persistence >= 5")
    exits = hit.sort_values("session").groupby("event_id").session.first().dt.date.to_dict()
    report = {
        "candidates_R0": digest(selection.design_candidates(WORKSPACE, "R0")),
        "candidates_bag5": digest(selection.design_candidates(WORKSPACE, "B+rule+ou__recent-bag5")),
        "time_stops": digest(sorted(desk.time_stops(WORKSPACE).items())),
        "monitor_exits": len(exits),
    }
    for name, legs in (("book_no_monitor", desk.desk_book(WORKSPACE, {}, set(), {})),
                       ("book_final", desk.desk_book(WORKSPACE, {}, set(), exits))):
        b = run(legs)
        report[name] = {"daily_returns": digest(np.round(b.daily_return.to_numpy(), 12).tolist()),
                        "stats_2010_2017": book.stats(b, 2010, 2017)}
    print(json.dumps(report, indent=1, default=str))
    if args.save:
        FINGERPRINT.parent.mkdir(parents=True, exist_ok=True)
        FINGERPRINT.write_text(json.dumps(report, indent=1, default=str))
        return
    saved = json.loads(FINGERPRINT.read_text())
    same = json.loads(json.dumps(report, default=str)) == saved
    print("REPRODUCED" if same else "DIFFERENT from the saved fingerprint")
    sys.exit(0 if same else 1)


if __name__ == "__main__":
    main()
