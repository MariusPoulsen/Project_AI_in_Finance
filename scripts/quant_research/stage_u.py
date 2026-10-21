"""Decision 108: hard 200 % gross cap and closing-auction checks on the Decision 107 book.

Usage: stage_u.py [--holdout]   (prints 2010-2017 unless --holdout)
"""
import sys, json, pickle, pandas as pd, numpy as np
from pathlib import Path
from structural_break.experiments import p6_resid as pr
from structural_break.experiments.p6_improvement import _sources
holdout = "--holdout" in sys.argv
out_dir = Path("outputs/p6_quant/stage_u"); out_dir.mkdir(parents=True, exist_ok=True)
blocks = (("2010-2017", 2010, 2017),) + ((("2018-2023", 2018, 2023), ("2010-2023", 2010, 2023)) if holdout else ())


def show(name, book):
    for label, a, b in blocks:
        v, c = pr.stats(book, a, b), pr.stats(book, a, b, cash=True)
        years = pd.to_datetime(book.session_date).dt.year.between(a, b)
        print(f"{name:14s} {label}: Sharpe {v['sharpe']:+.3f} CAGR {v['cagr']:+.2%} (+cash {c['cagr']:+.2%}) maxDD {v['maxdd']:.1%} gross mean {v['gross']:.2f} max {book.gross[years].max():.2f} capped days {(book.room[years] < 1).sum()} cost {v['cost']:.2%}/yr", flush=True)


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
common = {"capital": 1e7, "rf": rf, "speed": 0.10, "vol_target": 0.04, "vol_window": 60}
first, last = pd.Timestamp("2010-01-01"), pd.Timestamp("2023-12-31")
variants = {
    "D107": dict(timing="close"),
    "cap200": dict(timing="close", max_gross=2.0),
    "cap200-open": dict(timing="open", max_gross=2.0),
    **{f"cap200+{x}bps": dict(timing="close", max_gross=2.0, extra_bps=x) for x in (0.5, 1.0, 1.5, 2.0)},
}
books, summary = {}, {}
for name, kw in variants.items():
    books[name] = pr.run_book(panels, w, legs[kw["timing"]], first, last, **common, **kw)
split = books["cap200"].copy()
other = books["cap200-open"].set_index("session_date").reindex(split.session_date)
for c in ("daily_return", "interest", "cost", "turnover", "gross"):
    split[c] = 0.5 * (split[c].to_numpy() + other[c].to_numpy())
split["room"] = np.minimum(split["room"].to_numpy(), other["room"].to_numpy())
books["split-50/50"] = split
for name, book in books.items():
    book.to_parquet(out_dir / f"book_{name.replace('/', '-')}.parquet", index=False)
    summary[name.replace("/", "-")] = {"2010-2017": pr.stats(book, 2010, 2017)}
    show(name, book)
json.dump(summary, open(out_dir / "summary.json", "w"), indent=1)
