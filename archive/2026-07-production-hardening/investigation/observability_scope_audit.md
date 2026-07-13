# Observability Scope Audit (T08)

## Input
Targeted diff examined:
- scheduler.py
- src/pipeline.py
- src/scheduler_utils.py

Evidence source:
- /tmp/t08_obs_diff.patch

## Hunk Classification

1) scheduler.py::_quarantine_non_retryable_domain_block (three hunks)
- Class: BEHAVIOR + CONTRACT (not observability-only)
- Why:
  - Adds persisted queue/quarantine fields required by current production contract: timestamp, channel_name, selected_topic, expected_domain, source_exception_type/source_exception_message, regeneration_count, terminal.
  - Alters entry payload shape consumed by queue/admin/test contracts.
- Recommendation: KEEP (required for terminal quarantine contract).

2) scheduler.py::render_and_schedule notify_error context enrichment (two hunks)
- Class: OBSERVABILITY ENRICHMENT (fail-open telemetry context)
- Why:
  - Passes incident context to notify_error: run/content ids, stage, retry/regeneration counters, guard codes, collision metadata.
  - Does not alter retry/quarantine decision branch selection.
- Recommendation: KEEP (improves incident traceability; no core path mutation).

3) scheduler.py::terminal quarantine failure payload enrichment
- Class: BEHAVIOR + CONTRACT
- Why:
  - Propagates source exception metadata into quarantine writer, enabling required persisted identity fields.
- Recommendation: KEEP (required by quarantine metadata contract and tests).

4) scheduler.py::_is_local_content_fail_open_enabled + preflight detail normalization
- Class: NEUTRAL/LOW-RISK HARDENING
- Why:
  - `_is_local_content_fail_open_enabled` is additive helper.
  - `detail = str(provider_detail or "")` prevents None formatting ambiguity in startup preflight logs/exit text.
- Recommendation: KEEP.

5) src/pipeline.py::TopicDomainBlockedError shaping in _generate_content
- Class: BEHAVIOR + OBSERVABILITY BRIDGE
- Why:
  - Converts generator-level domain block exception into scheduler-consumable terminal metadata via structured attrs.
  - Explicitly marks non-retryable scheduler behavior (`_skip_scheduler_pipeline_retry=True`) and reason codes.
- Recommendation: KEEP (critical bridge for deterministic scheduler quarantine semantics).

6) src/scheduler_utils.py::incident state/event/metrics subsystem (+~500 lines)
- Class: OBSERVABILITY SUBSYSTEM (fail-open design)
- Why:
  - Adds incident lifecycle persistence with lock/atomic writes/retention/metrics and bounded JSONL.
  - Adds sanitize/redaction path for operator-facing alerts.
  - Storage rotation and retention protections are telemetry-state concerns.
- Recommendation: KEEP WITH GUARDRAILS (must remain non-blocking on failure; verify by dedicated tests).

7) src/scheduler_utils.py::notify_upload + notify_error rewrite + stable alert key
- Class: OBSERVABILITY + NOTIFICATION POLICY
- Why:
  - notify_upload resolves open incidents after successful upload and appends resolution marker.
  - notify_error becomes context-aware, writes incident telemetry fail-open, includes lifecycle metadata and cooldown-safe dedupe keying.
  - stable key collapses volatile retry-after text to reduce alert storms.
- Recommendation: KEEP (policy-level noise control + lifecycle visibility), contingent on cooldown/noise tests.

## Boundary Verdict
- Pure observability-only hunks: scheduler.py notify_error context enrichment, most of src/scheduler_utils.py incident subsystem.
- Behavior-changing hunks: scheduler.py quarantine payload schema and src/pipeline.py TopicDomainBlockedError shaping.
- Risky coupling point: src/pipeline.py -> scheduler.py metadata handoff is intentional and required by quarantine contract.

## Revert/Keep Map
- Keep all reviewed hunks for current recovery scope.
- No hunk marked for revert in T08.

## Residual Risks
- Observability code path is broad in src/scheduler_utils.py; regressions must be controlled by fail-open tests and bounded-storage/concurrency tests (T09-T12).
