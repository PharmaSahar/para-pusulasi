# Selection Policy v2 (Learning Mode) - Design Draft

## Goal
Evolve deterministic selection (`first`, `round_robin`, `deterministic_hash`) into a measured policy that can prefer historically stronger variants while remaining safe and reversible.

## Principles
- Backward compatible with v1 policies.
- Feature-gated rollout (`SELECTION_POLICY_V2_ENABLED=false` default).
- No silent behavior shifts.
- Full decision trace in metadata.

## Inputs
- Current candidate set (variant_id list)
- Evaluator outcomes (winner, confidence, decision reason)
- Optional recent performance window (CTR, watch time)

## Decision Strategy (Proposed)
1. If insufficient data -> fallback to v1 deterministic policy.
2. If evaluator confidence is high -> prefer historical winner when candidate present.
3. If confidence is medium/low -> blend deterministic hash with winner bias.
4. If winner not in candidate set -> fallback to v1 deterministic policy.

## Output Metadata
- selected_thumbnail_variant
- thumbnail_selection_policy (e.g. `learning_v2`)
- selection_decision_source (`evaluator` | `fallback_v1`)
- selection_confidence
- selection_explanation

## Safety and Rollback
- Hard off switch: feature flag.
- Runtime fail-open: fallback to v1 policy.
- Monitoring: selection_warning counters and decision source distribution.

## Open Questions
- Minimum sample size for evaluator-driven bias.
- Confidence threshold calibration.
- Exploration ratio for avoiding overfitting.
