"""Decision 113: overall overfitting audit of the Decision 110d book.

Trial matrix: monthly excess returns of the 99 Stage W exit configurations and the 33 desk
trials (Decision 110b/c), 2010-2023. Reports PBO by CSCV (14 yearly blocks) over the matrix,
and the final book's deflated Sharpe ratio at N = 132 (this matrix), 300 and 500 (the
project's earlier stages: about 150 trials before Stage U, plus Stages U, V, W and v2).
"""
import itertools
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import kurtosis, norm, skew

w = pd.read_parquet("outputs/p6_quant/stage_w/monthly_excess.parquet")
d = pd.read_parquet("outputs/p6_desk/monthly_excess.parquet")
w.columns = [f"stageW|{c}" for c in w.columns]
M = pd.concat([w, d], axis=1)
M = M[(M.index >= "2010-01") & (M.index <= "2023-12")].dropna(axis=1, how="any")
final = next(c for c in M.columns if "desk|R0|qNone|sizeFalse|rule(5, 5)" in c)
print("trial matrix", M.shape, "final book column:", final)


def sr(x):
    return x.mean() / x.std(ddof=1)


# PBO by CSCV: 14 blocks of 12 months; in-sample best -> its out-of-sample rank.
blocks = np.array_split(np.arange(len(M)), 14)
logits = []
for combo in itertools.combinations(range(14), 7):
    ins = np.concatenate([blocks[i] for i in combo])
    oos = np.setdiff1d(np.arange(len(M)), ins)
    best = sr(M.iloc[ins]).idxmax()
    rank = sr(M.iloc[oos]).rank()[best] / (M.shape[1] + 1)
    logits.append(math.log(rank / (1 - rank)))
pbo = float((np.array(logits) <= 0).mean())
trial = sr(M)
gamma = 0.5772156649


def dsr(r, n):
    s, g3, g4 = r.mean() / r.std(ddof=1), skew(r), kurtosis(r, fisher=False)
    sr0 = trial.std(ddof=1) * ((1 - gamma) * norm.ppf(1 - 1 / n) + gamma * norm.ppf(1 - 1 / (n * math.e)))
    z = (s - sr0) * math.sqrt(len(r) - 1) / math.sqrt(1 - g3 * s + (g4 - 1) / 4 * s * s)
    return {"monthly_sr": float(s), "annual_sr": float(s * math.sqrt(12)), "sr0_monthly": float(sr0),
            "dsr": float(norm.cdf(z))}


r = M[final].to_numpy()
holdout = M.loc[M.index >= "2018-01", final].to_numpy()
report = {
    "trials": int(M.shape[1]), "months": int(len(M)), "final_book": final,
    "pbo_cscv_2010_2023": pbo, "median_logit": float(np.median(logits)),
    "trial_annual_sr": {"mean": float(trial.mean() * math.sqrt(12)), "sd": float(trial.std() * math.sqrt(12)),
                        "max": float(trial.max() * math.sqrt(12))},
    "final_rank_in_matrix": int(trial.rank(ascending=False)[final]),
    "dsr_2010_2023": {n: dsr(r, n) for n in (132, 300, 500)},
    "dsr_2018_2023_holdout": {n: dsr(holdout, n) for n in (132, 300, 500)},
}
Path("outputs/p6_quant/audit_final.json").write_text(json.dumps(report, indent=1))
print(json.dumps(report, indent=1))
