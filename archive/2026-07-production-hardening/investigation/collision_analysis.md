# Collision Analysis

Collision groups analyzed: 17

## 1. activation_controller
- recommendation: MERGE
- relationship: duplicate naming
- rationale: Use `*_latest.json` as canonical and archive legacy non-latest copy in Phase 3.
- files involved:
  - logs/activation_controller_report.json (operational evidence artifact)
  - logs/activation_controller_report_latest.json (latest snapshot artifact)

## 2. auditl
- recommendation: ARCHIVE
- relationship: derived/temporary duplicate
- rationale: Simulation copies overlap with primary stream.
- files involved:
  - logs/_sim_canary_clean/audit.jsonl (simulation sandbox artifact)
  - logs/_sim_rollback_clean/audit.jsonl (simulation sandbox artifact)

## 3. channel_performancel
- recommendation: ARCHIVE
- relationship: derived/temporary duplicate
- rationale: Simulation copies overlap with primary stream.
- files involved:
  - logs/_sim_canary_clean/channel_performance.jsonl (simulation sandbox artifact)
  - logs/_sim_rollback_clean/channel_performance.jsonl (simulation sandbox artifact)
  - logs/channel_performance.jsonl (append-only event stream)

## 4. experimentsl
- recommendation: ARCHIVE
- relationship: derived/temporary duplicate
- rationale: Simulation copies overlap with primary stream.
- files involved:
  - logs/_sim_canary_clean/experiments.jsonl (simulation sandbox artifact)
  - logs/_sim_rollback_clean/experiments.jsonl (simulation sandbox artifact)
  - output/telemetry/experiments.jsonl (append-only event stream)

## 5. library
- recommendation: REVIEW
- relationship: uncertain overlap
- rationale: Need reference scan before canonical choice.
- files involved:
  - output/tmp_music_smoke2/library.json (repository file)
  - output/tmp_music_smoke3/library.json (repository file)

## 6. metadata_repair_pending_oauth_blockers_20260710
- recommendation: KEEP
- relationship: different responsibility
- rationale: JSON + MD for the same run serve different readers.
- files involved:
  - logs/metadata_repair_pending_oauth_blockers_20260710.json (operational evidence artifact)
  - logs/metadata_repair_pending_oauth_blockers_20260710.md (operational evidence artifact)

## 7. original_status_short.txt
- recommendation: REVIEW
- relationship: uncertain overlap
- rationale: Reference scan required before action.
- files involved:
  - logs/two_state_validation_20260710_204806/original_status_short.txt (operational evidence artifact)
  - logs/two_state_validation_20260710_204854/original_status_short.txt (operational evidence artifact)

## 8. patch_id_matches.txt
- recommendation: ARCHIVE
- relationship: derived/temporary duplicate
- rationale: Temporary work-folder duplicates.
- files involved:
  - logs/approved_governance_equivalence_work_20260711_111255/patch_id_matches.txt (temporary equivalence work artifact)
  - logs/approved_governance_equivalence_work_final/patch_id_matches.txt (temporary equivalence work artifact)

## 9. patch_ids.txt
- recommendation: ARCHIVE
- relationship: derived/temporary duplicate
- rationale: Temporary work-folder duplicates.
- files involved:
  - logs/approved_governance_equivalence_work_20260711_111255/patch_ids.txt (temporary equivalence work artifact)
  - logs/approved_governance_equivalence_work_final/patch_ids.txt (temporary equivalence work artifact)

## 10. production_dashboard
- recommendation: KEEP
- relationship: different responsibility
- rationale: Human and machine variants have different responsibilities.
- files involved:
  - docs/production_dashboard_latest.md (latest snapshot artifact)
  - logs/production_dashboard_latest.json (latest snapshot artifact)

## 11. routing_guard_decisionsl
- recommendation: ARCHIVE
- relationship: derived/temporary duplicate
- rationale: Simulation copies overlap with primary stream.
- files involved:
  - logs/_sim_canary_clean/routing_guard_decisions.jsonl (simulation sandbox artifact)
  - logs/_sim_rollback_clean/routing_guard_decisions.jsonl (simulation sandbox artifact)
  - logs/routing_guard_decisions.jsonl (append-only event stream)

## 12. runtime_flag_ab_evidence
- recommendation: MERGE
- relationship: duplicate naming
- rationale: Use `*_latest.json` as canonical and archive legacy non-latest copy in Phase 3.
- files involved:
  - logs/runtime_flag_ab_evidence.json (operational evidence artifact)
  - logs/runtime_flag_ab_evidence_latest.json (latest snapshot artifact)

## 13. state.txt
- recommendation: ARCHIVE
- relationship: derived/temporary duplicate
- rationale: Temporary work-folder duplicates.
- files involved:
  - logs/approved_governance_equivalence_work_20260711_111255/state.txt (temporary equivalence work artifact)
  - logs/approved_governance_equivalence_work_final/state.txt (temporary equivalence work artifact)

## 14. system_status
- recommendation: KEEP
- relationship: different responsibility
- rationale: JSON machine output + MD human summary are canonical pair.
- files involved:
  - artifacts/latest/system_status.json (canonical housekeeping output)
  - artifacts/latest/system_status.md (canonical housekeeping output)

## 15. validate_git_diff_check.out
- recommendation: ARCHIVE
- relationship: derived/temporary duplicate
- rationale: Temporary work-folder duplicates.
- files involved:
  - logs/approved_governance_equivalence_work_20260711_111255/validate_git_diff_check.out (temporary equivalence work artifact)
  - logs/approved_governance_equivalence_work_final/validate_git_diff_check.out (temporary equivalence work artifact)

## 16. validate_git_diff_check.rc
- recommendation: ARCHIVE
- relationship: derived/temporary duplicate
- rationale: Temporary work-folder duplicates.
- files involved:
  - logs/approved_governance_equivalence_work_20260711_111255/validate_git_diff_check.rc (temporary equivalence work artifact)
  - logs/approved_governance_equivalence_work_final/validate_git_diff_check.rc (temporary equivalence work artifact)

## 17. validate_import_integrity.out
- recommendation: ARCHIVE
- relationship: derived/temporary duplicate
- rationale: Temporary work-folder duplicates.
- files involved:
  - logs/approved_governance_equivalence_work_20260711_111255/validate_import_integrity.out (temporary equivalence work artifact)
  - logs/approved_governance_equivalence_work_final/validate_import_integrity.out (temporary equivalence work artifact)

## Summary
- KEEP: 3 groups
- MERGE: 2 groups
- ARCHIVE: 10 groups
- REVIEW: 2 groups

## Blockers
- REVIEW groups require reference scan in Phase 2B before execution plan can be marked final.
