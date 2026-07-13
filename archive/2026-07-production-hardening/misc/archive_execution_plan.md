# Archive Execution Plan (Phase 2B Planning Only)

## Scope Guard
- This document is planning-only.
- No move/archive/delete/rename was executed.
- No runtime behavior change, deploy, restart, commit, or push was executed.

## Phase 2A Consistency Validation
Source artifacts reviewed:
- artifacts/latest/maintenance_dry_run_plan.json
- config/runtime_manifest.json
- artifacts/latest/runtime_manifest_review.md
- artifacts/latest/collision_analysis.md
- artifacts/latest/phase2b_reference_scan.json

Consistency findings:
- Runtime manifest quality is internally consistent (130 runtime files, missing=0).
- Collision recommendations and dry-run archive list are NOT fully aligned.
- Conflict set (4 files):
  - logs/activation_controller_report_latest.json (MERGE but listed in to_archive)
  - docs/production_dashboard_latest.md (KEEP but listed in to_archive)
  - logs/production_dashboard_latest.json (KEEP but listed in to_archive)
  - logs/runtime_flag_ab_evidence_latest.json (MERGE but listed in to_archive)

## Candidate Sets

### Archive Candidates (from ARCHIVE recommendations)
1. logs/_sim_canary_clean/audit.jsonl
2. logs/_sim_rollback_clean/audit.jsonl
3. logs/_sim_canary_clean/channel_performance.jsonl
4. logs/_sim_rollback_clean/channel_performance.jsonl
5. logs/_sim_canary_clean/experiments.jsonl
6. logs/_sim_rollback_clean/experiments.jsonl
7. logs/_sim_canary_clean/routing_guard_decisions.jsonl
8. logs/_sim_rollback_clean/routing_guard_decisions.jsonl
9. logs/approved_governance_equivalence_work_20260711_111255/patch_id_matches.txt
10. logs/approved_governance_equivalence_work_final/patch_id_matches.txt
11. logs/approved_governance_equivalence_work_20260711_111255/patch_ids.txt
12. logs/approved_governance_equivalence_work_final/patch_ids.txt
13. logs/approved_governance_equivalence_work_20260711_111255/state.txt
14. logs/approved_governance_equivalence_work_final/state.txt
15. logs/approved_governance_equivalence_work_20260711_111255/validate_git_diff_check.out
16. logs/approved_governance_equivalence_work_final/validate_git_diff_check.out
17. logs/approved_governance_equivalence_work_20260711_111255/validate_git_diff_check.rc
18. logs/approved_governance_equivalence_work_final/validate_git_diff_check.rc
19. logs/approved_governance_equivalence_work_20260711_111255/validate_import_integrity.out
20. logs/approved_governance_equivalence_work_final/validate_import_integrity.out

Note:
- logs/channel_performance.jsonl, output/telemetry/experiments.jsonl, logs/routing_guard_decisions.jsonl are active primary streams and are explicitly excluded from archive execution set.

### Merge Candidates
1. logs/activation_controller_report.json -> canonical target: logs/activation_controller_report_latest.json
2. logs/runtime_flag_ab_evidence.json -> canonical target: logs/runtime_flag_ab_evidence_latest.json

### Review Candidates
1. output/tmp_music_smoke2/library.json
2. output/tmp_music_smoke3/library.json
3. logs/two_state_validation_20260710_204806/original_status_short.txt
4. logs/two_state_validation_20260710_204854/original_status_short.txt

## Reference Analysis Summary
Scan coverage:
- Python, JSON/JSONL, YAML, Markdown, shell, CI/workflow files, config and docs were scanned by literal path + basename.
- Results: artifacts/latest/phase2b_reference_scan.json

High-signal dependency results:
- No ARCHIVE simulation/work-folder file has direct runtime-path dependency from src/ except primary stream counterparts.
- Primary stream files with runtime/test usage (must not archive):
  - logs/channel_performance.jsonl
  - output/telemetry/experiments.jsonl
  - logs/routing_guard_decisions.jsonl
