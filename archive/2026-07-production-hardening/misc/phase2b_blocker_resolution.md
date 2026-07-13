# Phase 2B Blocker Resolution

## Final Decision

READY_FOR_PHASE3 = NO

## Executive Summary

Phase 2B planning blockers were narrowed and the maintenance dry-run now rejects unsafe archive candidates instead of silently including them. The collision-aware validation is working.

The remaining blocker to commit-ready readiness is validation: the repository-wide full pytest run still fails on unrelated pre-existing pipeline tests, so this scope is not yet ready to roll into Phase 3 execution.

Housekeeping scope status:
- Housekeeping planning blockers are resolved.
- Housekeeping safety validations (maintenance tests, runtime manifest validation, dry-run conflict guard) are passing.
- Repository-wide full-suite stability is being tracked as a separate non-housekeeping workstream.

## Original Blockers

### 1. Dry-run plan conflicts
Status: resolved in maintenance logic

Evidence reviewed:
- [artifacts/latest/maintenance_dry_run_plan.json](artifacts/latest/maintenance_dry_run_plan.json)
- [artifacts/latest/collision_analysis.md](artifacts/latest/collision_analysis.md)
- [artifacts/latest/archive_execution_plan.md](artifacts/latest/archive_execution_plan.md)
- [artifacts/latest/phase2b_reference_scan.json](artifacts/latest/phase2b_reference_scan.json)
- `ops/maintenance.py` dry-run validation output

Decision:
- Unsafe archive candidates are now rejected during dry-run validation.
- Executable archive actions no longer include KEEP/MERGE/REVIEW items.

Blocked archive candidates reported by validation:
- docs/production_dashboard_latest.md -> KEEP
- logs/activation_controller_report_latest.json -> MERGE
- logs/production_dashboard_latest.json -> KEEP
- logs/runtime_flag_ab_evidence_latest.json -> MERGE

### 2. activation_controller canonicalization
Decision: KEEP_BOTH

Evidence reviewed:
- [ops/activation_controller.py](ops/activation_controller.py)
- [ops/executive_dashboard_report.py](ops/executive_dashboard_report.py)
- [ops/generate_strict_evidence_report.py](ops/generate_strict_evidence_report.py)
- [ops/p0_p1_artifact_bundle.py](ops/p0_p1_artifact_bundle.py)
- [docs/activation_controller_runbook.md](docs/activation_controller_runbook.md)
- [docs/architecture.md](docs/architecture.md)
- [logs/activation_controller_report.json](logs/activation_controller_report.json)
- [logs/activation_controller_report_latest.json](logs/activation_controller_report_latest.json)
- [artifacts/latest/phase2b_reference_scan.json](artifacts/latest/phase2b_reference_scan.json)

Rationale:
- The legacy and latest files currently serve different consumers and have distinct operational roles.
- Legacy readers still exist in docs/ops, while latest readers are used by strict evidence and bundle generation.
- A safe canonicalization migration is not proven yet.

Compatibility risk:
- Medium

### 3. runtime_flag_ab_evidence canonicalization
Decision: KEEP_BOTH

Evidence reviewed:
- [ops/runtime_flag_ab_evidence.py](ops/runtime_flag_ab_evidence.py)
- [ops/p0_p1_artifact_bundle.py](ops/p0_p1_artifact_bundle.py)
- [logs/runtime_flag_ab_evidence.json](logs/runtime_flag_ab_evidence.json)
- [logs/runtime_flag_ab_evidence_latest.json](logs/runtime_flag_ab_evidence_latest.json)
- [artifacts/latest/phase2b_reference_scan.json](artifacts/latest/phase2b_reference_scan.json)

Rationale:
- The legacy writer path is still the direct runtime output path.
- The latest snapshot is consumed by bundle/report generation.
- Canonicalization would require a compatibility migration that is not yet proven safe.

Compatibility risk:
- Medium

### 4. library.json REVIEW group
Decision: ARCHIVE_SAFE

Evidence reviewed:
- [output/tmp_music_smoke2/library.json](output/tmp_music_smoke2/library.json)
- [output/tmp_music_smoke3/library.json](output/tmp_music_smoke3/library.json)
- Hash comparison output: both files have identical SHA-256 values
- Repository-wide reference search: no src/tests/ops/docs readers or writers found for these paths
- [artifacts/latest/phase2b_reference_scan.json](artifacts/latest/phase2b_reference_scan.json)

Ownership / retention analysis:
- Owning subsystem: temporary music smoke-test outputs
- Type: temporary test/evidence output
- Retention requirement: archive for evidence retention, not canonical runtime state
- Rollback path: restore the archived files to their original tmp_music_smoke* directories

