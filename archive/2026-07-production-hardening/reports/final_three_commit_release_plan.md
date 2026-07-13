# Final Three-Commit Release Plan

## Proof Basis
- Original candidate analysis proved:
  - scheduler.py cannot be safely split across separate release commits
  - original Candidate 1 and Candidate 2 were not independently releasable from HEAD
  - src/content_generator.py depends on the new trends metadata contract in src/trends_fetcher.py
- Therefore the minimum safe plan is three release commits.

## Commit 1
- Title: fix: separate runtime storage and harden scheduler observability
- Exact files:
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
- Exact rationale:
  - `scheduler.py` now imports `src.runtime_storage`, so runtime-storage separation is a hard prerequisite for any scheduler-based release unit.
  - modified provider guardrail coverage depends on the observability behavior in `src/scheduler_utils.py`.
  - combining runtime storage and scheduler observability yields the smallest independently compiling and independently testable base commit.
- Independent compile command:
  - `.venv-2/bin/python -m py_compile scheduler.py src/runtime_storage.py src/production_quality_platform.py src/scheduler_utils.py ops/refresh_governance_readiness.py ops/export_runtime_dashboard.py`
- Independent focused test command:
  - `.venv-2/bin/python -m pytest -q -W error tests/test_production_quality_platform.py tests/test_preprod_isolation_paths.py tests/test_refresh_governance_readiness.py tests/test_render_metrics.py tests/test_observability_incident_safety.py tests/test_scheduler_provider_guardrails.py`
- Rollback boundary:
  - runtime storage separation plus scheduler observability/alerting only
- Risk assessment:
  - Medium. It touches scheduler runtime paths, tracked-write protections, and incident/alert behavior, but proof run passed cleanly.
- Detached worktree proof:
  - apply: clean
  - compile: pass
  - focused tests: 49 passed

## Commit 2
- Title: fix: quarantine terminal topic-domain blocks exactly once
- Exact files:
  - scheduler.py
  - src/pipeline.py
  - tests/test_scheduler_topic_domain_guard.py
  - tests/test_analytics_join.py
  - tests/test_editor_review.py
- Exact rationale:
  - topic-domain quarantine handling is expressed jointly in scheduler and pipeline.
  - the analytics/editor tests need the pipeline-side `TopicDomainBlockedError` import compatibility shim and therefore belong with this release unit.
  - because scheduler.py is unsplittable, this commit is proven on top of the Commit 1 base established above.
- Independent compile command:
  - `.venv-2/bin/python -m py_compile scheduler.py src/runtime_storage.py src/production_quality_platform.py src/scheduler_utils.py ops/refresh_governance_readiness.py ops/export_runtime_dashboard.py src/pipeline.py`
- Independent focused test command:
  - `.venv-2/bin/python -m pytest -q -W error tests/test_scheduler_topic_domain_guard.py tests/test_analytics_join.py tests/test_editor_review.py`
- Rollback boundary:
  - topic-domain quarantine handling only
- Risk assessment:
  - Medium. It affects terminal block routing and quarantine persistence, but the focused guard suite passed cleanly.
- Detached worktree proof:
  - apply: clean
  - compile: pass
  - focused tests: 23 passed
  - note: this proof uses the Commit 1 prerequisite-safe base because earlier validation proved the scheduler runtime-storage dependency is unavoidable

## Commit 3
- Title: fix: harden content fallback and trend metadata contract
- Exact files:
  - src/content_generator.py
  - src/trends_fetcher.py
  - tests/test_content_generator_anthropic_guard.py
  - tests/test_content_generator_prompting.py
- Exact rationale:
  - `src/content_generator.py` already relies on `get_trending_topics_with_metadata`, while HEAD `src/trends_fetcher.py` does not provide it.
  - the content fail-open fallback and the trend metadata contract must ship together to avoid a broken production call path.
- Independent compile command:
  - `.venv-2/bin/python -m py_compile src/content_generator.py src/trends_fetcher.py`
- Independent focused test command:
  - `.venv-2/bin/python -m pytest -q -W error tests/test_content_generator_anthropic_guard.py tests/test_content_generator_prompting.py`
- Rollback boundary:
  - content fallback and trend metadata only
- Risk assessment:
  - Medium. It affects provider fail-open behavior and topic-source contract shape, but the focused suite passed cleanly.
- Detached worktree proof:
  - apply: clean
  - compile: pass
  - focused tests: 26 passed

## Independent Rollback Assessment
- Commit 1 can be rolled back without breaking Commit 3, but rolling it back would invalidate Commit 2 because Commit 2 depends on the scheduler runtime-storage base.
- Commit 2 can be rolled back independently once Commit 1 remains present.
- Commit 3 can be rolled back independently of Commits 1 and 2.
- Result:
  - release sequence is valid
  - rollback boundaries are clear
  - scheduler.py split remains invalid
  - commit sequence must stay ordered as 1 -> 2 -> 3

## Final Readiness
- Main worktree remains unstaged.
- No commits created.
- No push, merge, deploy, or release tag created.
- Ready to commit after approval: YES
