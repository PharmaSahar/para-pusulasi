# Production Observability Audit

Date: 2026-07-12
Scope: Audit and validation of the observability hardening patch before merge/deploy.

## Section Results (PASS/FAIL)

1. Capture repository state: PASS
2. Review complete diff and behavior-impact mapping: PASS
3. Incident identity semantics: FAIL
4. Concurrency and file safety: PASS
5. Bounded storage: PASS
6. Telegram behavior: FAIL
7. Collision diagnostics honesty: FAIL
8. Validation matrix: FAIL
9. Runtime smoke (isolated): PASS
10. Behavior-neutral proof: FAIL
11. Final report generation: PASS

## 1) Repository State Evidence

- Branch: master
- HEAD: d51e31578e3f3bd18674441f2f7545a2dce2dd05
- `git diff --check`: clean (no whitespace/check failures)
- Dirty worktree exists with many unrelated modified/untracked files.

Key modified tracked files in working tree:
- PROGRESS.md
- docs/governance_readiness_latest.md
- docs/production_dashboard_latest.md
- output/state/activation_reports/latest.json
- scheduler.py
- src/content_generator.py
- src/pipeline.py
- src/scheduler_utils.py
- src/trends_fetcher.py
- tests/test_analytics_join.py
- tests/test_content_generator_anthropic_guard.py
- tests/test_content_generator_prompting.py
- tests/test_editor_review.py
- tests/test_render_metrics.py
- tests/test_scheduler_provider_guardrails.py
- tests/test_scheduler_topic_domain_guard.py

New file added by this audit:
- tests/test_observability_incident_safety.py

## 2) Complete Diff Review Findings

Behavior-impacting paths identified from code paths (not comments):

- scheduler startup termination changed:
  - `scheduler.py`: provider preflight failure now continues when `ANTHROPIC_FAIL_OPEN_LOCAL_CONTENT=true`.
  - Prior behavior was terminate (`sys.exit(1)`) on provider preflight failure.

- scheduler render gating changed:
  - `scheduler.py`: global overload pause and provider circuit no longer force early-return in fail-open mode.
  - This changes render/upload execution opportunities under outage conditions.

- exception propagation / retry behavior changed:
  - `src/pipeline.py`: `TopicDomainBlockedError` is caught and enriched with `_skip_scheduler_pipeline_retry=True` and `_quarantine_reason`, then re-raised.
  - `scheduler.py` classification consumes these fields and can change retry/quarantine control flow.

- Telegram cooldown key semantics changed:
  - `src/scheduler_utils.py`: `_build_render_error_alert_key` now de-duplicates specific provider-cooldown errors globally across channels.

- return payload shape changed:
  - `notify_error` now returns incident metadata fields (`incident_id`, lifecycle counters).

Conclusion for section 2: Diff review completed, and multiple behavior-impacting changes were verified.

## 3) Incident Identity Semantics Audit

Results: FAIL

Evidence:
- Same real incident across retries can keep same `incident_id` when fingerprint inputs are stable (verified in isolated smoke).
- However, `notify_upload` resolves all open incidents for a channel, not one specific causal incident:
  - `_resolve_open_incidents_for_channel` iterates every open fingerprint for the channel and marks all as resolved.
  - A successful upload can close unrelated OPEN incidents on that channel.
- Fingerprint includes `run_id/content_id`; when these are missing or blank, separate incidents can collapse into same fingerprint tuple (channel+error_type+decision+stage).

## 4) Concurrency and File Safety Audit

Results: PASS (with residual risks)

Audit fix implemented (minimal, observability-only):
- Added process/thread lock around incident state mutation using file lock + thread lock.
- Converted incident state and metrics writes to atomic write+replace.
- Wrapped observability paths in fail-open handling so telemetry write errors do not block pipeline notifications.

Validated with added tests:
- Concurrent writes keep `incident_state.json` valid JSON structure.
- Incident write failure path keeps `notify_error` operational (non-blocking).

Residual risks:
- `fcntl` locking is POSIX-specific (acceptable for current macOS/Linux deployment assumptions).

## 5) Bounded Storage Audit

Results: PASS

Audit fix implemented:
- `production_incidents.jsonl` bounded by configurable max lines (`INCIDENT_EVENTS_MAX_LINES`, default 50000).
- `incident_state.json` prunes old resolved incidents by retention days (`INCIDENT_STATE_RETENTION_DAYS`, default 14).
- `incident_state.json` caps total incidents (`INCIDENT_STATE_MAX_RECORDS`, default 5000).
- Metrics generation now operates on pruned state snapshot.

Validated with added test:
- JSONL max-lines bound enforced and resulting rows remain valid JSON.

## 6) Telegram Behavior Verification

Results: FAIL

Verified:
- OPEN -> UPDATED -> RESOLVED lifecycle works in isolated runtime smoke.
- Cooldown suppression remains active.
- RESOLVED emitted via upload success path.
- Telegram send failures are non-blocking by design.

