# PROJECT 003 — Sprint 8 Recommendation Governance Foundation

Sprint 8 adds a deterministic recommendation-governance foundation that decides whether advisory recommendations are eligible under strict evidence and policy constraints. It does not execute actions, does not publish content, does not mutate runtime systems, and does not bypass human review.

## Baseline

- Authoritative baseline SHA: 3d388b66e83e012ea0b8df50fd5e7c78236216d3
- Baseline validation posture: CONDITIONALLY_VALIDATED

## Owned Responsibilities

- Canonical recommendation governance contract
- Deterministic recommendation state model
- Runtime-action denial for advisory payload keys
- Append-only recommendation governance store
- Replay-derived recommendation projection
- Deterministic assessment artifact generation
- Human-review gate enforcement for all advisory outputs

## Non-Goals

- Automated execution
- Scheduler activation
- Metadata mutation
- Thumbnail/title mutation
- Uploader integration
- Deployment actions
- VPS interaction
- YouTube API interaction
- Autonomous optimization

## Deterministic State Model

Allowed states:

- NOT_RECOMMENDABLE
- INSUFFICIENT_EVIDENCE
- ASSOCIATIONAL_ONLY
- CAUSALLY_INCONCLUSIVE
- CONTAMINATED
- POLICY_BLOCKED
- MODEL_LINEAGE_MISSING
- PROMPT_LINEAGE_MISSING
- RECOMMENDATION_ELIGIBLE
- ADVISORY_RECOMMENDATION
- HUMAN_REVIEW_REQUIRED
- INVALIDATED

State precedence is deterministic and fail-closed.

## Recommendation Safety and Deny Rules

Sprint 8 denies execution-like advisory payload directives deterministically.

Forbidden keys or action-values include:

- execute
- apply
- publish
- upload
- schedule
- mutate
- update_metadata
- change_thumbnail
- change_title
- activate
- deploy

Any advisory payload containing forbidden runtime-action semantics is rejected by contract validation.

## Human Review Governance

All recommendation outputs are advisory-only and human-review gated.
No record is considered an autonomous action.

## Event and Storage Model

Recommendation governance storage is append-only JSONL.

Store guarantees:

- deterministic IDs and hashes
- hash-chain verification
- exact duplicate idempotency
- conflict rejection for non-identical duplicate identities
- replay-based rebuilding
- malformed/truncated row detection
- unsupported-schema detection
- fail-closed append when history is corrupted

## Projection Semantics

Projection is replay-derived and deterministic. It exposes:

- latest state by recommendation record
- latest valid (non-invalidated) state
- recommendation-state counts
- policy-status counts
- blocking-reason counts
- recommendation eligibility counts
- human-review-required counts
- projection identity and hash

## Production Neutrality and Limitations

Sprint 8 is advisory-only, deterministic, offline-testable, and production-neutral.
It does not call external services and does not trigger operational side effects.

## Audit Artifact

Deterministic assessment artifact path:

- artifacts/latest/project003_sprint8_recommendation_governance_assessment.json
