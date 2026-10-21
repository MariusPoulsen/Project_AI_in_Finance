"""Decision 96: portfolio construction under per-stock costs."""
import sys, json, math, pandas as pd
from pathlib import Path
from structural_break.experiments import p6_quant_portfolio as qp, p6_quant_costs as qc
from structural_break.experiments.p6_improvement import _sources
capital = float(sys.argv[1]) if len(sys.argv) > 1 else 1e7
only = sys.argv[2:] or None
sectors = _sources(Path("data/team")).security_sectors()
cache = qp.load_cache(Path("outputs/p6_quant/requests.pkl"))
prices = pd.read_parquet("data/team/market/source_v1/prices.parquet", columns=["ticker", "trading_date", "open", "high", "low", "close", "adj_close", "volume"])
table = qc.lookup(qc.stock_inputs(prices))
sel = pd.read_parquet("outputs/p6_quant/select__m1.parquet")
chosen = [e for e in sel.loc[sel.top20 & sel.year.between(2010, 2023), "event_id"] if e in cache]
designs = {"N-25": (0.25, None), "N-10": (0.10, None), "N-5": (0.05, None), "N-10s": (0.10, 0.30), "N-5s": (0.05, 0.30)}
out_dir = Path("outputs/p6_quant/portfolio_n"); out_dir.mkdir(parents=True, exist_ok=True)
summary = {}
for name, (target, cap) in designs.items():
    if only and name not in only: continue
    out = qp.run_design(cache, chosen, (1.0, 5.0, 20, True), Path("configs"), target, sectors, table, capital, cap)
    m = out["marks"]; m = m[m.nav.notna()].copy(); m["y"] = pd.to_datetime(m.session_date).dt.year
    row = {}
    for label, (a, b) in (("2010-2017", (2010, 2017)), ("2018-2023", (2018, 2023)), ("2010-2023", (2010, 2023))):
        r = m[m.y.between(a, b)].daily_return.astype(float); nav = (1 + r).cumprod()
        row[label] = {"sharpe": r.mean() / r.std() * math.sqrt(252), "cagr": nav.iloc[-1] ** (252 / len(r)) - 1, "maxdd": (nav / nav.cummax() - 1).min()}
    summary[name] = row
    m.to_parquet(out_dir / f"nav_{name}_{int(capital)}.parquet", index=False)
    show = ["2010-2017"] if "--select" in sys.argv else list(row)
    print(name, int(capital), {k: {x: round(v, 4) for x, v in row[k].items()} for k in row if k in show or True and k == "2010-2017"}, flush=True)
json.dump(summary, open(out_dir / f"summary_{int(capital)}.json", "w"), indent=1)
