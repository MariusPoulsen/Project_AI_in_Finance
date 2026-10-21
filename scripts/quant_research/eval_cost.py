"""Per-candidate evaluation of selection files with a given net column of cost_model_nets."""
import sys, math, pandas as pd
from pathlib import Path
from structural_break.experiments import p6_boosting as pb
years = (int(sys.argv[1]), int(sys.argv[2])); column = sys.argv[3]; files = sys.argv[4:]
frame, _ = pb.load_data(Path("data/team"), Path("outputs/p6_improvement/walkforward/simulation_frozen_exit.parquet"))
months = frame.set_index("event_id")["event_date"].map(lambda d: str(d)[:7])
nets = pd.read_parquet("outputs/p6_quant/cost_model_nets.parquet").set_index("event_id")
net = nets[column].dropna()
cand = set(frame.loc[pd.to_datetime(frame.event_date).dt.year.between(*years), "event_id"])
net = net[net.index.isin(cand)]
for f in files:
    s = pd.read_parquet(f).set_index("event_id")
    sel = s.loc[s.index.intersection(net.index), "top20"]
    alloc = net[sel.index].where(sel, 0.0)
    m = alloc.groupby(sel.index.map(months)).mean()
    t = net[sel.index[sel.to_numpy()]]
    print(f"{Path(f).stem:20s} {column:9s} {years} trades {len(t)} per trade {t.mean()*1e4:+6.1f} per cand {alloc.mean()*1e4:+5.2f} Sharpe {m.mean()/m.std()*math.sqrt(12):+.2f}")
