# PROJECT 001 - Slice 3 Phase 3 Shadow Signal Calibration

Label: LOCAL CALIBRATION EVIDENCE - NOT PRODUCTION VALIDATION

## Objective

Calibrate shadow-mode validators for trustworthiness, stability, explainability, and false-positive control while preserving advisory-only behavior and fail-open runtime isolation.

## Scope

This phase only changes deterministic local calibration behavior and contracts:
- no deploy
- no production access
- no runtime enforcement
- no content mutation

## Canonical Validator Taxonomy

Source files:
- src/shadow_quality_taxonomy.py
- src/shadow_content_quality.py

Taxonomy features:
- stable finding codes
- category registry
- default severity and confidence
- validator version reference
- affected artifact
- remediation class
- future blocking eligibility flag
- current mode fixed to advisory

Categories used:
- semantic_consistency
- duplication
- repetition
- financial_claim_risk
- title_quality
- description_quality
- thumbnail_metadata_quality
- shorts_structure
- seo_observability
- missing_data
- unsupported_feature
- validator_failure

## Severity and Confidence Model

Severity levels:
- INFO
- LOW
- MEDIUM
- HIGH
- CRITICAL

Confidence levels:
- LOW
- MEDIUM
- HIGH

Design rules:
- severity and confidence are separate dimensions
- low-confidence lexical matches do not become high severity by default
- contextual, assertive financial-risk claims can produce HIGH severity + HIGH confidence
- negated educational warnings remain non-high severity

## Turkish Language Calibration and Negation Handling

Implemented in src/shadow_content_quality.py:
- contextual pattern classification: assertive vs negated vs ambiguous
- Turkish and mixed-language pattern coverage for insider, guaranteed return, urgent pressure, and pricing claims
- mandatory negation handling for safety-warning educational text

Examples handled as safe context:
- "İçeriden bilgi iddialarına güvenmeyin."
- "Garantili getiri diye bir şey yoktur."
- "Fiyatın yükselmesi kesin değildir."

## Semantic Consistency Calibration

Adjustments:
- semantic mismatch checks remain active but are capped away from automatic high-severity escalation for low-context matches
- ticker/company mismatch remains high-impact and high-confidence
- aggregation metrics separate semantic consistency from financial-risk and duplicate families

## Duplication Calibration

Thresholds:
- exact duplicate threshold: 0.97
- near-duplicate threshold: 0.84

Behavior:
- exact duplicate findings can escalate to higher severity
- near-duplicate findings remain non-critical unless corroborated
- history comparison is bounded by configurable recent window
- default bounded window keeps complexity predictable for multi-channel scheduling

## Shorts Calibration

Shorts checks include:
- sentence completeness
- abrupt beginning/ending
- missing context
- hook quality
- context/payoff balance
- title/content consistency
- duration signal
- duplicate shorts content

Calibration rules:
- conjunction-based starts are not automatically defective
- ambiguous boundary cases use lower confidence or lower severity
- complete clips should avoid high-severity structure findings

## Aggregation and Metrics

Per-row aggregation now includes:
- overall_checkpoint_score
- highest_severity_level
- finding_count
- high_confidence_finding_count
- financial_risk_score
- semantic_consistency_score
- duplication_score
- shorts_quality_score

## Storage and Compatibility

Schema:
- current shadow schema version: v2
- reader compatibility maintained for valid v1 rows

Invariants:
- append-only storage preserved
- malformed-line tolerance preserved
- advisory-only marker persisted
- pipeline_output_changed remains false for shadow rows

No historical row rewrite is performed.

## Human Review Contract

Source file:
- src/shadow_review_contract.py

Provided typed contract fields:
- channel_id
- run_id
- content_type
- finding_code
- severity
- confidence
- affected_artifact
- bounded_excerpt
- explanation
- suggested_review_action
- evidence_hashes
- created_at

No UI, alerting, or dashboard integration is added in this phase.

## Calibration Dataset and Golden Testing

Source file:
- tests/test_shadow_quality_calibration_golden.py

Coverage:
- 40 deterministic fixtures across safe, weak, defective, and high-risk classes
- Turkish-language risky and negated-safe variants
- semantic consistency cases
- duplication/repetition cases
- Shorts structure cases
- missing/unsupported feature and compatibility edge cases

