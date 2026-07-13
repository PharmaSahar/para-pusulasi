# Dashboard Mutation Forensics

Target: docs/production_dashboard_latest.md
Scope: read-only forensic attribution, no reset, no code/test edits.

## Step 3 - Runtime Writer Identification

### Direct writer function
- File: src/production_quality_platform.py:379
- Function: update_production_dashboard(...)
- Write mode: overwrite
- Concrete write: PRODUCTION_DASHBOARD_MD_PATH.write_text(...) at src/production_quality_platform.py:469
- Trigger type: runtime only (function call), not import-time
- Import-time check: only function definition in src/production_quality_platform.py:379; no top-level invocation

### Runtime callers in production paths
- src/pipeline.py:1864
  - call site in run completion/fail-open block
  - scheduler_status passed as "pipeline_run"
- scheduler.py:796
  - canary blocked path, scheduler_status="canary_blocked"
- scheduler.py:988
  - active success path, scheduler_status="active"
- scheduler.py:1032
  - active with blocks path, scheduler_status="active_with_blocks"
- scheduler.py:1130
  - exception/degraded path, scheduler_status="degraded"

### Additional write-capable helpers (not target markdown writer)
- _safe_write_json(...) in src/production_quality_platform.py writes JSON targets with atomic tmp+replace
- _append_jsonl(...) appends JSONL targets
- These do not directly write docs/production_dashboard_latest.md

## Step 4 - Diff Attribution

HEAD vs current working tree diff classes:

- timestamp only:
  - Generated at changed
- metrics only:
  - Queue depth, Videos, Avg render duration, Upload success count, Retries, channel totals
- generated evidence:
  - Scheduler status changed to degraded
  - Build SHA changed to d51e315
  - Scheduler PID changed to 13358
  - Last error changed to topic_provenance_collision payload
  - Channel Health expanded with multiple channels
- deterministic content:
  - Markdown structure/section order unchanged and exactly matches update_production_dashboard template
- manual content:
  - none detected
- unrelated:
  - none detected

Compatibility verdict: diff shape is fully compatible with update_production_dashboard generated output.

## Step 5 - Test Attribution

### Isolation fixture
- tests/conftest.py:10 autouse fixture _isolate_dashboard_artifacts
- tests/conftest.py:15 sets PRODUCTION_DASHBOARD_MD_PATH to tmp_path
- tests/conftest.py:41 monkeypatches function globals to tmp dashboard path

### Tests reaching writer
- tests/test_preprod_isolation_paths.py:98 and :119 call update_production_dashboard directly
- tests/test_production_quality_platform.py:33 calls update_production_dashboard
- Many tests call pipeline.run_full_pipeline(...) and scheduler.render_and_schedule(...), but fixture isolation redirects dashboard path to tmp_path during pytest

### Potential bypass check
- tests/test_preprod_validation_runner.py:337 writes Path('docs/production_dashboard_latest.md').write_text('changed\\n', ...)
- This test creates and uses an isolated temporary git repo root (tmp_path), not workspace tracked docs file
- No evidence this test mutates repository target docs/production_dashboard_latest.md

### Trace evidence
- artifacts/latest/dashboard_write_trace.jsonl target counts show tmp pytest dashboard paths and logs/* targets
- No trace hit for target_path = docs/production_dashboard_latest.md

Conclusion for test attribution: no evidence of test-path mutation of repository target file in this investigation.

## Correlated Runtime Evidence (who/when/why)

- Active process detected: python scheduler.py with PID 13358
- File mtime: 2026-07-12 20:08:07 +0300
- logs/scheduler.log includes matching event at 2026-07-12 20:08:07,086:
  - Scheduler [saglik_pusulasi] render error with exact token
  - topic_provenance_collision:.../run_629677d82d254b6d949c27f82044029d/content_8f42e0869dde4e85b60a26ecbd4e7d17.json
- The exact same token appears in mutated dashboard Last error line
- Same runtime identity appears in telemetry payload around the event window:
  - process_pid=13358, git_sha_short=d51e315
- Mutated dashboard also contains Scheduler PID 13358 and Build SHA d51e315

Attribution: the mutation is consistent with a live scheduler runtime call to update_production_dashboard in degraded path.

## Step 6 - Root Cause Classification

Selected class (exactly one): Environment/configuration issue

Reason:
- A long-running production scheduler process was active in the same workspace.
- Dashboard writer target resolves to tracked docs/production_dashboard_latest.md in that runtime context.
- This permits legitimate runtime overwrites of a tracked file during investigation.

## Step 7 - Safe Recovery Recommendation

Selected action (exactly one): A. Restore file then continue.

Why:
- Current mutation is uncommitted generated runtime output, not a committed source change.
- Validation evidence should not proceed on a mutated tracked dashboard file.
- After restore, keep scheduler process from rewriting this target (stop process or isolate dashboard path) before resuming validation.
