# Topic Filter Regression Report

Status: patch_ready_tested_preproduction
Date: 2026-07-11
Scope: fail-closed domain filtering and cross-domain leakage prevention

## Objective
Enforce fail-closed topic-domain validation to prevent cross-channel/domain contamination and bypass on retry/manual topic injection.

## Implemented Changes
- Domain guard exception model:
  - Added `TopicDomainBlockedError` in `src/content_generator.py`.
  - Raised when no valid candidate remains after filtering + channel-scoped fallback.
- Candidate filtering hardening:
  - Structured rejection reason capture via `_filter_candidates_with_reasons` trace.
  - Non-market niches are provider-anchored and do not admit unrelated AI-only topics.
  - Explicit-topic path (`topic=` retry/manual) now validated through same domain guard.
- Fallback hardening:
  - Channel-scoped fallback only.
  - No generic cross-domain fallback for unknown/invalid niche pathways.
- Scheduler behavior hardening in `scheduler.py`:
  - `topic_domain_blocked` and `topic_provenance_collision` treated as fatal-no-retry classes.
  - Domain-blocked runs are quarantined with guard reason codes and decision trail entry.

## Regression Coverage
Key tests covering guard behavior:
- `tests/test_topic_provenance.py`
  - health channel rejects finance contamination,
  - all rejected => channel-scoped fallback,
  - empty fallback => blocked,
  - explicit retry cannot bypass,
  - finance niche remains finance-capable.
- `tests/test_scheduler_topic_domain_guard.py`
  - quarantines domain-blocked output,
  - avoids retry loops.

Integrated suites also green:
- scheduler provider guardrails/cli,
- pipeline telemetry fail-open,
- pipeline quality integration,
- experiment registry integration.

Validation totals:
- strict targeted suites: 73 passed,
- full with warnings default: 589 passed,
- full normal: 589 passed.

## Incident Risk Posture
- Cross-domain topic leakage for non-market niches is now fail-closed by default.
- Retry/manual topic input no longer bypasses domain policy.
- Scheduler escalates blocked domain cases to quarantine instead of repeated execution.

## Maturity Label
REPORTED

Rationale:
- Implementation and regression tests are complete and passing.
- No production rollout/runtime incident metrics included yet.
