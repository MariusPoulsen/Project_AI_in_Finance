"""Decision 98: selection share under the full current design (prints 2010-2017 unless --holdout)."""
import sys, json, math, pandas as pd, numpy as np
from pathlib import Path
from structural_break.experiments import p6_quant_portfolio as qp, p6_quant_costs as qc, p6_boosting as pb
from structural_break.experiments.p6_improvement import _sources
holdout = "--holdout" in sys.argv
out_dir = Path("outputs/p6_quant/portfolio_o"); out_dir.mkdir(parents=True, exist_ok=True)
shares = (0.10, 0.15, 0.20, 0.30, 0.40, 0.50)
if not holdout:
    frame, _ = pb.load_data(Path("data/team"), Path("outputs/p6_improvement/walkforward/simulation_frozen_exit.parquet"))
    year = pd.to_datetime(frame.set_index("event_id").event_date).dt.year
    s = pd.read_parquet("outputs/p6_boosting2/scores.parquet"); s = s[s.variant.eq("R0_xgb_fixed")]
    r1 = set(pd.read_parquet("outputs/p6_quant/r1_events.parquet").event_id)
    cross = pd.read_parquet("outputs/p6_quant/features.parquet").set_index("event_id")["state_days_since_zero_cross"]
    costs = pd.read_parquet("outputs/p6_quant/cost_model_nets.parquet").set_index("event_id")
    rt = 2 * costs["rate_10m"]; ry = year.reindex(rt.index)
    cost_cut = {Y: np.nanquantile(rt[ry.eq(Y - 1)], 0.8) for Y in range(2010, 2024)}
    sectors = _sources(Path("data/team")).security_sectors()
    cache = qp.load_cache(Path("outputs/p6_quant/requests.pkl"))
    prices = pd.read_parquet("data/team/market/source_v1/prices.parquet", columns=["ticker", "trading_date", "open", "high", "low", "close", "adj_close", "volume"])
    table = qc.lookup(qc.stock_inputs(prices))
    summary = {}
    for share in shares:
        chosen = []
        for Y, g in s.groupby("year"):
            cut = float(np.quantile(g.loc[g.role.eq("threshold"), "score"], 1 - share))
            test = g[g.role.eq("test") & (g.score >= cut)]
            chosen += list(test.event_id)
        chosen = [e for e in chosen if e not in r1 and not (cross.get(e, 0) > 120) and not (rt.get(e, np.inf) >= cost_cut.get(year.get(e), np.inf)) and e in cache]
        out = qp.run_design(cache, chosen, (1.0, 5.0, 20, True), Path("configs"), 0.05, sectors, table, 1e7, None)
        m = out["marks"]; m = m[m.nav.notna()].copy(); m["y"] = pd.to_datetime(m.session_date).dt.year
        m.to_parquet(out_dir / f"nav_share{int(share*100)}.parquet", index=False)
        row = {"trades": int(out["stats"]["trade_status"].get("COMPLETE", 0)), "mean_gross": float(m.gross_fraction.astype(float).mean()), "mean_open": float(m.open_positions.mean())}
        for label, (a, b) in (("2010-2017", (2010, 2017)), ("2018-2023", (2018, 2023)), ("2010-2023", (2010, 2023))):
            r = m[m.y.between(a, b)].daily_return.astype(float); nav = (1 + r).cumprod()
            row[label] = {"sharpe": float(r.mean() / r.std() * math.sqrt(252)), "cagr": float(nav.iloc[-1] ** (252 / len(r)) - 1), "maxdd": float((nav / nav.cummax() - 1).min())}
        summary[str(int(share * 100))] = row
        sel = row["2010-2017"]
        print(f"top {int(share*100):2d}%  trades {row['trades']}  mean gross {row['mean_gross']:.2f} open {row['mean_open']:.1f} | 2010-2017 Sharpe {sel['sharpe']:+.2f} CAGR {sel['cagr']:+.2%} maxDD {sel['maxdd']:.1%}", flush=True)
    json.dump(summary, open(out_dir / "summary.json", "w"), indent=1)
else:
    summary = json.load(open(out_dir / "summary.json"))
    for k, row in summary.items():
        print(f"top {k}%: " + " | ".join(f"{p}: Sharpe {v['sharpe']:+.2f} CAGR {v['cagr']:+.2%} maxDD {v['maxdd']:.1%}" for p, v in row.items() if isinstance(v, dict)))
