import sys, pandas as pd, numpy as np, math
from pathlib import Path
from structural_break.experiments import p6_boosting as pb
years = (int(sys.argv[1]), int(sys.argv[2]))
grid = pd.read_parquet("outputs/p6_quant/exit_grid.parquet")
frame, _ = pb.load_data(Path("data/team"), Path("outputs/p6_improvement/walkforward/simulation_frozen_exit.parquet"))
months = frame.set_index("event_id")["event_date"].map(lambda d: str(d)[:7])
ch = "b1_snone_t20_news"
files = {"R-a B d45": "scores__B__d45", "R-b B+rule": "scores__B+rule__recent", "R-c return model": "returns__B+rule__recent"}
for label, f in files.items():
    s = pd.read_parquet(f"outputs/p6_quant/{f}.parquet").merge(grid[["event_id", f"{ch}|status", f"{ch}|net"]], on="event_id")
    s = s[s[f"{ch}|status"].eq("COMPLETE") & s.year.between(*years)]
    s["month"] = s.event_id.map(months)
    alloc = np.where(s["top20"], s[f"{ch}|net"].astype(float), 0.0)
    m = pd.Series(alloc).groupby(s["month"].to_numpy()).mean()
    t = s.loc[s["top20"], f"{ch}|net"].astype(float)
    print(f"{label:18s} {years} trades {len(t)} per trade {t.mean()*1e4:+6.1f} bps median {t.median()*1e4:+6.1f} per cand {alloc.mean()*1e4:+5.2f} Sharpe {m.mean()/m.std()*math.sqrt(12):+.2f}")
