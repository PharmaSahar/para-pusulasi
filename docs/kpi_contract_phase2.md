# KPI Contract - Phase 2 (Audience Performance Engine)

## Purpose
Define measurable success, failure thresholds, and rollback triggers before implementation work starts.

## Baseline Rule
- Baseline window: previous stable release window or last 28-day production baseline.
- Evaluation window: minimum sample period declared per experiment.

## KPI Targets
1. CTR uplift target: +10%
2. Average View Duration uplift target: +5%
3. First 30s retention uplift target: +8%
4. Audio normalization compliance target: 100%, lower limit 95%
5. Thumbnail validation pass rate target: 100%, lower limit 98%

## Failure Criteria
Any of the following is considered Phase 2 KPI failure:
- CTR uplift <= 0 after minimum sample requirement is met.
- Average View Duration below baseline after minimum sample requirement is met.
- First 30s retention below baseline after minimum sample requirement is met.
- Audio normalization compliance < 95% in release window.
- Thumbnail validation pass rate < 98% in release window.

## Rollback Criteria
Rollback is required when at least one high-impact KPI fails and no statistically credible recovery trend is present:
1. CTR drops below baseline and remains negative for the defined sample window.
2. First 30s retention drops below baseline and remains negative for the defined sample window.
3. Audio normalization compliance falls below 95% for production outputs.
4. Thumbnail validation pass rate falls below 98% for production outputs.

## Rollback Action Template
- Stop new exposure for failing variant.
- Restore last known good policy.
- Record rollback reason in experiment registry.
- Open follow-up remediation item before re-launch.

## Reporting Requirement
Every Phase 2 release or major experiment must publish a KPI summary that includes:
- Baseline
- Current value
- Delta (%)
- Pass/fail per KPI
- Rollback decision
