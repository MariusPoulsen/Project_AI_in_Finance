> **Original experiment reference.** These instructions describe the recorded
> 28-pair source/config generations. Use their original workspace and freeze;
> the active expanded workflow is in [the v2 runbook](../../RESEARCH_V2_RUNBOOK.md).
> Commands below use the explicit reference CLI.

# Original data capture and replay

The installed package owns all ingestion, validation and publication. No database
server, provider login or notebook kernel is required. The default window is
2014-01-01 through 2025-12-31, inclusive. Public downloads require internet; frozen
replay and historical queries do not.

## Capture and publish

After `uv sync --frozen`, copy `.env.example` to an ignored local `.env` and set
`SB_SEC_USER_AGENT` to a project name followed by your contact email. The SEC
identifier is sent only to SEC hosts. Do not put it in YAML, Git or shared logs.

```shell
uv run --frozen structural-break-reference ingest-data
uv run --frozen structural-break-reference verify-data
```

An automatically generated snapshot ID is printed on success. To name it explicitly:

```shell
uv run --frozen structural-break-reference ingest-data --snapshot-id my_data_freeze
```

Use a new ID for every capture. Existing immutable identities cannot be replaced.
Provider revisions therefore create a separate freeze. Retrieval uses bounded
retries; SEC requests are paced at two per second. No filing bodies are downloaded
in P1: the index covers 8-K, 10-Q, 10-K and their amendments. Document retrieval
belongs to P4.

Reference metadata is versioned in `configs/securities.yaml`; pair membership and
orientation remain governed by `configs/universe.yaml` and `docs/DECISIONS.md`.
The job validates all 56 issuers against the captured official ticker-CIK map and
downloads 65 market series: those equities, SPY and eight sector ETFs.

## Reproduce a freeze offline

```shell
uv run --frozen structural-break-reference replay-data --replay-from my_data_freeze --snapshot-id my_data_replay
uv run --frozen structural-break-reference verify-data
```

Replay requires a successfully registered source snapshot, its original final/raw
manifests and raw files/sidecars. It validates their hashes before transforming
them. Prior curated Parquet files need not exist; the job rebuilds them from raw
sources. Research settings must match the captured normalized configuration hash.
Later phases can add configuration fields and change that hash; replay an older
capture with its recorded code/config checkout. P2 can read already curated P1
files directly without replay or fresh source retrieval.
New curated rows receive the replay ID while preserving original source IDs,
retrieval times and raw hashes. No Yahoo, Cboe, SEC or news call occurs during replay.
Snapshot/run identities differ; normalized observations and computed context are
equal after excluding the new data-snapshot identity.

To relocate a workspace, close its database connections, copy the complete workspace
including `data/analytics`, `data/raw`, `data/snapshots` and `artifacts`, then run
the replay command above with `--workspace-root /new/workspace`. This verifies the
copied manifests and rebuilds the DuckDB view paths for that location. Query the
new replay after publication; a copied database's old absolute view paths must not
be used before rebinding. Colab keeps active files on local `/content`; archive the
workspace for Drive storage. See `COLAB.md`.

## Offline fixture acceptance

```shell
uv run --frozen structural-break-reference ingest-data --fixture tests/fixtures/phase1 --workspace-root .acceptance/phase1 --snapshot-id fixture_capture
uv run --frozen structural-break-reference replay-data --workspace-root .acceptance/phase1 --replay-from fixture_capture --snapshot-id fixture_replay
uv run --frozen structural-break-reference verify-data --workspace-root .acceptance/phase1
```

The fixture is explicitly synthetic: 38 exchange sessions in 2021, 65 price series,
two corporate actions and recent/older SEC shapes for every issuer. Its manifest
sets `synthetic: true`. It must never substitute for the research freeze. Normal
tests block network sockets and exercise this same production pipeline.

## Storage and queries

Each raw file has an adjacent `.source.json` with source URL, retrieval time,
request parameters, library version, response status where available, size and SHA256.
Yahoo exposes parsed vendor frames rather than HTTP response bytes/status; their
HTTP status is unknown and recorded as null. Local reference files also have no
HTTP status. Each freeze has a raw inventory and a final manifest. The final
manifest records configuration/code identities, schemas, row counts, source hashes,
curated hashes, actual per-dataset date ranges, QA findings and SEC timestamp coverage.

