"""Decision 101: residual-reversal sleeve, ETF/PCA x bands/continuous (prints 2010-2017 unless --holdout)."""
import sys, json, pandas as pd, numpy as np
from pathlib import Path
from structural_break.book import residual_sleeve as pr
from structural_break.pipeline.sources import _sources
out_dir = Path("outputs/p6_quant/stage_q"); out_dir.mkdir(parents=True, exist_ok=True)
blocks = (("2010-2017", 2010, 2017),) + ((("2018-2023", 2018, 2023), ("2010-2023", 2010, 2023)) if "--holdout" in sys.argv else ())
if "--holdout" in sys.argv and (out_dir / "summary.json").exists():
    summary = json.load(open(out_dir / "summary.json"))
    for name in summary:
        book = pd.read_parquet(out_dir / f"book_{name}.parquet")
        for label, a, b in blocks:
            v, c = pr.stats(book, a, b), pr.stats(book, a, b, cash=True)
            print(f"{name:16s} {label}: Sharpe {v['sharpe']:+.2f} CAGR {v['cagr']:+.2%} (+cash {c['cagr']:+.2%}) maxDD {v['maxdd']:.1%} vol {v['vol']:.1%}")
    sys.exit()
sectors = _sources(Path("data/team")).security_sectors()
prices = pd.read_parquet("data/team/market/source_v1/prices.parquet", columns=["ticker", "trading_date", "open", "high", "low", "close", "adj_close", "volume"])
panels = pr.load_panels(prices, sectors)
rf = pr.tbill(Path("data/external/irx_13w_tbill.csv"))
start = int(np.searchsorted(panels.dates, pd.Timestamp("2009-06-01")))
summary = {}
for model in ("etf", "pca"):
    s, kappa, beta = pr.signals(panels, model, start)
    np.savez_compressed(out_dir / f"signals_{model}.npz", s=s, kappa=kappa, beta=beta)
    for rule in ("bands", "continuous"):
        name = f"{model}_{rule}"
        w = pr.targets(panels, s, kappa, beta, rule)
        np.save(out_dir / f"targets_{name}.npy", w)
        book = pr.run_book(panels, w, [], pd.Timestamp("2010-01-01"), pd.Timestamp("2023-12-31"), rf=rf)
        book.to_parquet(out_dir / f"book_{name}.parquet", index=False)
        v = pr.stats(book, 2010, 2017)
        gross_r = book.daily_return - book.interest + book.cost
        years = pd.to_datetime(book.session_date).dt.year.between(2010, 2017)
        g = gross_r[years]
        v["gross_sharpe"] = float(g.mean() / g.std() * np.sqrt(252))
        summary[name] = {"2010-2017": v}
        print(f"{name:16s} 2010-2017: Sharpe {v['sharpe']:+.2f} (before costs {v['gross_sharpe']:+.2f}) CAGR {v['cagr']:+.2%} maxDD {v['maxdd']:.1%} vol {v['vol']:.1%} | turnover {v['turnover']:.0f}x/yr cost {v['cost']:.2%}/yr names {v['names']:.0f}", flush=True)
json.dump(summary, open(out_dir / "summary.json", "w"), indent=1)
