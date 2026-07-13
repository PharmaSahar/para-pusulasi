# Observability Line-Level Proof Audit

Date: 2026-07-12
Scope: Verify every current FAIL claim with code-level and runtime evidence.

## 1) Repository State

Current state at audit start:
- Branch: `master`
- HEAD: `d51e31578e3f3bd18674441f2f7545a2dce2dd05`
- `git status --short`: dirty working tree with existing modified tracked files and untracked artifacts.
- `git diff --stat`: 16 files changed, 1241 insertions, 118 deletions.
- `git diff --check`: clean.
- `git diff --name-status`: tracked modifications only, no deletions.

Saved diff artifact:
- [artifacts/latest/observability_line_proof_diff.patch](artifacts/latest/observability_line_proof_diff.patch)

Machine-readable replay summary:
- [artifacts/latest/observability_before_after_trace.json](artifacts/latest/observability_before_after_trace.json)

## 2) Complete Claim Verdict Matrix

| Claim | Verdict | Evidence summary | Production consequence |
|---|---|---|---|
| 1. Scheduler control flow changed | PROVEN | `scheduler.py` changed preflight/circuit/pause branches from exit/return to degraded continue when `ANTHROPIC_FAIL_OPEN_LOCAL_CONTENT` is enabled. | Scheduler can continue rendering under conditions that previously stopped it. |
| 2. Behavior-neutral proof is FAIL | PROVEN | Code diff changes execution path; deterministic replay summary shows baseline vs current divergence at startup and render gates. | Observability patch is not behavior-neutral. |
| 3. Telegram OPEN -> UPDATED -> RESOLVED lifecycle is incorrect | PARTIALLY PROVEN | Structured incident lifecycle produced `INCIDENT_OPEN`, `INCIDENT_UPDATED`, `INCIDENT_RESOLVED`, but Telegram payload sequence was only 2 messages in the isolated lifecycle probe. Policy for every retry emitting UPDATED was not documented. | Operator does not receive a one-to-one lifecycle card sequence. |
| 4. Cooldown suppresses required UPDATED notifications | PARTIALLY PROVEN | `notify_error()` suppresses the alert when `_should_alert()` returns false; same incident probe showed UPDATED lifecycle in events but no UPDATED Telegram card. Requirement for UPDATED on every retry is not documented. | UPDATE card can be skipped by cooldown. |
| 5. Non-debug path masking leaks absolute paths such as /var/... | PROVEN | Path-sanitizer probe showed raw `/var/log/demo/file.json`, `/home/user/data/file.json`, and `relative/path/file.json` surviving into Telegram payloads in non-debug mode. | Operator messages can expose local filesystem paths. |
| 6. Deployment must remain NO-GO | PROVEN | Claims 1, 2, and 5 are proven; 3 and 4 remain partially proven with policy ambiguity. | Do not deploy until behavior-neutrality and Telegram/path issues are fixed. |

## 3) Before/After Runtime Comparison

Saved summary:
- [artifacts/latest/observability_before_after_trace.json](artifacts/latest/observability_before_after_trace.json)

Verified scenarios:
- Provider preflight failure
- Circuit open
- Provider overload
- Local fail-open enabled
- Local fail-open disabled
- Topic provenance collision
- Retry after collision
- Successful recovery
- Render failure path
- Upload recovery path

Key before/after divergence facts:
- Baseline `scheduler.py` on preflight failure exits (`sys.exit(1)` in HEAD path).
- Current `scheduler.py` continues in degraded mode when `ANTHROPIC_FAIL_OPEN_LOCAL_CONTENT=true`.
- Baseline render gate skips on open circuit / overload pause.
- Current render gate continues in degraded mode when local fail-open is enabled.

## 4) Scheduler Control-Flow Proof

### A. Provider preflight

