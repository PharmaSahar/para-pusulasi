# PROJECT009B — Historical Snapshot Foundation Implementation Plan

## 1. Executive summary

CONFIRMED: PROJECT009-B1 is the first implementation slice for the PROJECT009 historical-learning foundation. It is explicitly a read-only, fixture-driven, network-free, scheduler-free, production-neutral foundation for canonical historical snapshots.

PROPOSED: The initial implementation will introduce a canonical snapshot domain model and a local append-only JSONL store that preserves provenance, channel isolation, schema versioning, deterministic snapshot identity, and explicit data-quality status.

UNKNOWN: Whether the repository will later ingest live YouTube Analytics API data remains unresolved and is explicitly out of scope for B1.

## 2. Relationship to PROJECT009-A

CONFIRMED: PROJECT009-A established the discovery posture and identified the absence of a canonical historical analytics foundation.

PROPOSED: PROJECT009-B1 will implement the first concrete foundation for that gap without introducing live API access or production mutation.

## 3. Objective

CONFIRMED: The B1 objective is to validate and persist immutable historical analytics snapshots in a local, append-only store that is safe for offline tests and review.

## 4. Confirmed repository capabilities

CONFIRMED:
- The repository already contains analytics-oriented guard and registry patterns under src/.
- The repository already uses dataclasses and append-only JSONL patterns in several modules.
- Existing repository conventions support temporary-directory-based unit tests and file-based persistence.

## 5. Confirmed gaps

CONFIRMED:
- There is no single canonical historical snapshot model yet.
- There is no local append-only snapshot store dedicated to analytics history.
- There is no deterministic snapshot identity contract that is independent of title or thumbnail changes.
- There is no explicit channel-isolated append-only storage path for analytics snapshots.

## 6. B1 implementation scope

CONFIRMED:
- Implement a canonical immutable snapshot record.
- Implement deterministic snapshot ID generation.
- Implement a local append-only JSONL store with per-channel isolation.
- Implement validation and quality guards for required semantics.
- Implement focused fixture-driven tests with temporary directories.

PROPOSED:
- The first coding slice will be limited to two implementation files and one focused test file.

## 7. Explicit non-goals

CONFIRMED:
- No live YouTube Analytics API calls.
- No live YouTube Data API calls.
- No OAuth credential usage.
- No scheduler integration.
- No production mutation.
- No upload behavior changes.
- No prompt or title/thumbnail generation changes.
- No recommendation or dashboard implementation.

## 8. Proposed module/file layout

PROPOSED:
- src/analytics_snapshot_foundation.py — canonical snapshot model, validation rules, deterministic ID generation, and append-only store.
- tests/test_analytics_snapshot_foundation.py — focused unit tests for schema, identity, persistence, validation, and isolation.

## 9. Canonical identity contract

CONFIRMED:
- Channel identity is mandatory and must be preserved.
- Internal video identity and YouTube video identity are both required.
- Content job identity is required.
- Snapshot identity must be deterministic and independent of mutable content descriptors such as title and thumbnail.

PROPOSED:
- The canonical identity is built from schema_version, channel_id, youtube_video_id, normalized snapshot_timestamp, and metric_source.

## 10. Canonical snapshot schema

CONFIRMED:
- schema_version is mandatory.
- snapshot_id is mandatory and generated deterministically.
- snapshot_timestamp and snapshot_date are mandatory.
- channel_id, youtube_channel_id, internal_video_id, youtube_video_id, content_job_id, content_type, metric_source, and provenance_reference are mandatory.
- title_at_snapshot, topic, topic_domain, language, duration_seconds, publication_timestamp, thumbnail_identity, and prompt_template_version are retained descriptors.
- cumulative metrics and rate metrics are included explicitly.
- partial-data and quality metadata are included explicitly.

PROPOSED:
- The schema will use explicit versioning and will reject unsupported versions.

## 11. Metric semantics

CONFIRMED:
- Missing values must remain distinct from zero.
- Cumulative metrics must not be negative.
- Duration must not be negative.
- CTR must use one documented scale consistently.
- Average percentage viewed must use one documented scale consistently.
- Partial snapshots must explicitly identify missing fields.