### 5. original_status_short.txt REVIEW group
Decision: ARCHIVE_SAFE

Evidence reviewed:
- [logs/two_state_validation_20260710_204806/original_status_short.txt](logs/two_state_validation_20260710_204806/original_status_short.txt)
- [logs/two_state_validation_20260710_204854/original_status_short.txt](logs/two_state_validation_20260710_204854/original_status_short.txt)
- Hash comparison output: both files have identical SHA-256 values
- [artifacts/latest/phase2b_reference_scan.json](artifacts/latest/phase2b_reference_scan.json)

Ownership / retention analysis:
- Origin: two_state_validation runs
- Type: operational evidence artifact
- Retention requirement: archive for evidence retention
- Archive destination: logs/archive/2026/07/two_state_validation/
- Rollback path: restore each file to its original validation-run directory

## Validation Summary

Targeted maintenance tests with `-W error`:
- [tests/test_maintenance.py](tests/test_maintenance.py)
- Result: 5 passed

Runtime manifest validation:
- Result: ok=true, runtime_files=130

Diff validation:
- `git diff --check`: passed

Full pytest with `-W default`:
- Result: not clean
- Remaining unrelated failures were observed in existing pipeline/render tests.

Full pytest normally:
- Result: not clean
- The same unrelated failures remain.

## Remaining Risks

- Existing unrelated pipeline/render regressions still prevent a fully clean repository validation.
- The repository already contains pre-existing modified/untracked files outside this task scope.
- No actual archive/move/delete/merge/canonicalization operation was executed.

## Next Logical Step

- Continue with a dedicated stabilization pass for non-housekeeping test regressions.
- Keep housekeeping scope frozen to planning artifacts + maintenance guardrails until full-suite stabilization completes.
- Re-run full-suite validation after stabilization and then re-evaluate `READY_FOR_PHASE3`.

## Exact File Lists

### Files eligible for archive
- docs/governance_readiness_latest.md
- logs/approved_governance_equivalence_latest.json
- logs/chapter_validator_latest.json
- logs/content_platform_experiments_latest.json
- logs/content_platform_health_latest.json
- logs/content_platform_recommendations_latest.json
- logs/content_quality_guard_latest.json
- logs/cutover_verify_latest.json
- logs/cutover_verify_latest.stderr.log
- logs/governance_bridge_daily_checklist_latest.md
- logs/governance_dashboard_bridge_latest.json
- logs/governance_refresh_run_latest.json
- logs/historical_content_audit_latest.json
- logs/image_relevance_guard_latest.json
- logs/local_production_delta_latest.json
- logs/p0_p1_artifacts_bundle_latest.json
- logs/p0_validation_metrics_latest.json
- logs/p0a_quarantine_report_latest.json
- logs/production_observability_latest.json
- logs/production_safety_gate_latest.json
- logs/proven_validated_status_latest.json
- logs/queue_quarantine_admin_apply_latest.json
- logs/queue_quarantine_admin_dry_run_latest.json
- logs/queue_quarantine_admin_latest.json
- logs/routing_guard_review_queue_latest.json
- logs/runtime_optimization_evidence_latest.json
- logs/strict_evidence_report_latest.md
- logs/thumbnail_403_root_cause_latest.json
- logs/thumbnail_intelligence_latest.json
- logs/thumbnail_streak_path_latest.json
- logs/trace_completeness_latest.json

### Files eligible for canonicalization
- None

### Protected files
- docs/governance_readiness_latest.md
- docs/production_dashboard_latest.md
- output/state/activation_reports/latest.json
- config/runtime_manifest.json
- ops/maintenance.py
- tests/test_maintenance.py
- artifacts/latest/maintenance_dry_run_plan.json
- artifacts/latest/collision_analysis.md
- artifacts/latest/phase2b_reference_scan.json
- artifacts/latest/archive_execution_plan.md
- artifacts/latest/runtime_manifest_review.md
- artifacts/latest/system_status.json
- artifacts/latest/system_status.md

## Proposed Phase 3 Scope

- Archive only the safe archive list above.
- Keep the KEEP_BOTH canonicalization decisions unchanged.
- Do not touch protected files.
- Continue to exclude the blocked archive candidates from executable archive actions.

## Rollback Strategy

- For archive actions: move each file back to its original path.
- For any future canonicalization work: preserve a compatibility window and restore legacy readers first if needed.
- For planner changes: revert only the maintenance logic and regenerated planning artifacts, not runtime code.

## Pre-existing Files Left Untouched

- docs/governance_readiness_latest.md
- docs/production_dashboard_latest.md
- output/state/activation_reports/latest.json

These files were present before this task and were not modified by the blocker-resolution work.