Current lines:
- [scheduler.py](scheduler.py#L1998)

Current block:
- `if not provider_ok:` now branches to degraded continuation when `fail_open_enabled` is true.

HEAD block:
- `HEAD:scheduler.py` at the same region exits immediately with `sys.exit(1)` after recording the failed preflight.

Executable evidence:
- `tests/test_scheduler_provider_guardrails.py::test_main_exits_when_provider_preflight_fails`
- `tests/test_scheduler_provider_guardrails.py::test_main_continues_when_provider_preflight_fails_but_local_fail_open_enabled`

### B. Global overload pause

Current lines:
- [scheduler.py](scheduler.py#L789)

Current block:
- `if pause.get("is_open"):` now continues when local fail-open is enabled and only returns in the disabled branch.

HEAD block:
- `HEAD:scheduler.py` returns immediately after `notify_error()`.

Executable evidence:
- `tests/test_scheduler_provider_guardrails.py::test_render_and_schedule_skips_when_provider_circuit_open`
- `tests/test_scheduler_provider_guardrails.py::test_render_and_schedule_continues_when_provider_circuit_open_in_fail_open_mode`

### C. Provider circuit open

Current lines:
- [scheduler.py](scheduler.py#L813)

Current block:
- `if circuit.get("is_open"):` now continues in degraded mode when local fail-open is enabled.

HEAD block:
- `HEAD:scheduler.py` returns immediately after `notify_error()`.

Executable evidence:
- same paired scheduler tests above.

### D. Retry / skip / raise / return paths

Current lines:
- [scheduler.py](scheduler.py#L885)
- [scheduler.py](scheduler.py#L1092)
- [scheduler.py](scheduler.py#L1143)

Current behavior:
- The scheduler now propagates richer retry metadata and uses `notify_error(..., context=...)` with incident fields.
- `_skip_scheduler_pipeline_retry` and `_quarantine_reason` are consumed by later branches.

HEAD behavior:
- The same branches called `notify_error()` without the added incident context and without the new pipeline-stage fields.

Behavior changed externally: YES for startup/render control flow, NO for logging-only lines.

## 5) Telegram Lifecycle Proof

Current lines:
- [src/scheduler_utils.py](src/scheduler_utils.py#L387)
- [src/scheduler_utils.py](src/scheduler_utils.py#L524)
- [src/scheduler_utils.py](src/scheduler_utils.py#L814)
- [src/scheduler_utils.py](src/scheduler_utils.py#L830)
- [src/scheduler_utils.py](src/scheduler_utils.py#L919)

Isolated lifecycle probe output:
- Structured events: `INCIDENT_OPEN`, `INCIDENT_UPDATED`, `INCIDENT_RESOLVED`
- Telegram messages sent: `2`
- Telegram messages:
  1. `INCIDENT_OPEN`
  2. upload success card with `🟢 Incident Resolved: <incident_id>`

What this proves:
- Telegram does not emit a three-message `OPEN -> UPDATED -> RESOLVED` sequence for the isolated incident probe.
- UPDATED exists in structured incident events, but the Telegram send path can be suppressed by cooldown before the payload is emitted.

What this does not prove:
- It does not prove the policy requires every retry to emit UPDATED.
- Therefore this claim is `PARTIALLY PROVEN`, not a confirmed defect by policy.

## 6) Cooldown Proof

Current lines:
- [src/scheduler_utils.py](src/scheduler_utils.py#L830)
- [src/scheduler_utils.py](src/scheduler_utils.py#L919)

Execution result:
- `notify_error()` computes a stable render-error alert key.
- The cooldown branch returns early without sending Telegram when `_should_alert()` is false.
- In the isolated lifecycle probe, the second lifecycle update did not produce a separate Telegram message.

Command evidence:
- `tests/test_scheduler_provider_guardrails.py::test_notify_error_dedupes_anthropic_cooldown_across_channels`
- `tests/test_scheduler_provider_guardrails.py::test_notify_error_keeps_non_cooldown_alerts_channel_scoped`

Verdict:
- Cooldown suppression is proven.
- Whether it violates a required UPDATED policy is not proven because that policy is not documented in the code or tests available here.

## 7) Path Sanitization Proof

Current lines:
- [src/scheduler_utils.py](src/scheduler_utils.py#L167)
- [src/scheduler_utils.py](src/scheduler_utils.py#L830)

Observed non-debug Telegram outputs from the sanitizer probe:
- `/tmp/alpha/file.json` -> masked
- `/var/log/demo/file.json` -> leaked raw path in final Telegram payload
- `/home/user/data/file.json` -> leaked raw path in final Telegram payload
- `relative/path/file.json` -> leaked raw path in final Telegram payload
- `/Users/tester/data/file.json` -> masked
- `C:\Users\tester\data\file.json` -> masked
- `\\server\share\data\file.json` -> masked or partially masked
- `/opt/app/data/file.json` -> masked

Production risk:
- Telegram payloads can expose host-local filesystem paths in non-debug mode.

## 8) Test Results

Full suite rerun:
- `648 passed`

Strict suite rerun:
- `648 passed`

Focused tests:
- Scheduler behavior tests: `4 passed`
- Telegram/cooldown tests: `5 passed`
- Sanitizer probe: `8 cases executed`

No current failing test was reproduced in the rerun.

## 9) Proven Defects Only

Proven defects:
1. Scheduler startup/render control flow can diverge from baseline and continue in degraded mode where HEAD exited/skipped.
2. Non-debug Telegram path sanitization leaks some absolute/relative paths.

Partially proven items:
1. Telegram lifecycle sequence is incomplete in payloads for the isolated probe.
2. Cooldown suppresses UPDATED notifications, but the required policy is not documented.

Rejected items:
- None of the current FAIL claims were fully rejected; claim 3 and claim 4 remain partially proven rather than rejected.

## 10) Minimal Repair Plan

Only for proven defects:

### A. Restore behavior-neutral scheduler control flow
- Affected file: [scheduler.py](scheduler.py)
- Affected functions: `main`, `render_and_schedule`
- Estimated LOC: 25-45
- Required regression test: deterministic preflight/circuit/overload branches must match HEAD baseline behavior except for logs/telemetry.
- Business behavior change: Yes, if keeping fail-open paths; otherwise no if reverted to baseline.

### B. Fix path sanitizer coverage
- Affected file: [src/scheduler_utils.py](src/scheduler_utils.py)
- Affected function: `_sanitize_operator_text`
- Estimated LOC: 6-12
- Required regression test: non-debug Telegram output must not contain raw `/var/`, `/home/`, `/Users/`, Windows drive, UNC, or relative paths.
- Business behavior change: No, only message redaction.

## 11) Final GO / NO-GO Recommendation

NO-GO

Reason:
- Behavior-neutral proof fails because control-flow changed.
- Telegram lifecycle is not proven compliant with the intended lifecycle requirement.
- Non-debug path sanitization leaks filesystem paths.
- Current full test suite passing does not override the runtime and code-path evidence above.
