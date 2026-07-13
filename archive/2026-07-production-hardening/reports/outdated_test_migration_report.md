# Outdated Test Migration Report (T07)

## Scope
Validated updated contract tests independently after T06 migration freeze.

Files under validation:
- tests/test_editor_review.py
- tests/test_pipeline_telemetry_fail_open.py
- tests/test_render_metrics.py
- tests/test_scheduler_topic_domain_guard.py

## Node List (Authoritative 8)
1. tests/test_editor_review.py::test_pipeline_keeps_full_flow_when_editor_review_succeeds
2. tests/test_pipeline_telemetry_fail_open.py::test_pipeline_marks_upload_failed_when_video_id_missing
3. tests/test_pipeline_telemetry_fail_open.py::test_pipeline_short_upload_is_skipped_when_main_upload_fails
4. tests/test_pipeline_telemetry_fail_open.py::test_pipeline_thumbnail_experiment_binding_fail_open_continues
5. tests/test_pipeline_telemetry_fail_open.py::test_pipeline_thumbnail_selection_fail_open_continues
6. tests/test_pipeline_telemetry_fail_open.py::test_pipeline_audio_metadata_validation_fail_open_sets_warning
7. tests/test_render_metrics.py::test_pipeline_keeps_fail_open_when_render_metrics_builder_raises
8. tests/test_scheduler_topic_domain_guard.py::test_scheduler_topic_domain_block_is_not_retried

## Executed Commands
- PYTHONPATH=. .venv-2/bin/python -m pytest -q tests/test_editor_review.py tests/test_pipeline_telemetry_fail_open.py tests/test_render_metrics.py tests/test_scheduler_topic_domain_guard.py
- PYTHONPATH=. .venv-2/bin/python -m pytest -q <8 exact node IDs>

## Evidence
- /tmp/t07_per_file.out
- /tmp/t07_per_node.out
- /tmp/t06_outdated_nodes.out

## Results
- Per-file sweep: 39 passed in 176.67s
- Per-node sweep: 8 passed in 57.93s
- T06 node validation replay: 8 passed in 58.24s

## Contract Integrity Notes
- No production source files were modified during T06/T07 migration scope.
- Node `test_scheduler_topic_domain_block_is_not_retried` fixture now emits production-shaped terminal metadata while preserving no-retry invariant.
- Upload-precheck fail-open/blocked assertions remain strict (no assertion weakening introduced in migrated node set).

## Residual Risk
- Normal runtime flake risk remains for time-sensitive test environments; no deterministic contract mismatch observed.
