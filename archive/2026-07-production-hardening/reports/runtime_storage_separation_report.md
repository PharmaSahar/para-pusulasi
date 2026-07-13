# Runtime Storage Separation Report

## 1. Original architecture

- Runtime dashboard markdown default target was tracked docs path:
  - src/production_quality_platform.py defaulted PRODUCTION_DASHBOARD_MD_PATH to docs/production_dashboard_latest.md.
- Governance readiness markdown default also targeted tracked docs:
  - ops/refresh_governance_readiness.py defaulted readiness markdown to docs/governance_readiness_latest.md.
- Scheduler runtime map still referenced docs defaults for mutable artifacts in preprod isolation checks.

## 2. Root cause

- Runtime storage and tracked documentation storage were not strictly separated by default path contract.
- Runtime writers could resolve to tracked docs when env overrides were absent.

## 3. New runtime storage model

- Added shared runtime storage/path layer in src/runtime_storage.py.
- Runtime defaults now resolve under runtime root (default output/runtime, overridable with RUNTIME_OUTPUT_ROOT).
- Runtime tracked-write guard prevents runtime writes to tracked docs and core tracked markdown files.

## 4. Modified files

- src/runtime_storage.py
- src/production_quality_platform.py
- scheduler.py
- ops/refresh_governance_readiness.py
- ops/export_runtime_dashboard.py
- tests/test_preprod_isolation_paths.py
- tests/test_production_quality_platform.py
- tests/test_refresh_governance_readiness.py
- artifacts/latest/runtime_write_inventory.md
- artifacts/latest/runtime_storage_contract.md
- artifacts/latest/runtime_storage_validation_evidence.txt

## 5. Runtime-only paths

- output/runtime/state/production_dashboard_latest.md
- output/runtime/state/production_dashboard_latest.json
- output/runtime/telemetry/production_events.jsonl
- output/runtime/telemetry/production_observability_latest.json
- output/runtime/state/governance_readiness_latest.md
- output/runtime/state/governance_refresh_run_latest.json
- output/runtime/logs/scheduler.log

## 6. Export workflow

- Added explicit export-only operation:
  - src/production_quality_platform.py function export_runtime_dashboard_to_docs(...)
  - ops/export_runtime_dashboard.py CLI wrapper
- Export behavior:
  - reads runtime markdown source
  - writes docs target using tmp + replace atomic overwrite
  - never auto-invoked by scheduler or pipeline

## 7. Validation evidence

- Step 6 focused storage gate passed under strict warnings mode:
  - 26 passed in 2.09s
  - tests/test_production_quality_platform.py
  - tests/test_preprod_isolation_paths.py
  - tests/test_refresh_governance_readiness.py
  - tests/test_render_metrics.py
- Step 7 strict full-suite repeated validation passed:
  - 5 independent runs
  - each run: 660 passed with -W error
  - each run: dashboard hash unchanged and no active writer process
- Step 8 export-boundary isolated validation passed:
  - missing source raises FileNotFoundError(runtime_dashboard_missing)
  - explicit export to temp target succeeds
  - temp shadow file removed after replace
  - tracked docs dashboard remained unchanged

## 8. Five strict-suite runs

- strict_run_1: PASS (660 passed in 211.39s)
- strict_run_2: PASS (660 passed in 219.01s)
- strict_run_3: PASS (660 passed in 217.88s)
- strict_run_4: PASS (660 passed in 212.66s)
- strict_run_5: PASS (660 passed in 227.62s)

## 9. Git cleanliness after each run

- docs/production_dashboard_latest.md was restored to HEAD before Step 6.
- During Step 6 and all 5 strict runs:
  - dashboard hash stayed constant at 6840cc7832d0df12f688e5ae981b53288908d205c74bece9bc61cc0d6127e6db
  - dashboard git status stayed empty
  - no scheduler/pipeline writer process was active
- Pre-existing unrelated workspace dirt remains, but no new tracked runtime dashboard mutation occurred.

## 10. Remaining risks

- Pre-existing dirty tracked docs can still fail operational cleanliness gates even when architecture is corrected.
- Long-running external scheduler processes launched with old environment can keep writing old locations unless restarted with new runtime path contract.

## 11. GO / NO-GO

- Current workspace gate decision: GO for runtime storage separation clean-state verification scope.
- Status maturity:
  - PLANNED: complete
  - REPORTED: complete
  - PROVEN: complete (live process control + strict test evidence + hash/status invariants)
  - VALIDATED: complete for requested verification scope
  - ROLLED_OUT: not claimed in this report
- Architecture hardening implementation status remains complete for runtime path separation and explicit export flow.
