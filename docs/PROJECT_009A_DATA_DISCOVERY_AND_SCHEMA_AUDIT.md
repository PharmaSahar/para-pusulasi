# PROJECT009A — Data Discovery and Canonical Schema Audit

## 1. Executive summary

PROJECT009 begins with a read-only discovery phase. The repository already contains substantial evidence of production hardening, telemetry handling, registry governance, and analytics-related planning, but it does not currently expose a single canonical analytics ingestion path that is both production-safe and versioned. The most important finding is that the system already has operational evidence and governance scaffolding, while the live analytics collector remains constrained by documented approval boundaries and the repository evidence does not establish a production analytics API connection in the current canonical state.

## 2. Existing analytics capability map

- The repository contains roadmap and architecture material for analytics snapshots, CTR analysis, retention analysis, watch-time analysis, subscriber conversion analysis, traffic-source analysis, and recommendation governance.
- The repository also contains governance and registry artifacts for recommendations, prompts, experiments, and analytics evidence joins.
- The current documented posture is that live analytics collection remains gated until a formal YouTube Analytics API decision is made.
- The current evidence base is oriented toward retained runtime evidence, governance artifacts, and documentation rather than a live, continuously synchronized analytics pipeline.

## 3. Existing data asset inventory

| Asset | Path | Tracked | Format | Producer | Consumer | Update mechanism | Suitability |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Runtime telemetry | /opt/parapusulasi-shared/runtime/output/runtime/telemetry/production_events.jsonl | runtime-only | JSONL | runtime | audit/operations | runtime emission | REUSE_AFTER_HARDENING |
| Channel queue state | /opt/parapusulasi-shared/runtime/output/runtime/state/channel_queue.json | runtime-only | JSON | scheduler/runtime | operations | runtime state updates | REUSE_AFTER_HARDENING |
| Evidence bundles | artifacts/latest | tracked | JSON/markdown | pipeline/docs | audits | repository artifacts | REUSE_AFTER_HARDENING |
| Registry and policy artifacts | config/ and docs/ | tracked | JSON/markdown | governance | runtime/tests | repository-managed | REUSE_DIRECTLY |
| Analytics-related tests | tests/ | tracked | Python | test suite | developers | test execution | REFERENCE_ONLY |
| Planned analytics docs | docs/PROJECT003_AUTONOMOUS_MEDIA_OS_ROADMAP.md and docs/MASTER_EXECUTION_PLAN_v1.md | tracked | markdown | planning | operators | manual update | REFERENCE_ONLY |

## 4. Existing API integration map

- Repository documents explicitly reference a live YouTube Analytics API collector as a future or gated capability rather than a currently active production dependency.
- The repository contains analytics-related tests and planning artifacts but no evidence of a live production API synchronization path in the current canonical state.
- The available production evidence is primarily retained runtime evidence and repository artifacts rather than fresh API pulls.

## 5. Current identity model

The current system already uses several identity concepts in different layers:

- channel identity appears through channel registry and runtime queue state
- content and upload identity appears through content/job and queue artifacts
- video identity is partly represented in runtime evidence and upload state
- topic and prompt identity are represented in governance and prompt-related artifacts

The main gap is that identity is distributed across multiple systems and is not yet consolidated into a single canonical chain suitable for historical analytics correlation.

## 6. Identity gaps

The repository evidence suggests the following unsafe or weak identity patterns:

- title-based correlation is possible but unreliable
- filename-based references are not sufficient for historical joins
- mutable text metadata may change over time and break lineage
- directory names and inferred channel names are not robust identifiers for analytics correlation

## 7. Available metrics

The repository and docs explicitly mention or imply the following metrics in planning and evidence contexts:

- impressions
- CTR
- watch time
- average view duration
- retention
- subscriber conversion
- traffic source
- likes, comments, shares

These are present as planned or documented analytics concepts, but the current canonical repository evidence does not establish an active production ingestion pipeline for them.

## 8. Missing metrics

The following metrics are not established as current production-available fields in the canonical repository evidence:

- live YouTube Analytics API metrics ingest
- daily or hourly snapshot history from a live source
- longitudinal retention curves with stable provenance
- consistent traffic-source breakdowns
- fully versioned per-video performance datasets

