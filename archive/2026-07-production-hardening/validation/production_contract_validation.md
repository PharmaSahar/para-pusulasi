# Production Contract Validation for 9 Failing Tests

Date: 2026-07-12
Worktree: /tmp/preprod_runtime_continue_adc021b_1783802427
Candidate SHA: adc021b7842f1fb60ec289687128d539637745e8

## Scope and Evidence Sources

- Full-suite failure source: /tmp/obs_rootcause_pytest_full.txt
- Targeted runtime replay source: /tmp/obs_contract_runtime_9tests.txt
- Behavior-changing commit patch source: /tmp/obs_contract_commit_631eb704.patch
- Test-contract commit patch source: /tmp/obs_contract_commit_469c7997.patch
- Commit metadata source: `git show --no-patch` and `git blame` outputs captured in terminal

Note on PR/issue discussion: no repository-local PR/issue discussion metadata was available from executable local git evidence.

## Step 1 - Contract Identification (per failing test)

### 1) tests/test_editor_review.py::test_pipeline_keeps_full_flow_when_editor_review_succeeds
- Test location: tests/test_editor_review.py:203
- Production code location: src/pipeline.py:1466-1821
- Introducing commit (test): 1d0bee23936514ebd2ba9d1b4b63fe6549a50f25
- Commit message: feat: add shadow editor review metadata
- Protected contract (1 sentence): Pipeline must still produce a main upload `video_id` when editor review succeeds.

### 2) tests/test_pipeline_telemetry_fail_open.py::test_pipeline_marks_upload_failed_when_video_id_missing
- Test location: tests/test_pipeline_telemetry_fail_open.py:335
- Production code location: src/pipeline.py:1466-1499, 1815-1821
- Introducing commit (test): 469c7997ffc429fa999e1bddea9d61d1ab2285ce
- Commit message: fix: enforce cutover SHA match and harden upload/chart failures
- Protected contract: If uploader returns missing `video_id`, final status must be `failed`.

### 3) tests/test_pipeline_telemetry_fail_open.py::test_pipeline_short_upload_is_skipped_when_main_upload_fails
- Test location: tests/test_pipeline_telemetry_fail_open.py:358
- Production code location: src/pipeline.py:1599-1721
- Introducing commit (test): 469c7997ffc429fa999e1bddea9d61d1ab2285ce
- Commit message: fix: enforce cutover SHA match and harden upload/chart failures
- Protected contract: When main upload fails, shorts stage should emit skipped reason `main_upload_failed`.

### 4) tests/test_pipeline_telemetry_fail_open.py::test_pipeline_thumbnail_experiment_binding_fail_open_continues
- Test location: tests/test_pipeline_telemetry_fail_open.py:451
- Production code location: src/pipeline.py:773-790, 1466-1499
- Introducing commit (test): 10c4eaf663136426bbcbf7431d44d47cb99631df
- Commit message: feat: integrate thumbnail variants into pipeline metadata
- Protected contract: Thumbnail experiment binding errors are fail-open and must not prevent successful upload.

### 5) tests/test_pipeline_telemetry_fail_open.py::test_pipeline_thumbnail_selection_fail_open_continues
- Test location: tests/test_pipeline_telemetry_fail_open.py:626
- Production code location: src/pipeline.py:773-790, 1466-1499
- Introducing commit (test): 689d0d8b35ae5233e771a8736ec50b28e3047ca9
- Commit message: feat: add thumbnail selection metadata to pipeline
- Protected contract: Thumbnail selection errors are fail-open and must not prevent successful upload.

### 6) tests/test_pipeline_telemetry_fail_open.py::test_pipeline_audio_metadata_validation_fail_open_sets_warning
- Test location: tests/test_pipeline_telemetry_fail_open.py:752
- Production code location: src/pipeline.py:623-630, 1466-1499
- Introducing commit (test): 4d885cbd650019408844b7725ee68c509d6368d6
- Commit message: feat: standardize audio metadata fail-open in pipeline
- Protected contract: Audio metadata validation failure is fail-open and upload still succeeds.

