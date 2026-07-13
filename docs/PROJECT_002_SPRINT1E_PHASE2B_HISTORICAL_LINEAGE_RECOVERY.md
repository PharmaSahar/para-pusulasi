# PROJECT 002 Sprint 1E Phase 2B - Historical Lineage Recovery (Deterministic, Non-Guessing)

## Scope and Safety
This phase performs dry-run historical recovery using deterministic evidence only.

Safety constraints preserved:
- advisory-only
- append-only output artifacts
- fail-open operation
- default-off runtime behavior
- no production interaction
- no historical artifact mutation
- no prompt/scheduler/uploader/generation/CQGA/planning/blueprint mutation
- `pipeline_output_changed=false`

## Recovery Architecture

### New module
- `src/historical_lineage_recovery.py`

Responsibilities:
- evidence source inventory
- deterministic recovery graph definition
- proven-only recovery model
- historical chain recovery engine
- dry-run reporting
- coverage before/after/delta computation
- random sample quality audit

### Runner tool
- `tools/project002_sprint1e_phase2b_historical_lineage_recovery.py`

Outputs:
- `artifacts/latest/project002_sprint1e_phase2b_historical_lineage_recovery/historical_recovery_report.json`
- `artifacts/latest/project002_sprint1e_phase2b_historical_lineage_recovery/assessment_summary.json`
- `artifacts/latest/project002_sprint1e_phase2b_historical_lineage_recovery/coverage_delta.json`
- `artifacts/latest/project002_sprint1e_phase2b_historical_lineage_recovery/quality_audit.json`

## Evidence Sources (Inventory)
Audited sources include:
- runtime evidence (`output/runtime/evidence`)
- content ownership (`output/state/content_ownership`)
- script lineage (`logs/script_lineage_evidence.jsonl`)
- shadow planning (`logs/shadow_generation_planning.jsonl`)
- shadow alignment (`logs/shadow_blueprint_prompt_alignment.jsonl`)
- prompt experiments (`logs/shadow_prompt_experiments.jsonl`)
- offline prompt candidates (`logs/offline_prompt_candidates.jsonl`)

Observed inventory in this run:
- runtime rows: 300
- ownership rows: 808
- planning rows: 394
- alignment rows: 372
- script lineage rows: 0
- prompt experiment rows + alignment prompt hashes: 543

## Deterministic Recovery Graph
Edge priority:
1. explicit IDs
2. canonical hashes
3. ownership linkage
4. content_id + run_id
5. validated blueprint hash

Allowed deterministic edges:
- runtime -> ownership via exact `content_id`
- ownership -> planning via exact `run_id`
- planning -> alignment via exact `run_id` + exact `blueprint_hash`
- alignment -> script via exact `run_id` + exact prompt hash along the ownership chain
- script -> render via runtime render record presence
- script -> upload via runtime upload video_id presence

Forbidden inference:
- filename similarity
- title similarity
- timestamp proximity
- semantic similarity
- AI inference
- manual guessing

## Recovery Model
Each recovered link stores:
- `recovery_id`
- `source_record`
- `target_record`
- `recovery_method`
- `confidence`
- `proof`
- `link_type`
- `created_at`
- `advisory_only`

Confidence policy:
- only `PROVEN`

No `LIKELY` / `POSSIBLE` levels are allowed.

## Recovery Results (Dry-run)
From `historical_recovery_report.json`:
- recoverable: 162
- unrecoverable: 138
- ambiguous: 0
- duplicates: 0
- orphan records: 138
- broken chains: 138
- runtime total: 300

Interpretation:
- deterministic ownership links were recoverable for 162 records
- 138 records remain broken due to missing ownership/run-id chain continuation
- no guessed links were introduced

## Coverage Delta
Before:
- planning linkage: 0.0%
- blueprint linkage: 0.0%
- prompt metadata linkage: 0.0%
- fully traceable content: 0.0%
- ownership linkage: 0.0%
- script lineage: 0.0%

After deterministic recovery:
- planning linkage: 0.0%
- blueprint linkage: 0.0%
- prompt metadata linkage: 0.0%
- fully traceable content: 0.0%
- ownership linkage: 54.0%
- script lineage: 0.0%

Delta:
- ownership linkage: +54.0 points
- other lineage dimensions: +0.0 points

Reason for limited lift:
- script lineage historical store is absent (`logs/script_lineage_evidence.jsonl` missing)
- many runtime rows still lack deterministic run-id continuity to planning/alignment

## Quality Audit
Random sample audit (`sample_size=25`) reports:
- no guessed links: true
- no duplicate chains: true
- no invalid joins: true
- stable replay: true

## Limitations and Gaps
Remaining deterministic gaps:
- no historical script lineage events to anchor script-level joins
- many orphan runtime records without ownership match
- no deterministic bridge to elevate planning/blueprint/prompt rates in this historical slice

## Future Migration Strategy
To improve historical determinism without guessing:
1. preserve ownership manifests for all pipeline outcomes
2. ensure run_id is persisted in runtime evidence for every record
3. persist script lineage events for all future runs (already available prospectively)
4. keep blueprint_hash and prompt_hash in aligned logs with strict run_id continuity

## Safety Confirmation
- no deploy
- no production access
- no historical file rewrite
- no content regeneration
- no prompt/scheduler/uploader/generation mutation
- no CQGA/planning/blueprint behavior mutation
- no Phase 3 work started
