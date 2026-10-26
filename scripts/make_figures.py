from typing import Any, cast

import matplotlib
import pandas as pd

matplotlib.use("Agg")
from pathlib import Path

import matplotlib.pyplot as plt
from sklearn.metrics import roc_auc_score, roc_curve

from structural_break.forecast import model_b as pb

out = Path("docs/figures/quant")
frame, _ = pb.load_data(
    Path("data/team"), Path("outputs/walkforward/simulation_frozen_exit.parquet")
)
info = frame[["event_id", "supervised_eligible", "y_revert_success"]]
specs = {
    "Original Model B": "B__d45",
    "Goal 1 model (+OU, bagged)": "B+rule+ou__recent-bag5",
    "Best observed (+track, bagged)": "B+rule+ou+track__recent-bag5",
}
data = {}
for label, n in specs.items():
    s = pd.read_parquet(f"outputs/book/scores__{n}.parquet").merge(info, on="event_id")
    data[label] = s[
        s.supervised_eligible.eq(True) & s.y_revert_success.notna() & s.year.between(2018, 2023)
    ].set_index("event_id")
common = set.intersection(*[set(d.index) for d in data.values()])
fig, ax = plt.subplots(figsize=(5.5, 5))
for label, d in data.items():
    d = d.loc[sorted(common)]
    f, t, _ = roc_curve(d.y_revert_success, d.raw)
    ax.plot(f, t, label=f"{label} (AUC {roc_auc_score(d.y_revert_success, d.raw):.3f})")
ax.plot([0, 1], [0, 1], "k--", lw=0.8)
ax.set_xlabel("False positive rate")
ax.set_ylabel("True positive rate")
ax.set_title("Reversion forecast, holdout 2018–2023")
ax.legend(fontsize=8, loc="lower right")
fig.tight_layout()
fig.savefig(out / "goal1_roc_holdout.png", dpi=150)
fig, ax = plt.subplots(figsize=(5.5, 5))
for label in ("Original Model B", "Goal 1 model (+OU, bagged)"):
    d = data[label].loc[sorted(common)]
    d["bin"] = pd.qcut(d.probability.rank(method="first"), 10, labels=False)
    g = d.groupby("bin").agg(p=("probability", "mean"), y=("y_revert_success", "mean"))
    ax.plot(g.p, g.y, "o-", label=label)
lim = max(ax.get_xlim()[1], ax.get_ylim()[1])
ax.plot([0, lim], [0, lim], "k--", lw=0.8)
ax.set_xlabel("Predicted reversion probability (decile mean)")
ax.set_ylabel("Observed reversion rate")
ax.set_title("Calibration, holdout 2018–2023")
ax.legend(fontsize=8)
fig.tight_layout()
fig.savefig(out / "goal1_calibration_holdout.png", dpi=150)
# Goal 2: the adopted book (Decision 110d), with and without the monitor exit
# (daily series written by scripts/verify_book.py).
curves = {
    "Adopted book (with monitor exit)": "outputs/book/book_final_daily.parquet",
    "Same book without the monitor exit": "outputs/book/book_no_monitor_daily.parquet",
}
fig, ax = plt.subplots(figsize=(8, 4.5))
for label, path in curves.items():
    m = pd.read_parquet(path)
    ax.plot(pd.to_datetime(m.session_date), (1 + m.daily_return).cumprod(), label=label)
ax.axvline(cast(Any, pd.Timestamp("2018-01-01")), color="grey", ls=":", lw=1)
ax.text(
    cast(Any, pd.Timestamp("2018-02-01")),
    ax.get_ylim()[1] * 0.98,
    "holdout →",
    fontsize=8,
    va="top",
)
ax.axhline(1.0, color="k", lw=0.6)
ax.set_ylabel("Portfolio value (start 1.0, with cash interest)")
ax.set_title("Adopted book, 2010–2023 (Decision 110d)")
ax.legend(fontsize=8)
fig.tight_layout()
fig.savefig(out / "goal2_equity_curves.png", dpi=150)
print("ok")
