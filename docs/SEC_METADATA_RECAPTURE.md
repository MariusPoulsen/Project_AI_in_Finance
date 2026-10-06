# SEC metadata availability replay

This is a separately versioned research-v2 correction prepared before actual
Model B fitting. It preserves the original Phase 4 experiment and the complete
`sec_metadata/source_v1` capture. It changes admissible research evidence times,
so the old normalized metadata and evidence outputs must not be silently reused.

## Timing policy and diagnostic scope

The earlier JSON normalizer was compared with 250 matched successful cached
submission captures whose original SGML source headers were hash-verified. It
matched 186 headers, placed availability four hours later in 49 and five hours
later in 15. No premature case was observed in these 250 comparisons. The old
capture contains 89,657 normalized filings; this diagnostic does not audit all
of them or establish a universal clock convention.

Under `sec-json-clock-upper-bound-v2`, absent and zero JSON offsets (including
`Z`) retain both UTC and New York wall-clock candidates. Evidence must be
available under both interpretations, so its upper bound governs admission.
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

The new main-workspace destination is
`data/research_v2/sec_metadata/source_v2`. The execution script imports source
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
coverage separately during evidence generation. Hosted CI `8f10d18` was green
for the earlier committed revision; new guard/schedule/replay gates remain
pending until their own checks complete.
