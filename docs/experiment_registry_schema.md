# Experiment Registry Schema

## Purpose
Provide a single source of truth for all performance experiments so decisions remain auditable over time.

## 1. Entity: Experiment

### Required Fields
1. `experiment_id`
2. `hypothesis`
3. `variant`
4. `randomization_unit`
5. `stratification`
6. `start_date`
7. `end_date`
8. `kpi`
9. `minimum_sample`
10. `significance_method`
11. `winner`
12. `rollback_status`
13. `status`
14. `schema_version`

### Field Guidance
- `experiment_id`: unique immutable identifier (example `EXP-2026-07-001`).
- `hypothesis`: explicit directional expectation.
- `variant`: control/treatment definition.
- `randomization_unit`: MVP default is `video`.
- `stratification`: channel/topic/publish slot dimensions.
- `kpi`: primary KPI plus optional guardrail KPIs.
- `minimum_sample`: minimum impressions and/or minimum days.
- `significance_method`: fixed before exposure starts.
- `winner`: `control`, `treatment`, `inconclusive`, or `pending`.
- `rollback_status`: `none`, `triggered`, `completed`.
- `status`: lifecycle state machine status.
- `schema_version`: document/model version marker for forward compatibility.

## 2. State Machine

Allowed states:
- `draft`
- `active`
- `completed`
- `rolled_back`
- `archived`

Allowed transitions:
1. `draft` -> `active`
2. `active` -> `completed`
3. `active` -> `rolled_back`
4. `completed` -> `archived`
5. `rolled_back` -> `archived`

Transition rules:
- No direct `draft` -> `completed`.
- `winner` can be finalized only in `completed`.
- `rollback_status=triggered|completed` requires `status=rolled_back` or archived history containing rolled_back event.

## 3. Lifecycle

1. Create experiment in `draft` with required metadata.
2. Validate configuration and activate (`active`).
3. Track exposure and KPI observations while active.
4. Close experiment as `completed` (winner selected) or `rolled_back` (rollback executed).
5. Move closed records to `archived` state after reporting is finalized.

MVP note:
- Lifecycle execution is manual/operator-driven at first; automation is out of scope for Sprint 2.1.

## 4. Storage Format

### Initial Storage (MVP)
- Append-only JSONL file.
- One record per event or snapshot append (do not rewrite history in-place).
- Recommended path pattern: `output/telemetry/experiments.jsonl`.

### Forward-Compatible Model
- Schema must map cleanly to tabular storage for SQLite/PostgreSQL.
- Keep stable field names and explicit timestamps to allow ETL migration.
- Preserve immutable `experiment_id` as primary linkage key across stores.

## 5. Event Flow

MVP event sequence:
1. `experiment_created` (status=`draft`)
2. `experiment_activated` (status=`active`)
3. `experiment_observation_appended` (0..N times)
4. `experiment_completed` OR `experiment_rolled_back`
5. `experiment_archived`

Event requirements:
- Every event must include `experiment_id`, `occurred_at`, and `schema_version`.
- Events are append-only; correction is a new event, not mutation.

## 6. Failure Cases

1. ID collision
- Behavior: reject write and log error event.

2. Invalid state transition
- Behavior: reject transition and keep previous valid state.

3. Missing required metadata
- Behavior: reject create/activate action.

4. Partial write / corrupted JSON line
- Behavior: fail current append, preserve existing lines, emit write failure signal.

5. Winner set before completion
- Behavior: reject update unless status is `completed`.

6. Rollback flagged without rollback state
- Behavior: reject update or auto-normalize via explicit `experiment_rolled_back` event.

## 7. Retention Policy

- Keep raw append-only JSONL history for auditability.
- Minimum recommended retention: 12 months.
- Archived experiments remain queryable; no hard delete in MVP.
- If compaction is needed later, compaction artifacts must preserve event ordering and IDs.

## 8. Versioning

- Use explicit `schema_version` in every experiment record/event.
- MVP starts at `v1`.
- Backward-incompatible field changes require version bump.
- Migration strategy for future stores:
  - keep `v1` reader,
  - add versioned transformer,
  - write new events in latest version only.

## Example Record
```json
{
  "schema_version": "v1",
  "experiment_id": "EXP-2026-07-001",
  "hypothesis": "Thumbnail policy v2 increases CTR by at least 10% vs control.",
  "variant": {
    "control": "thumbnail_policy_v1",
    "treatment": "thumbnail_policy_v2"
  },
  "randomization_unit": "video",
  "stratification": ["channel_id", "topic_cluster", "publish_slot"],
  "start_date": "2026-07-15",
  "end_date": "2026-07-22",
  "kpi": {
    "primary": "ctr",
    "guardrails": ["first_30s_retention", "thumbnail_validation_pass_rate"]
  },
  "minimum_sample": {
    "impressions": 10000,
    "min_days": 7
  },
  "significance_method": "frequentist_95_confidence",
  "status": "completed",
  "winner": "treatment",
  "rollback_status": "none",
  "start_date": "2026-07-15",
  "end_date": "2026-07-22"
}
```

## 9. Sprint 2.1 Minimum Acceptance Criteria

1. Experiment oluşturulabilir.
2. ID üretilebilir.
3. Metadata kaydedilebilir.
4. Status değiştirilebilir.
5. Winner ve rollback alanları tutulabilir.
6. JSONL kayıtları append-only olmalı.
7. Kod daha sonra eklenecek; bu adım sadece şema dokümanı.

## Operational Rules
- No experiment result can be accepted without minimum sample and significance method.
- No winner can be declared without explicit registry update.
- Any rollback must reference a valid experiment ID.
