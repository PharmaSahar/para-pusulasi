# Content Platform Weekly Review

- Generated at UTC: 2026-07-11T07:05:51.213387+00:00
- Health artifact: /Users/klara/Downloads/adsız klasör/logs/content_platform_health_latest.json
- Recommendations artifact: /Users/klara/Downloads/adsız klasör/logs/content_platform_recommendations_latest.json
- Experiments artifact: /Users/klara/Downloads/adsız klasör/logs/content_platform_experiments_latest.json

## System Health

- Channels scored: 12
- Triggered regressions: 0

## Channel Health Scores

- borsa_akademi: 55.243
- default: 60.827
- egitim_rehberi: 53.3
- gayrimenkul_tv: 49.278
- girisim_okulu: 55.793
- kariyer_pusulasi: 59.449
- kripto_rehber: 56.101
- para_pusulasi: 59.376
- saglik_pusulasi: 56.0
- teknoloji_pusulasi: 54.64
- test-channel: 60.338
- test_channel: 59.893

## Regressions

- No triggered regressions in current window.

## Recommendation Pipeline

- Recommended: 6
- Rejected/blocked: 1

- RECOMMENDED topic_priorities: focus_on_high_fit_topics (confidence=0.95)
- RECOMMENDED thumbnail_style: increase_contrast_and_specificity (confidence=0.7)
- RECOMMENDED hook_style: prefer_problem_solution_opening (confidence=0.68)
- RECOMMENDED script_length: trim_10_percent_for_low_retention_channels (confidence=0.66)
- RECOMMENDED visual_strategy: increase_visual_diversity_budget (confidence=0.71)
- RECOMMENDED retry_policy: exponential_backoff_with_cap (confidence=0.69)
- BLOCKED publication_time: low_confidence

## Experiments

- Tracked experiments: 7
- Rollback-triggered experiments: 1

## Governance Notes

- No automatic production rollout is allowed without validated canary evidence and explicit approval.
- Topic accuracy and safety floors are enforced before any change can enter canary.
- Every learned adjustment is persisted in content_platform_learning_audit.jsonl.
