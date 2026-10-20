import sys, pickle, math, pandas as pd, numpy as np
from pathlib import Path
from structural_break.backtest.production_policy import load_headline
from structural_break.experiments import p6_quant_trading as qt, p6_boosting as pb
years = (int(sys.argv[1]), int(sys.argv[2])); files = sys.argv[3:]
headline = load_headline(Path("configs"))
cache = pickle.load(open("outputs/p6_quant/requests.pkl", "rb"))
frame, _ = pb.load_data(Path("data/team"), Path("outputs/p6_improvement/walkforward/simulation_frozen_exit.parquet"))
months = frame.set_index("event_id")["event_date"].map(lambda d: str(d)[:7])
cand = frame.loc[pd.to_datetime(frame.event_date).dt.year.between(*years), "event_id"]
net = {}
for e in cand:
    if e not in cache: continue
    req, frozen, moments = cache[e]
    st, n, h, r = qt.exit_loop(req, frozen, headline, 1.0, 5.0, 20, moments)
    if st == "COMPLETE": net[e] = n
net = pd.Series(net)
for f in files:
    s = pd.read_parquet(f).set_index("event_id")
    sel = s.loc[s.index.intersection(net.index), "top20"]
    alloc = net[sel.index].where(sel, 0.0)
    m = alloc.groupby(sel.index.map(months)).mean()
    t = net[sel.index[sel.to_numpy()]]
    print(f"{Path(f).stem:28s} {years} trades {len(t)} per trade {t.mean()*1e4:+6.1f} median {t.median()*1e4:+6.1f} per cand {alloc.mean()*1e4:+5.2f} Sharpe {m.mean()/m.std()*math.sqrt(12):+.2f}")
