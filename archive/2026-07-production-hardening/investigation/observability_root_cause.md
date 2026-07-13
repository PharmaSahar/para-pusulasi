# Observability Root-Cause Audit (Executable Evidence)

Date: 2026-07-12
Worktree: /tmp/preprod_runtime_continue_adc021b_1783802427
Candidate SHA: adc021b7842f1fb60ec289687128d539637745e8

## Step 1 - Complete Suite Failure Capture

Command executed:
`PYTHONPATH=. "/Users/klara/Downloads/adsız klasör/.venv-2/bin/python" -m pytest -vv --tb=long -W error > /tmp/obs_rootcause_pytest_full.txt 2>&1`

Exit code: `1`

Failing tests (9):
- tests/test_editor_review.py::test_pipeline_keeps_full_flow_when_editor_review_succeeds
- tests/test_pipeline_telemetry_fail_open.py::test_pipeline_marks_upload_failed_when_video_id_missing
- tests/test_pipeline_telemetry_fail_open.py::test_pipeline_short_upload_is_skipped_when_main_upload_fails
- tests/test_pipeline_telemetry_fail_open.py::test_pipeline_thumbnail_experiment_binding_fail_open_continues
- tests/test_pipeline_telemetry_fail_open.py::test_pipeline_thumbnail_selection_fail_open_continues
- tests/test_pipeline_telemetry_fail_open.py::test_pipeline_audio_metadata_validation_fail_open_sets_warning
- tests/test_render_metrics.py::test_pipeline_keeps_fail_open_when_render_metrics_builder_raises
- tests/test_scheduler_topic_domain_guard.py::test_scheduler_quarantines_topic_domain_block
- tests/test_scheduler_topic_domain_guard.py::test_scheduler_topic_domain_block_is_not_retried

Production-impact ranking:
1. HIGH: Upload path blocked before `video_id` assignment in multiple pipeline tests.
2. HIGH: Topic-domain blocked path retries 3x and diverges from quarantine/no-retry expectation.
3. MEDIUM: Shorts-upload telemetry expectations diverge because main branch exits blocked.

Complete failure output (verbatim artifacts):
- /tmp/obs_rootcause_pytest_full.txt
- /tmp/obs_rootcause_failures_only.txt

## Step 2 - First Behavioral Divergence (Before vs After)

Trace chain audited:
scheduler -> planner -> topic selection -> guard -> retry -> regeneration -> render -> upload -> telegram -> exit

First divergence in pipeline flow:
- BEFORE (expected by tests): upload success/fail-open path reaches `video_id` assertions.
- AFTER (observed): `upload_precheck` returns blocked; flow exits without `video_id`.
- Earliest divergence point: guard stage (upload precheck decision).

Evidence:
- Failure logs contain `Upload precheck blocked` with reason codes:
	`upload_precheck_final_guard`, `upload_precheck_script_missing`,
	`upload_precheck_thumbnail_path_channel_scope_violation`,
	`upload_precheck_video_path_channel_scope_violation`.

First divergence in scheduler topic-domain flow:
- BEFORE (expected by tests): domain block is quarantined without retries.
- AFTER (observed): retries run (`Deneme 1/3`, `Deneme 2/3`), then terminal failure path.
- Earliest divergence point: retry stage.

## Step 3 - Behavior Change Proof per Function

SHA-level runtime diff check:
- Command:
	`git diff 631eb704d0af9a057cca6f737855f0d446da5f91..adc021b7842f1fb60ec289687128d539637745e8 -- scheduler.py src/pipeline.py src/scheduler_utils.py`
- Result: `0` changed lines.

Function: `src/pipeline.py::run_full_pipeline`
- Reason modified: no SHA-level code diff in compared range.
- Behavior before: tests assert successful/fail-open upload semantics with `video_id`.
- Behavior after: runtime chooses precheck-blocked branch; `video_id` absent.
- Can execution change?: YES
- Evidence: pytest failures and captured log lines.

Function: `scheduler.py::render_and_schedule`
- Reason modified: no SHA-level code diff in compared range.
- Behavior before: tests assert no-retry quarantine on topic-domain block.
- Behavior after: observed 3-attempt retry path.
- Can execution change?: YES
- Evidence: pytest failures and retry warning logs.