- MERGE candidates have ops/docs dependencies and require controlled migration.
- REVIEW candidates appear as isolated run artifacts; no runtime/test hard dependency detected.

## Archive Safety Analysis

### A1. Simulation audit files
- Current location: logs/_sim_canary_clean/audit.jsonl, logs/_sim_rollback_clean/audit.jsonl
- Reason: sandbox duplicate evidence
- Who uses: planning docs/maintenance report only
- Runtime access: no
- Tests access: no direct mandatory dependency
- Safe destination: logs/archive/2026/07/sim/
- Rollback: move files back to original paths
- Risk: Low
- Confidence: High
- Production impact: None
- Decision: SAFE

### A2. Simulation performance files
- Current location: logs/_sim_canary_clean/channel_performance.jsonl, logs/_sim_rollback_clean/channel_performance.jsonl
- Reason: sandbox duplicates of primary performance stream
- Who uses: tests/docs mention basename; primary active stream is logs/channel_performance.jsonl
- Runtime access: no direct runtime read to sim paths
- Tests access: tests use tmp paths, not sim paths
- Safe destination: logs/archive/2026/07/sim/
- Rollback: move files back to original paths
- Risk: Low
- Confidence: High
- Production impact: None
- Decision: SAFE

### A3. Simulation experiments files
- Current location: logs/_sim_canary_clean/experiments.jsonl, logs/_sim_rollback_clean/experiments.jsonl
- Reason: sandbox duplicates; primary stream is output/telemetry/experiments.jsonl
- Who uses: test basenames broadly, but not these exact sim paths
- Runtime access: no direct runtime read to sim paths
- Tests access: no direct hard dependency on sim paths
- Safe destination: logs/archive/2026/07/sim/
- Rollback: move files back
- Risk: Low
- Confidence: Medium-High
- Production impact: None
- Decision: SAFE

### A4. Simulation routing-guard files
- Current location: logs/_sim_canary_clean/routing_guard_decisions.jsonl, logs/_sim_rollback_clean/routing_guard_decisions.jsonl
- Reason: sandbox duplicates; primary stream is logs/routing_guard_decisions.jsonl
- Who uses: runtime/test/docs rely on primary stream basename
- Runtime access: primary file only
- Tests access: basename coverage exists; no direct sim path dependency
- Safe destination: logs/archive/2026/07/sim/
- Rollback: move files back
- Risk: Low
- Confidence: Medium-High
- Production impact: None
- Decision: SAFE

