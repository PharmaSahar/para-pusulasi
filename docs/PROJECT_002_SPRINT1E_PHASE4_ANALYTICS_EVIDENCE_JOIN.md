# PROJECT 002 Sprint 1E Phase 4 - Analytics Evidence Join Foundation

## Scope and Safety
This phase introduces a deterministic analytics evidence bridge.

Safety constraints preserved:
- advisory-only
- append-only storage
- default-off runtime
- fail-open behavior
- no deployment
- no VPS access
- no production modifications
- no scheduler/uploader/generation/CQGA logic changes
- no analytics collector behavior mutation
- `pipeline_output_changed=false`

## Architecture

### New module
- `src/analytics_evidence_join.py`

Responsibilities:
- analytics source inventory
- immutable analytics evidence model
- deterministic join rules with strict priority
- append-only join store with duplicate protection
- malformed row tolerance
- replay and deterministic ordering
- coverage metrics and CQGA impact estimate (advisory)

### Runtime integration
- `src/pipeline.py`

Runtime gate:
- `ANALYTICS_EVIDENCE_JOIN_ENABLED=true|false`

Optional output path override:
- `ANALYTICS_EVIDENCE_JOIN_PATH`

Default output path:
- `logs/analytics_evidence_join.jsonl`

Capture mode:
- single fail-open append from pipeline snapshot context
- no decision mutation

### Assessment runner
- `tools/project002_sprint1e_phase4_analytics_evidence_join.py`

Outputs:
- `artifacts/latest/project002_sprint1e_phase4_analytics_evidence_join/analytics_evidence_join_dry_run.json`
- `artifacts/latest/project002_sprint1e_phase4_analytics_evidence_join/assessment_summary.json`
- `artifacts/latest/project002_sprint1e_phase4_analytics_evidence_join/coverage_report.json`
- `artifacts/latest/project002_sprint1e_phase4_analytics_evidence_join/cqga_impact_estimate.json`

## Source Inventory (Phase 1)
Audited local analytics-related sources:
- `logs/channel_performance.jsonl`
- `logs/analytics_feedback.jsonl`
- `output/runtime/evidence/*.json`
- `output/state/content_ownership/*.json`

Inventory includes:
- availability
- row/file count
- malformed count

## Immutable Join Model (Phase 2)
Core fields:
- analytics_record_id
- content_id
- run_id
- upload_id
- channel_id
- snapshot_time
- metrics_version
- provenance
- advisory_only

Metric representation:
- `observed`
- `unavailable`
- `unknown`

No guessed defaults are injected for missing metrics.

## Deterministic Join Rules (Phase 3)
Priority order:
1. content_id
2. upload_id
3. run_id
4. ownership linkage

Explicitly forbidden linkage:
- title similarity
- filename similarity
- timestamp proximity
- semantic similarity

## Storage, Replay, Validation (Phase 4)
Store behavior:
- append-only JSONL
- schema validation
- duplicate protection by deterministic analytics_record_id
- deterministic serialization

Replay behavior:
- malformed row tolerance
- deterministic ordering by snapshot_time and analytics_record_id

## Coverage Metrics (Phase 5)
Reported metrics:
- analytics join rate
- upload linkage
- ownership linkage
- unresolved analytics
- orphan analytics
- ambiguous joins

## CQGA Impact Estimate (Phase 6)
No CQGA code modification was made.
Advisory estimate reports potential lift for:
- hook validation
- retention analysis
- CTR reasoning
- root-cause confidence
- recommendation confidence

Method:
- coverage-weighted estimation only
- non-binding, advisory artifact

## Tests (Phase 7)
Added tests:
- `tests/test_analytics_evidence_join_model.py`
- `tests/test_analytics_evidence_join_engine.py`
- `tests/test_analytics_evidence_join_store.py`
- `tests/test_analytics_evidence_join_replay.py`
- `tests/test_analytics_evidence_join_regression.py`
- `tests/test_analytics_evidence_join_pipeline_integration.py`

Validation includes:
- model validation
- deterministic join priority
- replay determinism
- duplicate protection
- regression guard against forbidden joins
- pipeline default-off/fail-open integration

## Limitations and Future Integration
Current limits:
- historical artifacts may be sparse in local workspace
- unresolved joins remain explicit when deterministic anchors are absent
- no retrospective guessing

Future Learning Engine integration (out of scope in this phase):
- consume analytics evidence join artifacts as trustable feature layer
- keep deterministic lineage prerequisites mandatory