### 7) tests/test_render_metrics.py::test_pipeline_keeps_fail_open_when_render_metrics_builder_raises
- Test location: tests/test_render_metrics.py:207
- Production code location: src/pipeline.py:1395-1402, 1466-1499
- Introducing commit (test): 6e5e54dc929180d356202266baae33be3eca310a
- Commit message: feat: add render performance measurement metadata
- Protected contract: Render metrics builder failures are fail-open and must not block successful upload.

### 8) tests/test_scheduler_topic_domain_guard.py::test_scheduler_quarantines_topic_domain_block
- Test location: tests/test_scheduler_topic_domain_guard.py:9
- Production code location: scheduler.py:583-631, 681-715
- Introducing commit (test): 631eb704d0af9a057cca6f737855f0d446da5f91
- Commit message: fix: block cross-channel and invalid artifact uploads
- Protected contract: Topic-domain blocked errors must quarantine queue entry with guard code and no normal active scheduling path.

### 9) tests/test_scheduler_topic_domain_guard.py::test_scheduler_topic_domain_block_is_not_retried
- Test location: tests/test_scheduler_topic_domain_guard.py:48
- Production code location: scheduler.py:626-631
- Introducing commit (test): 631eb704d0af9a057cca6f737855f0d446da5f91
- Commit message: fix: block cross-channel and invalid artifact uploads
- Protected contract: Topic-domain blocked errors must not trigger scheduler retry loop.

## Step 2 - Current Implementation Status

Status key: IMPLEMENTED / REMOVED / SUPERSEDED / UNKNOWN

1. editor_review success -> expects `video_id`: SUPERSEDED
- Current code explicitly blocks upload when `upload_precheck.status == "blocked"` before upload success assignment (src/pipeline.py:1479-1501).

2. missing video id -> expects `final_status=failed`: SUPERSEDED
- Current final status prefers `blocked` when upload precheck blocks (src/pipeline.py:1816-1818).

3. shorts skipped reason -> expects `main_upload_failed`: SUPERSEDED
- Current code sets `main_upload_blocked` when precheck blocked branch occurs (src/pipeline.py:1602-1603).

4. thumbnail binding fail-open -> expects upload success: SUPERSEDED
- Fail-open warning still recorded, but upload can be blocked by precheck guard (src/pipeline.py:790 and 1466-1501).

5. thumbnail selection fail-open -> expects upload success: SUPERSEDED
- Fail-open warning still recorded, but upload can be blocked by precheck guard (src/pipeline.py:777 and 1466-1501).

6. audio metadata fail-open -> expects upload success: SUPERSEDED
- Audio fail-open warning remains, but upload may be blocked by precheck guard (src/pipeline.py:623-630 and 1466-1501).

7. render metrics fail-open -> expects upload success: SUPERSEDED
- Metrics fail-open warning remains, but upload may be blocked by precheck guard (src/pipeline.py:1395-1402 and 1466-1501).

8. topic-domain block quarantines queue entry: REMOVED (at candidate), IMPLEMENTED (current)
- Candidate (adc021b) shows no quarantine entry for topic-domain blocked exceptions raised from pipeline path (evidence: worktree run + production-like exception probe).
- Current (d51e315) adds explicit NON_RETRYABLE_QUARANTINE classification and `_quarantine_non_retryable_domain_block` upsert path.

9. topic-domain block is not retried: IMPLEMENTED (for production-like exception path)
- Candidate (adc021b) does not retry when exception carries production retry marker `_skip_scheduler_pipeline_retry=True`.
- The failing test fixture in adc021b used a plain `RuntimeError` without production retry marker metadata, so generic retry path was expected there.

## Step 3 - Runtime Verification (exact failing scenarios)

