# Final Authoritative Contracts

Date: 2026-07-12
Scope: freeze authoritative production contracts for recovery execution.

## 1. Provider preflight failure behavior
- Source of truth: [scheduler.py](scheduler.py#L1998-L2017), [artifacts/latest/observability_line_level_proof.md](artifacts/latest/observability_line_level_proof.md)
- Exact function: `scheduler.main`
- Baseline behavior: provider preflight failure exits with `sys.exit(1)` after recording safety-gate failure.
- Current behavior: if `ANTHROPIC_FAIL_OPEN_LOCAL_CONTENT=true`, startup logs a degraded warning and continues.
- Intended behavior: baseline exit semantics must remain unless an explicit, documented degraded-mode contract authorizes continuation.
- Forbidden behavior: silently continuing production startup on preflight failure without explicit contract approval.
- Relevant tests: `tests/test_scheduler_provider_guardrails.py::test_main_exits_when_provider_preflight_fails`, `tests/test_scheduler_provider_guardrails.py::test_main_continues_when_provider_preflight_fails_but_local_fail_open_enabled`

## 2. Provider circuit-open behavior
- Source of truth: [scheduler.py](scheduler.py#L813-L831), [tests/test_scheduler_provider_guardrails.py](tests/test_scheduler_provider_guardrails.py#L121-L172)
- Exact function: `scheduler.render_and_schedule`
- Baseline behavior: open Anthropic circuit returns early after `notify_error`.
- Current behavior: with fail-open enabled, the branch logs degraded continuation and does not return immediately.
- Intended behavior: open provider circuits must not advance production work unless a documented degraded-mode contract explicitly allows it.
- Forbidden behavior: rendering/upload work while a circuit-open gate is intended to stop production work.
- Relevant tests: `tests/test_scheduler_provider_guardrails.py::test_render_and_schedule_skips_when_provider_circuit_open`, `tests/test_scheduler_provider_guardrails.py::test_render_and_schedule_continues_when_provider_circuit_open_in_fail_open_mode`

## 3. Global overload behavior
- Source of truth: [scheduler.py](scheduler.py#L789-L811), [tests/test_scheduler_provider_guardrails.py](tests/test_scheduler_provider_guardrails.py#L173-L223)
- Exact function: `scheduler.render_and_schedule`
- Baseline behavior: open global overload pause returns early after `notify_error`.
- Current behavior: with fail-open enabled, branch continues degraded instead of returning.
- Intended behavior: baseline pause/skip contract must be preserved unless the production contract explicitly authorizes degraded execution.
- Forbidden behavior: treating overload pause as a soft log-only condition when the baseline path was skip/return.
- Relevant tests: `tests/test_scheduler_provider_guardrails.py::test_render_and_schedule_skips_when_global_overload_pause_open`

## 4. Fail-open enabled behavior
- Source of truth: [scheduler.py](scheduler.py#L793-L823), [scheduler.py](scheduler.py#L2001-L2017)
- Exact function: `scheduler.render_and_schedule`, `scheduler.main`
- Baseline behavior: no local fail-open bypass existed for these gates.
- Current behavior: `ANTHROPIC_FAIL_OPEN_LOCAL_CONTENT=true` enables degraded continuation.
- Intended behavior: only explicitly contracted degraded paths may run; observability changes must not redefine business control flow by default.
- Forbidden behavior: changing production decisions through observability-only patching.
- Relevant tests: `tests/test_scheduler_provider_guardrails.py::test_main_continues_when_provider_preflight_fails_but_local_fail_open_enabled`, `tests/test_scheduler_provider_guardrails.py::test_render_and_schedule_continues_when_provider_circuit_open_in_fail_open_mode`

## 5. Fail-open disabled behavior
- Source of truth: [scheduler.py](scheduler.py#L789-L811), [scheduler.py](scheduler.py#L815-L831), [scheduler.py](scheduler.py#L1998-L2017)
- Exact function: `scheduler.render_and_schedule`, `scheduler.main`
- Baseline behavior: exit/return on provider preflight failure, circuit-open, and global overload pause.
- Current behavior: disabled path still matches baseline in the targeted tests.
- Intended behavior: disabled mode must preserve baseline control flow exactly.
- Forbidden behavior: any degraded continuation when fail-open is disabled.
- Relevant tests: `tests/test_scheduler_provider_guardrails.py::test_main_exits_when_provider_preflight_fails`, `tests/test_scheduler_provider_guardrails.py::test_render_and_schedule_skips_when_provider_circuit_open`, `tests/test_scheduler_provider_guardrails.py::test_render_and_schedule_skips_when_global_overload_pause_open`

## 6. Terminal topic_domain_blocked behavior
- Source of truth: [artifacts/latest/production_contract_validation.md](artifacts/latest/production_contract_validation.md), [artifacts/latest/unknown_contract_resolution.md](artifacts/latest/unknown_contract_resolution.md), [scheduler.py](scheduler.py#L896-L915)
- Exact function: `scheduler.render_and_schedule`, `scheduler._classify_pipeline_failure`
- Baseline behavior: in the validated production contract set, terminal topic-domain blocks must quarantine and must not retry.
- Current behavior: current code paths include non-retryable quarantine logic, but legacy test fixtures may omit production retry-skip metadata.
- Intended behavior: terminal topic-domain blocks are quarantined exactly once and do not enter the generic retry loop.
- Forbidden behavior: retrying terminal topic-domain blocks; dropping quarantine entry creation; uploading blocked content.
- Relevant tests: `tests/test_scheduler_topic_domain_guard.py::test_scheduler_quarantines_topic_domain_block`, `tests/test_scheduler_topic_domain_guard.py::test_scheduler_topic_domain_block_is_not_retried`, `tests/test_scheduler_topic_domain_guard.py::test_quarantine_duplicate_handling_is_idempotent`

## 7. Quarantine queue contract
- Source of truth: [artifacts/latest/current_production_contracts.md](artifacts/latest/current_production_contracts.md), [tests/test_scheduler_topic_domain_guard.py](tests/test_scheduler_topic_domain_guard.py#L1-L160)
- Exact function: `scheduler._quarantine_non_retryable_domain_block`
- Baseline behavior: queue quarantine entry must be idempotent and include identity/guard metadata.
- Current behavior: current scheduler code materializes quarantined entries with guard metadata and upserts duplicates.
- Intended behavior: one quarantined entry per same terminal item identity; blocked item remains non-active.
- Forbidden behavior: missing queue entry, duplicate queue entries, or active/restored status for a blocked item.
- Relevant tests: `tests/test_scheduler_topic_domain_guard.py::test_quarantine_entry_contains_identity_fields`, `tests/test_scheduler_topic_domain_guard.py::test_quarantine_duplicate_handling_is_idempotent`

## 8. Retryable exception behavior
- Source of truth: [scheduler.py](scheduler.py#L896-L903), [tests/test_scheduler_topic_domain_guard.py](tests/test_scheduler_topic_domain_guard.py#L56-L160)
- Exact function: `scheduler._classify_pipeline_failure`, `scheduler.render_and_schedule`
- Baseline behavior: transient provider/network failures remain retryable.
- Current behavior: transient failure test still retries to success.
- Intended behavior: only terminal domain-policy failures skip retry; ordinary transient failures continue retrying.
- Forbidden behavior: globally disabling retries for transient failures.
- Relevant tests: `tests/test_scheduler_topic_domain_guard.py::test_transient_provider_failure_remains_retryable`

## 9. Observability fail-open behavior
- Source of truth: [artifacts/latest/observability_root_cause.md](artifacts/latest/observability_root_cause.md), [src/scheduler_utils.py](src/scheduler_utils.py#L830-L879)
- Exact function: `src.scheduler_utils.notify_error`, `src.scheduler_utils.notify_upload`, `src.scheduler_utils._load_incident_state`
- Baseline behavior: observability write/send failures are non-blocking telemetry failures.
- Current behavior: notifier and incident resolve telemetry are wrapped so exceptions are caught and logged.
- Intended behavior: observability failures must not alter render/upload decision flow.
- Forbidden behavior: alert persistence or Telegram timeout causing render/upload divergence.
- Relevant tests: `tests/test_observability_incident_safety.py::test_notify_error_fail_open_when_incident_write_fails`

## 10. Telegram lifecycle policy
- Source of truth: [artifacts/latest/observability_root_cause.md](artifacts/latest/observability_root_cause.md), [artifacts/latest/production_observability_audit.md](artifacts/latest/production_observability_audit.md)
- Exact function: `src.scheduler_utils.notify_error`, `src.scheduler_utils._register_incident_event`, `src.scheduler_utils.notify_upload`
- Baseline behavior: structured incident lifecycle is recorded in state/events, but not every lifecycle transition is necessarily emitted as a Telegram card.
- Current behavior: isolated lifecycle probe produced OPEN and upload-resolve Telegram messages; UPDATED existed in structured events but not as a Telegram card.
- Intended behavior: lifecycle policy must be explicit before treating missing UPDATED notifications as a defect.
- Forbidden behavior: claiming exact OPEN -> UPDATED -> RESOLVED Telegram parity without a documented policy.
- Relevant tests: `tests/test_observability_incident_safety.py`, `tests/test_scheduler_provider_guardrails.py::test_notify_error_dedupes_anthropic_cooldown_across_channels`

## 11. Telegram cooldown policy
- Source of truth: [src/scheduler_utils.py](src/scheduler_utils.py#L919-L935), [tests/test_scheduler_provider_guardrails.py](tests/test_scheduler_provider_guardrails.py#L363-L394)
- Exact function: `src.scheduler_utils._build_render_error_alert_key`, `src.scheduler_utils.notify_error`
- Baseline behavior: cooldown suppresses repeated render-error alerts by key.
- Current behavior: cooldown suppresses duplicate/cross-channel provider cooldown noise and returns without sending a Telegram message.
- Intended behavior: OPEN and RESOLVED semantics should not be silently lost unless policy explicitly permits that cooldown class.
- Forbidden behavior: unbounded alert spam or collision of unrelated incidents under the same cooldown key.
- Relevant tests: `tests/test_scheduler_provider_guardrails.py::test_notify_error_dedupes_anthropic_cooldown_across_channels`, `tests/test_scheduler_provider_guardrails.py::test_notify_error_keeps_non_cooldown_alerts_channel_scoped`

## 12. Non-debug path redaction contract
- Source of truth: [src/scheduler_utils.py](src/scheduler_utils.py#L167-L173), [artifacts/latest/observability_root_cause.md](artifacts/latest/observability_root_cause.md)
- Exact function: `src.scheduler_utils._sanitize_operator_text`
- Baseline behavior: operator text should hide raw absolute/relative paths when debug mode is off.
- Current behavior: sanitizer masks some paths but leaks `/var/...`, `/home/...`, and `relative/path/...` in the final Telegram payload probe.
- Intended behavior: non-debug Telegram/operator payloads must not expose raw filesystem paths.
- Forbidden behavior: raw absolute path leakage in operator-facing messages.
- Relevant tests: `tests/test_observability_incident_safety.py` path-sanitizer probe, `tests/test_scheduler_provider_guardrails.py` cooldown tests
