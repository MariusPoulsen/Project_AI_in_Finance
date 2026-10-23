"""Decision 111 (Stage V): time stop and pairs gross cap on the Decision 108 book, no agents.

Usage: stage_v.py [--holdout]   (2010-2017 unless --holdout)
Step 1: time stop T in {20, 25, 30, 40} at gross cap 1.0. Step 2: gross cap {1.5, 2.0}
at the chosen T. Then an information table of risk targets (4/6/8 %), not a Sharpe choice.
"""
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from structural_break.experiments import p6_agents as pa
from structural_break.experiments import p6_quant_costs as qc
from structural_break.experiments import p6_quant_portfolio as qp
from structural_break.experiments import p6_resid as pr
from structural_break.experiments.p6_improvement import _sources

holdout = "--holdout" in sys.argv
ws = Path("data/team")
out = Path("outputs/p6_quant/stage_v")
out.mkdir(parents=True, exist_ok=True)
cache = qp.load_cache(Path("outputs/p6_quant/requests_long.pkl"))
chosen = pa.design_candidates(ws)
sectors = _sources(ws).security_sectors()
prices = pd.read_parquet(ws / "market/source_v1/prices.parquet",
                         columns=["ticker", "trading_date", "open", "high", "low", "close", "adj_close", "volume"])
costs = qc.lookup(qc.stock_inputs(prices))
panels = pr.load_panels(prices, sectors)
rf = pr.tbill(Path("data/external/irx_13w_tbill.csv"))
w = np.load("outputs/p6_quant/stage_q/targets_pca_continuous.npy") * 0.25
spans = [("2010-2017", 2010, 2017)] + ([("2018-2023", 2018, 2023), ("2010-2023", 2010, 2023)] if holdout else [])


def design(timeout, cap):
    d = qp.run_design(cache, chosen, (1.0, 5.0, timeout, True), Path("configs"), 0.075, sectors, costs, 1e7,
                      policy_override={"gross_entry_cap": cap})
    legs, holds, reasons = [], [], Counter()
    for event_id, fraction in d["allocations"].items():
        result = d["results"][event_id]
        if result.exit is None:
            continue
        request = cache[event_id][0]
        days = [x.session_date for x in request.sessions]
        trigger = days[days.index(result.exit.session_date) - 1]
        holds.append(result.holding_sessions)
        reasons[str(result.reason)] += 1
        for ticker, units, price in ((request.leg_a, result.position.units_a, result.entry.price_a),
                                     (request.leg_b, result.position.units_b, result.entry.price_b)):
            legs.append(pr.Leg(str(ticker), pd.Timestamp(days[0]), pd.Timestamp(trigger), fraction * units * price))
    status = Counter(str(v) for v in d["status"].values())
    return legs, {"trades": len(holds), "mean_holding": float(np.mean(holds)), "exit_reasons": dict(reasons),
                  "portfolio_status": dict(status)}


def book(legs, vol_target=0.04, clip=(0.5, 2.0), max_gross=2.0):
    return pr.run_book(panels, w, legs, pd.Timestamp("2010-01-01"), pd.Timestamp("2023-12-31"), capital=1e7, rf=rf,
                       speed=0.10, vol_target=vol_target, vol_window=60, scale_clip=clip, timing="close",
                       max_gross=max_gross)


def show(name, b, info):
    row = {"name": name, **info}
    for label, a, z in spans:
        s, c = pr.stats(b, a, z), pr.stats(b, a, z, cash=True)
        row[label] = {"sharpe": s["sharpe"], "cagr": s["cagr"], "cagr_cash": c["cagr"], "maxdd": s["maxdd"],
                      "gross": s["gross"]}
        print(f"{name:22s} {label}: Sharpe {s['sharpe']:+.3f} CAGR {s['cagr']:+.2%} (+cash {c['cagr']:+.2%}) "
              f"maxDD {s['maxdd']:.1%} gross {s['gross']:.2f}", flush=True)
    print(f"{'':22s} trades {info['trades']} mean hold {info['mean_holding']:.1f} exits {info['exit_reasons']} "
          f"portfolio {info['portfolio_status']}", flush=True)
    return row


rows = []
step1 = {}
for timeout in (20, 25, 30, 40):
    legs, info = design(timeout, 1.0)
    b = book(legs)
    step1[timeout] = (pr.stats(b, 2010, 2017)["sharpe"], legs, info)
    rows.append(show(f"T{timeout} cap1.0", b, info))
if abs(step1[20][0] - 0.6122) > 0.001:
    raise SystemExit("T20 does not reproduce the Decision 108 book; stopping")
best_t = max(step1, key=lambda t: step1[t][0])
step2 = {1.0: (step1[best_t][0], step1[best_t][1], step1[best_t][2])}
for cap in (1.5, 2.0):
    legs, info = design(best_t, cap)
    b = book(legs)
    step2[cap] = (pr.stats(b, 2010, 2017)["sharpe"], legs, info)
    rows.append(show(f"T{best_t} cap{cap}", b, info))
best_cap = max(step2, key=lambda c: step2[c][0])
print(f"chosen on 2010-2017: time stop {best_t}, pairs gross cap {best_cap}")
legs, info = step2[best_cap][1], step2[best_cap][2]
for vt in (0.04, 0.06, 0.08):  # information only: risk appetite, not a Sharpe choice
    k = vt / 0.04
    rows.append(show(f"risk target {vt:.0%}", book(legs, vt, (0.5, 2.0 * k), 2.0 * k), info))
json.dump({"chosen": {"time_stop": best_t, "gross_cap": best_cap}, "rows": rows},
          open(out / ("summary_holdout.json" if holdout else "summary.json"), "w"), indent=1, default=str)
