# PROJECT 001 - Slice 4 Phase 4: Controlled Prompt Experiment Framework

## Scope

This phase implements a local, advisory-only shadow prompt laboratory for deterministic offline comparison of prompt strategies.

Explicit constraints enforced:
- no production prompts changed
- no runtime prompt replacement
- no upload behavior changes
- no scheduler behavior changes
- no analytics behavior changes
- advisory only

Maturity label:
- REPORTED (local deterministic evidence)
- Not yet PROVEN/VALIDATED in production runtime

## Architecture

Core modules:
- `src/shadow_prompt_experiment_registry.py`
  - Versioned prompt variant registry.
  - Required variants: CURRENT_PRODUCTION, CONTROL, CANDIDATE_A, CANDIDATE_B, FUTURE.
  - All variants inactive and advisory-only.
- `src/shadow_prompt_experiment_framework.py`
  - Immutable experiment/comparison/recommendation models.
  - Deterministic execution runner for multi-variant offline evaluation.
  - Deterministic scoring and recommendation logic.
  - Append-only JSONL storage and replay support.
  - Malformed-line tolerance and secret-like content rejection.
- `src/pipeline.py`
  - Shadow-path integration only, under existing shadow planning branch.
  - Fail-open fallback payload when experiment analysis fails.
  - `pipeline_output_changed` invariant remains false.

## Prompt Inventory (Authoritative Audit)

Primary runtime prompt sources:
- `src/content_generator.py`
  - `_system_prompt` (provider system prompt composition)
  - `_build_topic_prompt` (topic ideation prompt)
  - `_build_content_prompt` (main content generation prompt)
  - retry/regeneration guidance path through `prompt_variants` and `additional_guidance`

Prompt metadata and safe representation:
- `src/prompt_registry.py`
  - deterministic prompt metadata
  - safe prompt representation extraction

Prompt-related shadow analysis context:
- `src/shadow_blueprint_prompt_alignment.py`
  - safe prompt representation consumer for alignment analysis

Provider preflight probe (operational check, not content generation template):
- `src/scheduler_utils.py`
  - `run_anthropic_preflight` with minimal `"ok"` message

Deterministic editor review is non-generative and does not rewrite prompts:
- `src/editor_review.py`

No production prompt templates were replaced or activated.

## Variant Registry

Implemented variant states:
- CURRENT_PRODUCTION: baseline locked
- CONTROL: control locked
- CANDIDATE_A: inactive candidate
- CANDIDATE_B: inactive candidate
- FUTURE: reserved slot

Each entry contains:
- strategy name
- rationale
- supported channels
- supported content types
- supported blueprint versions
- status
- compatibility contract
- experiment scope

All entries enforce:
- advisory_only=true
- active=false

## Experiment Lifecycle

1. Build experiment seed from blueprint hash + baseline prompt hash + objective tuple.
2. Resolve enabled variant IDs for offline evaluation.
3. Derive deterministic candidate prompt text per variant in memory only.
4. Compute deterministic dimension metrics per variant.
5. Build explicit comparison states against CURRENT_PRODUCTION.
6. Produce recommendation outcomes without promotion.
7. Emit fixed decision `NO_RUNTIME_CHANGE` with selected runtime variant `CURRENT_PRODUCTION`.
8. Persist append-only JSONL row for replay and audit.

## Comparison Model

Dimensions implemented:
- blueprint coverage
- finance safety
- hook quality
- narrative completeness
- retention planning
- SEO planning
- Shorts planning
- thumbnail alignment
- duplication risk
- prompt complexity
- estimated token size
- unsupported features

State model:
- BETTER
- SAME
- WORSE
- UNSUPPORTED
- UNKNOWN

## Recommendation Model

Outcomes implemented:
- KEEP_CURRENT
- EXPERIMENT_FURTHER
- PROMISING
- NEEDS_MORE_DATA
- REJECT
- UNSUPPORTED

Safety/policy constraints:
- no auto-promotion
- no runtime selection changes
- final decision always `NO_RUNTIME_CHANGE`

## Storage and Replay

Store:
- `logs/shadow_prompt_experiments.jsonl`

Properties:
- deterministic serialization (sorted-key JSON)
- schema validation
- append-only writes
- stable hash-based IDs
- malformed-line tolerant loader
- replay aggregation by variant/recommendation
- bounded text only
- secret-like content rejection

## Calibration Strategy

Fixtures:
- `tests/fixtures/slice4_phase4_prompt_experiment_fixtures.py`
- 30 deterministic scenarios covering finance, education, career, entrepreneurship, shorts, long-form, duplicate topics, safety edges, SEO-heavy prompts, hook/narrative/thumbnail mismatch, unsupported feature marker.

Deterministic local evidence snapshot:
- fixture_count: 30
- recommendation distribution across 5 variants x 30 fixtures:
  - KEEP_CURRENT: 96
  - PROMISING: 24
  - EXPERIMENT_FURTHER: 20
  - REJECT: 5
  - UNSUPPORTED: 5

## Performance (Local)

Benchmark (50 runs, deterministic local):
- one_experiment_ms: 0.623
- fifty_experiment_ms: 31.153
- variant_count: 5
- complexity: O(variant_count * metrics_dimensions)

Interpretation:
- Local overhead is low for offline shadow evaluation.
- This is local evidence only, not production SLO proof.

## Limitations

- Heuristic scoring; no external offline LLM judge integrated yet.
- Variant prompt texts are derived strategy simulations, not runtime replacements.
- No production shadow artifact trend analysis performed in this phase.

## Promotion Criteria (Future)

To move beyond REPORTED:
- collect broader shadow evidence across channels/time windows
- validate recommendation stability against downstream quality outcomes
- confirm no drift in safety/conflict metrics
- maintain runtime immutability guarantees before any future promotion policy

## Safety Confirmation

Confirmed for this phase:
- no production prompts changed
- no runtime prompt replacement
- no upload changes
- no scheduler changes
- no analytics changes
- advisory-only shadow results