## 9. Existing snapshot/storage model

- The repository contains artifact and evidence directories under artifacts/latest and archive/.
- Runtime evidence is retained in runtime directories outside the repository in the production environment.
- The repository evidence model is mostly append-and-retain rather than a formal versioned analytics database.
- Snapshot durability and schema versioning are not established as a single canonical analytics store in the current repository evidence.

## 10. Data-quality findings

- Cross-channel mixing is a risk because channel isolation is required but not yet a formal analytics identity guarantee.
- Title-based joins and mutable metadata are weak for historical correlation.
- Snapshot overwrite and schema drift risks are not yet bounded by a canonical ingestion contract.
- The repository contains evidence of governance and quality protections, but not a single read-only analytics validation stack for production metrics.

## 11. Cross-channel isolation findings

The repository already documents channel isolation as a critical principle, especially for prompts, policies, and content generation. That principle should be extended to analytics data handling so that analytics snapshots and recommendations are never merged across channels without explicit separation and provenance metadata.

## 12. Canonical schema proposal

A proposed canonical schema should include the following fields.

### Identity

- channel_id
- youtube_channel_id
- internal_video_id
- youtube_video_id
- content_job_id
- content_type
- snapshot_date
- snapshot_timestamp
- schema_version
- source
- provenance_reference

### Content descriptors

- title
- topic
- topic_domain
- duration_seconds
- publication_timestamp
- shorts_or_long_form
- language
- thumbnail_identity_or_hash
- prompt_template_version

### Performance metrics

- impressions
- impressions_ctr
- views
- unique_viewers
- watch_time_minutes
- average_view_duration_seconds
- average_percentage_viewed
- subscribers_gained
- subscribers_lost
- likes
- comments
- shares

### Dimensions

- traffic_source
- geography
- device_type
- viewer_type
- subscribed_status
- age_of_video_days

### Quality fields

- fetched_at
- data_freshness
- completeness_status
- missing_fields
- api_query_version
- partial_data_reason
- validation_status

## 13. Reuse decisions

- REUSE_DIRECTLY: registry, policy, and governance artifacts for channel isolation and evidence handling
- REUSE_AFTER_HARDENING: runtime telemetry and evidence bundles, because they need explicit provenance and schema versioning
- REFERENCE_ONLY: analytics tests and planning documents, because they describe intent rather than a deployed implementation
- UNKNOWN: any live YouTube analytics integration path, because the repository evidence does not establish a current canonical implementation

## 14. Required hardening

- Introduce a canonical identity chain that is not based on mutable title or directory name.
- Enforce append-only historical snapshots with versioned schemas.
- Add data-quality guards for missing fields, partial snapshots, and cross-channel contamination.
- Preserve provenance for every ingested record.
- Keep all analytics ingestion and reasoning read-only until explicit approval.

## 15. Dependencies

- existing runtime evidence and repository artifacts
- governance and policy documents
- channel registry and content identity sources
- future API contract decisions if live analytics data is later required

## 16. Risks

- Cross-channel analytics mixing
- Title-based joins
- Duplicate video identities
- Shorts/long-form confusion
- Timezone drift and snapshot overwrite
- Missing historical days and delayed analytics availability
- Schema changes without versioning

## 17. Recommended implementation architecture

The next implementation slice should be a read-only ingestion and storage layer that:

1. consumes retained evidence and approved snapshots,
2. validates schema and provenance,
3. writes append-only versioned records,
4. preserves channel isolation,
5. emits explainable data-quality summaries,
6. never mutates production state.

## 18. PROJECT009 milestone backlog

- 009-A — Data Discovery and Canonical Schema: COMPLETE
- 009-B — Historical Snapshot Foundation: planned
- 009-C — Analytics Intelligence: planned
- 009-D — Recommendation Engine: planned
- 009-E — Historical Learning Engine: planned
- 009-F — Experiment Platform: planned

## 19. Acceptance gates for 009-B

- canonical identity chain defined
- append-only snapshot storage accepted
- schema versioning enforced
- channel isolation guards present
- data-quality validation documented
- read-only ingestion verified

## 20. Exact next implementation slice

The next implementation slice is a read-only historical snapshot foundation that ingests validated evidence into a versioned schema without changing live production behavior.
