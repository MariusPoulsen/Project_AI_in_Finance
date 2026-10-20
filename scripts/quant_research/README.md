# Quant research stage scripts (DECISIONS 79–92)

These scripts drive individual stages of the quant programme. Run them from
the repository root with the project interpreter, for example
`.venv\Scripts\python.exe -W ignore scripts\quant_research\eval_sel.py 2010 2017 <selection files>`.
They read and write `outputs/p6_quant/`.

| Script | Stage |
|---|---|
| `run_rc.py` | Decision 79 R-c, the return-regression ranking |
| `rank_eval.py` | Decision 79 ranking comparison (`<start> <end>`) |
| `tp_extend.py` | Decision 83 take-profit extension |
| `stage_d.py` | Decision 85 OU-alone forecaster and Goal 2 selections |
| `stage_f.py` | Decision 87 expected-value rankings |
| `eval_sel.py` | Per-candidate evaluation of selection files under the adopted exit |
| `recal.py` | Decision 90 recalibration variants |
| `cost_sens.py`, `leverage.py` | Sensitivities reported in `docs/P6_QUANT_RESEARCH.md` |
| `figures.py` | Figures in `docs/figures/quant/` |
