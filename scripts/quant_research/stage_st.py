"""Decisions 106-107: risk targeting (stage S) and close execution (stage T) on the Decision 105 book.

Usage: stage_st.py S|T [--base VT60|VT20|none] [--holdout]   (prints 2010-2017 unless --holdout)
"""
import sys, json, pickle, pandas as pd, numpy as np
from pathlib import Path
from structural_break.experiments import p6_resid as pr
from structural_break.experiments.p6_improvement import _sources
stage = sys.argv[1]
holdout = "--holdout" in sys.argv
out_dir = Path(f"outputs/p6_quant/stage_{stage.lower()}"); out_dir.mkdir(parents=True, exist_ok=True)
blocks = (("2010-2017", 2010, 2017),) + ((("2018-2023", 2018, 2023), ("2010-2023", 2010, 2023)) if holdout else ())


def show(name, book):
    for label, a, b in blocks:
        v, c = pr.stats(book, a, b), pr.stats(book, a, b, cash=True)
        years = pd.to_datetime(book.session_date).dt.year.between(a, b)
        print(f"{name:16s} {label}: Sharpe {v['sharpe']:+.3f} CAGR {v['cagr']:+.2%} (+cash {c['cagr']:+.2%}) maxDD {v['maxdd']:.1%} vol {v['vol']:.1%} gross mean {v['gross']:.2f} max {book.gross[years].max():.2f} cost {v['cost']:.2%}/yr", flush=True)


if holdout:
    for name in json.load(open(out_dir / "summary.json")):
        show(name, pd.read_parquet(out_dir / f"book_{name}.parquet"))
    sys.exit()
sectors = _sources(Path("data/team")).security_sectors()
prices = pd.read_parquet("data/team/market/source_v1/prices.parquet", columns=["ticker", "trading_date", "open", "high", "low", "close", "adj_close", "volume"])
panels = pr.load_panels(prices, sectors)
rf = pr.tbill(Path("data/external/irx_13w_tbill.csv"))
legs = pickle.load(open("outputs/p6_quant/pairs_legs.pkl", "rb"))
w = np.load("outputs/p6_quant/stage_q/targets_pca_continuous.npy") * 0.25
common = {"capital": 1e7, "rf": rf, "speed": 0.10}
first, last = pd.Timestamp("2010-01-01"), pd.Timestamp("2023-12-31")
risk = {"none": {}, "VT60": {"vol_target": 0.04, "vol_window": 60}, "VT20": {"vol_target": 0.04, "vol_window": 20}}
if stage == "S":
    variants = {name: dict(timing="open", **kw) for name, kw in risk.items()}
else:
    base = risk[sys.argv[sys.argv.index("--base") + 1]]
    variants = {"open": dict(timing="open", **base), "C-close": dict(timing="close", **base), "C-close+2bps": dict(timing="close", extra_bps=2.0, **base)}
summary = {}
for name, kw in variants.items():
    book = pr.run_book(panels, w, legs[kw["timing"]], first, last, **common, **kw)
    book.to_parquet(out_dir / f"book_{name}.parquet", index=False)
    summary[name] = {"2010-2017": pr.stats(book, 2010, 2017)}
    show(name, book)
json.dump(summary, open(out_dir / "summary.json", "w"), indent=1)
