# PROJECT 002 Sprint 1E Phase 1 - Script Continuity and Content-Lineage Evidence Enrichment

## Scope and Safety
This phase implements advisory-only, prospective, local evidence enrichment for script lineage.

Explicit non-goals in this phase:
- no historical content regeneration
- no CQGA scoring/taxonomy/threshold change
- no prompt change
- no scheduler decision change
- no uploader behavior change
- no production rollout
- no deploy

Safety guarantees:
- disabled by default
- append-only evidence write
- fail-open behavior
- non-blocking behavior
- non-mutating behavior
- backward-compatible pipeline flow
- `pipeline_output_changed=false`

## Step 1 Baseline (Worktree Safety)
At phase start:
- repository root: `/Users/klara/Projects/parapusulasi`
- branch: `master`
- HEAD: `f5e30233d112431e4d86b834d5a298a77fdd31b8`
- upstream: `origin/master`
- worktree: clean
- staged files: none
- modified files: none
- untracked files: none

No overlapping local changes were detected.

## Step 2 Script Lifecycle Map (Authoritative)

### Lifecycle Graph
Topic -> PlanningContext -> GenerationBlueprint -> Prompt Metadata -> Initial Script -> Optional Regeneration/Rewrite -> Final Script -> Render -> Shorts Derivation -> Upload Evidence -> CQGA Evidence

### Stage Inventory
1. Topic selection and content generation
- Producer: `src/content_generator.py` (`ContentGenerator.generate_and_save`)
- Consumer: `src/pipeline.py` (`run_full_pipeline`)
- Identifier(s): `content_id`, `run_id`, `channel_id`, topic provenance payload
- Storage: `output/scripts/*.json` via `VideoContent.save`
- Completeness now: full script exists in script file, but not deterministically linked in lineage store before this phase
- Replacement behavior: regenerations re-run generation and can replace active in-memory `content`
- Failure behavior: fail-open/retry logic in pipeline, then block only by existing quality gates

2. Planning/blueprint shadow artifacts
- Producer: `src/shadow_generation_planning.py`
- Consumer: `src/pipeline.py` and shadow analyzers
- Identifier(s): `run_id`, `blueprint_id`, `blueprint_hash`, `channel_id`
- Storage: `logs/shadow_generation_planning.jsonl`
- Completeness now: present in shadow mode, advisory-only, link to script previously indirect
- Replacement behavior: append-only shadow row per run
- Failure behavior: fail-open fallback object in pipeline

3. Prompt metadata
- Producer: `src/content_generator.py` (prompt metadata in `VideoContent`)
- Consumer: pipeline shadow alignment + analytics metadata
- Identifier(s): prompt metadata hash (new in this phase), experiment id
- Storage: in-memory result payload and script JSON
- Completeness now: available per generated content, but no canonical script-lineage storage before this phase
- Replacement behavior: regenerated script carries refreshed prompt metadata
- Failure behavior: fail-open

4. Ownership preview and artifact linkage
- Producer: `src/upload_precheck.py` (`persist_ownership_manifest`)
- Consumer: upload precheck and audits
- Identifier(s): `content_id`, `run_id`, `channel_id`
- Storage: `output/state/content_ownership/content_*_run_*.json`
- Completeness now: preview-only (`script_preview`), not full script continuity
- Replacement behavior: per content/run manifest write
- Failure behavior: precheck blocks upload if ownership tuple/hash checks fail

5. Render and shorts consumption
- Producer: `src/video_creator.py`, `src/shorts_creator.py`
- Consumer: pipeline upload stage and observability
- Identifier(s): `content_id`, `run_id`, media paths
- Storage: output media files + runtime evidence payload
- Completeness now: media linkage available; script version consumed not explicit before this phase
- Replacement behavior: retries may re-render
- Failure behavior: shorts fail-open; main render exceptions fail stage

6. Upload linkage and runtime evidence
- Producer: `src/pipeline.py` upload stage + `src/production_quality_platform.py` (`write_production_evidence`)
- Consumer: dashboards, audits, CQGA input assembly
- Identifier(s): `content_id/generation_id`, `video_id`, URLs
- Storage: `output/runtime/evidence/content_*.json`
- Completeness now: script hash in runtime evidence, but no version chain
- Replacement behavior: append/write per run result
- Failure behavior: fail-open for evidence write

## Step 3 Canonical Script Evidence Model
Implemented in [src/script_lineage_evidence.py](src/script_lineage_evidence.py).

Schema version:
- `v1`

Core identity fields:
- `evidence_id`
- `content_id`
- `run_id`
- `canonical_channel_id`
- `content_type`

Script continuity fields:
- `script_hash`
- `normalized_script_hash`
- `script_length_chars`
- `script_word_count`
- `script_sentence_count`
- `script_version`
- `parent_script_hash`
- `supersedes_script_hash`

Lineage linkage fields:
- `planning_context_id`
- `blueprint_id`
- `blueprint_hash`
- `prompt_metadata_hash`
- `experiment_id`
- `lineage_link_status`

