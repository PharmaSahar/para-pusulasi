# PROJECT 002 Sprint 1E Phase 2 - Planning-Blueprint-Script Evidence Linkage

## Scope and Safety
This phase adds deterministic, advisory-only evidence linkage for future runs.

Safety invariants:
- default-off runtime gate
- append-only JSONL evidence
- fail-open behavior
- no runtime decision mutation
- no generation behavior mutation
- no scheduler mutation
- no uploader mutation
- no CQGA mutation
- no production change
- `pipeline_output_changed=false`

## Architecture

### New module
- `src/planning_blueprint_lineage_evidence.py`

Responsibilities:
- canonical planning lineage record model
- explicit linkage status classification
- append-only evidence storage
- deterministic replay reconstruction
- identifier audit (canonical/duplicate/missing/inferred)
- historical linkage dry-run assessment

### Pipeline integration
- file: `src/pipeline.py`
- gate: `PLANNING_BLUEPRINT_LINEAGE_EVIDENCE_ENABLED` (default false)
- storage path override: `PLANNING_BLUEPRINT_LINEAGE_EVIDENCE_PATH`

Capture points:
1. after generation/regeneration (`INITIAL_GENERATION`, `FACT_CHECK_REGENERATION`, `QUALITY_REGENERATION`)
2. before TTS finalization pass (`FINALIZED` or last known stage)

Failure behavior:
- all capture failures are warning-only
- pipeline continues without retrying lineage writes

## Identifier Audit (Phase 1)
Output:
- `artifacts/latest/project002_sprint1e_phase2_planning_blueprint_linkage/identifier_audit.json`

Audited identifiers:
- planning_context_id
- blueprint_id
- blueprint_hash
- prompt_metadata_hash
- experiment_id
- content_id
- run_id
- ownership_id

Observed summary (sample_count=300):
- canonical blueprint_id: 300
- canonical blueprint_hash: 300
- canonical prompt_metadata_hash: 185
- canonical content_id: 300
- canonical run_id: 300
- canonical ownership_id: 300
- duplicate prompt_metadata_hash buckets: 1
- missing prompt_metadata_hash: 115
- missing run_id in runtime evidence projection path: 300
- inferred ids detected by heuristic: 0

Interpretation:
- planning and blueprint identifiers are available in shadow planning artifacts.
- runtime evidence remains run-id sparse historically, preventing deterministic linkage without guessing.

## Planning Lineage Model (Phase 2/3)
Each immutable record contains:
- `planning_context_id`
- `blueprint_id`
- `blueprint_hash`
- `prompt_metadata_hash`
- `experiment_id`
- `content_id`
- `run_id`
- `script_hash`
- `link_status`
- `created_at`
- `schema_version`
- `advisory_only`

Additional metadata:
- `evidence_id` (deterministic)
- `source_stage`
- `generation_attempt`
- `pipeline_output_changed`

Link statuses:
- `LINKED`
- `PARTIAL`
- `MISSING`
- `AMBIGUOUS`
- `INVALID`

Status rules are deterministic and avoid inferred joins.

## Storage (Phase 4)
Path:
- `logs/planning_blueprint_lineage_evidence.jsonl`

Properties:
- append-only writes
- schema validation before write
- deterministic JSON serialization (`sort_keys=True`)
- malformed-row tolerance on read
- duplicate protection by deterministic `evidence_id`
- replay reconstruction by `content_id::run_id`

## Historical Dry-run (Phase 6)
Output:
- `artifacts/latest/project002_sprint1e_phase2_planning_blueprint_linkage/historical_linkage_dry_run_report.json`

Result (sample_count=300):
- linked: 0
- partial: 0
- missing: 0
- ambiguous: 0
- invalid: 300
- planning linked: 0
- blueprint linked: 0
- prompt metadata linked: 0
- fully traceable: 0

Reason:
- historical runtime evidence often lacks deterministic `run_id`; exact joins to planning/blueprint/prompt metadata cannot be established without guessing.

## Coverage Metrics (Phase 7)
Output:
- `artifacts/latest/project002_sprint1e_phase2_planning_blueprint_linkage/coverage_metrics.json`

Observed rates:
- planning linkage rate: 0.00%
- blueprint linkage rate: 0.00%
- prompt metadata linkage rate: 0.00%
- fully traceable content rate: 0.00%
- partial traceability rate: 0.00%
- ambiguous traceability rate: 0.00%
- missing traceability rate: 100.00%

## CQGA Impact Estimate (Phase 8, qualitative only)
Output:
- `artifacts/latest/project002_sprint1e_phase2_planning_blueprint_linkage/cqga_impact_estimate.json`

Estimated impacts (no CQGA change implemented):
- root cause analysis: HIGH
- planning consistency: HIGH
- blueprint consistency: HIGH
- duplicate detection: MEDIUM
- narrative analysis: MEDIUM
- hook analysis: MEDIUM

## Tests (Phase 9)
Added tests:
- `tests/test_planning_blueprint_lineage_evidence_model.py`
- `tests/test_planning_blueprint_lineage_evidence_store.py`
- `tests/test_planning_blueprint_lineage_evidence_pipeline_integration.py`
- `tests/test_planning_blueprint_lineage_evidence_replay.py`
- `tests/test_planning_blueprint_lineage_evidence_legacy_assessment.py`
- `tests/test_planning_blueprint_lineage_evidence_traceability.py`

Coverage areas:
- model invariants
- storage append/duplicate/tolerance
- pipeline default-off and fail-open behavior
- replay state reconstruction
- dry-run historical assessment
- identifier audit and traceability classification

## Performance
Output:
- `artifacts/latest/project002_sprint1e_phase2_planning_blueprint_linkage/performance_benchmarks.json`

Measured locally:
- append one event: low millisecond scale
- append 100 events: low tens of milliseconds scale
- replay benchmark events: low millisecond scale

## Limitations
- no historical regeneration is performed
- no guessed relationships are introduced
- linkage is constrained by existing run-id availability
- this phase does not include analytics enrichment
- this phase does not include thumbnail enrichment

## Future Analytics Integration Boundary
Phase 2 exposes deterministic lineage keys that can be used later for analytics joins:
- `content_id`
- `run_id`
- `script_hash`
- `planning_context_id`
- `blueprint_id`
- `blueprint_hash`
- `prompt_metadata_hash`

No analytics joins are activated in this phase.

## Safety Confirmation
- no deploy
- no VPS access
- no production mutation
- no scheduler behavior change
- no uploader behavior change
- no generation behavior change
- no CQGA logic/scoring/threshold change
- no runtime decision mutation