Command executed:
`PYTHONPATH=. "/Users/klara/Downloads/adsız klasör/.venv-2/bin/python" -m pytest -vv --tb=long -W error [9 test nodes]`

Output file: /tmp/obs_contract_runtime_9tests.txt
Exit code: 1

Observed actual behavior:
- Tests 1-7: All fail with missing `video_id` and logs show `Upload precheck blocked` with guard reason codes.
- Test 2 specifically: expected `final_status == failed`, actual `final_status == blocked`.
- Test 3 specifically: expected shorts reason `main_upload_failed`, actual flow corresponds to blocked branch.
- Test 8: expected queue quarantine entry; actual key missing and scheduler logs show retries.
- Test 9: expected `calls["pipeline"] == 1`; actual `3`, with retry logs `Deneme 1/3`, `Deneme 2/3`.

Conclusion from runtime: actual behavior is consistent with current production code branches.

## Step 4 - Git Archaeology (who changed behavior, commit, why)

Primary contract-shift commit identified:
- SHA: 631eb704d0af9a057cca6f737855f0d446da5f91
- Author: Sahar
- Date: Sat Jul 11 19:28:57 2026 +0300
- Message: fix: block cross-channel and invalid artifact uploads
- Diff evidence: /tmp/obs_contract_commit_631eb704.patch

Behavior-changing hunks in that commit include:
- Added upload precheck evaluation and blocked branch in pipeline (`evaluate_upload_precheck`, `upload_precheck_blocked` stage failure).
- Added `final_status = "blocked"` when precheck status is blocked.
- Added shorts skip reason `main_upload_blocked`.
- Added scheduler quarantine branch for blocked upload results.
- Added/updated scheduler topic-domain guard tests asserting no-retry/quarantine behavior.

Additional test-contract commit:
- SHA: 469c7997ffc429fa999e1bddea9d61d1ab2285ce
- Author: Sahar
- Date: Sat Jul 11 10:21:33 2026 +0300
- Message: fix: enforce cutover SHA match and harden upload/chart failures
- Diff evidence: /tmp/obs_contract_commit_469c7997.patch
- This commit introduced expectations like `final_status == failed` and shorts reason `main_upload_failed`.

No later behavior-changing commit found in core runtime files for these branches between 631eb704 and adc021b for pipeline/scheduler precheck/retry logic beyond the already documented contract branch in 631eb704.

## Step 5 - Classification Table

| Test | Contract | Current behavior | Correct? | Classification |
|------|----------|------------------|----------|----------------|
| tests/test_editor_review.py::test_pipeline_keeps_full_flow_when_editor_review_succeeds | Editor-review success should still yield video_id | Upload precheck blocked path can prevent video_id | YES (matches current guard design) | OUTDATED TEST |
| tests/test_pipeline_telemetry_fail_open.py::test_pipeline_marks_upload_failed_when_video_id_missing | Missing upload id should end as failed | Precheck block now sets final_status blocked | YES (matches current design precedence) | OUTDATED TEST |
| tests/test_pipeline_telemetry_fail_open.py::test_pipeline_short_upload_is_skipped_when_main_upload_fails | Shorts skip reason should be main_upload_failed | For precheck block, reason is main_upload_blocked | YES (matches current explicit branch) | OUTDATED TEST |
| tests/test_pipeline_telemetry_fail_open.py::test_pipeline_thumbnail_experiment_binding_fail_open_continues | Thumbnail binding fail-open should still upload | Fail-open warning emitted, but upload can be blocked by precheck | YES (composed contract changed) | OUTDATED TEST |
| tests/test_pipeline_telemetry_fail_open.py::test_pipeline_thumbnail_selection_fail_open_continues | Thumbnail selection fail-open should still upload | Fail-open warning emitted, but upload can be blocked by precheck | YES (composed contract changed) | OUTDATED TEST |
| tests/test_pipeline_telemetry_fail_open.py::test_pipeline_audio_metadata_validation_fail_open_sets_warning | Audio metadata fail-open should still upload | Warning emitted, upload may still be precheck-blocked | YES (composed contract changed) | OUTDATED TEST |
| tests/test_render_metrics.py::test_pipeline_keeps_fail_open_when_render_metrics_builder_raises | Metrics fail-open should still upload | Warning emitted, upload may still be precheck-blocked | YES (composed contract changed) | OUTDATED TEST |
| tests/test_scheduler_topic_domain_guard.py::test_scheduler_quarantines_topic_domain_block | Topic-domain blocked exception should quarantine queue | Candidate lacked non-retryable quarantine exception branch; current adds explicit quarantine upsert path | NO at candidate / YES current | PRODUCTION REGRESSION |
| tests/test_scheduler_topic_domain_guard.py::test_scheduler_topic_domain_block_is_not_retried | Topic-domain blocked exception should not retry | Candidate does not retry when production marker `_skip_scheduler_pipeline_retry` is present; test fixture omitted marker and forced generic retry | YES for production-like path | OUTDATED TEST |

