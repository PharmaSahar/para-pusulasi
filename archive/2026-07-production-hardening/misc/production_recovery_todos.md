# Production Recovery TODOs

- [x] T00 Repository state capture
- [x] T01 Current contract evidence freeze
- [x] T02 Reproduce the single production regression
- [x] T03 Implement minimal scheduler quarantine fix
- [x] T04 Add regression tests for quarantine metadata and no-retry behavior
- [x] T05 Validate the production regression fix
- [x] T06 Update the 8 outdated tests to the current production contract
- [x] T07 Validate all updated test contracts independently
- [x] T08 Audit observability patch boundaries
- [x] T09 Harden observability fail-open behavior
- [ ] T10 Validate incident identity and lifecycle
- [ ] T11 Validate Telegram cooldown and noise behavior
- [ ] T12 Validate concurrency and bounded storage
- [ ] T13 Run full validation matrix
- [ ] T14 Produce final release-readiness report
- [ ] T15 Prepare commit plan without committing
- [ ] T16 Final GO / NO-GO decision

## T00 Repository state capture
- Status: COMPLETED
- Objective: Capture exact repository/worktree state before any recovery changes.
- Files involved: artifacts/latest/repository_state_before_recovery.txt
- Commands: cd '/Users/klara/Downloads/adsız klasör' && { date -u; pwd; git branch --show-current; git rev-parse HEAD; git status --short; git diff --stat; git diff --check; git diff --name-status; git ls-files --others --exclude-standard; git worktree list; } > artifacts/latest/repository_state_before_recovery.txt
- Evidence: artifacts/latest/repository_state_before_recovery.txt contains branch=master, HEAD=d51e31578e3f3bd18674441f2f7545a2dce2dd05, full tracked/untracked inventory, and worktree list.
- Result: Repository and active worktree are confirmed; state is frozen before recovery edits.
- Risks: Dirty tree is large and includes many pre-existing tracked/untracked files; unrelated changes must remain untouched.
- Next step: freeze authoritative production contract sources in a dedicated contracts file.

## T01 Current contract evidence freeze
- Status: COMPLETED
- Objective: Freeze current production contracts from authoritative sources.
- Files involved: artifacts/latest/current_production_contracts.md
- Commands: read_file on artifacts/latest/production_contract_validation.md, artifacts/latest/unknown_contract_resolution.md, artifacts/latest/observability_root_cause.md, tests/test_scheduler_topic_domain_guard.py, scheduler.py, src/pipeline.py, src/scheduler_utils.py
- Evidence: artifacts/latest/current_production_contracts.md created with 8 required contracts and source/commit/code/test/intended/forbidden fields.
- Result: authoritative contract baseline frozen for recovery work.
- Risks: contract data is tied to current dirty workspace snapshot and prior evidence artifacts; any later code drift requires re-freeze.
- Next step: reproduce the single proven production regression with full before-state capture.

