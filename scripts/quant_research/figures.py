import json, numpy as np, pandas as pd, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path
from sklearn.metrics import roc_curve, roc_auc_score
from structural_break.experiments import p6_boosting as pb
out = Path("docs/figures/quant")
frame, _ = pb.load_data(Path("data/team"), Path("outputs/p6_improvement/walkforward/simulation_frozen_exit.parquet"))
info = frame[["event_id", "supervised_eligible", "y_revert_success"]]
specs = {"Original Model B": "B__d45", "Goal 1 model (+OU, bagged)": "B+rule+ou__recent-bag5", "Best observed (+track, bagged)": "B+rule+ou+track__recent-bag5"}
data = {}
for label, n in specs.items():
    s = pd.read_parquet(f"outputs/p6_quant/scores__{n}.parquet").merge(info, on="event_id")
    data[label] = s[s.supervised_eligible.eq(True) & s.y_revert_success.notna() & s.year.between(2018, 2023)].set_index("event_id")
common = set.intersection(*[set(d.index) for d in data.values()])
fig, ax = plt.subplots(figsize=(5.5, 5))
for label, d in data.items():
    d = d.loc[sorted(common)]; f, t, _ = roc_curve(d.y_revert_success, d.raw)
    ax.plot(f, t, label=f"{label} (AUC {roc_auc_score(d.y_revert_success, d.raw):.3f})")
ax.plot([0, 1], [0, 1], "k--", lw=0.8); ax.set_xlabel("False positive rate"); ax.set_ylabel("True positive rate")
ax.set_title("Reversion forecast, holdout 2018–2023"); ax.legend(fontsize=8, loc="lower right"); fig.tight_layout(); fig.savefig(out / "goal1_roc_holdout.png", dpi=150)
fig, ax = plt.subplots(figsize=(5.5, 5))
for label in ("Original Model B", "Goal 1 model (+OU, bagged)"):
    d = data[label].loc[sorted(common)]; d["bin"] = pd.qcut(d.probability.rank(method="first"), 10, labels=False)
    g = d.groupby("bin").agg(p=("probability", "mean"), y=("y_revert_success", "mean"))
    ax.plot(g.p, g.y, "o-", label=label)
lim = max(ax.get_xlim()[1], ax.get_ylim()[1]); ax.plot([0, lim], [0, lim], "k--", lw=0.8)
ax.set_xlabel("Predicted reversion probability (decile mean)"); ax.set_ylabel("Observed reversion rate"); ax.set_title("Calibration, holdout 2018–2023"); ax.legend(fontsize=8); fig.tight_layout(); fig.savefig(out / "goal1_calibration_holdout.png", dpi=150)
curves = {"Trade every divergence, frozen exit": "outputs/p6_portfolio/nav_P0_baseline0_frozen_frozen_25pct.parquet",
          "Model B + news exit (Decision 73)": "outputs/p6_quant/portfolio/nav_D73_ra_e3_frozen_25pct.parquet",
          "Programme design": "outputs/p6_quant/portfolio_h/nav_H_b_nocross120_frozen_25pct.parquet"}
fig, ax = plt.subplots(figsize=(8, 4.5))
for label, path in curves.items():
    m = pd.read_parquet(path); m = m[m.nav.notna()]
    ax.plot(pd.to_datetime(m.session_date), m.nav, label=label)
ax.axvline(pd.Timestamp("2018-01-01"), color="grey", ls=":", lw=1); ax.text(pd.Timestamp("2018-02-01"), ax.get_ylim()[1] * 0.98, "holdout →", fontsize=8, va="top")
ax.axhline(1.0, color="k", lw=0.6); ax.set_ylabel("Portfolio value (start 1.0)"); ax.set_title("Portfolio value, 2010–2023 (frozen policy, 25 % per entry, gross ≤ 100 %)"); ax.legend(fontsize=8); fig.tight_layout(); fig.savefig(out / "goal2_equity_curves.png", dpi=150)
print("ok")
