# ADR-001: Free-First Service Policy

## Status
Accepted

## Date
2026-07-09

## Context
System costs and operational volatility increased as the pipeline added more generation and media steps. The product needs predictable baseline behavior even when paid providers are unavailable, quota-limited, or temporarily failing.

## Decision
Adopt a free-first policy for default execution paths.

- Default providers should be free-tier or locally available where feasible.
- Paid providers remain optional accelerators, not hard dependencies.
- If a paid provider fails, the pipeline should prefer deterministic fallback paths over stopping the whole run.
- Premium-only paths should be explicitly marked in telemetry and docs.

## Consequences
- Lower baseline cost and easier scaling across multiple channels.
- Better resilience during provider outages or quota exhaustion.
- Potential quality variance between free and premium paths must be measured.
- Product behavior remains available-first, not premium-first.

## Non-goals
- Forbidding all premium providers.
- Guaranteeing identical output quality across all fallback paths.

## Follow-ups
- Track free vs premium execution share in telemetry.
- Define quality guardrails so fallback output remains publishable.
