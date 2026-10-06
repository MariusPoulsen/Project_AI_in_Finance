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

The next main-workspace destination is
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
The new v3 envelope, source replay and canonical
SGML checks remain pending. Do not begin actual B fits until that gate passes.

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
