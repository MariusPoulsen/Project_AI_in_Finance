import sys, pickle, math, json, itertools, pandas as pd, numpy as np
from pathlib import Path
from structural_break.backtest.production_policy import load_headline
from structural_break.experiments import p6_quant_trading as qt, p6_boosting as pb
headline = load_headline(Path("configs"))
cache = pickle.load(open("outputs/p6_quant/requests.pkl", "rb"))
sel = pd.read_parquet("outputs/p6_quant/select__c2a.parquet")
frame, _ = pb.load_data(Path("data/team"), Path("outputs/p6_improvement/walkforward/simulation_frozen_exit.parquet"))
months = frame.set_index("event_id")["event_date"].map(lambda d: str(d)[:7])
variants = list(itertools.product((1.0, 1.25, 1.5), (5.0, 99.0)))
rows = []
for r in sel.itertuples():
    if r.event_id not in cache: continue
    req, frozen, moments = cache[r.event_id]
    row = {"event_id": r.event_id, "year": r.year, "selected": r.top20, "month": months[r.event_id]}
    for band, stop in variants:
        st, net, hold, reason = qt.exit_loop(req, frozen, headline, band, stop, 20, moments)
        row[f"{band}_{stop}"] = net if st == "COMPLETE" else np.nan
    rows.append(row)
d = pd.DataFrame(rows)
d.to_parquet("outputs/p6_quant/tp_extend.parquet", index=False)
cols = [f"{b}_{s}" for b, s in variants]
d = d.dropna(subset=cols)
years = (int(sys.argv[1]), int(sys.argv[2]))
x = d[d.year.between(*years)]
for c in cols:
    alloc = np.where(x.selected, x[c], 0.0); m = pd.Series(alloc).groupby(x.month.to_numpy()).mean()
    print(years, c, "per trade %+.1f" % (x.loc[x.selected, c].mean() * 1e4), "per cand %+.2f" % (alloc.mean() * 1e4), "SR %+.2f" % (m.mean() / m.std() * math.sqrt(12)))