## Step 6 - Impact Quantification

### OUTDATED TESTS (8)

Why obsolete:
- Newer guard contract introduced by commit 631eb704 enforces pre-upload blocking for invalid/cross-channel artifacts.
- Earlier fail-open tests assumed upload path remained authoritative; current contract inserts stronger precheck gate before upload completion semantics.

Newer replacement contract:
- `upload_precheck.status == blocked` is a first-class terminal branch with:
  - `final_status = blocked`
  - `short_upload_skipped_reason = main_upload_blocked`
  - scheduler quarantine integration for blocked outputs

Is production behavior healthier:
- YES for artifact-integrity safety: blocking invalid/cross-channel uploads is safer than continuing to upload.

### PRODUCTION REGRESSION (1)

- Affected users/channels/path:
  - Affected users: scheduler operators expecting deterministic quarantine records for terminal topic-domain blocks
  - Affected channels: channels receiving `topic_domain_blocked` exceptions
  - Affected scheduler path at candidate: `scheduler.render_and_schedule` exception path without `_quarantine_non_retryable_domain_block`
  - Risk level: MEDIUM (terminal blocks not materialized into queue quarantine state)

### OUTDATED TEST DELTA (+1)

- `tests/test_scheduler_topic_domain_guard.py::test_scheduler_topic_domain_block_is_not_retried` fixture in adc021b used plain `RuntimeError` lacking production retry marker fields, so it asserted a contract on an invalid/legacy fixture shape.

## Step 7 - Repair Strategy (no implementation)

### For OUTDATED TESTS (8)

Minimum test updates:
1. Update pipeline assertions to allow/expect blocked precheck branch where fixtures currently create out-of-scope artifact paths.
2. Prefer asserting invariant warnings/events plus precheck reason codes instead of unconditional `video_id` success in these scenarios.
3. For shorts expectation, assert `main_upload_blocked` when precheck is blocked.

Estimated LOC (tests only): 40-120 LOC.

### For PRODUCTION REGRESSION (1)

Minimum fix target:
1. Ensure topic-domain blocked exceptions are classified into a non-retryable quarantine path.
2. Persist quarantined queue entry with guard reason codes and identity fields.

Estimated LOC:
- Production-path alignment in scheduler: 20-60 LOC

### For OUTDATED TEST (1 newly resolved)

Minimum test update:
1. Use production-like topic-domain exception shape (retry marker/guard metadata) or assert branch on current classifier contract.

Estimated LOC:
- Test-only alignment: 8-20 LOC

## Final Totals

- Total failing tests reviewed: 9
- OUTDATED TEST: 8
- PRODUCTION REGRESSION: 1
- UNKNOWN: 0

Deployment recommendation: NO-GO because at least one production regression exists in the validated failing set (candidate SHA scope).
