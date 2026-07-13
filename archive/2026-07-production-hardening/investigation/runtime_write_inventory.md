# Runtime Write Inventory

Scope: Runtime execution paths used by scheduler/pipeline/production quality platform.
Goal: Identify runtime writers and classify tracked vs runtime targets.

## Summary

- Root risk discovered: default runtime write targets included tracked docs paths.
- Critical tracked targets found:
  - docs/production_dashboard_latest.md
  - docs/governance_readiness_latest.md
- Hardening action: runtime defaults moved to output/runtime/* via a shared runtime path abstraction.

## Writer Inventory

| File | Function | Caller | Target Path | Runtime/Test | Tracked or Runtime Path |
| --- | --- | --- | --- | --- | --- |
| src/production_quality_platform.py | update_production_dashboard | scheduler.render_and_schedule; src.pipeline.run_full_pipeline | PRODUCTION_DASHBOARD_MD_PATH (default was docs/production_dashboard_latest.md) | Runtime | Tracked before hardening; runtime after hardening |
| src/production_quality_platform.py | update_production_dashboard | scheduler.render_and_schedule; src.pipeline.run_full_pipeline | PRODUCTION_DASHBOARD_JSON_PATH | Runtime | Runtime |
| src/production_quality_platform.py | _safe_write_json | update_production_dashboard / update_production_observability_latest / registry/evidence flows | PRODUCTION_OBSERVABILITY_LATEST_PATH, PRODUCTION_DASHBOARD_JSON_PATH, UPLOAD_REGISTRY_PATH, others | Runtime | Runtime |
| src/production_quality_platform.py | _append_jsonl | record_production_event / dead-letter flows | PRODUCTION_EVENTS_PATH, DEAD_LETTER_QUEUE_PATH | Runtime | Runtime |
| ops/refresh_governance_readiness.py | _write_text | run_refresh | GOVERNANCE_READINESS_MD_PATH (default was docs/governance_readiness_latest.md) | Runtime (invoked by scheduler maintenance cycle) | Tracked before hardening; runtime after hardening |
| ops/refresh_governance_readiness.py | _write_json | run_refresh | GOVERNANCE_REFRESH_LATEST_PATH | Runtime | Runtime |
| scheduler.py | save_queue / update_queue | scheduler loop | SCHEDULER_QUEUE_FILE | Runtime | Runtime |
| scheduler.py | _write_pid_record | scheduler startup | SCHEDULER_PID_FILE | Runtime | Runtime |
| scheduler.py | _save_scheduler_singleton_meta | singleton lock handling | SCHEDULER_SINGLETON_META_FILE | Runtime | Runtime |
| src/scheduler_utils.py | _atomic_write_json / _jsonl_append | incident and alert-state handling | output/state/*, logs/production_incidents.jsonl (env-overridable) | Runtime | Runtime |

## Notes

- Tests intentionally simulate tracked-mutation detection in isolated temporary git repositories (for gate logic validation), but these are test-only and not production runtime writes.
- Runtime tracked-write guard now blocks docs/ and core tracked docs write attempts from runtime writers.
