# Current-study monitoring and SHAP

The monitor uses `demo/results/forecasts.parquet` as its event population. Its
periods are selection 2010–2017, holdout 2018–2023 and final test 2024–2025. Each
annual forecaster fits earlier resolved labels; these are evaluation periods,
not a replacement for the original frozen fitting/calibration partitions.
Final-test counts remain pending until the results export includes them.
The main Versions table describes the current results export. Superseded frozen
evaluation, backtest and explanation-status rows are omitted. The still-used
input registry, SEC generation, protocol and bundle identities remain available
under the collapsed Input data provenance section.
Numbered decision references and links to the development decision log are not
shown in app copy, settings, tables or authorization labels. Source comments,
development documentation, stored unlock records and research artifacts retain
their original references.
The methodology's displayed research feature blocks omit the Gemma catalyst
extraction row and description. This is a presentation filter; it does not
change fitted feature sets, stored research results or historical artifacts.

Counts retain all scored events and separately report labelled events, positive
labels and labelled-event reversion rates. At export 50dd896, the counts are
11,236/11,214 scored events and 11,048/10,940 labelled events in selection/holdout.
The older frozen report's 21,137/3,762/3,430 fit/calibration/assessment counts are
not the headline forecasters' evaluation populations.

SEC coverage and drift left-join quantitative, metadata and FinBERT input values
by current event ID. No fitted probabilities, old labels or catalyst fields are
used. The committed input bundle lacks 566 of 22,450 current scored events; they
remain in coverage denominators, with missing SEC metadata counted as UNKNOWN.
FinBERT known coverage requires an explicit known flag. Annual drift includes
missing-value shares and only lists input fields actually present in this export.
It cannot describe engineered peer/OU/track features absent from the export.
The UI change does not remove predictors from, or refit, the scientific models.

## Baselines in Model Lab

The Comparison tab includes Baseline 0 (take every fresh divergence) and
Baseline 1 (take only historical ACTIVE relationships). They are evaluated as
constant/binary ranking rules on the same labelled forecast events in each
period, including rejected events. Baseline 0's ROC AUC is 0.5 and its average
precision equals the base rate. Baseline 1 ranks ACTIVE above inactive events;
its admitted-event count is shown separately. These entry rules have no
probability forecasts, so their log loss and Brier are unavailable. No base rate
is fitted using holdout outcomes and no old frozen-period metric is reused.

`baseline_events.parquet` contains verified eligibility flags for all 22,450
development forecast events, exported from the registered h20 model inputs.
Its provenance and forecast-file binding live in the results manifest. A missing,
duplicate or UNKNOWN flag is rejected, rather than interpreted as inactive.
This small sidecar preserves the forecast bytes and existing SHAP binding.
Regenerate it for a development results copy with:

```shell
uv run --frozen python scripts/export_forecast_baselines.py --workspace-root C:/Users/mariu/dev/Project_AI_in_Finance/data/team --evaluation-version research_evaluation_16a431c4fea73ffd35f56062 --results demo/results
```

## Full model forecasting view

The Full model tab explains the actual annual logistic stack: bagged B+rule+ou
probability plus six entry-desk inputs (explains-move, persistence, relationship
change, explains × persistence, no-news and abstain). Conditional debate and
citation review validate evidence; the statistical stack, rather than the LLM,
produces the probability. The position monitor remains a trading exit component.

The selected period controls a matched four-metric comparison of the same
logistic stack with and without the agent inputs. It displays signed differences,
sample size and base rate, and rejects mismatched exported cohort counts/rates.
The comparator is a probability-only stack on desk-covered events, not the
headline forecaster's all-event result. Performance conclusions stay in the report.

## SHAP export

Model Lab has a SHAP tab for verified current-model explanations. The committed
export contains 240 target-blind sampled events per model across 2018–2023
(40 per year), for R0 and both bagged forecasters. Every raw annual score was
reproduced before exporting the native attributions. Selection-period SHAP is
not included. Frozen-study TreeSHAP is not a substitute for the annual models.
To regenerate, run from a separate checkout with read-only development inputs:

```shell
uv run --frozen python scripts/export_forecast_shap.py
```

Paths can be overridden with `--results`, `--workspace-root` and `--outputs-root`.
The verified inputs on the owner's computer are under
`C:/Users/mariu/dev/Project_AI_in_Finance/data/team` and
`C:/Users/mariu/dev/Project_AI_in_Finance/outputs`. The source `demo/results`
must also remain read-only: Claude regenerates it independently. Pass this
checkout's results copy to `--results`. Do not use the final-test workspace.
Default years are 2018–2023, with 40 events per year, chosen by the lowest SHA-256
of event ID independently in each year. The sample never uses outcomes, scores
or feature values. `--years` accepts development years 2010–2023 only.

This is an explicit diagnostic batch job. It reconstructs R0, bagged B+rule+ou
and bagged B+rule+ou+track using the existing harness, fixed parameters, seeds,
feature sets and label-window cutoffs. It must reproduce every published annual
raw score before exporting any explanation. It never writes research outputs or
changes forecast results, settings or final-test records. Its cost includes
reconstructing the annual fits; app browsing never launches it.

The job writes `shap_events.parquet`, `shap_values.parquet`, `shap.json` and an
updated presentation manifest under `demo/results`. Publish those files together.
It binds the forecast SHA, input hashes and XGBoost version. Reading verifies
source binding, event/year/model identities, seeds, component completeness,
SHAP additivity, sigmoid margins and component means against published scores.

Native TreeSHAP explains each seed model's log-odds. The bag averages
probabilities, so averaged component margins are not an additive decomposition
of the bag's probability. The UI therefore shows a sample-wide importance
summary across seed fits and an event waterfall for a selected seed component,
with the published calibrated ensemble probability separately labelled.

Model A has no annual score export for verification here, and the Full model
uses a logistic stack; neither receives a fabricated tree explanation. All
explanations are model behaviour, not causal effects or performance evidence.

## Complete pair histories

`demo/pair_history` supplements the small showcase app bundle with all 736
registered development pairs (75.1 MB compressed). The export verifies the
registered registry, each pair manifest, daily state, snapshots, crossings and
market prices before projecting the columns used by Pair Detail. It reads
DuckDB registrations and immutable Parquet without modifying them; it does not
download, refit or reconstruct SEC text.

```shell
uv run --frozen python scripts/export_pair_history.py --workspace-root C:/Users/mariu/dev/Project_AI_in_Finance/data/team
```

Choose a new `--output` directory when regenerating; existing exports are not
overwritten. Publish this directory beside `app_bundle`, including its manifest
and all Parquet shards. The loader requires the same registry identity and exact
pair roster, verifies file hashes before use and reads only the selected pair's
rows. The supplement ends in 2023 and makes no claim of final-test history.
It removes the demo's previous "events only" limitation without copying the
SEC archive or putting a database in Git. Browsing never starts an export job.

Code changes target `main` (or `app/refresh` while integration is active), not
the deployment-only `deploy` branch. The deployment maintainer merges code and
publishes the matching results/history exports together. Preserve the current
`pipeline.news_exit.load_exits` support for `exits_final.parquet` during integration.
