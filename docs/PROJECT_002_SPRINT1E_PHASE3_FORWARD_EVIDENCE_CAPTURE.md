# PROJECT 002 Sprint 1E Phase 3 - Forward Evidence Capture and Complete Traceability

## Scope and Safety
This phase adds forward-only evidence capture for newly produced content sessions.

Safety constraints preserved:
- advisory-only
- append-only output artifacts
- fail-open runtime behavior
- default-off runtime gate
- no production interaction
- no behavior mutation on generation/render/upload decisions
- no historical backfill guessing
- `pipeline_output_changed=false`

## Architecture

### New module
- `src/forward_evidence_capture.py`

Responsibilities:
- forward stage taxonomy for deterministic capture
- session/event model validation
- append-only JSONL store with duplicate protection
- replay and state reconstruction
- integrity checks for stage continuity and lineage consistency
- completeness scoring for planning-to-upload traceability

### Runtime integration
- `src/pipeline.py`

Integration points (all fail-open, default-off):
- planning complete
- blueprint finalized
- prompt finalized
- script finalized
- thumbnail finalized
- render complete
- ownership finalized
- upload complete

Runtime gate:
- `FORWARD_EVIDENCE_CAPTURE_ENABLED=true|false`

Optional output path override:
- `FORWARD_EVIDENCE_CAPTURE_PATH`

Default output path:
- `logs/forward_evidence_capture.jsonl`

### Runner tool
- `tools/project002_sprint1e_phase3_forward_evidence_capture.py`

Outputs:
- `artifacts/latest/project002_sprint1e_phase3_forward_evidence_capture/assessment_summary.json`
- `artifacts/latest/project002_sprint1e_phase3_forward_evidence_capture/integrity_report.json`
- `artifacts/latest/project002_sprint1e_phase3_forward_evidence_capture/completeness_report.json`

## Deterministic Session and Event Model
Session key:
- deterministic hash of `content_id + run_id`

Event key:
- deterministic hash of `session_id + stage + stage_order + explicit evidence keys`

No non-deterministic joins are used.
No inferred historical bridges are introduced.

## Integrity and Completeness
Integrity checks include:
- missing mandatory stages
- duplicate stages
- broken lineage indicators (missing script/render/upload evidence)
- unexpected stage ordering
- orphan evidence

Completeness scores include:
- planning coverage
- blueprint coverage
- prompt coverage
- script coverage
- thumbnail coverage
- render coverage
- upload coverage
- lineage completeness
- overall traceability

## Tests Added
- `tests/test_forward_evidence_capture_model.py`
- `tests/test_forward_evidence_capture_store.py`
- `tests/test_forward_evidence_capture_replay.py`
- `tests/test_forward_evidence_capture_pipeline_integration.py`

Coverage intent:
- model validation and deterministic IDs
- append-only and malformed row tolerance
- replay and scoring consistency
- pipeline integration behavior parity (default-off vs enabled)
- fail-open behavior under storage failures

## Non-Goals
- no thumbnail lineage phase work
- no analytics join phase work
- no runtime business logic mutation
- no deployment or VPS operations
