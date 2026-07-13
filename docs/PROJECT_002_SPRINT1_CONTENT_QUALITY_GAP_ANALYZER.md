# PROJECT 002 Sprint 1 - Content Quality Gap Analyzer Foundation

## Scope
Sprint 1 introduces an advisory-only Content Quality Gap Analyzer (CQGA) that explains why generated content is likely to succeed or fail. The analyzer is deterministic, local, and fail-open.

## Design Goals
- Advisory only: never mutate runtime publishing decisions.
- Explainability first: every gap has root cause and evidence.
- Deterministic replay: stable IDs and stable scoring for identical input.
- Safe local evidence: append-only JSONL storage with malformed-line tolerance.

## Core Module
- Source: src/content_quality_gap_analyzer.py
- Schema version: v1
- Analyzer version: v1
- Storage path: logs/content_quality_gap_analysis.jsonl

### Input Model
`QualityAnalysisInput` carries title, script, thumbnail prompt, SEO fields, shorts fields, and channel/audience context.

### Analyzer Dimensions
- Script: hook, first 30s, pacing, repetition, clarity, educational depth.
- Title: CTR psychology, intent alignment, promise accuracy, clickbait risk.
- Thumbnail metadata: trigger, contrast, hierarchy, trust, misleading risk.
- Shorts: hook, beginning completeness, context, payoff, looping.
- SEO: description completeness, tags/hashtags quality, cards/end screens.
- Channel consistency: niche/tone/authority/audience alignment.
- Cross-content consistency: topic-title-thumbnail-script-description overlap.

### Gap Object
Each `QualityGap` includes:
- category and severity
- confidence
- affected component
- root cause and evidence
- expected effect
- estimated priority
- recommended future action
- advisory contract flags

### Root-Cause Engine
Symptoms map to human-readable causes:
- Weak hook
- Thumbnail mismatch
- Promise mismatch
- Audience mismatch
- Template repetition
- Overly generic opening
- Poor pacing
- Wrong CTA timing
- Weak search intent
- Poor browse optimization
- Weak curiosity
- Weak payoff
- Insufficient authority
- Low educational depth
- Topic saturation
- Unsupported claims

## Scorecard
`QualityScorecard` reports per-dimension score and confidence:
- hook, narrative, retention, ctr, thumbnail, seo, discovery
- consistency, finance_safety, educational_quality, maintainability
- overall_confidence

Each dimension includes a short `why` and evidence excerpt to support explainability.

## Pipeline Integration
CQGA is attached inside shadow-mode advisory path in src/pipeline.py as:
- shadow_content_quality_gap

Behavior:
- Success path stores advisory CQGA payload.
- Failure path emits fail-open fallback payload with:
  - advisory_only=true
  - pipeline_output_changed=false
  - error_type set
- Runtime publish output remains unchanged.

## Storage and Replay
- `build_storage_row` creates compact replay row.
- `append_storage_row` writes append-only JSONL.
- `load_storage_rows` skips malformed lines and reports count.
- `replay_storage` aggregates root-cause frequencies.

## Calibration
`run_local_calibration` evaluates fixture expectations against predicted categories/causes and reports:
- precision, recall, specificity
- root cause accuracy
- score stability
- ranking stability
- false positive/negative counts

Determinism check compares repeated runs on same fixture.

## Performance
`benchmark_analyzer` runs 1 / 100 / 1000 analyses and reports runtime metrics with deterministic and bounded-memory contract flags.

## Fixtures and Tests
Fixtures:
- tests/fixtures/project002_sprint1_quality_gap_fixtures.py
- 100 deterministic scenarios: 5 domains x 2 modes x 10 quality patterns

Tests:
- tests/test_content_quality_gap_analyzer.py
- tests/test_pipeline_offline_prompt_candidate_integration.py (extended with CQGA checks)

Coverage includes:
- analyzer metric ranges
- result schema and advisory contract
- storage append/load/replay malformed-line tolerance
- calibration stability and benchmark contract
- shadow pipeline attachment and fail-open behavior

## Known Limits (Sprint 1)
- Heuristic scoring is rule-based and not model-trained.
- No direct production analytics feedback loop yet.
- Category taxonomy is intentionally compact for deterministic baseline.

## Future Integration Direction
- Connect CQGA findings to offline candidate lab ranking explanations.
- Add time-window replay for trend drift detection.
- Introduce policy-aware confidence decay under sparse evidence.
- Add controlled threshold tuning with explicit calibration artifacts.
