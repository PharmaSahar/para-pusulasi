# PROVEN / VALIDATED Criteria and Alerting

This document defines the runtime maturity gate and the alert semantics used by `ops/proven_validated_gate.py`.

## Maturity Ladder

1. PLANNED
2. REPORTED
3. PROVEN
4. VALIDATED
5. ROLLED_OUT

## Runtime Gate vs Change Status

The ladder above is a runtime evidence ladder, not a software delivery ladder.

- Use `IMPLEMENTED` to mean code exists but runtime evidence is not yet claimed.
- Use `TESTED` to mean targeted tests or checks passed for the changed slice.
- Use `REPORTED` only after runtime artifacts are being emitted.
- Do not collapse `IMPLEMENTED`, `TESTED`, and `REPORTED` into one statement.

Recommended reporting order for change summaries:

1. IMPLEMENTED
2. TESTED
3. REPORTED
4. PROVEN
5. VALIDATED
6. ROLLED_OUT

## Evidence Sources

- Runtime monitor feed: `logs/proven_validated_monitor.jsonl`
- Latest governance summary: `logs/governance_refresh_run_latest.json`
- Refresh entrypoint: `ops/refresh_governance_readiness.py`
- Latest gate output: `logs/proven_validated_status_latest.json`
- Notification state: `logs/proven_validated_notify_state.json`

## Reporting Discipline

When summarizing a patch or an operational run, prefer this structure:

1. `Patch`: what changed.
2. `Verification`: which command or test was run.
3. `Evidence`: concrete artifact paths, timestamps, or log lines.

Avoid treating phrases such as "made changes", "patch verified", or "wrapper works" as sufficient evidence on their own.

## Healthy Snapshot Definition

A monitor row is healthy when all of the following are true:

- `ok == true`
- `degraded == false`
- `required_passed == required_total`

## Default Thresholds

- Freshness window: 20 minutes
- PROVEN requires 6 consecutive healthy samples
- VALIDATED requires 36 consecutive healthy samples and at least 6 healthy hours
- ROLLED_OUT requires 72 consecutive healthy samples and at least 12 healthy hours

## Health Check Scope

`scheduler.py --health-check` is a startup and dependency check only.

- It confirms the scheduler can boot with the current environment.
- It does not prove uploads are succeeding.
- It does not prove queue execution is healthy.
- It does not prove collector or learning loops are healthy.

Treat health-check PASS as necessary but not sufficient evidence for production behavior.

## Alert Rules

The gate emits alerts when:

1. Maturity level changes.
2. Blocker list changes.
3. Transition enters PROVEN.
4. Transition enters VALIDATED.

Alert semantics:

- Level change alert: sent for every maturity transition, including upward or downward movement.
- Blocker change alert: sent whenever blocker signature changes, even if maturity stays the same.
- PROVEN alert: sent only on transition into PROVEN.
- VALIDATED alert: sent only on transition into VALIDATED.

## Operational Interpretation

- REPORTED means we have runtime evidence, but not enough for PROVEN.
- PROVEN means the latest snapshot is fresh and the recent tail is healthy.
- VALIDATED means the healthy runtime window is sustained long enough to be treated as stable.
- ROLLED_OUT means the runtime window is strong enough for long-lived rollout confidence.

## Conservative Policy

- Do not claim PROVEN from unit tests alone.
- Do not claim VALIDATED without sustained runtime evidence.
- If the latest snapshot is stale or unhealthy, the gate should remain at REPORTED or lower.

## Critical Infrastructure Debt

The current governance refresh path still contains infrastructure debt when a wrapper succeeds by falling back to pre-existing artifacts instead of invoking canonical producer scripts.

Current high-priority debt to track explicitly:

- Missing producer entrypoints for `p0_validation_metrics`, `p0_p1_artifact_bundle`, and `executive_dashboard` in the current repo tree.
- `ops/refresh_governance_readiness.py` can currently mark steps PASS via artifact fallback when those producer scripts are absent.

This should be treated as critical infrastructure debt until each governed artifact has exactly one canonical producer and fallback-only PASS behavior is no longer needed for required production evidence.