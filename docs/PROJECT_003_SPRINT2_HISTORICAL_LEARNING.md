# PROJECT 003 Sprint 2 Historical Learning Foundation

## Scope

Sprint 2 introduces the historical learning truth layer as append-only, deterministic, replayable infrastructure.

It does not implement prediction, recommendation, attribution logic, policy mutation, or runtime automation.

## Architecture

Sprint 2 implementation layers:
1. Canonical Learning Record contract in src/learning_record_contract.py.
2. Historical Learning Store in src/historical_learning_store.py.
3. Replay-derived Learning Index in src/learning_feature_projection.py.
4. Deterministic audit runner in src/run_historical_learning_audit.py.

## Learning Record

Required identity:
- schema_version
- learning_record_id
- learning_event_id
- decision_id
- correlation_id
- channel_id
- content_id
- content_type

Observation window fields:
- window_type
- window_start
- window_end
- measurement_timestamp

Evidence references:
- decision_record_ref
- analytics_evidence_refs
- cqga_evidence_refs
- runtime_evidence_refs
- experiment_evidence_refs

Observed metrics in Sprint 2 only:
- impressions
- views
- ctr_ratio
- watch_time_hours
- average_view_duration_seconds
- average_percentage_viewed_ratio
- subscribers_gained
- likes
- comments

Excluded from Sprint 2:
- revenue and monetization fields
- confidence and prediction fields

## Learning Quality

Included quality fields:
- metric_completeness
- evidence_completeness
- sample_sufficiency
- provisional_status
- unknown_reasons

Unknown and unavailable states are preserved. Unknown is never coerced into zero.

## Maturity Model

Supported states:
- UNKNOWN
- IMMATURE
- PARTIALLY_OBSERVED
- MATURE
- ARCHIVED
- SUPERSEDED

Transitions are append-only through new events. Late metrics and corrections append new rows and never overwrite existing rows.

## Outcome Attribution Extension Point

Sprint 2 defines a reserved attribution_extension interface placeholder in the learning record.

No attribution logic, causal scoring, winner selection, or optimization is implemented.

## Historical Learning Store

Store characteristics:
- append-only JSONL source of truth
- deterministic IDs and hashes
- hash-chain protected rows
- duplicate and conflict handling
- corruption detection (malformed, truncated, unsupported schema, chain breaks)
- deterministic replay and projection rebuild

## Learning Index

Learning Index is a replay-derived projection and not source of truth.

Initial index fields:
- learning_record_id
- decision_id
- channel_id
- content_id
- topic
- content_type
- publish_slot
- impressions
- views
- ctr_ratio
- watch_time_hours
- average_view_duration_seconds
- subscribers_gained
- maturity_state
- metric_completeness
- evidence_completeness

## Decision Memory Integration

Sprint 2 links to Sprint 1 Decision Memory through decision identifiers and typed references.

Decision records are not fabricated. Existing historical content without full linkage is represented with explicit unknown reasons.

## Determinism and Replay

Canonical record validation recomputes deterministic record_hash and learning_event_id.

Replay sorting uses measurement_timestamp, created_at, and learning_event_id to ensure stable projection outputs.

## Audit

run_historical_learning_audit emits deterministic assessment artifacts:
- artifacts/latest/project003_sprint2_learning_assessment.json

Artifact includes acceptance matrix, validation summary, hash, and overall status.

## Security and Production Neutrality

Sprint 2 is offline and repository-local.

No YouTube API access, VPS interaction, deployment, scheduler mutation, uploader mutation, or runtime behavior change is part of Sprint 2 foundation.

## Backward Compatibility

Sprint 2 is additive and keeps Sprint 1 contracts unchanged.

Adjacent Sprint 1 and Project 002 compatibility tests remain required validation gates.
