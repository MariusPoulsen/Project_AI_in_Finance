# Econometric history runbook

Phase 2 reconstructs monthly relationships and daily signal state from a frozen
Phase 1 market snapshot. It uses the fixed pair registry and A-on-B orientation;
it never searches the reverse regression, retrieves data, constructs labels or
simulates trades. Source adjustment-vintage and static-reference limitations from
[the data runbook](DATA_RUNBOOK.md) still apply.

## Commands

Install the locked default environment with `uv sync --frozen`; no optional ML,
agent or app dependency group is needed. A complete artificial fixture works
independently of Phase 1 ingestion:

```shell
uv run --frozen structural-break build-relationships --relationship-fixture --workspace-root .acceptance/phase2 --relationship-version fixture-p2
uv run --frozen structural-break verify-relationships --workspace-root .acceptance/phase2
```

The fixture contains shared-trend/mean-reverting, independent-random-walk and
stationary-level pairs. All identities and generated prices are synthetic.
It exercises estimation, chronological daily state, storage, publication and
verification without network or credentials.

For project data, select the workspace containing the verified Phase 1 snapshot:

```shell
uv run --frozen structural-break verify-data
uv run --frozen structural-break build-relationships
uv run --frozen structural-break verify-relationships
```

All commands accept `--project-root` and `--workspace-root`. The default range is
the configured 2014-01-01 through 2025-12-31 history. `build-relationships` also
accepts `--start YYYY-MM-DD`, `--end YYYY-MM-DD` and `--relationship-version NAME`.
Start bounds the daily outputs; earlier supplied observations remain formation
warm-up. A partial final month does not introduce an extra refit.

An automatic output version hashes the source dataset, configuration, requested
range, installed Python source and numerical dependency versions. Source hashing
normalizes CRLF/LF so Windows and Linux checkouts share the same identity.
Repeating an already registered version verifies its manifest/artifacts and returns
the stored output; it does not reactivate an older version. Changed inputs/settings
or computation require a new identity, including when an explicit name is supplied.

P2 reads verified P1 curated files directly and can use the existing P1 freeze.
Its added configuration defaults change the global config hash. To replay an older
P1 raw capture, use its recorded P1 code/config checkout (the project freeze used
`43c1851ee895c12e951eb1257ec00936a8dc3dfd`); replay intentionally rejects a
different config hash. Do not recapture sources to replace a historical freeze.

## Chronology and missing data

Each actual XNYS month-end T fits the latest 504 valid common adjusted closes
observed on or before T. Both securities must have finite positive prices for an
observation to enter the window. Missing/nonpositive/invalid rows are excluded
before logarithms; prices are never filled. The actual window start/end and count
are stored, including when the last valid observation precedes T.

The stored estimation timestamp is the actual exchange close, including early
closes and daylight saving. A snapshot becomes effective at the next XNYS open;
its effective end is the next scheduled snapshot's start, exclusively. Formation
coefficients, residual mean/standard deviation and lifecycle status remain frozen
during that interval. Daily signals are available at the actual session close.

Rejected/insufficient monthly attempts remain audit rows with reasons. They are
not usable relationship fits. Daily state begins only after a full estimable
formation fit. The latest monthly attempt governs the next interval: an unusable
new fit suppresses daily states rather than reusing an older successful model.

Daily velocity and crossing checks require prices on the exact preceding XNYS
session. At a refit boundary, the previous day's spread/z-score is recomputed with
the same newly effective coefficients and formation scale as today's score.
Consequently a coefficient change alone cannot create a divergence crossing.
Missing current prices produce no state; missing prior prices leave one-day
velocity/crossing state unavailable. Sign changes and returns do not bridge gaps.
Zero-crossing recency becomes unknown after a gap until an observed adjacent-session
crossing; observed trailing crossing counts expose their completeness flag.

## Statistics and lifecycle

The two-price model uses log adjusted close, a constant-only OLS relation and
`statsmodels.tsa.stattools.coint` with augmented Engle–Granger/AIC selection.
Its MacKinnon cointegration outputs govern the 5% starting threshold; generic
residual ADF p-values are not used as the cointegration gate. ADF/KPSS diagnostics
on levels/differences check I(1) compatibility under globally fixed specifications.

Stored diagnostics include formation spread scale, AR(1) rho/error-correction
coefficient, nullable half-life, correlations, beta drift, trailing spread
volatility and zero crossings. Non-mean-reverting or oscillatory AR coefficients
yield a null half-life with a reason; long half-life and stability diagnostics do
not introduce an unspecified hard gate. Zero volume remains an exposed source
warning; no new liquidity threshold is invented.

