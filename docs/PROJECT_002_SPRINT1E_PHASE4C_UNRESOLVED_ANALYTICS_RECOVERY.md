# PROJECT 002 Sprint 1E Phase 4C - Unresolved Analytics Recovery

## Scope
This phase audits the original 102 unresolved analytics rows from Phase 4B and classifies each row deterministically.

Safety invariants:
- local only
- append-only
- advisory-only
- fail-open
- default-off
- pipeline_output_changed=false
- no production behavior change
- no title-based matching
- no automatic regulation

Explicitly:
- unresolved does not mean defective
- no row was force-linked
- no title-based matching was used
- no production behavior changed
- no automatic learning or regulation was enabled

## Frozen Input
Authoritative source:
- Phase 4B assessment summary at `artifacts/latest/project002_sprint1e_phase4b_studio_export_learning/assessment_summary.json`

Frozen reconstruction rule:
1. read Phase 4B source hash
2. verify current `logs/channel_performance.jsonl` first 788 lines reproduce that exact hash
3. filter append-only canonical analytics store by that exact source hash
4. keep only rows with `join_outcome=UNRESOLVED`

Result:
- imported rows: 788
- linked rows before Phase 4C: 686
- unresolved rows frozen for audit: 102
- source hash: `15beaf8f468a287d25e6f95f15aa4ce193aca88f5a338f7c6f7e963941966a03`

Precondition lifecycle:
- missing required baseline files => `ENVIRONMENT_NOT_PREPARED`
- files present but invariant checks fail => `ENVIRONMENT_INCONSISTENT`
- all frozen-file and count/hash invariants pass => `ENVIRONMENT_READY`

Run before Phase4C validation:
- `python tools/project002_sprint1e_phase4b_precondition_check.py`

Important:
- the gate is read-only and validation-only
- it does not bootstrap historical Phase4B files
- it does not mutate logs, canonical rows, or source analytics inputs

The manifest stores deterministic row IDs, source row numbers, source hash, row hash, identity fields, snapshot range, metric field presence, and original unresolved join state.

## Deterministic Recovery Rules
Allowed proof surfaces:
1. exact video ID
2. exact upload-result video ID / upload ID
3. exact content ID
4. exact run ID
5. exact ownership mapping
6. exact forward-evidence session ID
7. exact script-lineage evidence ID
8. exact planning/blueprint lineage hash

Forbidden joins:
- title similarity
- description similarity
- semantic similarity
- timestamp proximity alone
- filename similarity
- LLM inference
- manual guessing

Recovered rows emit new append-only recovery evidence rows and do not rewrite the historical analytics rows.

## Taxonomy
Primary categories supported by the engine:
- MISSING_VIDEO_ID
- VIDEO_ID_NOT_IN_UPLOAD_MAP
- MISSING_UPLOAD_ID
- UPLOAD_ID_NOT_IN_EVIDENCE
- MISSING_CONTENT_ID
- CONTENT_ID_NOT_IN_OWNERSHIP
- MISSING_RUN_ID
- RUN_ID_NOT_IN_LINEAGE
- MISSING_OWNERSHIP_RECORD
- LEGACY_UPLOAD
- LEGACY_ANALYTICS_ROW
- DELETED_VIDEO
- PRIVATE_OR_UNLISTED_VIDEO
- CHANNEL_MISMATCH
- PROVIDER_MISMATCH
- SCHEMA_MISMATCH
- DUPLICATE_SNAPSHOT
- DUPLICATE_SOURCE_ROW
- AMBIGUOUS_IDENTITY
- UNSUPPORTED_AGGREGATE_ROW
- UNSUPPORTED_METRIC_SHAPE
- MALFORMED_ROW
- INSUFFICIENT_IDENTITY_EVIDENCE
- UNKNOWN

Each classification carries evidence, confidence, recoverability, required missing proof, and future prevention status.

## Recoverability Model
States:
- RECOVERABLE_NOW
- RECOVERABLE_WITH_STUDIO_EXPORT
- RECOVERABLE_WITH_OFFICIAL_API
- RECOVERABLE_WITH_FUTURE_FORWARD_EVIDENCE
- PERMANENTLY_UNRECOVERABLE
- AMBIGUOUS
- INVALID
- UNKNOWN

## Local Result
Observed final split from the authoritative 102-row set:
- RECOVERED: 102
- STILL_UNRESOLVED: 0
- PERMANENTLY_UNRECOVERABLE: 0
- AMBIGUOUS: 0
- INVALID: 0

Observed primary root cause:
- MISSING_OWNERSHIP_RECORD: 102

Observed proof method:
- content_id: 102

Explanation:
- each of the 102 unresolved rows carried an exact canonical `content_id`
- each matching target existed in local runtime evidence
- Phase 4B only checked `content_id` against ownership manifests, not runtime-evidence content identity
- therefore the rows were unresolved in Phase 4B but recoverable now without guessing

## Coverage Delta
Before:
- total rows: 788
- linked: 686
- unresolved: 102
- ambiguous: 0
- invalid: 0
- join rate: 0.870558

After:
- recovered: 102
- linked total: 788
- still unresolved: 0
- permanently unrecoverable: 0
- ambiguous: 0
- invalid: 0
- join rate: 1.0

## Duplicate and Snapshot Handling
The Phase 4C audit distinguishes:
- exact duplicate source rows
- duplicate snapshots with the same identity and date window
- later valid snapshots
- overlapping snapshot windows
- incompatible snapshot definitions
- aggregate rows
- content-level rows

No source rows are deleted. Duplicate dispositions are recorded append-only.

## Studio Export Requirements
Required operator fields:
- Video ID
- Content title, descriptive only
- Channel ID
- Content type
- Date or snapshot range
- Views
- Impressions
- Impressions CTR
- Watch time
- Average view duration
- Average percentage viewed
- Shorts feed metrics
- traffic-source fields

Checklist:
- export content-level rows only
- preserve Video ID column unchanged
- preserve snapshot date/range exactly
- do not edit localized numeric formats before import
- do not scrape or automate Studio downloads

## Future Official API Handoff
Rows classified as `RECOVERABLE_WITH_OFFICIAL_API` require:
- YouTube Analytics API
- YouTube Data API
- read-only analytics scope
- read-only YouTube scope
- exact `video` identity dimension

This phase performs no OAuth flow and no API calls.

## Prevention Matrix
Phase 4C evaluates the current architecture across:
- Forward Evidence Capture
- Analytics Evidence Join
- Studio Export Bridge
- Script Lineage
- Planning/Blueprint Lineage
- Upload-result persistence
- Future official provider

For the observed `MISSING_OWNERSHIP_RECORD` category:
- forward/script/planning/upload-result persistence are partially preventive
- current analytics join is not fully preventive because it did not consume runtime `content_id` proof in Phase 4B
- future official provider is partially preventive

## Limitations
- historical identity may still be irretrievable for other datasets
- deleted videos can remain unresolved if no retained identity exists
- Studio exports still depend on operator availability
- official API permissions remain a separate concern
- no causal learning is performed here
- no automatic recommendation application is performed here

## Operational Recommendations
- retain ownership manifests for every uploaded content item
- preserve exact upload-result video IDs prospectively
- keep forward/script/planning lineage enabled for future auditability
- use Studio export Video ID as the only Studio identity proof