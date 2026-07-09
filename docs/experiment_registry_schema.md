# Experiment Registry Schema

## Purpose
Provide a single source of truth for all performance experiments so decisions remain auditable over time.

## Required Fields
1. Experiment ID
2. Hypothesis
3. Variant
4. Randomization unit
5. Stratification
6. Start date
7. End date
8. KPI
9. Minimum sample
10. Significance method
11. Winner
12. Rollback status

## Field Guidance
- Experiment ID: unique immutable identifier (for example EXP-2026-07-001).
- Hypothesis: clear expected directional effect.
- Variant: control/treatment definition.
- Randomization unit: usually video.
- Stratification: channel, topic cluster, publish slot, or equivalent.
- KPI: primary KPI plus optional guardrail KPIs.
- Minimum sample: minimum impressions or time window.
- Significance method: fixed method selected before exposure.
- Winner: control, treatment, inconclusive.
- Rollback status: none, triggered, completed.

## Example Record
```json
{
  "experiment_id": "EXP-2026-07-001",
  "hypothesis": "Thumbnail policy v2 increases CTR by at least 10% vs control.",
  "variant": {
    "control": "thumbnail_policy_v1",
    "treatment": "thumbnail_policy_v2"
  },
  "randomization_unit": "video",
  "stratification": ["channel_id", "topic_cluster", "publish_slot"],
  "start_date": "2026-07-15",
  "end_date": "2026-07-22",
  "kpi": {
    "primary": "ctr",
    "guardrails": ["first_30s_retention", "thumbnail_validation_pass_rate"]
  },
  "minimum_sample": {
    "impressions": 10000,
    "min_days": 7
  },
  "significance_method": "frequentist_95_confidence",
  "winner": "treatment",
  "rollback_status": "none"
}
```

## Operational Rules
- No experiment result can be accepted without minimum sample and significance method.
- No winner can be declared without explicit registry update.
- Any rollback must reference a valid experiment ID.
