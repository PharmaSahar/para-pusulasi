# Final Commit Plan

## Independence Proof Summary
- Original Candidate 1 failed from HEAD because `scheduler.py` imports `src.runtime_storage` and therefore is not independent without runtime-storage prerequisites.
- Original Candidate 2 failed from HEAD for the same reason: `scheduler.py` requires `src.runtime_storage` before topic-domain guard tests can even import.
- Original Candidate 3 passed independently from HEAD.
- Original Candidate 4 core observability patch passed independently from HEAD, but the modified `tests/test_scheduler_provider_guardrails.py` only passed when runtime-storage and observability changes were present together.
- Original Candidate 5 tests-only migration passed independently from HEAD.
- `src/content_generator.py` already referenced `get_trending_topics_with_metadata` at HEAD, while `src/trends_fetcher.py` at HEAD did not define it. Therefore the release plan must carry the `src/trends_fetcher.py` helper into the same or earlier commit than any production use that relies on that contract.

## Final Release Commit Sequence

### Commit 1
- Title: fix: separate runtime storage and harden scheduler observability
- Files:
  - scheduler.py
  - src/runtime_storage.py
  - src/production_quality_platform.py
  - src/scheduler_utils.py
  - ops/refresh_governance_readiness.py
  - ops/export_runtime_dashboard.py
  - tests/conftest.py
  - tests/test_preprod_isolation_paths.py
  - tests/test_production_quality_platform.py
  - tests/test_refresh_governance_readiness.py
  - tests/test_render_metrics.py
  - tests/test_observability_incident_safety.py
  - tests/test_scheduler_provider_guardrails.py
- Rationale:
  - runtime-storage is a hard prerequisite for current `scheduler.py`
  - modified provider-guardrail coverage depends on both scheduler runtime-path changes and `src/scheduler_utils.py` observability behavior
  - keeping these together gives one rollback boundary for tracked-write separation plus scheduler observability/alerting behavior
- Proof from detached HEAD worktree:
  - patch applied cleanly
  - `py_compile` passed
  - focused suite passed: 49 passed
- Verification command:
  - `.venv-2/bin/python -m pytest -q -W error tests/test_production_quality_platform.py tests/test_preprod_isolation_paths.py tests/test_refresh_governance_readiness.py tests/test_render_metrics.py tests/test_observability_incident_safety.py tests/test_scheduler_provider_guardrails.py`
- Rollback boundary: runtime storage and scheduler observability only
- Estimated risk: Medium

### Commit 2
- Title: fix: quarantine terminal topic-domain blocks exactly once
- Files:
  - scheduler.py
  - src/pipeline.py
  - tests/test_scheduler_topic_domain_guard.py
  - tests/test_analytics_join.py
  - tests/test_editor_review.py
- Rationale:
  - topic-domain quarantine behavior depends on current pipeline exception metadata and scheduler quarantine persistence
  - the analytics/editor test shims are direct compatibility fixes for the pipeline-side `TopicDomainBlockedError` import path and belong with this behavior change
- Proof from detached HEAD worktree with Commit 1 prerequisites present:
  - patch applied cleanly
  - `py_compile` passed
  - focused suite passed: 23 passed
- Verification command:
  - `.venv-2/bin/python -m pytest -q -W error tests/test_scheduler_topic_domain_guard.py tests/test_analytics_join.py tests/test_editor_review.py`
- Rollback boundary: quarantine handling only
- Estimated risk: Medium

### Commit 3
- Title: fix: harden content fallback and trend metadata contract
- Files:
  - src/content_generator.py
  - src/trends_fetcher.py
  - tests/test_content_generator_anthropic_guard.py
  - tests/test_content_generator_prompting.py
- Rationale:
  - `src/content_generator.py` already depends on `get_trending_topics_with_metadata`
  - `src/trends_fetcher.py` introduces that missing helper contract
  - content fail-open fallback and prompting/trend metadata coverage are safest as one content-generation rollback boundary
- Proof from detached HEAD worktree:
  - patch applied cleanly
  - `py_compile` passed
  - focused suite passed: 26 passed
- Verification command:
  - `.venv-2/bin/python -m pytest -q -W error tests/test_content_generator_anthropic_guard.py tests/test_content_generator_prompting.py`
- Rollback boundary: content generation fallback and trend metadata only
- Estimated risk: Medium

## Removed From Release Commit Plan
- Empty documentation Commit 6 removed.
- Standalone tests-only Candidate 5 removed as a separate release commit because its files are now absorbed into Commit 2 where the dependency actually originates.
- Standalone observability Candidate 4 removed as a separate release commit because modified scheduler guardrail coverage is only valid when runtime-storage prerequisites are present; those changes are now absorbed into Commit 1.

## Excluded From Staging
- Generated or runtime files:
  - docs/governance_readiness_latest.md
  - output/state/activation_reports/latest.json
  - artifacts/deployment/**
  - artifacts/incidents/cross_channel_contamination/**
  - artifacts/latest/**
  - config/runtime_manifest.json
- Unrelated source/test changes:
  - PROGRESS.md
  - ops/maintenance.py
  - tests/test_maintenance.py

## Staging Readiness
- `git diff --check` is clean in the main worktree.
- Main worktree remains unstaged.
- Release plan is ready only after staging is performed according to the revised 3-commit sequence above.