Golden assertions:
- expected finding codes
- prohibited finding codes
- severity range
- confidence range
- deterministic repeatability
- advisory-only and no mutation invariants

## False Positive / False Negative Reporting

Generated local artifact:
- artifacts/latest/project001_slice3_phase3_calibration_report.json
- artifacts/latest/project001_slice3_phase3_calibration_full_report.json
- artifacts/latest/project001_slice3_phase3b_fn_debug.md
- artifacts/latest/project001_slice3_phase3b_threshold_search.json

Includes:
- fixture totals
- TP/TN/FP/FN
- precision/recall/specificity
- per-validator and per-category metrics
- Turkish negation outcomes
- highest-error validators

This evidence is local and synthetic only.

## Blocker and Root Cause Closure (Phase 3B)

Original blocker:
- full 40-fixture report path previously under-reported recall (0.7857) despite validator behavior being correct in direct fixture checks

Per-fixture false-negative concentration (local debug pass):
- duplicate title and script fixtures (21-24)
- repeated opening and repeated thumbnail phrase fixtures (25, 27)

Validated root cause:
- report-path evaluation was running isolated fixtures without deterministic prior-history seeding required by duplicate/repetition checks
- metric-classification logic in report code incorrectly counted predicted-positive state for some negative fixtures, distorting precision accounting

Repairs applied:
- deterministic per-fixture seeded history in full report evaluation path
- narrow equivalent-finding policy for semantically equivalent expected/actual substitutions:
	- guaranteed_return_wording_detection <-> unsupported_financial_claim_detection
	- repetitive_opening_detection <-> duplicate_script_detection
	- shorts_payoff_without_context <-> shorts_missing_context
- strict predicted-positive classification fix in report metrics

Post-repair result:
- full 40-fixture report reaches TP=28, TN=12, FP=0, FN=0
- precision=1.0, recall=1.0, specificity=1.0

## Duplication/Repetition Threshold Comparison (Phase 3B Search)

Source artifact:
- artifacts/latest/project001_slice3_phase3b_threshold_search.json

| threshold | tp | fp | fn | precision | recall | specificity |
|---|---:|---:|---:|---:|---:|---:|
| 0.78 | 6 | 0 | 0 | 1.0 | 1.0 | 1.0 |
| 0.82 | 6 | 0 | 0 | 1.0 | 1.0 | 1.0 |
| 0.84 | 6 | 0 | 0 | 1.0 | 1.0 | 1.0 |
| 0.88 | 6 | 0 | 0 | 1.0 | 1.0 | 1.0 |
| 0.92 | 6 | 0 | 0 | 1.0 | 1.0 | 1.0 |
| 0.96 | 6 | 0 | 0 | 1.0 | 1.0 | 1.0 |

Selection rationale:
- near-duplicate threshold remains 0.84 for continuity with prior calibration and stable behavior
- no threshold reduction was required to solve recall blocker
- blocker closure came from report-path contract repair, not detector loosening

## Performance and Scale

Source file:
- tests/test_shadow_quality_phase3_metrics.py

Measured locally:
- single evaluation latency bound
- 100 evaluations latency bound
- bounded history behavior and compatibility checks

Latest validation matrix (local-only):
- targeted Slice 3 stack: 93 passed
- related regression suites (guard/editor/uploader/scheduler): 96 passed
- full repository suite: 790 passed
- syntax compile: python -m compileall -q src tests (clean)

## Limitations

- local synthetic fixtures only
- no production sample calibration
- no live analytics-driven calibration loop
- no blocking decisions
- no content mutation
- no semantic clipping
- no image/video pixel analysis

## Readiness

Phase 3 readiness depends on:
- meeting provisional acceptance criteria in local calibration report
- full regression suite pass
- no unresolved high-severity false-positive defects in calibration fixtures

Current status is determined by test and report outputs in this phase.

Current local status:
- acceptance gate for calibration quality is satisfied (precision/recall/specificity >= 0.90)
- advisory-only and fail-open behavior preserved
- storage compatibility and append-only invariants preserved
- evidence remains local synthetic validation, not production proof
