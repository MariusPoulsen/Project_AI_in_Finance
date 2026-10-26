import pandas as pd, numpy as np, math, sys
from pathlib import Path
from structural_break.experiments import p6_boosting as pb
frame, _ = pb.load_data(Path("data/team"), Path("outputs/p6_improvement/walkforward/simulation_frozen_exit.parquet"))
ou = pd.read_parquet("outputs/p6_quant/ou_features.parquet")
f = frame.merge(ou, on="event_id", how="left")
year = pd.to_datetime(f.event_date).dt.year
# The OU-alone forecaster (Decision 85) was erased in the Decision 114 cleanup.
# Goal 2 candidate selections (exclude R1, as in C2-a)
c2a = pd.read_parquet("outputs/p6_quant/select__c2a.parquet")
r1_removed = pd.read_parquet("outputs/p6_quant/scores__B__d45.parquet")[["event_id", "top20"]].merge(c2a, on="event_id", suffixes=("_ra", ""))
r1 = set(r1_removed.loc[r1_removed.top20_ra & ~r1_removed.top20, "event_id"])
ev_cut = {Y: np.nanquantile(f.loc[year.eq(Y - 1), "ou_ev_bps"], 0.8) for Y in range(2010, 2024)}
tp_med = {Y: np.nanquantile(f.loc[year.eq(Y - 1), "ou_p_tp"], 0.5) for Y in range(2010, 2024)}
g = f[year.between(2010, 2023)][["event_id", "ou_ev_bps", "ou_p_tp"]].assign(year=year)
g["gb"] = (g.ou_ev_bps >= g.year.map(ev_cut)) & ~g.event_id.isin(r1)
gc = c2a.merge(g[["event_id", "ou_p_tp"]], on="event_id", how="left")
gc["top20"] = gc.top20 & (gc.ou_p_tp >= gc.year.map(tp_med))
g[["event_id", "year"]].assign(top20=g.gb).to_parquet("outputs/p6_quant/select__gb.parquet", index=False)
gc[["event_id", "year", "top20"]].to_parquet("outputs/p6_quant/select__gc.parquet", index=False)
print("built; G-b trades", int(g.gb.sum()), "G-c trades", int(gc.top20.sum()), "G-a trades", int(c2a.top20.sum()))
