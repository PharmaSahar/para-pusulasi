# PROJECT 003 Sprint 7 Causal Attribution Foundation

## Mission

Sprint 7 adds a deterministic causal-attribution foundation that decides whether available evidence is eligible for causal interpretation. It does not choose winners, does not issue recommendations, does not mutate policy, and does not perform runtime actions.

## Baseline

- Authoritative baseline SHA: 1a2a424f70274efc3a593c5b21bfc051bc58f275
- Baseline validation posture: CONDITIONALLY_VALIDATED

## Owned Responsibilities

- Canonical causal attribution contract
- Deterministic causal state model
- Explicit confounder governance
- Explicit counterfactual governance
- Append-only attribution store
- Replay-derived attribution projection
- Deterministic audit artifact generation
- Causal blocking reason accounting

## Non-Goals

- Winner selection
- Recommendation logic
- Policy mutation
- Scheduler integration
- Uploader integration
- OAuth/API configuration changes
- Runtime activation or deployment
- YouTube API interaction
- VPS interaction
- Autonomous optimization

## Causal Eligibility Model

Causal support is eligible only when treatment/control assignment lineage is complete, exposure and outcome evidence are complete, outcome windows are mature, contamination is absent, confounders are resolved, statistical prerequisites are satisfied, and replay integrity is valid.

Observational evidence remains associational by design and is classified as ASSOCIATIONAL_ONLY or CAUSALLY_INCONCLUSIVE.

## Deterministic State Model

Allowed states:

- NOT_ATTRIBUTABLE
- INSUFFICIENT_LINEAGE
- INSUFFICIENT_CONTROL
- IMMATURE_OUTCOME
- CONTAMINATED
- CONFOUNDED
- UNDERPOWERED
- ASSOCIATIONAL_ONLY
- ATTRIBUTION_ELIGIBLE
- CAUSALLY_INCONCLUSIVE
- CAUSALLY_SUPPORTED
- INVALIDATED

Precedence is deterministic and fail-closed. Any corruption, synthetic evidence, unresolved confounder, or incomplete lineage prevents CAUSALLY_SUPPORTED.

## Confounder Governance

Sprint 7 records confounder governance explicitly with:

- confounder_set_id
- declared_confounders
- unresolved_confounders
- confounder_status
- confounder_evidence_refs

Supported confounder statuses:

- NOT_DECLARED
- DECLARED
- PARTIALLY_RESOLVED
- RESOLVED
- UNRESOLVED
- INVALID

Any unresolved or invalid confounder condition blocks causal support.

## Counterfactual Governance

Counterfactual metadata is explicit and deterministic:

- counterfactual_method
- counterfactual_status
- counterfactual_evidence_refs
- counterfactual_is_observed
- counterfactual_is_synthetic

Supported counterfactual statuses:

- OBSERVED_CONTROL_OUTCOME
- EXPERIMENT_DERIVED_COUNTERFACTUAL
- UNAVAILABLE
- SYNTHETIC_OR_SIMULATED

Synthetic counterfactuals may be stored as research metadata but cannot support causal claims.

## Event and Storage Model

The attribution store is append-only JSONL. Every late correction, reclassification, or invalidation is represented as a new event. Historical rows are never overwritten.

Store guarantees:

- deterministic IDs and hashes
- hash-chain verification
- duplicate idempotency for exact duplicates
- conflict rejection for non-identical duplicate identities
- replay-based rebuilding
- malformed/truncated row detection
- unsupported-schema detection
- fail-closed append when history is corrupted

## Projection Semantics

Projection is replay-derived and not a source of truth. It deterministically exposes:

- latest state by attribution record
- latest valid (non-invalidated) state
- attribution-state counts
- confounder-state counts
- counterfactual-state counts
- causal blocking reason counts
- attribution eligibility counts
- projection identity and hash

Unknown versus false versus zero distinctions are preserved directly from replayed records.

## Statistical Confidence Prerequisites

Causal support requires confidence prerequisites to be satisfied:

- sample_sufficiency true
- power_sufficiency true
- multiple_comparison_governed true
- effect_size_available true
- uncertainty_available true
- confidence_state compatible with support

## Production Neutrality and Limitations

Sprint 7 is advisory-only, deterministic, offline-testable, and production-neutral. It does not autonomously determine why performance changed; it only classifies whether evidence is eligible for causal interpretation under explicit governance constraints.

## Audit Artifact

Deterministic assessment artifact path:

- artifacts/latest/project003_sprint7_causal_attribution_assessment.json
