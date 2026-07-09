# ADR-005: Thumbnail Generation Policy and Diversity Guard

## Status
Accepted

## Date
2026-07-09

## Context
Thumbnail quality directly affects CTR, while repeated visual patterns reduce channel freshness and can trigger platform fatigue. The system needs both readability and diversity guarantees.

## Decision
Adopt a policy-driven thumbnail generation strategy.

- Enforce readability guardrails (safe text area, line limits, contrast/readability checks).
- Enforce diversity guardrails to avoid repetitive visual outputs over recent history.
- If a generated thumbnail violates policy, regenerate within bounded attempts.
- Record rejection reason and accepted variant metadata for audit and tuning.

## Consequences
- More consistent visual quality for Shorts.
- Reduced visual repetition risk across consecutive outputs.
- Slightly higher generation cost due to guard-driven retries.

## Non-goals
- Manual art-direction for every video.
- Fully model-free thumbnail generation.

## Follow-ups
- Track policy pass/fail rates and top rejection causes.
- Periodically tune thresholds per channel DNA.
