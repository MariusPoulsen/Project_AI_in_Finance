import pickle, sys, math, pandas as pd, numpy as np
from pathlib import Path
from structural_break.backtest.production_policy import load_headline
from structural_break.experiments import p6_quant_trading as qt, p6_boosting as pb
h = load_headline(Path("configs")); cache = pickle.load(open("outputs/p6_quant/requests.pkl", "rb"))
frame, _ = pb.load_data(Path("data/team"), Path("outputs/p6_improvement/walkforward/simulation_frozen_exit.parquet"))
f = frame[pd.to_datetime(frame.event_date).dt.year.between(2010, 2023)][["event_id", "event_date", "spread_std", "beta"]].copy()
net = {}
for e in f.event_id:
    if e in cache:
        r, fr, m = cache[e]; st, n, _, _ = qt.exit_loop(r, fr, h, 1.0, 5.0, 20, m)
        if st == "COMPLETE": net[e] = n
f["net"] = f.event_id.map(net); f["scale"] = f.spread_std / (1 + f.beta.abs())
f["year"] = pd.to_datetime(f.event_date).dt.year
f.to_parquet("outputs/p6_quant/adopted_exit_net.parquet", index=False)
r1 = set(pd.read_parquet("outputs/p6_quant/r1_events.parquet").event_id)
for tag, src in (("fa", "scores__B+rule+ou__recent"), ("fb", "scores__B__d45")):
    s = f.merge(pd.read_parquet(f"outputs/p6_quant/{src}.parquet")[["event_id", "raw"]], on="event_id")
    s["ev"] = np.nan
    for Y in range(2011, 2024):
        tr = s[(s.year < Y) & s.net.notna()]
        y = (tr.net / tr.scale).clip(*(tr.net / tr.scale).quantile([0.01, 0.99]))
        b, a = np.polyfit(tr.raw, y, 1)
        cur = s.year.isin([Y - 1, Y])
        s.loc[cur & s.year.eq(Y), "ev"] = s.loc[cur & s.year.eq(Y), "scale"] * (a + b * s.loc[cur & s.year.eq(Y), "raw"])
        prev = s[s.year.eq(Y - 1)]
        prev_ev = prev.scale * (a + b * prev.raw)
        s.loc[s.year.eq(Y), "cut"] = np.quantile(prev_ev, 0.8)
        print(tag, Y, "a %+.3f b %+.3f" % (a, b))
    s["top20"] = (s.ev >= s.cut) & ~s.event_id.isin(r1) & s.year.ge(2011)
    s[["event_id", "year", "top20"]].to_parquet(f"outputs/p6_quant/select__{tag}.parquet", index=False)
