# PROJECT 002 Sprint 1C - Real-World Blind Validation (CQGA)

## Scope
Sprint 1C validates CQGA against real historical repository artifacts only.
No CQGA optimization was performed in this sprint.
The goal is evidence collection for generalization assessment.

## Constraints and Safety
- Advisory-only behavior preserved.
- No deployment, no VPS access, no browser automation.
- No scheduler/uploader/prompt/pipeline output behavior change.
- `pipeline_output_changed` contract remains unchanged.

## Phase 1 - Repository Artifact Inventory
Historical local artifacts discovered:

1. Runtime evidence files:
- `output/runtime/evidence/content_*.json`
- Count: 1071
- Contains: title, description, tags, topic, channel, render/upload metadata

2. Ownership state files:
- `output/state/content_ownership/content_*_run_*.json`
- Contains: script_preview, title, topic, channel_id, artifact pointers
- Direct script_preview coverage matched to real evidence: 6

3. Shadow/quality/review JSONL artifacts:
- `logs/shadow_content_quality_results.jsonl`
- `logs/shadow_blueprint_prompt_alignment.jsonl`
- `logs/shadow_prompt_experiments.jsonl`
- `logs/offline_prompt_candidates.jsonl`
- `logs/content_quality_gap_analysis.jsonl`
- Plus operational analytics snapshots and trails under `logs/`

4. Additional outputs:
- `output/telemetry/`
- `output/runtime/`
- `output/queue/`
- `output/state/`

## Phase 2 - Blind Validation Dataset
Dataset selection rules:
- Source: real runtime evidence only.
- Excluded obvious placeholders: titles matching `test|x|ornek|example|dummy`.
- Deterministic ordering: lexical path order.
- Selected first 300 real samples to satisfy minimum requirement.

Counts:
- Real candidates after filtering: 408
- Blind dataset size used: 300
- Synthetic fixtures reused in blind dataset: 0

Dataset artifact outputs:
- `artifacts/latest/project002_sprint1c_real_world_validation/blind_dataset.jsonl`
- `artifacts/latest/project002_sprint1c_real_world_validation/cqga_predictions.jsonl`
- `artifacts/latest/project002_sprint1c_real_world_validation/reference_labels.jsonl`
- `artifacts/latest/project002_sprint1c_real_world_validation/agreement_summary.json`

## Phase 3 - Blind CQGA Evaluation
CQGA run mode:
- Executed via `analyze_content_quality_gaps` with production-like advisory-only input construction.
- Stored predicted gaps, root causes, scorecards, and confidence.

## Phase 4 - Independent Reference Labels
Reference labels were produced independently from CQGA outputs using a deterministic rubric based on:
- title/description/topic/tag lexical evidence
- script_preview when available
- overlap and quality heuristics
- explicit uncertainty marking when script evidence unavailable

Reference captures:
- actual quality issues
- actual root causes
- actual consistency
- actual finance safety
- actual SEO quality
- actual hook quality
- actual repetition

## Phase 5 - Agreement Analysis
Overall (from `agreement_summary.json`):
- Precision: 1.0000
- Recall: 0.2769
- Specificity: 1.0000
- F1: 0.4338
- Cohen's Kappa: 0.3379
- Root cause agreement: 0.1293
- TP: 167
- FP: 0
- FN: 436
- TN: 1203
- Evaluated decisions: 1806
- Uncertain decisions: 594

Confusion matrix:
- TP=167
- FP=0
- FN=436
- TN=1203

Per-category agreement highlights:
- Strong specificity across categories.
- Significant recall gaps in:
  - `THUMBNAIL_TITLE_MISMATCH`
  - `SEO_INCOMPLETE`

Score correlation (predicted vs reference):
- hook: 0.0000
- seo: 0.9733
- consistency: 0.5718
- finance_safety: 0.0000

## Phase 6 - Failure Analysis
Top disagreement patterns:
1. `THUMBNAIL_TITLE_MISMATCH | missing heuristic` (300)
2. `SEO_INCOMPLETE | missing heuristic` (136)

Disagreement taxonomy used:
- taxonomy ambiguity
- threshold issue
- missing heuristic
- false heuristic
- insufficient evidence
- borderline case
- label ambiguity

Common root pattern:
- Real-world samples often lack rich script/thumbnail prompt evidence in local artifacts.
- This creates systematic under-detection in categories that require cross-modal consistency evidence.

## Phase 7 - Generalization Assessment
Synthetic baseline (Sprint 1B):
- precision: 0.9024
- recall: 0.9737
- specificity: 0.9765
- root_cause_agreement: 0.9767

Real-world blind (Sprint 1C):
- precision: 1.0000
- recall: 0.2769
- specificity: 1.0000
- root_cause_agreement: 0.1293
- kappa: 0.3379

Interpretation:
- CQGA does not generalize sufficiently to real historical artifacts under current evidence availability.
- The largest drop is recall and root-cause agreement, indicating over-reliance on richer synthetic evidence patterns.
- This is an overfitting risk relative to synthetic fixtures.

## Phase 8 - Acceptance Decision
Required thresholds:
- precision >= 0.85: PASS
- recall >= 0.85: FAIL
- specificity >= 0.90: PASS
- root cause agreement >= 0.85: FAIL
- Cohen's Kappa >= 0.80: FAIL

Decision:
- **BLOCKED - REAL-WORLD VALIDATION FAILED**

## Phase 9 - Validation Gates Executed
- CQGA/calibration/regression/pipeline integration set: 30 passed
- compileall: passed
- full repository suite: 911 passed

## Recommendation for Sprint 2 Readiness
Current state is **not Sprint 2 ready** based on real-world validation criteria.
Required before readiness:
- improve observable evidence completeness for real artifact inputs
- reduce missing-heuristic disagreements for thumbnail mismatch and SEO incompleteness
- raise real-world recall, kappa, and root-cause agreement to acceptance levels

## Known Limitations
- Real local artifacts contain sparse script/thumbnail prompt evidence for many samples.
- Human-reference proxy is deterministic rubric-based, not manually curated annotation.
- Result should be treated as strict blind evidence under available local artifacts, not production truth.