## T02 Reproduce the single production regression
- Status: COMPLETED
- Objective: Isolated deterministic reproduction for topic-domain quarantine regression.
- Files involved: artifacts/latest/topic_domain_quarantine_regression_before.txt, tests/repro_topic_domain_quarantine.py
- Commands: (1) isolated pytest node at current HEAD and candidate worktree adc021b with identical env isolation flags, (2) production-like probe evidence from artifacts/latest/unknown_contract_evidence/*_production_like_exception_probe.out, (3) standalone repro script execution with PYTHONPATH=. and isolated paths.
- Evidence: artifacts/latest/topic_domain_quarantine_regression_before.txt; artifacts/latest/topic_domain_quarantine_repro_output.json; artifacts/latest/unknown_contract_evidence/before_production_like_exception_probe.out; artifacts/latest/unknown_contract_evidence/after_production_like_exception_probe.out; tests/repro_topic_domain_quarantine.py
- Result: Regression is reproducible in candidate scope (adc021b: FAIL KeyError + retry loop) and resolved at current HEAD (d51e315: PASS). First divergent branch frozen as generic retry branch vs non-retryable quarantine branch.
- Risks: Current head no longer reproduces the failing node, so all "before" evidence must stay explicitly candidate-scoped to avoid false interpretation.
- Next step: verify whether any minimal production fix is still required in current workspace or already present; only patch if contract gap remains.

## T03 Implement minimal scheduler quarantine fix
- Status: COMPLETED
- Objective: Fix only terminal topic_domain_blocked quarantine path.
- Files involved: scheduler.py
- Commands: apply_patch on scheduler.py (_quarantine_non_retryable_domain_block + NON_RETRYABLE_QUARANTINE exception call payload), then get_errors for scheduler.py
- Evidence: scheduler.py now persists terminal quarantine metadata fields (timestamp, channel_name, selected_topic, expected_domain, source_exception_type/message, regeneration_count, terminal) in the same non-retryable path.
- Result: Minimal production-path patch applied without altering generic retry classification for unrelated exceptions.
- Risks: Queue schema widened with additional fields; downstream readers expecting strict minimal schema may need tolerant parsing (existing dict readers are expected to be compatible).
- Next step: add/strengthen focused regression tests for new required metadata and no-retry invariants.

## T04 Add regression tests for quarantine metadata and no-retry behavior
- Status: COMPLETED
- Objective: Add focused regression tests covering quarantine metadata/no-retry invariants.
- Files involved: tests/test_scheduler_topic_domain_guard.py
- Commands: apply_patch on tests/test_scheduler_topic_domain_guard.py (strengthened metadata assertions + 4 new focused tests), get_errors on updated test file
- Evidence: test_quarantine_entry_contains_identity_fields now validates required quarantine metadata fields; added tests for no scheduled uploaded content, other-channel continuity, and persistence-failure fail-safe behavior.
- Result: regression test coverage now includes required contract invariants without relaxing assertions.
- Risks: new tests rely on monkeypatched scheduler internals (update_queue) and could require refresh if queue API changes.
- Next step: run focused validation matrix and generate before/after comparison artifact.

## T05 Validate the production regression fix
- Status: COMPLETED
- Objective: Validate before/after regression behavior and guardrails.
- Files involved: artifacts/latest/topic_domain_quarantine_before_after.json
- Commands: py_compile scheduler.py; pytest single node tests/test_scheduler_topic_domain_guard.py::test_scheduler_quarantines_topic_domain_block; pytest file tests/test_scheduler_topic_domain_guard.py; pytest tests/test_scheduler_provider_guardrails.py (rerun with PREPROD_ISOLATION_MODE=false for behavior assertions); pytest tests/test_queue_quarantine_admin.py; pytest tests/test_governance_dashboard_safety.py
- Evidence: /tmp/t05_py_compile.out, /tmp/t05_single.out, /tmp/t05_guard_file.out, /tmp/t05_provider_guardrails_noiso.out, /tmp/t05_quarantine_admin.out, /tmp/t05_production_safety.out, artifacts/latest/topic_domain_quarantine_before_after.json
- Result: regression validation PASS in current workspace; before/after artifact confirms candidate failure (attempt=3, no quarantine) vs current behavior (attempt=1, quarantine created with required metadata).
- Risks: provider guardrails are sensitive to PREPROD_ISOLATION_MODE=true global env in test runtime; behavior validation uses PREPROD_ISOLATION_MODE=false to avoid unrelated isolation-gate failures.
- Next step: migrate only the 8 outdated tests to current contract without production-source edits.

## T06 Update the 8 outdated tests to the current production contract
- Status: COMPLETED
- Objective: Migrate only outdated tests to current contract without production code changes.
- Files involved: tests/test_editor_review.py, tests/test_pipeline_telemetry_fail_open.py, tests/test_render_metrics.py, tests/test_scheduler_topic_domain_guard.py
- Commands: extracted node list from artifacts/latest/production_contract_validation.md Step 5; apply_patch on tests/test_scheduler_topic_domain_guard.py to use production-shaped topic-domain exception fixture; pytest -q on exact 8 node IDs.
- Evidence: outdated node list frozen below; /tmp/t06_outdated_nodes.out (8 passed in 58.24s).
- Result: COMPLETED. All 8 formerly outdated nodes now pass against current production contract expectations.
- Risks: residual flake risk only; independent per-file validation remains in T07.
- Next step: run independent contract validation sweeps and persist migration report artifact.

Outdated node IDs (authoritative list):
1. tests/test_editor_review.py::test_pipeline_keeps_full_flow_when_editor_review_succeeds
2. tests/test_pipeline_telemetry_fail_open.py::test_pipeline_marks_upload_failed_when_video_id_missing
3. tests/test_pipeline_telemetry_fail_open.py::test_pipeline_short_upload_is_skipped_when_main_upload_fails
4. tests/test_pipeline_telemetry_fail_open.py::test_pipeline_thumbnail_experiment_binding_fail_open_continues
5. tests/test_pipeline_telemetry_fail_open.py::test_pipeline_thumbnail_selection_fail_open_continues
6. tests/test_pipeline_telemetry_fail_open.py::test_pipeline_audio_metadata_validation_fail_open_sets_warning
7. tests/test_render_metrics.py::test_pipeline_keeps_fail_open_when_render_metrics_builder_raises
8. tests/test_scheduler_topic_domain_guard.py::test_scheduler_topic_domain_block_is_not_retried

## T07 Validate all updated test contracts independently
- Status: COMPLETED
- Objective: Validate each migrated test independently and by file.
- Files involved: artifacts/latest/outdated_test_migration_report.md
- Commands: pytest -q tests/test_editor_review.py tests/test_pipeline_telemetry_fail_open.py tests/test_render_metrics.py tests/test_scheduler_topic_domain_guard.py; pytest -q on exact 8 node IDs.
- Evidence: /tmp/t07_per_file.out, /tmp/t07_per_node.out, /tmp/t06_outdated_nodes.out, artifacts/latest/outdated_test_migration_report.md
- Result: COMPLETED. Per-file sweep PASS (39/39) and node-level sweep PASS (8/8).
- Risks: residual runtime flake risk only; no contract mismatch detected.
- Next step: start T08 observability boundary audit with behavior-vs-observability hunk classification.

## T08 Audit observability patch boundaries
- Status: COMPLETED
- Objective: Separate observability-only hunks from behavior-changing hunks.
- Files involved: artifacts/latest/observability_scope_audit.md
- Commands: git diff -- scheduler.py src/scheduler_utils.py src/pipeline.py; hunk-map extraction; targeted source reads.
- Evidence: /tmp/t08_obs_diff.patch, artifacts/latest/observability_scope_audit.md
- Result: COMPLETED. Hunks classified into behavior+contract vs observability-only with keep/revert map.
- Risks: broad observability subsystem in src/scheduler_utils.py requires explicit fail-open/concurrency validation in T09-T12.
- Next step: execute fail-open safety validation and patch only if proven gaps exist.

## T09 Harden observability fail-open behavior
- Status: PASS
- Objective: Ensure observability failures cannot block business path.
- Files involved: src/scheduler_utils.py, tests/test_observability_incident_safety.py
- Commands: (1) git status --short, (2) git diff --check, (3) python -m py_compile src/scheduler_utils.py, (4) python -m pytest -vv -s --tb=long -W error on focused sanitizer/fail-open nodes, (5) python -m pytest -vv --tb=long -W error tests/test_observability_incident_safety.py, (6) python -m pytest -vv --tb=long -W error on focused scheduler/provider guardrail invariants.
- Evidence: artifacts/latest/t09_observability_fail_open_validation.txt
- Result: PASS. Focused sanitizer matrix and wider observability safety suite passed with -W error; guardrail invariants also passed.
- Risks: none identified in T09 scope after focused validation.
- Next step: T10 is now the next allowed TODO.

## T10 Validate incident identity and lifecycle
- Status: TODO
- Objective: Validate incident identity stability and lifecycle correctness.
- Files involved: artifacts/latest/production_recovery_validation.txt, artifacts/latest/production_recovery_final_report.md
- Commands: pending
- Evidence: pending
- Result: pending
- Risks: pending
- Next step: execute targeted lifecycle scenarios.

## T11 Validate Telegram cooldown and noise behavior
- Status: TODO
- Objective: Validate cooldown/noise policy and sanitizer coverage.
- Files involved: artifacts/latest/production_recovery_validation.txt
- Commands: pending
- Evidence: pending
- Result: pending
- Risks: pending
- Next step: run targeted cooldown/sanitizer tests.

## T12 Validate concurrency and bounded storage
- Status: TODO
- Objective: Validate concurrent writes, locking, rotation, retention bounds.
- Files involved: artifacts/latest/production_recovery_validation.txt
- Commands: pending
- Evidence: pending
- Result: pending
- Risks: pending
- Next step: run concurrency and storage safety tests.

## T13 Run full validation matrix
- Status: TODO
- Objective: Execute full matrix including strict -W error suite.
- Files involved: artifacts/latest/production_recovery_validation.txt
- Commands: pending
- Evidence: pending
- Result: pending
- Risks: pending
- Next step: run ordered validation commands and log outcomes.

## T14 Produce final release-readiness report
- Status: TODO
- Objective: Produce final PASS/FAIL evidence report.
- Files involved: artifacts/latest/production_recovery_final_report.md
- Commands: pending
- Evidence: pending
- Result: pending
- Risks: pending
- Next step: compile validated evidence into final report.

## T15 Prepare commit plan without committing
- Status: TODO
- Objective: Build commit plan boundaries and rollback lines without git commit.
- Files involved: artifacts/latest/production_recovery_final_report.md
- Commands: pending
- Evidence: pending
- Result: pending
- Risks: pending
- Next step: map files into independent commit groups.

## T16 Final GO / NO-GO decision
- Status: TODO
- Objective: Decide GO/NO-GO strictly on validated gates.
- Files involved: artifacts/latest/production_recovery_final_report.md
- Commands: pending
- Evidence: pending
- Result: pending
- Risks: pending
- Next step: evaluate all hard gates after full validation.