Failed check:
- Path hiding in non-debug mode is incomplete.
- Isolated smoke shows non-debug payload still exposes `/var/...` paths; expected `[path_hidden]` behavior was not met for this path family.

## 7) Collision Diagnostics Honesty

Results: FAIL

Evidence mapping in `_classify_collision_reason`:
- `metadata mismatch`: `expected_channel != detected_channel`.
- `cross-channel cache reuse`: any error text containing `cross_channel_topic_contamination` or `topic_provenance_collision`.
- `wrong topic inheritance`: error text contains `inherit` or trace includes `fallback_source`.
- `llm hallucinated category`: rejected candidates include `market_term_not_allowed_for_non_market_niche`.
- `planner selected invalid topic`: rejected candidates include `missing_expected_domain_anchor` or `missing_market_domain_anchor`.
- `keyword overlap`: text contains `overlap` or `similar`.
- `unknown`: fallback.

Issue:
- `topic_provenance_collision` text alone maps to `cross-channel cache reuse` even when trace evidence is absent/inconclusive.
- This can over-attribute root cause instead of returning `unknown`.

## 8) Validation Matrix

Results: FAIL (strict criteria)

Executed:
- Compile check modified modules: PASS
  - `python -m py_compile scheduler.py src/scheduler_utils.py src/pipeline.py`
- Full suite: PASS
  - `648 passed`
- Warnings as errors (`-W error`): FAIL
  - `647 passed, 1 failed` (`tests/test_render_metrics.py::test_pipeline_keeps_fail_open_when_render_metrics_builder_raises`)
- Explicit smoke/safety subset: PASS
  - `12 passed`
- Added focused coverage: PASS
  - `tests/test_observability_incident_safety.py` -> `3 passed`

No repository formatter/linter configuration was found in project config files.

## 9) Runtime Smoke Test (Isolated, No Live Credentials)

Results: PASS

Simulation in temporary directory:
- one `topic_provenance_collision` event
- one retry of same event
- one successful recovery (`notify_upload`)

Observed structured lifecycles:
- `INCIDENT_OPEN`
- `INCIDENT_UPDATED`
- `INCIDENT_RESOLVED`

Observed:
- single incident id persisted across OPEN/UPDATED/RESOLVED in deterministic retry scenario.
- Telegram payloads emitted as expected for OPEN and upload success card with resolved incident reference.

## 10) Behavior-Neutral Proof (Before vs After)

Results: FAIL

A (expected before observability patch intent):
- provider preflight failure at startup => terminate.
- open circuit/global pause => skip render and return.
- no incident lifecycle persistence/side effects.

B (current patch):
- provider preflight failure can continue in degraded mode when local fail-open env is enabled.
- open circuit/global pause can continue degraded render path.
- TopicDomainBlockedError handling now enriches and marks explicit skip-retry path consumed by scheduler.

Therefore, this is not observability-only. Control flow differences are present beyond logs/events.

## 11) Risks Found / Fixes Made / Remaining Risks

Risks found:
- Non-neutral control-flow changes in scheduler startup and render gating.
- Incident resolver can close unrelated OPEN incidents on same channel.
- Collision cause over-attribution (honesty risk).
- Non-debug path masking incomplete for `/var/...` style paths.

Fixes made during audit (minimal and scoped to observability safety):
- Added lock + atomic writes for incident state/metrics IO.
- Added bounded retention/rotation for incident files.
- Added fail-open handling for observability write failures.
- Added focused tests:
  - fail-open on telemetry write error
  - concurrent state writes
  - JSONL bounds

Remaining risks:
- Behavior-neutral requirement still violated by pre-existing patch changes in `scheduler.py` and `src/pipeline.py`.
- Strict `-W error` matrix not fully green due unrelated failing test in dirty tree.
- Telegram path masking still incomplete for some absolute paths.
- Incident resolve-by-channel can still over-resolve.

## Commands Executed

- `git branch --show-current && git rev-parse HEAD`
- `git status --short`
- `git diff --stat`
- `git diff --check`
- `git ls-files --others --exclude-standard`
- `git diff -- <target files> > /tmp/audit_diff_*.patch`
- `python -m py_compile scheduler.py src/scheduler_utils.py src/pipeline.py`
- `python -m pytest -q`
- `python -m pytest -q -W error`
- `python -m pytest -q tests/test_research_pipeline_smoke.py tests/test_config_smoke_compat.py tests/test_governance_dashboard_safety.py`
- `python -m pytest -q tests/test_observability_incident_safety.py`
- isolated runtime smoke via Python snippet execution tool (temporary directory)

## Deployment Recommendation

NO-GO

Rationale:
- Behavior-neutral proof failed.
- Incident identity semantics has incorrect resolution behavior.
- Collision diagnostic honesty and Telegram path masking are not fully compliant with stated requirements.
