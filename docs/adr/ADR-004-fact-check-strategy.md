# ADR-004: Fact-Check Strategy with Regeneration Guard

## Status
Accepted

## Date
2026-07-09

## Context
Content quality and trust depend on factual consistency. Fully open-ended regeneration loops can create instability and unpredictable latency, while zero-regeneration can ship incorrect content.

## Decision
Use bounded fact-check and regeneration strategy.

- Run fact-check validation before publish-critical stages.
- If fact-check fails in a recoverable way, allow one controlled regeneration attempt.
- If validation still fails, block publish path or degrade to safe fallback content based on policy.
- Persist audit trail for initial failure, regeneration attempt, and final outcome.

## Consequences
- Lower risk of publishing factually incorrect output.
- Bounded retry keeps latency and cost predictable.
- Governance and observability improve incident analysis.

## Non-goals
- Guaranteeing perfect factual correctness for every domain.
- Unlimited self-healing loops.

## Follow-ups
- Keep validator rules explicit and versioned.
- Include fact-check status in pre-release and post-incident reviews.
