"""Decision 97: probability of backtest overfitting (CSCV) and deflated Sharpe ratio."""
import itertools, math, pandas as pd, numpy as np
from pathlib import Path
from scipy.stats import norm, skew, kurtosis
from structural_break.experiments import p6_boosting as pb
frame, _ = pb.load_data(Path("data/team"), Path("outputs/p6_improvement/walkforward/simulation_frozen_exit.parquet"))
month = frame.set_index("event_id")["event_date"].map(lambda d: str(d)[:7])
year = pd.to_datetime(frame.set_index("event_id")["event_date"]).dt.year
series = {}
def add(name, selected, net):
    common = selected.index.intersection(net.dropna().index)
    common = common[year.reindex(common).between(2010, 2023).to_numpy()]
    alloc = net[common].where(selected[common], 0.0)
    series[name] = alloc.groupby(month.reindex(common).to_numpy()).mean()
grid = pd.read_parquet("outputs/p6_quant/exit_grid.parquet").set_index("event_id")
ra = pd.read_parquet("outputs/p6_quant/scores__B__d45.parquet").set_index("event_id")["top20"]
for c in [c[:-4] for c in grid.columns if c.endswith("|net")]:
    add(f"exit:{c}", ra, grid[f"{c}|net"].where(grid[f"{c}|status"].eq("COMPLETE")).astype(float))
tp = pd.read_parquet("outputs/p6_quant/tp_extend.parquet").set_index("event_id")
for c in [c for c in tp.columns if c[0].isdigit()]:
    add(f"tp:{c}", tp["selected"], tp[c].astype(float))
adopted = pd.read_parquet("outputs/p6_quant/adopted_exit_net.parquet").set_index("event_id")["net"]
for tag in ("c2a", "ha", "hb", "ka", "la", "gb", "gc", "gd", "ge", "fa", "fb", "m1", "m2"):
    s = pd.read_parquet(f"outputs/p6_quant/select__{tag}.parquet").set_index("event_id")["top20"]
    add(f"sel:{tag}", s, adopted)
M = pd.DataFrame(series).sort_index().dropna(how="any")
print("trial matrix", M.shape)
# CSCV
blocks = np.array_split(np.arange(len(M)), 14)
sr = lambda X: X.mean() / X.std(ddof=1)
lam = []
for combo in itertools.combinations(range(14), 7):
    ins = np.concatenate([blocks[i] for i in combo]); oos = np.setdiff1d(np.arange(len(M)), ins)
    best = sr(M.iloc[ins]).idxmax()
    ranks = sr(M.iloc[oos]).rank()
    w = ranks[best] / (M.shape[1] + 1)
    lam.append(math.log(w / (1 - w)))
lam = np.array(lam); print("PBO %.3f (median logit %.2f)" % ((lam <= 0).mean(), np.median(lam)))
trial_sr = sr(M); V = trial_sr.var(ddof=1)
print("trial monthly SR: mean %.3f sd %.3f max %.3f (annualised max %.2f)" % (trial_sr.mean(), math.sqrt(V), trial_sr.max(), trial_sr.max() * math.sqrt(12)))
g = 0.5772156649
def dsr(r, N):
    T = len(r); s = r.mean() / r.std(ddof=1); g3 = skew(r); g4 = kurtosis(r, fisher=False)
    sr0 = math.sqrt(V) * ((1 - g) * norm.ppf(1 - 1 / N) + g * norm.ppf(1 - 1 / (N * math.e)))
    z = (s - sr0) * math.sqrt(T - 1) / math.sqrt(1 - g3 * s + (g4 - 1) / 4 * s * s)
    return s, sr0, norm.cdf(z), g3, g4
hb = series["sel:hb"].reindex(M.index)
nav = pd.read_parquet("outputs/p6_quant/portfolio_n/nav_N-5_10000000.parquet"); nav = nav[nav.nav.notna()]
port = nav.assign(m=pd.to_datetime(nav.session_date).dt.strftime("%Y-%m")).groupby("m").daily_return.apply(lambda s: float(np.prod(1 + s.astype(float)) - 1))
for label, r in (("H-b per-candidate (flat costs)", hb.to_numpy()), ("N-5 portfolio at $10m (per-stock costs)", port.to_numpy())):
    for N in (50, 150, 300):
        s, sr0, p, g3, g4 = dsr(r, N)
        print(f"{label:42s} N={N:3d} SR monthly {s:.3f} (annual {s*math.sqrt(12):.2f}) SR0 {sr0:.3f} DSR {p:.3f} skew {g3:.2f} kurt {g4:.2f}")
