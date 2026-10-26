# Quant research stage scripts (DECISIONS 79–92)

These scripts drive individual stages of the quant programme. Run them from
the repository root with the project interpreter, for example
`.venv\Scripts\python.exe -W ignore scripts\quant_research\eval_sel.py 2010 2017 <selection files>`.
They read and write `outputs/p6_quant/`.

| Script | Stage |
|---|---|
| `tp_extend.py` | Decision 83 take-profit extension |
| `stage_d.py` | Decision 85 Goal 2 selections (the OU-alone forecaster was erased, Decision 114) |
| `stage_f.py` | Decision 87 expected-value ranking (F-b; F-a erased, Decision 114) |
| `eval_sel.py` | Per-candidate evaluation of selection files under the adopted exit |
| `cost_sens.py`, `leverage.py` | Sensitivities reported in `docs/FORECASTING_AND_BOOK.md` |
| `figures.py` | Figures in `docs/figures/quant/` |
