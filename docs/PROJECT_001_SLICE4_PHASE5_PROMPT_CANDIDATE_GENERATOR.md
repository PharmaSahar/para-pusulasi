# PROJECT 001 - Slice 4 Phase 5: Offline Prompt Candidate Generator

## Scope

This phase introduces a deterministic offline prompt candidate laboratory.

Hard guarantees:
- no runtime prompt generation
- no production prompt changes
- advisory only
- offline only
- no scheduler behavior change
- no uploader behavior change
- no runtime generation mutation

Maturity status:
- REPORTED (local deterministic evidence)
- not production validated

## Architecture

Core module:
- `src/offline_prompt_candidate_generator.py`
  - Prompt strategy taxonomy (typed)
  - Immutable prompt candidate generator
  - Typed prompt plan model (directive-only)
  - Multi-dimensional evaluator
  - Hard/soft scoring model
  - Deterministic ranking engine
  - Structured explanation engine
  - Append-only JSONL storage and replay
  - Calibration and benchmark helpers

Shadow integration:
- `src/pipeline.py`
  - integrated only inside existing shadow planning path
  - fail-open advisory attachment at `shadow_prompt_candidate_lab`
  - `pipeline_output_changed` invariant remains false

## Strategy Taxonomy

Implemented strategies:
- STRUCTURED_EDUCATIONAL
- SOCRATIC
- CASE_STUDY
- PROBLEM_SOLUTION
- MYTH_REALITY
- TIMELINE
- CHECKLIST
- INVESTIGATION
- STORY_DRIVEN
- ANALYTICAL
- SHORTS_OPTIMIZED
- SEO_OPTIMIZED

Each strategy defines:
- narrative style
- hook philosophy
- retention philosophy
- SEO philosophy
- Shorts suitability
- finance suitability
- expected strengths
- expected weaknesses

No runtime mapping or activation path exists.

## Candidate Generator

Generator:
- `PromptCandidateGenerator` (immutable)

Input:
- `GenerationBlueprint`

Output:
- multiple immutable `PromptCandidate` objects
- each candidate carries only structured planning information

Important constraint:
- no raw prompt text is generated
- only plan directives and hashes are produced

## Prompt Plan Model

Typed `PromptPlan` includes:
- narrative directives
- hook directives
- transition directives
- retention directives
- CTA directives
- thumbnail directives
- SEO directives
- Shorts directives
- finance safety directives
- uncertainty directives
- duplication avoidance directives

Model explicitly rejects secret-like content and empty directives.

## Evaluation Engine

Dimensions evaluated independently:
- blueprint coverage
- finance safety
- educational quality
- audience suitability
- narrative quality
- hook quality
- retention quality
- SEO quality
- Shorts suitability
- duplication resistance
- maintainability
- complexity

Each dimension includes:
- score
- confidence
- rationale
- evidence
- advisory_flag

## Scoring Model

Deterministic weighted model with separation:
- hard constraints
  - finance safety
  - unsupported claims
  - uncertainty handling
  - channel compatibility
- soft preferences
  - hook
  - retention
  - SEO
  - storytelling
  - readability

No opaque single-number collapse is used.
The breakdown remains explicit in every evaluation payload.

## Ranking Engine

Deterministic rankings produced for:
- best overall
- safest
- highest retention
- best SEO
- best Shorts
- most maintainable

Tie-breaking is deterministic via ordered keys and candidate IDs.

## Explanation Engine

Structured explanation per candidate:
- why it scored well
- why it lost
- strongest dimensions
- weakest dimensions
- finance concerns
- blueprint gaps

No secrets or credentials are surfaced.

## Storage and Replay

Store path:
- `logs/offline_prompt_candidates.jsonl`

Storage contract:
- append-only
- deterministic serialization
- schema validation
- stable hashes
- replay support
- malformed-line tolerance
- advisory-only invariant
- no prompt text persistence
- no credentials/secrets persistence

## Calibration

Fixtures:
- `tests/fixtures/slice4_phase5_prompt_candidate_fixtures.py`
- 40 deterministic fixtures covering:
  - finance
  - crypto
  - careers
  - entrepreneurship
  - education
  - Shorts
  - long-form
  - evergreen
  - breaking topics
  - safe finance
  - unsafe finance
  - beginner
  - advanced
  - duplicate topics
  - SEO-heavy
  - retention-heavy

Latest local calibration:
- fixture_count: 40
- deterministic_repeated_runs: true
- ranking_stability: 1.0
- score_reproducibility: 1.0
- tie_stability: 1.0
- safety_detection: 1.0
- duplicate_resistance: 1.0
- unsafe_recommendation_promotions: 0
- nondeterministic_rankings: 0

Acceptance outcome:
- deterministic repeated runs: PASS
- zero nondeterministic ranking: PASS
- zero unsafe recommendation promotion: PASS

## Performance

Local benchmark (50 runs):
- one_lab_run_ms: 4.475
- fifty_lab_run_ms: 223.772
- strategy_count: 12
- complexity: O(strategy_count * dimension_count)

## Limitations

- Heuristic evaluator; not an external model-judged semantic evaluator.
- Candidate plans are intent directives, not executable prompts.
- No production shadow longitudinal validation in this phase.

## Promotion Path

Future progression path:
1. Keep candidate generation offline and advisory.
2. Expand calibration and stability evidence on larger fixture banks.
3. Compare candidate recommendations with downstream quality outcomes in shadow evidence.
4. Keep runtime pinning to production until explicit policy gate approves controlled experiments.

## Safety Confirmation

Confirmed in this phase:
- no runtime prompt generation
- no production prompt changes
- no runtime prompt replacement
- advisory-only attachments in shadow path
- no scheduler changes
- no uploader changes
- no analytics pipeline changes
- no deployment or production operations