The seven immutable datasets sit below `data/snapshots/{id}/`. Canonical latest
copies occupy the paths in `DECISIONS.md`. DuckDB readers use views pointing directly
to immutable files; batch publication updates all views, active ID and registry
records in one transaction. If validation or publication fails, prior reader views
and canonical copies remain active. Failed QA findings are stored in
`ops.data_quality_results` and `quality_failed.json`; job failures are recorded in
`ops.job_runs` and HTTP-source failures in `ops.source_health`.

| View | Content |
| --- | --- |
| `ref.security_master` | 56 reviewed security identities and SEC CIKs |
| `ref.pair_universe` | 28 fixed orientations and economic rationale |
| `ref.sector_etf_map` | Static project sector proxies |
| `market.prices_daily` | Equities, SPY and ETFs; OHLCV, adjusted close, actions, returns |
| `market.corporate_actions` | Dividend/split audit observations |
| `market.market_context_daily` | Session/sector context with separate SPY/ETF/VIX lineage |
| `ref.sec_filing_index` | Relevant filing metadata and raw/exact UTC acceptance times |

From a script run with `uv run --frozen python your_script.py`:

```python
from datetime import UTC, date, datetime
from pathlib import Path
from structural_break.config.paths import ProjectPaths
from structural_break.services.data_queries import DataRepository

paths = ProjectPaths.resolve(Path("/path/to/Project_AI_in_Finance"))
data = DataRepository(paths)
manifest = data.active_manifest()  # registered manifest + raw/curated hash checks
prices = data.pair_prices("KO__PEP", date(2021, 1, 4), date(2021, 2, 26))
filings = data.eligible_filings("US:KO", datetime(2021, 2, 5, 21, tzinfo=UTC))
```

The service verifies the active snapshot before each historical query. Missing SEC
acceptance times are retained with explicit ineligibility; filing date is never
substituted for availability. Naive cutoff timestamps are rejected.

## Information-set conventions and limits

- Market timestamps use actual XNYS UTC closes, including DST and early closes.
  Values are preserved without forward filling, interpolation or vendor repair.
  Returns and trailing volatility do not bridge missing sessions.
- The user selected previous-session VIX. Each context row joins exactly that
  XNYS session; missing observations remain missing and prevent publishing complete
  context. The 16:16 New York observation proxy is conservative relative to the
  official daily close calculation. It does not establish when a historical CSV
  was published. Same-day VIX is excluded at the equity-close cutoff.
  Official Cboe weekday observations outside the equity calendar remain in the raw
  CSV with an audit warning and do not enter equity-session context. Weekend or
  out-of-range normalized observations remain blocking calendar failures.
- Yahoo adjusted closes are a frozen retrospective vendor history, not a vintage
  point-in-time adjustment feed. Subsequent research must disclose this prototype
  limitation; freezing a download does not prove historical publication times.
- Sector/exchange labels are static reviewed project metadata, not historical GICS
  or a historical listing database. In particular WMT/TGT use XLP and V/MA use XLF
  throughout the research window. Exchange changes are noted; active-from/to remain
  null with lifecycle status `UNKNOWN` rather than invented listing dates.
- Missing equity sessions fail by default (`max_missing_session_fraction: 0`);
  required SPY/ETF coverage is complete. Zero volumes and unusual raw-close jumps
  generate review warnings. Invalid prices, timestamps, keys or lineage block release.
- Source freshness is assessed relative to the original capture time so an old
  deliberately frozen snapshot remains reproducible. Its original retrieval age is
  visible in the manifest; a replay does not claim a fresh provider retrieval.
- Optional GDELT is a separate current/demo adapter and remains disabled in research.
  Ambiguous source dates never become an asserted publication time or admissible
  historical evidence. P1 does not request paid APIs or LLM credentials.

Source contracts: [SEC EDGAR APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces),
[SEC fair access](https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data),
[Cboe VIX history](https://www.cboe.com/tradable_products/vix/vix_historical_data),
[yfinance download](https://ranaroussi.github.io/yfinance/reference/api/yfinance.download.html).
Ingestion includes 2024–2025 source history but computes no headline final-test
outcomes, predictive metrics or strategy results. P2 begins only on separate instruction.
