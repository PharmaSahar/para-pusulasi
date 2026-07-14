# PROJECT 003 Sprint 1 Decision Memory

## Scope and Ownership

Sprint 1 owns canonical decision recording, append-only decision event storage, deterministic replay, and audit-time verification for decision records.

Primary implementation owners in repository:
- src/evidence_reference.py
- src/decision_contract.py
- src/decision_memory.py
- src/run_decision_memory_audit.py

## Architecture

The Sprint 1 implementation is split into four layers:
1. Evidence reference contract and validators.
2. Decision record contract and canonical row builder/validator.
3. Append-only JSONL store with replay and projections.
4. Audit runner that summarizes validation and emits a deterministic artifact.

No runtime deployment, scheduler mutation, uploader mutation, or external API interaction is performed by these Sprint 1 modules.

## Schema

Schema version is defined by the decision contract constant:
- DECISION_CONTRACT_SCHEMA_VERSION in src/decision_contract.py

Decision records include deterministic identity fields, state fields, evidence references, explanation fields, and hash-chain fields:
- decision_id
- decision_event_id
- record_hash
- previous_record_hash
- decision_state
- human_approval_state
- evidence reference collections
- decision_explanation

Unsupported schema versions fail explicit validation.

## State Machine

State transitions are validated by decision contract transition rules.
Terminal states are explicitly defined and guarded.
Store transition append rejects invalid transitions and unknown decision ids.

## Append-Only Model

Decision Memory persistence is append-only JSONL.
Rows are appended using os.O_APPEND and never rewritten in place.
Corrupt history is detected and raised as DecisionMemoryCorruptionError before new append attempts.

## Deterministic Hashing

Deterministic identity and hashing are contract-owned:
- compute_decision_id
- compute_decision_event_id
- compute_record_hash

Canonical row generation is centralized and reused by builder and validator paths.

## Replay

Replay consumes stored canonical rows, sorts deterministically by timestamp and event identity, and rebuilds current state and timeline projections.

## Projections

Sprint 1 projections include:
- current state by decision id
- decision timeline
- content/channel/type indexes
- unresolved review required list
- quarantined list
- superseded chain
- rollback history
- evidence/version indexes
- deterministic decision feature projection

## Evidence References

Evidence references are typed and validated in src/evidence_reference.py.
Availability states are explicit, including unavailable evidence.
Reference normalization is deterministic and used by contract/store paths.

## Explanation Contract

Decision explanation structure is validated with required fields and typed enums.
Explanation data is normalized into a deterministic dictionary form used by canonical rows.

## Corruption Handling

Load and replay diagnostics track malformed rows, partial trailing rows, duplicate rows, unsupported schema rows, and broken hash links.
Store operations enforce a clean-history gate before mutation.

## Idempotency

Exact duplicate appends are idempotent and return duplicate results without appending new rows.
Conflicting duplicates are rejected explicitly.

## Backward Compatibility

Backward compatibility smoke coverage exists in tests/test_decision_backward_compat.py for related Project 002 modules and prompt metadata helpers.
Sprint 1 modules are additive and isolated from scheduler/uploader operational behavior.

## Security Boundaries

Sprint 1 code paths are local-file and git-metadata based.
Audit execution is offline and deterministic in tests.
No secrets or credentials are emitted by Sprint 1 artifact generation.

## Production Neutrality

Sprint 1 components are validation and storage-contract focused.
They do not call YouTube APIs, do not mutate OAuth configuration, and do not perform deployment actions.

## Future Sprint 2 Integration Points

These are identified extension points, not implemented behavior:
- richer policy gates on top of decision projections
- higher-order recommendation logic consuming deterministic feature projections
- expanded audit dimensions over additional runtime evidence classes
