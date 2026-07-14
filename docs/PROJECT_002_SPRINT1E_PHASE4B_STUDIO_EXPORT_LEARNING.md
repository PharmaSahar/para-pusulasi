# PROJECT 002 Sprint 1E Phase 4B - Studio Export Learning Bridge

## Scope
This phase builds a provider-neutral analytics ingestion and learning foundation with no production mutation.

Guaranteed constraints:
- no scraping
- no browser automation
- no production changes
- no automatic optimization
- Studio export is an interim provider
- official API can be added later
- advisory-only
- append-only
- fail-open
- default-off
- pipeline_output_changed=false

## Studio Export Workflow
1. User places YouTube Studio export files locally.
2. Studio parser reads CSV/TSV exports safely.
3. Parser normalizes localized fields and number formats.
4. Deterministic join layer links rows to canonical content identity.
5. Import manifest tracks file-hash imports.
6. Canonical analytics rows append to store without rewrite.
7. Learning signals and advisory recommendations are generated offline.

## Supported Formats
- CSV and TSV Studio exports
- local JSONL analytics artifacts
- local runtime evidence and ownership mappings

Current local finding:
- no actual Studio export CSV/TSV files detected outside environment/vendor samples
- bridge remains ready and validated with deterministic local scenarios/tests

## Canonical Schema
Implemented in [src/studio_analytics_learning_bridge.py](src/studio_analytics_learning_bridge.py).

Identity fields include:
- schema_version
- analytics_record_id
- provider
- source_file_hash
- source_row_number
- canonical_channel_id
- content_id
- youtube_video_id
- content_type
- snapshot_start
- snapshot_end
- imported_at
- metrics_version
- provenance
- advisory_only

Content types:
- LONG_FORM
- SHORT
- LIVE
- UNKNOWN

Metric states:
- OBSERVED
- UNAVAILABLE
- UNKNOWN
- NOT_APPLICABLE
- INVALID

## Deterministic Joins
Priority:
1. exact YouTube video ID
2. upload-result video ID
3. exact canonical content ID
4. exact ownership/upload mapping
5. unresolved

Outcomes:
- LINKED
- UNRESOLVED
- AMBIGUOUS
- INVALID

Forbidden identity methods:
- title similarity
- semantic similarity
- timestamp proximity alone
- filename similarity
- manual guessing
- LLM inference

## Append-Only Imports and Replay
Storage paths:
- logs/youtube_studio_import_manifest.jsonl
- logs/canonical_content_analytics.jsonl

Behavior:
- append-only manifest
- deterministic record IDs
- duplicate file import prevention by source hash
- repeated file imports are idempotent
- later snapshots append as new observations
- malformed-line tolerance on replay
- no historical rewrite

## Metric Histories
Per-content reconstruction includes:
- first snapshot
- latest snapshot
- observation count
- duplicate snapshots
- missing periods
- provider transitions
- metric deltas where definitions are compatible

Incompatible metric windows/definitions are explicitly flagged and not subtracted.

## Baselines
Deterministic baselines are computed by:
- channel
- content type

Summary statistics:
- median
- p25
- p75
- sample count

No direct Shorts/long-form mixing in a single baseline bucket.

## Learning Signals
Rule-based, explainable, advisory-only signals include:
- LOW_CTR_HIGH_RETENTION
- HIGH_CTR_LOW_RETENTION
- EARLY_RETENTION_DROP
- STRONG_SEARCH_WEAK_BROWSE
- STRONG_BROWSE_WEAK_SEARCH
- WEAK_SUGGESTED_TRAFFIC
- STRONG_SUGGESTED_TRAFFIC
- SHORTS_HIGH_SWIPE_AWAY
- SHORTS_STRONG_HOOK
- LOW_AVERAGE_PERCENTAGE_VIEWED
- STRONG_AVERAGE_PERCENTAGE_VIEWED
- CARD_UNDERPERFORMANCE
- END_SCREEN_UNDERPERFORMANCE
- PLAYLIST_OPPORTUNITY
- SUBSCRIBER_CONVERSION_STRENGTH
- SUBSCRIBER_CONVERSION_WEAKNESS
- INSUFFICIENT_DATA

Causal limitations are explicitly preserved:
- hypotheses are not facts
- correlation is not causation
- alternatives and data limits are included

## Advisory Recommendations and Review Contract
Recommendations are advisory only and never auto-applied.
Each includes:
- evidence
- expected direction
- confidence
- minimum sample size
- rollback requirement
- human approval requirement

Review payloads include:
- signal
- supporting metrics
- hypothesis
- recommended action
- affected channel/content type
- confidence
- sample size
- data limitations
- advisory-only

No auto-submit to production channels or dashboards.

## Future Official API Provider
Provider abstraction implemented:
- StudioExportProvider
- ExistingLocalAnalyticsProvider
- FutureOfficialYouTubeProvider (interface only)

Provider priority is explicit and stable.
Official provider handoff can be added later without changing downstream learning logic.
No API calls and no OAuth implementation are included in this phase.

## Privacy and Security
- no credentials in manifests or canonical analytics rows
- no cookies
- no raw auth/session data
- local file ingestion only

## Known Gaps
- local workspace currently has no real Studio export files for direct ingestion coverage
- historical identity completeness still depends on deterministic IDs in source artifacts
- retention curve references are only available when exported
- production validation is out of scope
- automatic regulation remains disabled

## Phase4C Precondition Gate
Phase4C depends on frozen historical Phase4B state and does not bootstrap that state automatically.

Required precondition command:
- `python tools/project002_sprint1e_phase4b_precondition_check.py`

Expected outcomes:
- `PHASE4B ENVIRONMENT READY` means frozen baseline inputs are present and internally consistent for Phase4C validation.
- `PHASE4B ENVIRONMENT PRECONDITION FAILED` means historical inputs are missing or inconsistent.

Policy:
- this checker is read-only
- it does not generate, backfill, copy, or rewrite historical analytics inputs
- test environments must satisfy the precondition explicitly before running Phase4C baseline-dependent assertions

## Promotion Criteria
Before any learning signal may influence generation:
- sufficient per-channel sample size
- stable metric definitions
- acceptable join coverage
- human-reviewed signals
- low false-causation rate
- separate experiment flag
- controlled A/B design
- rollback plan
- explicit approval
- no production default change