State and stage fields:
- `script_completeness_state`
- `script_source_stage`
- `generation_attempt`
- `regeneration_reason`
- `created_at`
- `finalized_at`
- `render_consumed`
- `shorts_consumed`
- `upload_result_linked`

Invariant fields:
- `advisory_only=true`
- `pipeline_output_changed=false`

Explicit completeness states:
- `COMPLETE`
- `PARTIAL`
- `PREVIEW_ONLY`
- `MISSING`
- `INVALID`
- `UNKNOWN`

Explicit source stages:
- `INITIAL_GENERATION`
- `FACT_CHECK_REGENERATION`
- `QUALITY_REGENERATION`
- `EDITOR_REWRITE`
- `MANUAL_OVERRIDE`
- `LEGACY_IMPORT`
- `UNKNOWN`

Typed lineage status:
- `LINKED`
- `PARTIAL`
- `MISSING`
- `AMBIGUOUS`
- `INVALID`

## Step 4 Privacy and Retention Policy
Centralized retention modes implemented:
- `HASH_ONLY`
- `BOUNDED_EXCERPT`
- `FULL_LOCAL_SCRIPT`

Default mode:
- `HASH_ONLY`

Rules:
- deterministic hashes are always persisted
- full script excerpt persistence is controlled by retention mode only
- secret-like content is rejected in excerpt paths
- no credentials/tokens/secrets are persisted in excerpts
- no script is written into exception text by lineage module

Configuration:
- `SCRIPT_LINEAGE_RETENTION_MODE` (default `HASH_ONLY`)
- `SCRIPT_LINEAGE_EXCERPT_MAX_CHARS` (bounded, sanitized)

## Step 5 Stable Identifiers and Join Keys
Deterministic joins now defined around:
- `content_id`
- `run_id`
- `script_hash`
- `script_version`
- `planning_context_id`
- `blueprint_id`
- `blueprint_hash`
- `prompt_metadata_hash`
- `experiment_id`

No joins are performed by title-only, filename guess-only, or timestamp-only.
Missing links are represented explicitly using lineage status enums.

## Step 6 Version and Supersession Model
Version behavior (append-only):
- initial generation -> version 1
- regeneration/rewrite with changed script hash -> new immutable version
- previous version preserved and superseded deterministically
- identical retry (same script hash) -> no false new version; linkage update event
- finalized script is explicitly marked via `SCRIPT_FINALIZED`
- history is replayable and deterministic

## Step 7 Append-only Script Evidence Store
Path:
- `logs/script_lineage_evidence.jsonl`

Capabilities implemented:
- append-only JSONL writes
- schema validation before write
- malformed-line tolerance during load
- idempotent duplicate evidence-id ingestion
- deterministic serialization (`sort_keys=True`)
- replay to reconstruct current/final script state
- invalid row diagnostics
- no in-place rewrite

Supported event types:
- `SCRIPT_CREATED`
- `SCRIPT_FINALIZED`
- `SCRIPT_SUPERSEDED`
- `SCRIPT_CONSUMED_BY_RENDER`
- `SCRIPT_CONSUMED_BY_SHORTS`
- `SCRIPT_LINKED_TO_UPLOAD`
- `LINEAGE_LINK_UPDATED`
- `SCRIPT_INVALIDATED`

## Step 8 Prospective Pipeline Integration
Integrated in [src/pipeline.py](src/pipeline.py), gated by:
- `SCRIPT_LINEAGE_EVIDENCE_ENABLED`

Default:
- disabled

Capture points implemented:
1. after script generation (`SCRIPT_CREATED`)
2. after each regeneration/rewrite (`SCRIPT_CREATED` or idempotent `LINEAGE_LINK_UPDATED`)
3. final selection before TTS (`SCRIPT_FINALIZED`)
4. before render consumes script (`SCRIPT_CONSUMED_BY_RENDER`)
5. when shorts consumes script (`SCRIPT_CONSUMED_BY_SHORTS`)
6. after successful upload link (`SCRIPT_LINKED_TO_UPLOAD`)

Fail-open behavior:
- any lineage write failure logs warning and continues pipeline
- no retries are triggered by lineage component
- no generation blocking
- no upload blocking

## Step 9 Minimum Planning/Blueprint Linkage
When available, script evidence links:
- `planning_context_id` (from shadow planning context/run)
- `blueprint_id`
- `blueprint_hash`
- `prompt_metadata_hash`
- `experiment_id`

When unavailable:
- lineage status marked `MISSING` or `PARTIAL`
- pipeline continues normally
- no guessed linkage is introduced

## Step 10 Legacy Import Assessment (Dry-run)
Dry-run only in this phase.

Assessment artifacts:
- [artifacts/latest/project002_sprint1e_phase1_script_lineage/legacy_import_dry_run_report.json](artifacts/latest/project002_sprint1e_phase1_script_lineage/legacy_import_dry_run_report.json)
- [artifacts/latest/project002_sprint1e_phase1_script_lineage/assessment_summary.json](artifacts/latest/project002_sprint1e_phase1_script_lineage/assessment_summary.json)

Sample size:
- 300

Classification result:
- full script recoverable: 0
- preview only: 2
- hash-only recoverable: 298
- ambiguous: 0
- unrecoverable: 0

