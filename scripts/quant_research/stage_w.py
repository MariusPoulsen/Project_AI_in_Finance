"""Decision 112 (Stage W): a wider exit grid on the Decision 108 book, robust selection.

Usage: stage_w.py [--holdout]
Grid: 11 time rules x 3 take-profit bands x 3 disaster stops = 99 configurations at
pairs gross cap 1.0 (the Decision 111 cap result is not carried forward). Choice: the
highest plateau score (mean 2010-2017 Sharpe of a configuration and its grid
neighbours). PBO (CSCV, 12 half-year blocks) and the deflated Sharpe are reported.
"""
import itertools
import json
import math
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import kurtosis, norm, skew

from structural_break.experiments import p6_agents as pa
from structural_break.experiments import p6_quant_costs as qc
from structural_break.experiments import p6_quant_portfolio as qp
from structural_break.experiments import p6_resid as pr
from structural_break.experiments.p6_improvement import _sources

holdout = "--holdout" in sys.argv
ws = Path("data/team")
out = Path("outputs/p6_quant/stage_w")
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
version = _sources(ws).binding.evaluation.version
half_life = pd.read_parquet(ws / "artifacts/research" / version / "model_inputs.parquet",
                            columns=["event_id", "half_life"]).set_index("event_id")["half_life"]

FIXED = (15, 20, 25, 30, 35, 40)
HALF_LIFE = (1.0, 1.5, 2.0)
SOFT = (0.75, 1.0)
BANDS = (0.5, 0.75, 1.0)
STOPS = (4.0, 5.0, 99.0)


def time_rules():
    for t in FIXED:
        yield ("fixed", t)
    for k in HALF_LIFE:
        yield ("halflife", k)
    for r in SOFT:
        yield ("soft", r)


def timeout_of(rule):
    family, value = rule
    if family == "fixed":
        return value, None
    if family == "soft":
        return 40, (20, value)
    hl = half_life.reindex(chosen)
    return {e: int(min(max(math.ceil(value * h), 10), 40)) if np.isfinite(h) and h > 0 else 20
            for e, h in hl.items()}, None


def run(rule, band, stop):
    timeout, soft = timeout_of(rule)
    settings = (band, stop, timeout, True) + ((soft,) if soft else ())
    d = qp.run_design(cache, chosen, settings, Path("configs"), 0.075, sectors, costs, 1e7)
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
    book = pr.run_book(panels, w, legs, pd.Timestamp("2010-01-01"), pd.Timestamp("2023-12-31"), capital=1e7, rf=rf,
                       speed=0.10, vol_target=0.04, vol_window=60, timing="close", max_gross=2.0)
    blocked = sum(1 for v in d["status"].values() if str(v) == "CAPACITY_REJECTED")
    return book, {"trades": len(holds), "mean_holding": float(np.mean(holds)), "exits": dict(reasons), "blocked": blocked}


def monthly_excess(book):
    b = book.assign(m=pd.to_datetime(book.session_date).dt.strftime("%Y-%m"))
    return b.groupby("m").apply(lambda g: float(np.prod(1 + g.daily_return) / np.prod(1 + g.interest) - 1))


configs = list(itertools.product(time_rules(), BANDS, STOPS))
rows, monthly = [], {}
for number, (rule, band, stop) in enumerate(configs, start=1):
    book, info = run(rule, band, stop)
    name = f"{rule[0]}:{rule[1]}|tp{band}|stop{'none' if stop > 50 else stop}"
    row = {"name": name, "family": rule[0], "value": rule[1], "band": band, "stop": stop, **info}
    for label, a, z in (("2010-2017", 2010, 2017),) + ((("2018-2023", 2018, 2023), ("2010-2023", 2010, 2023)) if holdout else ()):
        s = pr.stats(book, a, z)
        row[label] = {"sharpe": s["sharpe"], "cagr": s["cagr"], "maxdd": s["maxdd"]}
    rows.append(row)
    monthly[name] = monthly_excess(book)
    print(f"{number:3d}/{len(configs)} {name:32s} 2010-2017 Sharpe {row['2010-2017']['sharpe']:+.3f} "
          f"hold {info['mean_holding']:.1f} blocked {info['blocked']}", flush=True)
table = pd.DataFrame(rows)
if not holdout:
    base = table[(table.family == "fixed") & (table.value == 20) & (table.band == 1.0) & (table.stop == 5.0)]
    if abs(base["2010-2017"].iloc[0]["sharpe"] - 0.6122) > 0.001:
        raise SystemExit("The current design does not reproduce; stopping")
order = {"fixed": list(FIXED), "halflife": list(HALF_LIFE), "soft": list(SOFT)}
sharpe = {r["name"]: r["2010-2017"]["sharpe"] for r in rows}
plateau = {}
for r in rows:
    values = order[r["family"]]
    i, j, k = values.index(r["value"]), BANDS.index(r["band"]), STOPS.index(r["stop"])
    near = [r["name"]]
    for other in rows:
        if other["family"] != r["family"]:
            continue
        di = abs(values.index(other["value"]) - i)
        dj, dk = abs(BANDS.index(other["band"]) - j), abs(STOPS.index(other["stop"]) - k)
        if di + dj + dk == 1:
            near.append(other["name"])
    plateau[r["name"]] = float(np.mean([sharpe[n] for n in near]))
chosen_name = max(plateau, key=plateau.get)
raw_best = max(sharpe, key=sharpe.get)
# PBO on 2010-2017 monthly excess returns, 12 half-year blocks.
M = pd.DataFrame(monthly)
M = M[(M.index >= "2010-01") & (M.index <= "2017-12")]
blocks = np.array_split(np.arange(len(M)), 12)
sr = lambda X: X.mean() / X.std(ddof=1)  # noqa: E731
logits = []
for combo in itertools.combinations(range(12), 6):
    ins = np.concatenate([blocks[i] for i in combo])
    oos = np.setdiff1d(np.arange(len(M)), ins)
    best = sr(M.iloc[ins]).idxmax()
    rank = sr(M.iloc[oos]).rank()[best] / (M.shape[1] + 1)
    logits.append(math.log(rank / (1 - rank)))
pbo = float((np.array(logits) <= 0).mean())
trial_sr = sr(M)
r = M[chosen_name].to_numpy()
s, g3, g4 = r.mean() / r.std(ddof=1), skew(r), kurtosis(r, fisher=False)
dsr = {}
for n in (99, 300):
    gamma = 0.5772156649
    sr0 = trial_sr.std(ddof=1) * ((1 - gamma) * norm.ppf(1 - 1 / n) + gamma * norm.ppf(1 - 1 / (n * math.e)))
    z = (s - sr0) * math.sqrt(len(r) - 1) / math.sqrt(1 - g3 * s + (g4 - 1) / 4 * s * s)
    dsr[n] = float(norm.cdf(z))
summary = {"chosen_by_plateau": chosen_name, "plateau": plateau[chosen_name], "chosen_sharpe": sharpe[chosen_name],
           "raw_best": raw_best, "raw_best_sharpe": sharpe[raw_best], "pbo_2010_2017": pbo, "dsr": dsr,
           "trials": len(rows), "rows": rows}
print(json.dumps({k: v for k, v in summary.items() if k != "rows"}, indent=1, default=str))
json.dump(summary, open(out / ("summary_holdout.json" if holdout else "summary.json"), "w"), indent=1, default=str)
