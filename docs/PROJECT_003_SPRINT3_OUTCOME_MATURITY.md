# PROJECT 003 Sprint 3 Outcome Maturity Layer

## Scope

Sprint 3 introduces a deterministic Outcome Maturity layer that is append-only, replayable, and advisory-only.

Sprint 3 does not implement prediction, recommendation, causal attribution, or policy mutation.

## Architecture

Sprint 3 implementation layers:
1. Canonical Outcome Maturity contract in src/outcome_maturity_contract.py.
2. Append-only Outcome Maturity Store in src/outcome_maturity_store.py.
3. Replay-derived Outcome Snapshot in src/outcome_snapshot.py.
4. Deterministic audit runner in src/run_outcome_maturity_audit.py.

## Outcome Contract

Required identity fields:
- schema_version
- outcome_record_id
- outcome_event_id
- decision_id
- learning_record_id
- correlation_id
- channel_id
- content_id

Observation identity fields are mandatory:
- observation_window_type
- observation_start
- observation_end
- observation_timestamp

Outcome records without an explicit observation window are invalid.

## Observation Windows

Allowed observation_window_type values:
- ONE_HOUR
- SIX_HOURS
- TWENTY_FOUR_HOURS
- SEVEN_DAYS
- TWENTY_EIGHT_DAYS
- NINETY_DAYS
- LIFETIME

## KPI Category Model

Sprint 3 defines deterministic KPI category metadata only.

Exposure KPI category:
- impressions
- ctr_ratio

Engagement KPI category:
- watch_time_hours
- average_view_duration_seconds
- average_percentage_viewed_ratio

Community KPI category:
- subscribers_gained
- likes
- comments

No scoring, ranking, prediction, or recommendation logic is implemented.

## Outcome Maturity States

Supported states:
- UNKNOWN
- IMMATURE
- PARTIALLY_OBSERVED
- MATURE
- ARCHIVED
- SUPERSEDED

State transitions are append-only and enforced through new events.
Late observations and corrections append new rows; they never overwrite existing history.

## Outcome Store

Store characteristics:
- append-only JSONL source of truth
- deterministic IDs and hashes
- hash-chain protection
- duplicate detection
- corruption detection for malformed and broken chain data
- deterministic replay

## Outcome Snapshot

Outcome Snapshot is replay-derived and not source of truth.

Snapshot properties:
- immutable read model
- deterministic identity and hash
- stable deterministic rebuild from source rows

Future consumers should read Outcome Snapshot while source authority remains the append-only Outcome Store.

## Determinism and Replay

Outcome validation recomputes deterministic hashes and event identifiers.
Replay sorting uses observation_timestamp, created_at, and outcome_event_id.

## Audit

run_outcome_maturity_audit emits deterministic assessment artifacts:
- artifacts/latest/project003_sprint3_outcome_maturity_assessment.json

Artifact includes acceptance matrix, validation summary, hash, and overall status.

## Production Neutrality

Sprint 3 is offline and repository-local.

No YouTube API calls, no VPS interaction, no deployment behavior, and no runtime mutation are part of Sprint 3.

## Backward Compatibility

Sprint 3 is additive and does not modify Sprint 1 or Sprint 2 contracts.

Backward-compatibility and adjacent regression gates remain required.
