"""Decision 104: slower PCA residual sleeve (prints 2010-2017 unless --holdout)."""
import sys, json, pandas as pd, numpy as np
from pathlib import Path
from structural_break.experiments import p6_resid as pr
from structural_break.experiments.p6_improvement import _sources
q_dir = Path("outputs/p6_quant/stage_q"); out_dir = Path("outputs/p6_quant/stage_q2"); out_dir.mkdir(parents=True, exist_ok=True)
holdout = "--holdout" in sys.argv
blocks = (("2010-2017", 2010, 2017),) + ((("2018-2023", 2018, 2023), ("2010-2023", 2010, 2023)) if holdout else ())


def show(name, book):
    for label, a, b in blocks:
        v, c = pr.stats(book, a, b), pr.stats(book, a, b, cash=True)
        years = pd.to_datetime(book.session_date).dt.year.between(a, b)
        g = (book.daily_return - book.interest + book.cost)[years]
        print(f"{name:22s} {label}: Sharpe {v['sharpe']:+.2f} (before costs {g.mean() / g.std() * np.sqrt(252):+.2f}) CAGR {v['cagr']:+.2%} (+cash {c['cagr']:+.2%}) maxDD {v['maxdd']:.1%} vol {v['vol']:.1%} | turnover {v['turnover']:.0f}x cost {v['cost']:.2%}/yr", flush=True)


if holdout:
    for name in json.load(open(out_dir / "summary.json")):
        show(name, pd.read_parquet(out_dir / f"book_{name}.parquet"))
    sys.exit()
sectors = _sources(Path("data/team")).security_sectors()
prices = pd.read_parquet("data/team/market/source_v1/prices.parquet", columns=["ticker", "trading_date", "open", "high", "low", "close", "adj_close", "volume"])
panels = pr.load_panels(prices, sectors)
rf = pr.tbill(Path("data/external/irx_13w_tbill.csv"))
controls = {"W5": {"every": 5}, "W21": {"every": 21}, "S10": {"speed": 0.10}}
summary = {}
for rule in ("bands", "continuous"):
    w = np.load(q_dir / f"targets_pca_{rule}.npy")
    for label, kwargs in controls.items():
        name = f"pca_{rule}_{label}"
        book = pr.run_book(panels, w, [], pd.Timestamp("2010-01-01"), pd.Timestamp("2023-12-31"), rf=rf, **kwargs)
        book.to_parquet(out_dir / f"book_{name}.parquet", index=False)
        summary[name] = {"2010-2017": pr.stats(book, 2010, 2017)}
        show(name, book)
json.dump(summary, open(out_dir / "summary.json", "w"), indent=1)
