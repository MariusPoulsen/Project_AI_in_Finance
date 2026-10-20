import sys, pandas as pd, numpy as np
from pathlib import Path
from structural_break.experiments import p6_boosting as pb
from structural_break.ml.model import fit_sigmoid
spec = sys.argv[1]; years = (int(sys.argv[2]), int(sys.argv[3]))
frame, _ = pb.load_data(Path("data/team"), Path("outputs/p6_improvement/walkforward/simulation_frozen_exit.parquet"))
info = frame[["event_id", "event_date", "horizon_end_date", "supervised_eligible", "y_revert_success"]]
s = pd.read_parquet(f"outputs/p6_quant/scores__{spec}.parquet").merge(info, on="event_id")
s["lab"] = s.supervised_eligible.eq(True) & s.y_revert_success.notna()
lg = pb._logit
out = {"I-0": s.probability.copy(), "I-1": pd.Series(np.nan, index=s.index), "I-2": pd.Series(np.nan, index=s.index)}
for Y in range(2011, 2024):
    for name, back in (("I-1", 1), ("I-2", 2)):
        tr = s[s.year.between(Y - back, Y - 1) & s.lab & pd.to_datetime(s.horizon_end_date).lt(pd.Timestamp(Y, 1, 1))]
        cal = fit_sigmoid(lg(tr.raw.to_numpy()), tr.y_revert_success)
        idx = s.index[s.year.eq(Y)]
        out[name].loc[idx] = cal.predict(lg(s.loc[idx, "raw"].to_numpy()))
keep = s.year.between(*years) & s.lab
y = s.loc[keep, "y_revert_success"].to_numpy()
for name, p in out.items():
    q = np.clip(p[keep].to_numpy(), 1e-12, 1 - 1e-12)
    print(f"{spec} {years} {name}: log loss {-(y*np.log(q)+(1-y)*np.log(1-q)).mean():.5f} Brier {np.mean((q-y)**2):.5f}")
pd.DataFrame({"event_id": s.event_id, **{k: v for k, v in out.items()}}).to_parquet(f"outputs/p6_quant/recal__{spec}.parquet", index=False)
