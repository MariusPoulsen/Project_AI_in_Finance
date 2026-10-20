import argparse, pandas as pd
from pathlib import Path
from structural_break.experiments import p6_quant as pq
args = pq.parser().parse_args(["run"])
frame, base, exits = pq.load(args)
grid = pd.read_parquet("outputs/p6_quant/exit_grid.parquet")
col = pq.ADOPTED_EXIT
g = grid[["event_id", f"{col}|status", f"{col}|net"]]
g = g.assign(target=g[f"{col}|net"].where(g[f"{col}|status"].eq("COMPLETE")).astype(float))
frame = frame.merge(g[["event_id", "target"]], on="event_id", how="left")
sets = pq.feature_sets(base, list(frame.columns))
scored = pq.run_return_spec(frame, sets["B+rule"], "target")
scored.to_parquet("outputs/p6_quant/returns__B+rule__recent.parquet", index=False)
print("done", len(scored))
