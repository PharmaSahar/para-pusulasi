# ADR-002: Retry Policy for Generation and External Calls

## Status
Accepted

## Date
2026-07-09

## Context
Blind multi-retry behavior can amplify duplicate work, increase costs, and hide systemic failures. No-retry behavior increases transient failure rates. The system needs bounded retries with predictable blast radius.

## Decision
Use bounded retry defaults with explicit per-stage overrides.

- Default policy: max 1 retry for critical but transient-prone stages.
- Retry should apply only to classified transient errors (network, timeout, rate-limit) and not logical validation failures.
- Each retry attempt must be observable in telemetry with error class and stage.
- Idempotency-sensitive stages (upload/publish side effects) need stricter guards before retry.

## Consequences
- Better balance between resilience and cost.
- Reduced duplicate side effects compared to unbounded retries.
- Failures become easier to classify and triage.

## Non-goals
- Solving all reliability issues via retry.
- Retrying validation failures caused by bad inputs.

## Follow-ups
- Standardize error classification taxonomy across uploader, fetchers, and generation adapters.
- Add stage-level retry counters to release review dashboards.
