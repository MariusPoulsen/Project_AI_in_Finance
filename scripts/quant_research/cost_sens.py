import pandas as pd, math
from pathlib import Path
from structural_break.experiments import p6_quant_portfolio as qp
from structural_break.backtest import production_policy as ppol
from structural_break.experiments.p6_improvement import _sources
base = ppol.load_headline(Path("configs"))
sectors = _sources(Path("data/team")).security_sectors()
cache = qp.load_cache(Path("outputs/p6_quant/requests.pkl"))
sel = pd.read_parquet("outputs/p6_quant/select__c2a.parquet")
chosen = [e for e in sel.loc[sel.top20 & sel.year.between(2010, 2023), "event_id"] if e in cache]
for label, upd in (("costs x0.5", {"entry_cost_bps": 2.5, "exit_cost_bps": 2.5}), ("costs x2", {"entry_cost_bps": 10.0, "exit_cost_bps": 10.0}), ("borrow 2%", {"annual_borrow_rate": 0.02})):
    cfg = base.model_copy(update=upd)
    qp.load_headline = lambda _p, cfg=cfg: cfg
    out = qp.run_design(cache, chosen, (1.0, 5.0, 20, True), Path("configs"), 0.25, sectors)
    f = out["stats"]["full"]
    print(f"{label:12s} CAGR {f['cagr']:+.2%} Sharpe {f['sharpe']:+.2f} maxDD {f['max_drawdown']:.1%}", {k: round(v["sharpe"], 2) for k, v in out["stats"]["periods"].items()})
