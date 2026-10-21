"""Decision 99: position sizing, uniform and liquidity-scaled (prints 2010-2017 unless --holdout)."""
import sys, json, math, pandas as pd, numpy as np
from pathlib import Path
from structural_break.experiments import p6_quant_portfolio as qp, p6_quant_costs as qc, p6_boosting as pb
from structural_break.experiments.p6_improvement import _sources
out_dir = Path("outputs/p6_quant/portfolio_p"); out_dir.mkdir(parents=True, exist_ok=True)
if "--holdout" in sys.argv:
    for k, row in json.load(open(out_dir / "summary.json")).items():
        print(f"{k:6s} " + " | ".join(f"{p}: Sharpe {v['sharpe']:+.2f} CAGR {v['cagr']:+.2%} maxDD {v['maxdd']:.1%}" for p, v in row.items() if isinstance(v, dict)))
    sys.exit()
capital = 1e7
frame, _ = pb.load_data(Path("data/team"), Path("outputs/p6_improvement/walkforward/simulation_frozen_exit.parquet"))
year = pd.to_datetime(frame.set_index("event_id").event_date).dt.year
s = pd.read_parquet("outputs/p6_boosting2/scores.parquet"); s = s[s.variant.eq("R0_xgb_fixed")]
r1 = set(pd.read_parquet("outputs/p6_quant/r1_events.parquet").event_id)
cross = pd.read_parquet("outputs/p6_quant/features.parquet").set_index("event_id")["state_days_since_zero_cross"]
costs = pd.read_parquet("outputs/p6_quant/cost_model_nets.parquet").set_index("event_id")
rt = 2 * costs["rate_10m"]; ry = year.reindex(rt.index)
cost_cut = {Y: np.nanquantile(rt[ry.eq(Y - 1)], 0.8) for Y in range(2010, 2024)}
chosen = []
for Y, g in s.groupby("year"):
    cut = float(np.quantile(g.loc[g.role.eq("threshold"), "score"], 0.8))
    chosen += list(g[g.role.eq("test") & (g.score >= cut)].event_id)
cache = qp.load_cache(Path("outputs/p6_quant/requests.pkl"))
chosen = [e for e in chosen if e not in r1 and not (cross.get(e, 0) > 120) and not (rt.get(e, np.inf) >= cost_cut.get(year.get(e), np.inf)) and e in cache]
sectors = _sources(Path("data/team")).security_sectors()
prices = pd.read_parquet("data/team/market/source_v1/prices.parquet", columns=["ticker", "trading_date", "open", "high", "low", "close", "adj_close", "volume"])
table = qc.lookup(qc.stock_inputs(prices))
designs = {"P-2.5": (0.025, None), "P-5": (0.05, None), "P-7.5": (0.075, None), "P-10": (0.10, None), "P-L3": (0.10, 3.0), "P-L5": (0.10, 5.0)}
summary = {}
for name, (target, budget) in designs.items():
    fractions = None
    if budget is not None:
        fractions = {}
        for e in chosen:
            req, fr, _ = cache[e]
            f = qc.impact_capped_fraction(table, req, fr, capital, budget, target)
            if f is not None and f > 1e-4:
                fractions[e] = f
        sel = [e for e in chosen if e in fractions]
    else:
        sel = chosen
    out = qp.run_design(cache, sel, (1.0, 5.0, 20, True), Path("configs"), target, sectors, table, capital, None, fractions)
    m = out["marks"]; m = m[m.nav.notna()].copy(); m["y"] = pd.to_datetime(m.session_date).dt.year
    m.to_parquet(out_dir / f"nav_{name}.parquet", index=False)
    row = {"mean_gross": float(m.gross_fraction.astype(float).mean()), "mean_fraction": float(np.mean(list(fractions.values()))) if fractions else target, "last_known": str(m.session_date.iloc[-1])}
    for label, (a, b) in (("2010-2017", (2010, 2017)), ("2018-2023", (2018, 2023)), ("2010-2023", (2010, 2023))):
        r = m[m.y.between(a, b)].daily_return.astype(float); nav = (1 + r).cumprod()
        row[label] = {"sharpe": float(r.mean() / r.std() * math.sqrt(252)), "cagr": float(nav.iloc[-1] ** (252 / len(r)) - 1), "maxdd": float((nav / nav.cummax() - 1).min())}
    summary[name] = row
    v = row["2010-2017"]
    print(f"{name:6s} mean size {row['mean_fraction']:.3f} mean gross {row['mean_gross']:.2f} | 2010-2017 Sharpe {v['sharpe']:+.2f} CAGR {v['cagr']:+.2%} maxDD {v['maxdd']:.1%}", flush=True)
json.dump(summary, open(out_dir / "summary.json", "w"), indent=1)
