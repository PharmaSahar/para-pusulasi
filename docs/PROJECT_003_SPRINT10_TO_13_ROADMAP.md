# PROJECT 003 — SPRINT 10 TO 13 ROADMAP

## Starting Point

- Baseline repository SHA for Sprint 10 planning: `836dfe3fbe15faadfec40e3acd3b40799a5ad37b`
- Sprint 9 is closed and published.
- Sprint 10 must remain additive and governed.
- Production remains unchanged during roadmap planning.

## SPRINT 10 — Recommendation Evaluation Foundation

### Mission
Evaluate already-governed candidate recommendations using Sprint 1-9 evidence and registries.

### Owned Responsibilities
- canonical evaluation contract
- deterministic evidence aggregation
- recommendation eligibility verification
- model/prompt/policy registry resolution
- causal evidence resolution
- confidence evidence resolution
- policy compliance evaluation
- evaluation score components
- blocking reasons
- advisory evaluation result
- append-only evaluation store
- replay-derived evaluation projection
- deterministic audit

### Required Properties
- advisory-only
- deterministic
- replayable
- append-only
- offline-testable
- fail-closed
- human-review-required
- production-neutral

### Non-Goals
- generating new recommendations
- ranking multiple recommendations
- selecting winners
- creating experiments
- changing YouTube
- scheduler/uploader mutation
- autonomous execution

### Immutable Modules
- Sprint 1-9 implementation modules and tests
- production deployment scripts
- Project 002 quarantine work

### Reused Modules
- registry contracts and projections from Sprint 9
- audit runner patterns from existing governance modules
- repository evidence and validation baselines

### Evaluation Contract
- eligibility input
- evidence input
- policy input
- registry resolution input
- blocking reason output
- advisory result output

### State Model
- pending
- eligible
- blocked
- advisory_pass
- advisory_fail

### Append-Only Store
- one record per evaluation decision
- canonical JSON serialization
- replay-derived projection
- hash-chain validation
- corruption detection
- fail-closed replay

### Evidence Prerequisites
- resolved registry references
- documented validation evidence
- deterministic provenance fields

### Blocking Precedence
1. policy mismatch
2. missing evidence
3. unresolved registry reference
4. corrupted input
5. non-deterministic or incomplete evidence

### Targeted Tests
- contract tests
- replay determinism tests
- hash-chain tests
- corruption tests
- backward compatibility tests
- audit runner tests

### Adjacent Suites
- Sprint 9 registry suite
- recommendation compatibility suite
- registry backward compatibility suite
- production-safety guard suites

### Full-Suite Gate
- repository-wide pytest suite must remain green or be accurately classified

### Acceptance Criteria
- deterministic evaluation output for identical inputs
- advisory-only result with explicit blocking reasons
- append-only persistence and replay projection
- no production activation or YouTube mutation

### Required Output
- evaluation contract module
- projection module
- audit module
- tests
- documentation evidence

## SPRINT 11 — Recommendation Ranking Foundation

### Mission
Rank multiple eligible advisory recommendations without executing or selecting a final production action.

### Owned Responsibilities
- canonical ranking contract
- deterministic comparable score normalization
- ranking cohorts
- tie handling
- diversity constraints
- channel/topic conflict constraints
- ranking explanations
- ranking invalidation
- append-only ranking store
- replay-derived ranking projection
- deterministic audit

### Non-Goals
- automatic winner activation
- experimentation
- YouTube mutation
- production execution

## SPRINT 12 — Experiment Planning Foundation

### Mission
Convert a human-selected advisory recommendation into a governed experiment plan.

### Owned Responsibilities
- hypothesis contract
- treatment/control plan
- primary and guardrail metrics
- sample-size and duration prerequisites
- audience allocation plan
- contamination controls
- stopping rules
- rollback conditions
- experiment-plan state machine
- append-only experiment-plan store
- replay projection
- deterministic audit

### Non-Goals
- launching the experiment
- changing traffic allocation
- metadata mutation
- automatic winner selection
- production execution

## SPRINT 13 — Human Approval and Execution Authorization Foundation

### Mission
Introduce explicit, auditable human approval before any future action can become execution-eligible.

### Owned Responsibilities
- approval request contract
- approver identity and authority
- approval/rejection/expiry/revocation states
- separation of duties
- immutable approval evidence
- authorization scope
- execution intent record
- rollback authorization
- append-only approval store
- replay projection
- deterministic audit

### Non-Goals
- direct YouTube execution
- automatic approval
- autonomous optimization
- scheduler/uploader mutation

## Post-Sprint-13 Direction

After Sprint 13, define a separate future production-integration program. Sprint 13 itself must not be represented as live production change.

## Roadmap Constraints

- Sprint 10 must not become an emergency hotfix bucket.
- Sprint 10 must stay additive.
- Emergency triage must remain separated from roadmap scope.
- Production remains unchanged until a separate governed activation program exists.
