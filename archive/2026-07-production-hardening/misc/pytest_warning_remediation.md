# Pytest Warning Remediation

## Final Decision

WARNING_BLOCKERS_CLEARED

## What Was Fixed

1. `scheduler.py` ResourceWarning
- Root cause: import-time `logging.FileHandler("logs/scheduler.log")` was left open.
- Fix: the file handler is now created once, registered with `atexit`, and explicitly flushed/closed during shutdown.
- Regression coverage: added a subprocess-based import test with `-W error::ResourceWarning`.

2. `src/scheduler_utils.py` DeprecationWarning
- Root cause: `_now_utc()` returned `datetime.utcnow()`.
- Fix: `_now_utc()` now returns `datetime.now(timezone.utc)`.
- Compatibility fix: provider-health timestamps and circuit-window serialization now use the existing UTC formatter so comparisons and stored values remain valid.

3. `src/content_quality_guard.py` DeprecationWarning
- Root cause: `datetime.utcnow()` was used for `registered_at`, `timestamp`, and `last_updated`.
- Fix: all three fields now use `datetime.now(timezone.utc).isoformat()`.
- Regression coverage: existing content-quality tests continue to pass under `-W error`.

4. `tests/test_scheduler_singleton_lock.py` ResourceWarning
- Root cause: the subprocess pipe from the lock probe was not fully drained/closed on the teardown path.
- Fix: the test now uses `communicate(timeout=5)` in the cleanup path so stdout/stderr are closed reliably.

## Warnings Fixed

- `ResourceWarning` at `scheduler.py:63`
- `ResourceWarning` at `_pytest/python.py:167` during `tests/test_scheduler_singleton_lock.py`
- `DeprecationWarning` at `src/scheduler_utils.py:416`
- `DeprecationWarning` at `src/content_quality_guard.py:322`
- `DeprecationWarning` at `src/content_quality_guard.py:353`
- `DeprecationWarning` at `src/content_quality_guard.py:360`

## Warnings Remaining

- None from the previously identified blocker set.
- Full suite under `-W default` completed cleanly after the fixes.

## Remaining Warning Categories

- project code warning: 0
- test code warning: 0
- third-party dependency warning: 0
- deprecation warning: 0
- resource/runtime warning: 0
- duplicate/repeated warning: 0

## Runtime Behavior Impact

- `scheduler.py`: behavior is unchanged except for safe log-handler cleanup on shutdown.
- `src/scheduler_utils.py`: UTC timestamps are now timezone-aware; serialized values remain valid UTC strings, and provider-circuit comparisons continue to work.
- `src/content_quality_guard.py`: timestamp fields now use timezone-aware UTC; business logic thresholds and decisions are unchanged.
- `tests/test_scheduler_singleton_lock.py`: only test cleanup behavior changed.

## Validation Results

Targeted warning-related tests with `-W error`:
- `tests/test_scheduler_cli.py`
- `tests/test_scheduler_singleton_lock.py`
- `tests/test_content_quality_guard.py`
- Result: 45 passed

Maintenance tests:
- `tests/test_maintenance.py`
- Result: 4 passed

Full suite with `-W default`:
- Result: 574 passed

Full suite normally:
- Result: 574 passed

Diff validation:
- `git diff --check`: passed

## Working Tree Check

Final `git status --short` showed pre-existing modified/untracked items still present, including:
- `docs/governance_readiness_latest.md`
- `docs/production_dashboard_latest.md`
- `output/state/activation_reports/latest.json`
- `artifacts/`, `config/`, `ops/maintenance.py`, `tests/test_maintenance.py`

These were not modified by the warning remediation work beyond preserving the existing working tree state.

## Conclusion

The confirmed project-code warnings were fixed at the source, the test-harness ResourceWarning was cleaned up, and the full suite now passes under both normal execution and `-W default`.
