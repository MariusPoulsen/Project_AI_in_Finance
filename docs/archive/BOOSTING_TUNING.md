# Workstream 1: boosting, tuning and cointegration experiments

Branch `p6/boosting-tuning`. Pre-registrations and results:
[DECISIONS 65–70](../DECISIONS.md). Nothing here changes the frozen Decision
36–42 policies or the accepted v2 snapshot, and the 2024–2025 final test
stays locked.

## Results

| Experiment | Decision | Verdict | Key number (Model B, 2010–2021) |
|---|---|---|---|
| Re-tuned XGBoost, LightGBM and CatBoost (Optuna, forward or purged K-fold CV), an ensemble, and returns-oriented tuning | 65 → 66 | **Fails**: no variant beats the fixed XGBoost | Return gains −0.85 to −2.59 bps per candidate; returns-oriented tuning was worst |
| 21 alternative cointegration features (Johansen, two-way Engle-Granger, total least squares, minimum-ADF and minimum-half-life hedge ratios, Kalman, KPSS, Hurst) | 67 → 69 | **Fails** the Brier test; the logistic models gain on returns | Brier +0.8 × 10⁻⁴ (Holm p 0.46); logistic B +1.9 bps per candidate |
| Cointegration validity gates | 67 → 69 | Chosen gate (two-way Engle-Granger) **fails** (p = 0.085) | Kept events revert twice as often but earn little |
| Seed bagging, linear start, return weighting and cointegration block, built on R0 with the E3 news exit | 68 → 70 | **Fails**: R0 stays best | R0 + E3: +9.3 bps per trade, Sharpe 0.31 |

The best candidate model remains the fixed Decision 45 XGBoost Model B with
the E3 news exit.

## Running

```powershell
powershell -File scripts\boosting_watcher.ps1     # Decision 65 tuning (resumable, ~5 h on 7 workers)
powershell -File scripts\boosting_progress.ps1    # its progress
.venv\Scripts\python.exe -m structural_break.experiments.p6_coint build          # cointegration features (~10 min)
.venv\Scripts\python.exe -m structural_break.experiments.p6_coint models
.venv\Scripts\python.exe -m structural_break.experiments.p6_coint gate-explore
.venv\Scripts\python.exe -m structural_break.experiments.p6_coint gate-confirm
.venv\Scripts\python.exe -m structural_break.experiments.p6_boosting2            # round 2 (~1 h)
```

LightGBM, CatBoost and Optuna are in the `research` extra:
`uv sync --extra research`.
