# SEC metadata availability replay

This is a separately versioned research-v2 correction prepared before actual
Model B fitting. It preserves the original Phase 4 experiment and the complete
`sec_metadata/source_v1` capture. It changes admissible research evidence times,
so the old normalized metadata and evidence outputs must not be silently reused.

## Timing policy and diagnostic scope

JSON metadata was compared with 250 matched successful cached submission
captures whose original SGML source headers were hash-verified. In 186 cases the
timestamps matched; 49 JSON `Z` values were themselves four hours later and 15
five hours later. This is observed source timestamp lag, not an issue caused
only by parsing naive clocks. No premature case was observed in these 250
comparisons. The old capture contains 89,657 normalized filings; this diagnostic
does not audit all of them or establish a universal clock convention.

The completed `sec-json-clock-upper-bound-v2` metadata replay retained UTC and
New York wall-clock candidates for absent/zero offsets, including `Z`. Its upper
bound was conservative in the sample, but the interval excluded the 64 earlier
SGML headers below its lower bound. That is a canonical document-validation
failure even though metadata reconstruction and zero-network replay passed.
Preserve source_v2; it is not evidence admissibility acceptance.

Prepare `sec-json-clock-envelope-v3` with the inverse UTC-to-New-York-wall-clock
candidate added to widen the lower bound for the observed source lag. Preserve
the v2 conservative upper bound. Evidence must be available under the full
envelope, so only that upper bound admits it.
Explicit nonzero offsets remain exact. Missing acceptance times are
UNKNOWN; a filing date cannot substitute for an acceptance timestamp. An
interval crossing a relevant cutoff or 30/180/400-calendar-day selection boundary
also keeps coverage UNKNOWN. The lower/upper bounds and raw source timestamp
remain auditable. Conservative postponement is an acknowledged coverage cost.

## Frozen input and expected side effects

The parent is `data/research_v2/sec_metadata/source_v1`, snapshot
`research_sec_a26f07f21c33a8d662ab87b0`. Its manifest SHA-256 is
`a9b53e407e4ebdf6f39fdb101f24e2843bf6d171335803ba9b6a2d6d3f5c99da`.
The parent has 250 complete source issuers, 735 official submissions responses
and 735 response sidecars (183,624,710 bytes together). Every file listed by the
parent manifest, including its old derived outputs, is verified read-only.
Only the 1,470 response/sidecar files seed the new capture. Preserve exact source
URLs, retrieval times, status codes and raw hashes; do not fetch current versions
of these endpoints or copy the old derived metadata/coverage/manifest outputs.

The latest main-workspace destination is
`data/research_v2/sec_metadata/source_v3`. The execution script imports source
code explicitly from the isolated `finance-sec-availability` checkout. Before
execution, review and freeze that code after the guards and catalyst scheduling
changes settle. The ignored local wrapper
`.acceptance/replay_sec_metadata_v2.py` first offers a read-only plan. Its execution
requires the reviewed code fingerprint; it verifies the fingerprint before and
after collection and rechecks the parent inventory afterward. Filing membership
and all non-timing metadata must remain identical to the old source outputs;
only availability fields and the new snapshot identity may change.

The public `collect_sec_metadata` and `verify_sec_metadata` functions regenerate
the new normalized outputs with the new policy/schema. A missing-cache callback
raises an uncaught `RuntimeError`, and socket connection/DNS guards prohibit
HTTP fallback. A cache gap aborts instead of becoming a successful UNKNOWN
issuer. The script writes a separate immutable `replay_provenance.json` receipt
binding parent manifest/inventory, code fingerprint and derived manifest hash;
this receipt is an audit alongside the canonical capture manifest, not an
unhashed field added to that manifest identity. Archive/pin both receipt and
canonical manifest hashes when registering downstream evidence.

New files comprise the copied raw cache, freshly derived `filings.parquet`,
`coverage.json`, `sources.json`, `manifest.json` and the replay receipt. No old
source, database, registry, evidence or fitted-model generation is changed. No
LLM call, model-weight download, equity data request, final-test outcome access
or billable request is part of this replay. Existing whole submissions JSON can
contain later records; normalized research metadata still ends on 2023-12-31.

## Local acceptance execution