Function: `src/scheduler_utils.py::notify_error`
- Reason modified: no SHA-level code diff in compared range.
- Behavior before/after: channel-scoped cooldown key suppression.
- Can execution change?: YES
- Evidence: simulation output `/tmp/obs_failopen_sim_clean.json`.

## Step 4 - Telegram Audit

Question: OPEN -> UPDATED -> RESOLVED exactly once?

Answer: NO.

Evidence:
- Simulation output `/tmp/obs_failopen_sim_clean.json`:
	- same channel + same incident twice -> message count remains 1
	- different channel + same incident -> message count increases to 2
- Key format includes channel scope:
	- `render_error::chana::...`
	- `render_error::chanb::...`
- No explicit UPDATED/RESOLVED notifier lifecycle implementation found in scheduler notifier path.

## Step 5 - Incident Identity Audit

Same retry/regeneration/channel:
- Same effective key; repeated alert suppressed.
- Evidence: `same_retry_same_channel_counts = [1, 1]`.

Different channels:
- Different effective keys.
- Evidence: distinct `alerts_keys` entries for `chana` and `chanb`.

Restart behavior:
- Persistent alerts state file -> merged/suppressed.
- Lost alerts state file -> treated as new incident.
- Evidence: `after_restart_persistent_state_count = 1`, `after_restart_lost_state_count = 2`.

## Step 6 - Observability Fail-Open Matrix

Source: `/tmp/obs_failopen_sim_clean.json`

- disk full: Pipeline continues? NO (`pipeline_called = 0`)
- permission denied (alerts write): Pipeline continues? NO (`raised = true`)
- corrupted json: Pipeline continues? YES (`notify_error_messages = 1`)
- missing directory: Pipeline continues? YES (`notify_error_messages = 1`, file created)
- telegram timeout: Pipeline continues? NO (`raised = true`)
- lock timeout/lock-busy: Pipeline continues? NO (`pipeline_called = 0`)

## Step 7 - Production Risk Matrix

1. Upload-precheck branch blocks expected upload path
- Severity: HIGH
- Probability: HIGH
- Impact: missing `video_id` on main path; cascades into downstream mismatch
- Recommended fix: align precheck contract and test fixtures around allowed manifest/script/video/thumbnail scope
- Estimated code size: 20-80 LOC

2. Topic-domain retry/quarantine mismatch
- Severity: HIGH
- Probability: HIGH
- Impact: repeated retries vs expected immediate quarantine
- Recommended fix: explicit no-retry classification for topic-domain blocked exceptions or align tests to actual policy
- Estimated code size: 15-50 LOC

3. Telegram lifecycle protocol gap
- Severity: MEDIUM
- Probability: HIGH
- Impact: OPEN/UPDATED/RESOLVED audit cannot pass
- Recommended fix: incident lifecycle states + stable incident identity
- Estimated code size: 80-180 LOC

4. Notifier path not fully fail-open (timeout/permission)
- Severity: MEDIUM
- Probability: MEDIUM
- Impact: notifier exceptions can alter control flow
- Recommended fix: non-blocking error handling around alert send/persist
- Estimated code size: 25-70 LOC

## Step 8 - Minimal Repair Plan (No Implementation)

Minimum code scope to reach PASS/PASS/GO:
1. `tests/test_editor_review.py`, `tests/test_render_metrics.py`, `tests/test_pipeline_telemetry_fail_open.py`
	 - align expected upload-precheck contract and fixture inputs
2. `tests/test_scheduler_topic_domain_guard.py` and/or `scheduler.py`
	 - make topic-domain retry/quarantine contract deterministic
3. `src/scheduler_utils.py`
	 - add incident lifecycle semantics and harden notify path fail-open behavior

Estimated footprint:
- Affected files: 4-7
- Affected functions: 6-10
- Estimated LOC: 140-380

## Final Determination

- Behavior-neutral proof: FAIL
- Telegram-noise: FAIL
- Deployment recommendation: NO-GO

All conclusions are based on executable evidence captured in this audit.