### A5. Governance equivalence temporary work-folder files
- Current location: logs/approved_governance_equivalence_work_20260711_111255/* and logs/approved_governance_equivalence_work_final/*
- Reason: temporary duplicate work products
- Who uses: maintenance/collision docs only
- Runtime access: no
- Tests access: no
- Safe destination: logs/archive/2026/07/equivalence_work/
- Rollback: restore file set from archive to original folder names
- Risk: Low
- Confidence: High
- Production impact: None
- Decision: SAFE

## Merge Safety Analysis

### M1. activation_controller report family
- Canonical file: logs/activation_controller_report_latest.json
- Legacy file: logs/activation_controller_report.json
- Differences: naming and pointer semantics; both are currently referenced by ops/docs
- Reference differences:
  - legacy referenced by ops/executive_dashboard_report.py and runbook/docs
  - latest referenced by strict-evidence and bundle flows
- Migration steps:
  1. Update ops/docs readers to canonical latest path
  2. Keep temporary compatibility shim (read latest else legacy)
  3. After verification window, archive legacy file
- Rollback:
  - restore legacy reader paths and restore archived file
- Risk: Medium
- Confidence: Medium
- Decision: BLOCKED (until all readers are unified)

### M2. runtime_flag_ab_evidence family
- Canonical file: logs/runtime_flag_ab_evidence_latest.json
- Legacy file: logs/runtime_flag_ab_evidence.json
- Differences: naming consistency with latest ecosystem
- Reference differences:
  - ops references still include legacy locations in some contexts
- Migration steps:
  1. Standardize writers/readers to *_latest.json
  2. Add fallback read during transition
  3. Archive legacy file after verification
- Rollback:
  - restore legacy read path and unarchive legacy file
- Risk: Medium
- Confidence: Medium
- Decision: BLOCKED (reader alignment required)

## Review Safety Analysis

### R1. tmp_music smoke library files
- Files: output/tmp_music_smoke2/library.json, output/tmp_music_smoke3/library.json
- Observed dependencies: no runtime/test direct path dependency found
- Risk if archived: low
- Decision: BLOCKED for automatic action pending owner confirmation of smoke-test retention policy

### R2. two_state_validation original_status files
- Files: logs/two_state_validation_20260710_204806/original_status_short.txt, logs/two_state_validation_20260710_204854/original_status_short.txt
- Observed dependencies: no runtime/test direct path dependency found
- Risk if archived: low
- Decision: BLOCKED for automatic action pending evidence-retention policy decision

## Runtime Protection Review

### False Positives
- channels/_pending/** removed from runtime whitelist (correct)
- client_secrets.json removed from runtime whitelist (correct)
- pytest.ini removed from runtime whitelist (correct)

### False Negatives
- No missing runtime file detected from current manifest list.
- Potential policy-level gap: `protected_globs` still includes broad `channels/**` and `assets/**`; execution engine must prioritize explicit runtime file whitelist over broad glob when deciding archival eligibility.

### Optional Runtime Files
- Per-channel branding files may be optional for channels not currently active but still should be treated cautiously.

### Must Never Move
- All files in config/runtime_manifest.json: production_runtime_files
- scheduler.py, main.py, auth.py, src/**
- Active stream files:
  - logs/channel_performance.jsonl
  - logs/routing_guard_decisions.jsonl
  - output/telemetry/experiments.jsonl

### May Safely Archive (Phase 3 candidates)
- Simulation duplicates under logs/_sim_canary_clean and logs/_sim_rollback_clean
- Temporary equivalence work-folder duplicates under logs/approved_governance_equivalence_work_*

## Phase 3 Execution Outline (Planned)

### Phase 3 Step 1: Preflight Guard + Snapshot
- Freeze candidate list to SAFE subset only.
- Record pre-action checksum manifest for all candidate files.
- Verify runtime whitelist + do-not-touch blacklist.

### Phase 3 Step 2: Controlled Archive Execution
- Archive SAFE subset only to dated archive roots.
- Log per-file action with before/after path and checksum.
- Do not process BLOCKED candidates.

### Phase 3 Step 3: Post-Archive Verification
- Re-run runtime manifest validation.
- Re-run targeted maintenance validations.
- Confirm scheduler/runtime critical files untouched.

## Rollback Procedure
1. Read execution ledger (source, destination, checksum).
2. Move each archived file back to original path.
3. Re-run runtime manifest validation and targeted tests.
4. Verify critical runtime streams and latest reports.

## Estimated Execution Time (Phase 3)
- SAFE subset archive: 5-15 minutes
- Verification and rollback-ready snapshot: 5-10 minutes
- Total planned window: 10-25 minutes

## Expected Repository Impact
- File relocations only for SAFE archival set.
- No source code mutation required for SAFE archive set.

## Expected Production Impact
- None (planning indicates no runtime dependency on SAFE archive set).

## Expected Git Diff (Phase 3)
- Mostly path changes for archived files and updated latest planning/report artifacts.
- No changes expected under src/ runtime code for SAFE archive subset.

## Files Affected (Phase 3 SAFE subset)
- Simulation log duplicates (`logs/_sim_*/*` subset listed above)
- Governance equivalence temporary work-folder duplicate text artifacts

## Risk Assessment
- SAFE archive subset: Low risk
- MERGE subset: Medium risk, currently BLOCKED
- REVIEW subset: Low technical risk, policy BLOCKED