A complete estimable I(1)-compatible relationship with cointegration p-value below
the threshold is ACTIVE. The first invalid monthly attempt is WATCH; two successive
invalid attempts are RETIRED. A later valid attempt resets the statistical invalid
counter and can recover ACTIVE status. Manual terminal lifecycle retirement requires
a declared effective date and remains permanent after that date. Undated terminal
flags are rejected rather than retroactively changing historical eligibility.
Unexpected statistical errors fail the whole job with pair/date/config context
rather than skipping that pair.

## Raw crossing outputs

A fresh divergence occurs when `abs(previous_z) < entry_z <= abs(current_z)`.
Baseline 0 records it for any currently estimable spread, including relationships
that fail integration/cointegration gates or have WATCH/RETIRED status. Baseline 1
adds ACTIVE eligibility. Crossing direction is +1 when A is high relative to B and
−1 when A is low. Fixed starting entry/exit/adverse boundaries are 2.0/0.5/3.0.

These are raw P2 crossings. P3 owns unresolved-event deduplication, non-overlap,
forward resolution and labels. No success/failure outcome can appear in these
feature/state rows. Generation of 2024–2025 state does not unlock its headline
outcome/performance evaluation.

## Storage, lineage and queries

Canonical objects are `analytics.relationship_snapshots`,
`analytics.pair_state_daily` and `analytics.divergence_crossings`. Core columns are
queryable SQL fields; complete monthly `diagnostics` and daily/crossing `details`
JSON retain the full scientific/audit fields. `analytics.relationship_versions`
and `ops.active_relationship_version` identify the published version. SQL migration
004 adds these objects without modifying earlier migrations.

Each version also has immutable complete Parquet files and a hashed manifest under
`artifacts/relationships/{relationship_version}/`. The manifest records the input
snapshot/config/range, source metadata, code/library version, synthetic flag and
output hashes/counts. Monthly and crossing IDs hash their scientific identity;
wall-clock creation time and job run ID do not affect those IDs. Source price
identities/hashes and configuration/specification versions accompany output rows.
Tables, version metadata and successful run registration publish in one transaction.

Read existing outputs through the read-only repository service:

```python
from datetime import date
from pathlib import Path

from structural_break.config.paths import ProjectPaths
from structural_break.services.relationships import RelationshipsRepository

paths = ProjectPaths.resolve(Path.cwd())  # add an explicit workspace override if needed
repository = RelationshipsRepository(paths)
manifest = repository.active_manifest()
states = repository.pair_states("KO__PEP", date(2022, 1, 3), date(2023, 12, 29))
snapshot = repository.snapshot_for_session("KO__PEP", date(2023, 6, 1))
baseline0 = repository.crossings("KO__PEP")
baseline1 = repository.crossings("KO__PEP", eligible_only=True)
```

Run snippets using the project Python environment. For SQL fields beyond the core
columns, read the JSON payload or complete immutable Parquet columns. Ordinary
queries do not refit or write analytics. For representative visual/manual checks,
use synthetic, training or validation dates and compare fitted diagnostics,
frozen spread/z plots and the effective interval. Keep final-test outcome metrics
closed until explicit final-run authorisation.

[The diagnostic inspection script](../scripts/inspect_relationships.py) exports
z-score/cointegration plots plus a JSON diagnostic record without outcomes:

```shell
uv run --frozen python scripts/inspect_relationships.py --workspace-root .acceptance/phase2 --pairs KO__PEP HD__LOW WMT__TGT --end 2018-12-31
```

For published project data, omit the fixture workspace and pair overrides; the
defaults inspect KO/PEP, HD/LOW and TXN/ADI through 2023-12-31. Reports live under
`artifacts/reports/{relationship_version}/`. This Phase 2 inspection script rejects
end dates from 2024 onward to preserve the final-test boundary during manual review.

## Failure recovery

Verification rejects changed manifests or artifact bytes. A failed build does not
replace the active relationship version or publish partial analytics. Failure
records under the attempted version retain run/config/data context and estimation
pair/date when available. Fix the cause and rerun; unregistered partial output is
archived before a fresh attempt, while registered immutable versions are verified
and reused. Provider logins are not involved in Phase 2.

Google Colab runs the same commands in its isolated Python 3.11 environment;
[the Colab instructions](COLAB.md) include the fixture bootstrap and project-data
build. Archive the completed local workspace after database connections close.
