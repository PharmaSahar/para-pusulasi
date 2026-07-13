# Repository Hygiene Classification

Generated: 2026-07-12 (UTC)

## Scope

This report classifies each remaining path from the audit request using exactly one category and one proposed action.

| Path | Tracked? | Classification | Creator | Purpose | Deterministic? | Production Runtime Rewrites? | Belongs In Current Release? | Proposed Action |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| PROGRESS.md | tracked (dirty before restore) | GENERATED RUNTIME OUTPUT | `scheduler.py` daily maintenance writer (`update_progress`) | Operational status snapshot (timestamps/queue state) | No (time + queue dependent) | Yes | No | RESTORE TO HEAD |
| docs/governance_readiness_latest.md | tracked (dirty before restore) | GENERATED RUNTIME OUTPUT | `ops/refresh_governance_readiness.py` + governance report jobs | Latest governance snapshot for current run state | No (time/artifact dependent) | Yes (via governance refresh jobs) | No | RESTORE TO HEAD |
| output/state/activation_reports/latest.json (requested as latest.json) | tracked (dirty before restore) | GENERATED RUNTIME OUTPUT | `ops/activation_controller.py` archive writer | Latest activation controller report pointer and payload | No (time/tmp-path dependent) | Yes | No | RESTORE TO HEAD |
| artifacts/deployment/** | untracked | VALIDATION EVIDENCE | Preprod/final validation runners and runtime probes | Deployment-readiness evidence bundles | No (run-id/time/context dependent) | Yes (new runs append/replace) | No | ADD TO .gitignore |
| artifacts/incidents/cross_channel_contamination/** | untracked | INCIDENT FORENSICS | Incident investigation and replay workflows | Root cause, replay, remediation evidence | No (investigation-run dependent) | Not production runtime; investigation tooling may rewrite | No | ADD TO .gitignore |
| artifacts/latest/** | untracked | VALIDATION EVIDENCE | Audit/validation scripts and manual evidence capture runs | Latest working evidence snapshots | No (latest-run dependent) | Yes (frequent overwrite by validations) | No | ADD TO .gitignore |
| config/runtime_manifest.json | untracked | GENERATED RUNTIME OUTPUT | `ops/maintenance.py` (`_build_runtime_manifest` + `_write_json`) | Machine snapshot of runtime file inventory | No (host-path/time/content dependent) | Yes (maintenance regeneration) | No | ADD TO .gitignore |
| ops/maintenance.py | untracked | SEPARATE FEATURE | Manual in-progress feature work | Repository housekeeping utility (audit/cleanup/manifest) | N/A (source file) | No | No (not part of validated 3-commit release scope) | KEEP UNTRACKED FOR LATER TASK |
| tests/test_maintenance.py | untracked | SEPARATE FEATURE | Manual in-progress feature work | Test suite for maintenance utility | N/A (source file) | No | No (paired with separate feature) | KEEP UNTRACKED FOR LATER TASK |
| tests/repro_topic_domain_quarantine.py | untracked | TEST-ONLY REPRODUCTION | Manual diagnostic script | Reproduce topic-domain quarantine behavior in isolation | No (temp dirs/runtime monkeypatching) | No | No (coverage already present in committed guard tests) | KEEP UNTRACKED FOR LATER TASK |

## Notes

- No path required the UNKNOWN classification.
- The three tracked dirty files were treated as generated snapshots and restored individually after preserving patch evidence in `artifacts/latest/repository_hygiene_tracked_diff_evidence.patch`.
- `ops/maintenance.py` + `tests/test_maintenance.py` form a coherent independent feature and are intentionally excluded from the current release hygiene push.