# SEC metadata availability replay

This separately versioned research-v2 correction was prepared before actual
Model B fitting and supplies the accepted source-v3 availability contract. It preserves the original reference experiment and the complete
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

The accepted `sec-json-clock-envelope-v3` adds the inverse UTC-to-New-York-wall-clock
candidate to widen the lower bound for the observed source lag. Preserve
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

The accepted destination is `data/research_v2/sec_metadata/source_v3`.
Recorded reproduction used explicitly frozen isolated source and a fingerprint-
bound local wrapper. Its execution details and subsequent proof receipts are in
[the replay history](archive/SEC_METADATA_RECAPTURE_HISTORY.md#local-acceptance-execution).
A replay must keep filing membership and all non-timing metadata identical;
only the availability fields and new generation identity may change.

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
subsequent proofs in the archived replay history clear that engineering gate without rewriting the
original capture receipt/proof. Source-v1/v2 remain immutable.

## Current acceptance boundary

The separate canonical replay of 250 cached accession inventories passed: all
sampled official SGML headers lie inside the v3 envelope, with response/retrieval
identities unchanged and zero HTTP calls. This is not a full audit of all 89,657
filing headers or complete historical NLP coverage. Every subsequently selected
filing still requires its own raw-hash, SGML-clock and event-cutoff checks.

The accepted metadata is `sec_metadata/source_v3`, manifest SHA-256
`39a6e5e417a2c3e8ddfa75c04564453c0157a37ca43b46ad1b14a3e0935853a9`.
The quality-v2 text amendment changes preprocessing, not this SEC clock envelope
or raw source provenance. Parser caching and audited checkpoint recovery likewise
preserve this source and its admission rules. Independent scientific verification
uses fresh raw-source replay; a checkpoint audit alone is not that acceptance.

See [the current protocol](RESEARCH_V2_PROTOCOL.md), [delivery gates](STATUS.md)
and [archived replay/engineering history](archive/SEC_METADATA_RECAPTURE_HISTORY.md)
for the distinct source, inference and publication gates. Preserve source_v1/v2/v3,
all body/retrieval identities, previous tone policies/caches and failed attempts.
