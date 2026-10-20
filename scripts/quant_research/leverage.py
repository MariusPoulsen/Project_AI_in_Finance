import pandas as pd, math
from pathlib import Path
from structural_break.experiments import p6_quant_portfolio as qp, p6_portfolio as pp
from structural_break.backtest import production_policy as ppol
from structural_break.experiments.p6_improvement import _sources
sectors = _sources(Path("data/team")).security_sectors()
cache = qp.load_cache(Path("outputs/p6_quant/requests.pkl"))
sel = pd.read_parquet("outputs/p6_quant/select__c2a.parquet")
chosen = [e for e in sel.loc[sel.top20 & sel.year.between(2010, 2023), "event_id"] if e in cache]
base = ppol.load_analysis_policies(Path("configs"))
for cap, target in ((1.0, 0.25), (1.5, 0.375), (2.0, 0.5)):
    pol = base.portfolio.model_copy(update={"gross_entry_cap": cap})
    an = base.model_copy(update={"portfolio": pol})
    qp.load_analysis_policies = lambda _p, an=an: an
    out = qp.run_design(cache, chosen, (1.0, 5.0, 20, True), Path("configs"), target, sectors)
    f = out["stats"]["full"]
    print(f"gross cap {cap:.1f} target {target:.3f}: CAGR {f['cagr']:+.2%} vol {f['volatility']:.2%} Sharpe {f['sharpe']:+.2f} maxDD {f['max_drawdown']:.1%} total {f['total_return']:+.1%} mean gross {f['mean_gross_fraction']:.2f}")
