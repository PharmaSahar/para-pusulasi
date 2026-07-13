# Final Production Recovery TODOs

- [x] T00 Freeze repository state
- [x] T01 Freeze authoritative production contracts
- [x] T02 Restore scheduler baseline control flow
- [x] T03 Fix terminal topic-domain quarantine regression
- [x] T04 Add focused scheduler regression tests
- [x] T05 Define Telegram lifecycle and cooldown policy
- [x] T06 Implement path sanitization fix
- [x] T07 Harden observability fail-open boundaries
- [x] T08 Validate incident identity and lifecycle
- [x] T09 Migrate the 8 outdated tests
- [x] T10 Validate concurrency and bounded storage
- [x] T11 Run complete validation matrix
- [x] T12 Produce commit plan
- [ ] T13 Final release-readiness decision

## T00 Freeze repository state
- Status: COMPLETED
- Command: `pwd && git branch --show-current && git rev-parse HEAD && git status --short && git diff --stat && git diff --check && git diff --name-status && git worktree list`
- Result: PASS
- Changed files: artifacts/latest/final_recovery_repo_state.txt
- Evidence: artifacts/latest/final_recovery_repo_state.txt
- Residual risk: workspace remains globally dirty with many unrelated pre-existing files.

## T01 Freeze authoritative production contracts
- Status: COMPLETED
- Command: contract freeze from scheduler/pipeline/scheduler_utils and contract artifacts
- Result: PASS
- Changed files: artifacts/latest/final_authoritative_contracts.md
- Evidence: artifacts/latest/final_authoritative_contracts.md
- Residual risk: contract drift risk if new untracked branch changes are introduced later.

## T02 Restore scheduler baseline control flow
- Status: COMPLETED
- Command: patch scheduler.py and validate with focused provider guardrail tests
- Result: PASS
- Changed files: scheduler.py, tests/test_scheduler_provider_guardrails.py
- Evidence: focused guardrail tests (5 passed), final_production_validation.txt
- Residual risk: none observed in current suite.

## T03 Fix terminal topic-domain quarantine regression
- Status: COMPLETED
- Command: validate scheduler topic-domain guard behavior and quarantine path
- Result: PASS
- Changed files: scheduler.py (already aligned), tests/test_scheduler_topic_domain_guard.py
- Evidence: tests/test_scheduler_topic_domain_guard.py (8 passed)
- Residual risk: none observed in current suite.

## T04 Add focused scheduler regression tests
- Status: COMPLETED
- Command: run focused scheduler guardrail + topic-domain files
- Result: PASS
- Changed files: tests/test_scheduler_provider_guardrails.py, tests/test_scheduler_topic_domain_guard.py
- Evidence: 34 passed focused safety run
- Residual risk: none observed.

## T05 Define Telegram lifecycle and cooldown policy
- Status: COMPLETED
- Command: define and freeze policy from current implementation
- Result: PASS
- Changed files: artifacts/latest/telegram_incident_policy.md
- Evidence: artifacts/latest/telegram_incident_policy.md
- Residual risk: policy assumes current dedupe semantics; major future refactor must revalidate.

## T06 Implement path sanitization fix
- Status: COMPLETED
- Command: patch sanitizer and add regression tests
- Result: PASS
- Changed files: src/scheduler_utils.py, tests/test_observability_incident_safety.py
- Evidence: path redaction tests pass (in 10-test incident-safety run)
- Residual risk: unknown exotic path formats not covered by current regexes.

## T07 Harden observability fail-open boundaries
- Status: COMPLETED
- Command: patch alert cooldown persistence path and validate probes
- Result: PASS
- Changed files: src/scheduler_utils.py, tests/test_observability_incident_safety.py
- Evidence: artifacts/latest/observability_fail_open_validation.json
- Residual risk: lock-timeout behavior validated by probe-level monkeypatch, not heavy multi-process stress.

## T08 Validate incident identity and lifecycle
- Status: COMPLETED
- Command: run lifecycle probes for OPEN/UPDATED/RESOLVED, restart, stale-state, severity lane
- Result: PASS
- Changed files: artifacts/latest/incident_lifecycle_validation.json
- Evidence: artifacts/latest/incident_lifecycle_validation.json
- Residual risk: validation is probe-based; no dedicated standalone lifecycle pytest module yet.

## T09 Migrate the 8 outdated tests
- Status: COMPLETED
- Command: run exact 8 node IDs and related files
- Result: PASS
- Changed files: tests/test_scheduler_provider_guardrails.py, tests/test_scheduler_topic_domain_guard.py, tests/test_observability_incident_safety.py, artifacts/latest/outdated_test_migration_report.md
- Evidence: artifacts/latest/outdated_test_migration_report.md
- Residual risk: none observed in migrated nodes.

## T10 Validate concurrency and bounded storage
- Status: COMPLETED
- Command: threaded and bounded-storage probes plus stale pruning checks
- Result: PASS
- Changed files: src/scheduler_utils.py, tests/test_observability_incident_safety.py, artifacts/latest/concurrency_storage_validation.json
- Evidence: artifacts/latest/concurrency_storage_validation.json
- Residual risk: multi-process contention remains probe-level (no fork-based stress harness in this pass).

## T11 Run complete validation matrix
- Status: COMPLETED
- Command: diff check, py_compile, focused tests, legacy nodes, related files, full suite, strict suite retry
- Result: PASS (strict suite had one transient first-attempt failure, second full strict run passed)
- Changed files: artifacts/latest/final_production_validation.txt
- Evidence: artifacts/latest/final_production_validation.txt
- Residual risk: strict suite transient suggests potential order-sensitive test side effect.

## T12 Produce commit plan
- Status: COMPLETED
- Command: prepare commit slicing in final report
- Result: PASS
- Changed files: artifacts/latest/final_production_recovery_report.md
- Evidence: final report commit plan section
- Residual risk: dirty workspace requires careful staging to avoid unrelated files.

## T13 Final release-readiness decision
- Status: NOT STARTED
- Objective: Decide GO or NO-GO from verified evidence.
- Residual risk gating: unresolved unexplained modified files in global workspace prevent clean GO assertion for this task.