PROPOSED:
- Metric semantics will be enforced through validation rules rather than silent coercion.

## 12. Append-only storage decision

CONFIRMED:
- Append-only JSONL storage is the preferred implementation choice for this slice because it matches repository conventions and keeps the feature local and testable.

PROPOSED:
- Each canonical channel will have an isolated ledger path rooted under a configurable store directory.
- Existing records will never be rewritten during append.
- Duplicate snapshot_id values will be treated as idempotent no-ops.
- Conflicting payloads for the same snapshot_id will fail loudly.

## 13. Deduplication and idempotency

CONFIRMED:
- Deduplication is enforced through deterministic snapshot_id matching.
- Duplicates must not create additional ledger rows.
- Conflicting duplicates must be treated as hard errors.

## 14. Channel isolation

CONFIRMED:
- Snapshots are channel-scoped and must not be appended into another channel's ledger.
- Cross-channel data mixing is rejected.

## 15. Shorts/long-form treatment

CONFIRMED:
- content_type must explicitly distinguish SHORT and LONG_FORM.
- Shorts and long-form records will be validated separately and not conflated.

## 16. Data-quality guards

CONFIRMED:
- Missing required identity is rejected.
- Naive timestamps are rejected.
- Invalid content_type values are rejected.
- Negative metrics are rejected.
- Invalid CTR and percentage-viewed ranges are rejected.
- Malformed ledger content is rejected.
- Path traversal is rejected.

PROPOSED:
- Partial snapshots are accepted when the required identity, provenance, and quality metadata are present, but they must carry explicit missing-field metadata.

## 17. Provenance and evidence

CONFIRMED:
- provenance_reference is mandatory.
- No secrets, OAuth values, or raw API payloads are stored in snapshots.
- Evidence is tracked through metadata, not by storing live API credentials.

## 18. Error handling

CONFIRMED:
- Validation and storage errors fail closed.
- The implementation will reject malformed or conflicting data rather than silently coerce it.

## 19. Security boundaries

CONFIRMED:
- No production credentials or live environment values are used.
- Paths are validated to remain within the configured root.
- The implementation is limited to local fixture-driven data.

## 20. Test strategy

CONFIRMED:
- Tests will use temporary directories and local fixture dictionaries.
- No network or credentials are required.
- Tests will verify validity, determinism, append-only behavior, duplicate handling, channel isolation, and malformed-ledger failures.

## 21. Observability

PROPOSED:
- Each store operation will expose whether it appended, skipped a duplicate, or failed validation.
- Errors will be surfaced through explicit exceptions and return values.

## 22. Migration and compatibility

PROPOSED:
- The schema version will be explicit and stable for the first slice.
- Future migrations can add fields if a new semantic version is introduced, but the initial B1 model will be strict and documented.

## 23. Rollback/non-impact model

CONFIRMED:
- The implementation remains read-only and does not interact with scheduling, uploads, content generation, or deployment systems.
- If validation fails, the store does not change.

## 24. Milestones

CONFIRMED:
- M1: canonical schema and validation model
- M2: deterministic snapshot identity
- M3: append-only per-channel store
- M4: focused unit tests

## 25. Acceptance criteria

CONFIRMED:
- Valid complete and partial fixtures can be stored.
- Deterministic snapshot IDs are generated.
- Duplicate ingestion is idempotent.
- Conflicting duplicates are rejected.
- Channel mismatch is rejected.
- Malformed store content fails closed.
- No production mutation or network call occurs.

## 26. Exact implementation file scope

CONFIRMED:
- src/analytics_snapshot_foundation.py
- tests/test_analytics_snapshot_foundation.py

## 27. Exact first coding slice

CONFIRMED:
- Implement the immutable snapshot record and validation layer.
- Implement deterministic snapshot ID generation.
- Implement the append-only per-channel store.
- Add focused tests for the accepted behaviors and hard failures.

## 28. Open questions

UNKNOWN:
- Whether later slices will ingest live API data remains open and is intentionally deferred.
- Whether the repository will eventually need a dedicated analytics storage directory is still open.

## 29. Next safe action

CONFIRMED:
- Implement the B1 foundation in the local repository and validate it with targeted tests only.