From the isolated checkout, first run the ignored script with explicit absolute
`--source-dir`, `--universe-dir` and new main `--output-dir` paths. Omit
`--execute` to verify the parent and print a read-only plan. The script's optional
`--plan-output` records the complete raw/code inventory in an ignored acceptance
file. After code freeze, invoke the same paths with `--execute` and
`--expected-code-fingerprint` equal to the reviewed plan fingerprint. A completed
destination cannot be rebuilt; verify its existing manifest and receipt instead.
An interrupted raw-only destination may resume from identical hash-verified
cache bytes. Preserve and inspect any destination containing partial derived
outputs rather than deleting them to force a retry.

Record zero HTTP/socket attempts, all 735 response identities unchanged, the new
policy/schema, complete issuer count, filing count, missing-time counts, parent
unchanged verification and output hashes. Record timestamp-boundary UNKNOWN
coverage separately during evidence generation. Hosted CI `3c01d262` passed on
Windows, Linux and Colab, including its committed schedule and v2 guards.
The v3 envelope/header guards passed focused checks at `100e1e48`; its source
replay completed. Hosted CI for `100e1e48` subsequently passed the complete
Windows/Linux regression jobs and Linux Colab bootstrap in
[run 37451417275](https://github.com/MariusPoulsen/Project_AI_in_Finance/actions/runs/37451417275).
That result does not cover subsequent isolated log-loss/subgroup-report changes,
which require their own committed hosted verification. Canonical SGML replay and genuine FinBERT verification remain
separate proofs; both now pass on the recorded 250-inventory sample and genuine
SEC-text smoke. Full historical feature generation and A/B fitting remain pending.

## Completed source-v2 metadata replay

Frozen code `3c01d2628b33c33777660e19c56459e0513d3e22` produced snapshot
`research_sec_e46167640c423d79c6314c79`, with the same 250 complete issuers,
735 response identities, 89,657 filing rows and non-timing metadata. HTTP and
socket attempts were zero. Its manifest SHA-256 is
`295ac93b2f19be8f23669d47018dc6519e4407da2b45aaa51cdd3af04d34fb26`;
the separate replay receipt SHA-256 is
`d866c0edac60a4a834f199d29180264459df7943211f12158c1c52245a18f935`.
The capture-level proof is present in both workspaces at
`.acceptance/research_sec_source_v2_acceptance.json`, SHA-256
`4eb76e30fa07a4dff46ddba5382c3f79c68c0c8cbf4d0cbd998e030087760a57`.
It explicitly records the SGML-bound mismatch and does not permit actual B
fitting. Its constructed intervals were four hours wide for 57,876 rows and five
hours for 31,781; these are metadata-policy measurements, not verified SGML
containment for all rows. Keep every source-v2 file immutable when deriving v3.
The exact ignored wrapper used for v2 is also preserved locally as
`.acceptance/frozen_replay_sec_metadata_source_v2.py`, verified against the
receipt's wrapper SHA-256
`8f2861b78f411ff21b04f4980a04c2f3cf10083c01685fcaf11ee85adc7bd756`.
Restore it under the original wrapper filename in a reproduction checkout when
reconstructing the recorded code fingerprint; the current generic wrapper may
bind a later acceptance policy for v3.

## Completed source-v3 metadata replay

Frozen code `100e1e48a62397ad5cb409fae8e316573cae57c9` produced snapshot
`research_sec_5f856a4e440531e2742bf1d8`, using policy
`sec-json-clock-envelope-v3` in the `research-sec-metadata-v2` storage schema.
It retains the exact source-v1 responses, 250 complete source issuers, 89,657
filings, and all non-timing metadata, with zero HTTP/socket calls. Its upper
bound equals v2 for every filing, and its lower bound is widened or unchanged.
Constructed intervals span eight hours for 57,876 rows and ten hours for 31,781;
these are metadata-policy measurements, not a full SGML audit.

The source-v3 manifest SHA-256 is
`39a6e5e417a2c3e8ddfa75c04564453c0157a37ca43b46ad1b14a3e0935853a9`;
its replay receipt SHA-256 is
`9748019c1f77152cfbace641f93b037b1f86c0d066af5237f2c3a77fb108f5b7`.
The capture proof exists in both workspaces at
`.acceptance/research_sec_source_v3_acceptance.json`, SHA-256
`8e03c2ac136fb9cbaf7613fc07d95313a74e76a5f94969981eb8b3611db9d200`.
It recorded canonical SGML replay as pending when capture completed. The
subsequent proofs below clear that engineering gate without rewriting the
original capture receipt/proof. Source-v1/v2 remain immutable.

## Passed canonical replay and genuine SEC-text inference

The main-workspace `.acceptance/sec_v2_document_replay.json` proof records 250
canonical accession inventories replayed from original Phase 4 raw responses.
Despite the historical filename, it binds source-v3 metadata manifest
`39a6e5e417a2c3e8ddfa75c04564453c0157a37ca43b46ad1b14a3e0935853a9` and
`sec-json-clock-envelope-v3`. All 250 sampled official SGML acceptance headers
fall within the envelope; original response bytes, URLs, HTTP statuses and
retrieval identities are unchanged. No HTTP calls occurred. Its proof SHA-256
is `2e456e7f6c9653741df76e27d3ade1977aa8fbb830be2c7cfb1b8e3be3fa8b36`.
This passes the canonical sample replay gate, not a claim that every one of the
89,657 metadata rows has been checked against an SGML body.

The main-workspace `.acceptance/finbert_real_sec_smoke.json` proof uses genuine
V/MA SEC evidence at cutoff 2016-01-08T21:00:00Z, with three selected filings,
six chunks and 210 token windows. Pinned CPU inference took 53.235 seconds and
replayed exactly from cache. All five model/tokenizer asset hashes were checked;
there were no network/LLM calls or final-outcome reads. Its proof SHA-256 is
`190d80d09f49952e9ad9aac03e4ea6fa755c1e3fb8bac136a8204c391674521d`.
This is a genuine adapter/source check, not representative sentiment accuracy
or completed historical feature coverage.

Legacy batch `development_v3_100e1e4` is STOPPED and incomplete as of
2026-10-07 05:10 UTC. Its session/process are absent; the log ends at 1,494
completed checkpoints at 03:33 UTC without traceback/terminal manifest.
The cause is unknown, not recorded as an intentional stop or confirmed FAILED
publication. Preserve its partial records. It used frozen source `100e1e48`,
source_v3, 37,421 scheduled events and a separate 500-event Gemma pilot, without
`--max-events` or disabled inference. Feature completion and all actual A/B
comparisons remain pending.

The tested replacement evidence batch `development_quality_v2` uses the separately versioned
`sec-sentence-quality-wordpiece-v2` FinBERT amendment described in
[the protocol](RESEARCH_V2_PROTOCOL.md#fit-input-preprocessing-amendment).
It is based on nineteen FIT-only source inputs after quantitative cohorts were
constructed and before any research model assessment; no labels/scores or
calibration/assessment text informed it. This changes sentiment preprocessing,
not the accepted SEC source-v3 clock envelope or its raw provenance. Keep all
source snapshots, original body/retrieval identities and legacy tone proofs/
caches immutable. Preserve raw text offsets, full-source token denominators and
explicit partial coverage in the new tone inventory. Production tokenizer
acceptance confirms 8,292 raw physical-line windows versus 8,720 legacy
newline-plus-punctuation windows, with the same 39,879 raw tokens. V2 scores
1,259 windows/20,957 tokens and excludes 7,033 windows/18,922 tokens, with no
budget omissions in this sample; nineteen genuine legacy records replay exactly.
The production receipt is `.acceptance/finbert_quality_v2_plan_acceptance.json`,
SHA-256 `ca0113d09e9c1d12a1d61b6286ad44fd58626516bfbd89e7cc1b2fe8f0d3f407`.
Genuine quality-v2 CPU inference on ADBE/ADSK at the first FIT event passed in
31.766 seconds with exact cache replay, all five asset hashes verified, 388
legacy cache files unchanged and no network/LLM/outcome access. Its separate
proof is `.acceptance/finbert_quality_real_sec_smoke.json`, SHA-256
`582866c4f633775a41532b3b0a20914dbe1f13975848d27908034bf0a2059c1c`.
Its time is not compared with the different V/MA legacy smoke event.
The combined amendment passed 100 focused tests, whole Ruff/133-file format,
strict mypy/66-source and four final native-model integration checks in
83.74 seconds. New commit/input freeze, fresh hosted CI and launch remain
pending; this document does not claim replacement completion or predictive gain.