Dry-run behavior:
- no source artifact mutation
- no bulk import execution
- report-only output
- imported stage semantics reserved for `LEGACY_IMPORT` when enabled later

## Step 11 Coverage and Continuity Metrics
Coverage report:
- [artifacts/latest/project002_sprint1e_phase1_script_lineage/coverage_metrics.json](artifacts/latest/project002_sprint1e_phase1_script_lineage/coverage_metrics.json)

Observed (before):
- full-script coverage: 0.00%
- preview-only coverage: 0.67%
- hash-only coverage: 99.33%
- missing coverage: 0.00%
- unambiguous content-id join rate: 100.00%
- run-id join rate: 100.00%
- blueprint linkage rate: 0.00%
- ownership linkage rate: 100.00%
- render linkage rate: 0.00%
- shorts linkage rate: 0.00%
- upload linkage rate: 0.00%
- final-script identification rate: 0.00%
- version-chain completeness: 0.00%
- ambiguous-link count: 0

Projected after prospective new-run enrichment (not observed):
- full-script coverage: 100.00%
- blueprint linkage rate: 100.00%
- render/shorts/upload linkage: 100.00%
- final-script identification rate: 100.00%
- version-chain completeness: 100.00%

## Step 12 CQGA Impact Estimation (No CQGA Change)

| CQGA dimension | current evidence | enriched evidence | expected impact | confidence |
| --- | --- | --- | --- | --- |
| hook detection | hash/preview dominant | full script continuity + versions | HIGH | MEDIUM |
| opening analysis | incomplete opening context | full initial/final script text | HIGH | MEDIUM |
| repetition | weak preview-only detection | deterministic normalized hash + full script | HIGH | HIGH |
| narrative structure | low observability | full script + version chain | HIGH | MEDIUM |
| pacing | limited proxies | sentence/word structure + full script | MEDIUM | MEDIUM |
| CTA timing | often unavailable | final script and render consumption link | MEDIUM | MEDIUM |
| ending quality | low evidence continuity | finalized script persistence | MEDIUM | MEDIUM |
| title/script consistency | partial consistency checks | prompt/blueprint/script lineage | HIGH | MEDIUM |
| Shorts source consistency | inferred only | explicit script consumed-by-shorts linkage | HIGH | MEDIUM |
| root-cause classification | sparse root signal | stronger script continuity and lineage joins | HIGH | MEDIUM |

## Step 13-14 Test and Scenario Coverage
New targeted tests:
- [tests/test_script_lineage_evidence_model.py](tests/test_script_lineage_evidence_model.py)
- [tests/test_script_lineage_evidence_store.py](tests/test_script_lineage_evidence_store.py)
- [tests/test_script_lineage_evidence_pipeline_integration.py](tests/test_script_lineage_evidence_pipeline_integration.py)
- [tests/test_script_lineage_evidence_legacy_import.py](tests/test_script_lineage_evidence_legacy_import.py)
- [tests/test_script_lineage_evidence_scenarios.py](tests/test_script_lineage_evidence_scenarios.py)

Scenario set includes deterministic coverage for:
- initial generation
- fact-check regeneration
- quality regeneration
- editor rewrite
- identical retry idempotency
- missing planning context
- linked blueprint
- render consumption
- shorts consumption
- upload linkage
- preview-only legacy
- ambiguous legacy
- missing script
- malformed evidence row
- storage failure behavior
- hash-only retention
- bounded excerpt retention
- secret-like content rejection
- multi-version with final selection
- replay/final reconstruction

All scenario assertions enforce advisory invariant and `pipeline_output_changed=false`.

## Step 15 Performance
Performance artifacts:
- [artifacts/latest/project002_sprint1e_phase1_script_lineage/performance_benchmarks.json](artifacts/latest/project002_sprint1e_phase1_script_lineage/performance_benchmarks.json)

Measured (local):
- append one event: ~0.484 ms
- append 100 events: ~17.886 ms
- replay events (benchmark set): ~2.243 ms
- reconstructed state count: 1 benchmark content chain
- replay errors: 0

Operational note for 201 channels:
- append is O(1) per event write
- replay is O(N events)
- version-chain reconstruction is linear in event count per content/run
- JSONL growth should be managed by periodic archival/rotation policy in later phase

## Limitations and Phase Boundaries
Limitations in this phase:
- prospective evidence only
- historical full scripts are mostly unrecoverable from current artifacts
- no thumbnail enrichment implementation
- no analytics-content join implementation
- no discovery metadata enrichment implementation
- no CQGA revalidation yet
- no production rollout

Phase 2 boundary:
- thumbnail lineage and metadata enrichment
- analytics-content join enrichment
- discovery linkage enrichment
- extended legacy import beyond dry-run (only with unambiguous provenance)

## Final Safety Confirmation
- no deploy
- no production access
- no restart
- no release
- no YouTube/channel metadata change
- no prompt behavior change
- no CQGA behavior change
- no scheduler behavior change
- no uploader behavior change
- no persistent feature enablement (default remains disabled)
- no secret exposure
