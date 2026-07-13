# Production Baseline v1.0

Baseline creation date: 2026-07-13 UTC
Current production SHA: c732427367d782f56c335e52dd063deaa8db3e0d
Production status: healthy, release baseline established
Last validated deployment: 2026-07-12 VPS deployment validated at SHA c732427367d782f56c335e52dd063deaa8db3e0d with smoke validation passing and service active

## 1. Baseline Information

This document is the authoritative baseline for the repository after the successful production hardening release.

Current repository structure:
- Python application root with scheduler, pipeline, and operational tooling.
- Runtime code in `src/`.
- Regression and safety tests in `tests/`.
- Operational scripts and validation runners in `ops/`.
- Configuration and environment definitions in `config/`.
- Active documentation and governance material in `docs/`.
- Historical documentation in `docs/archive/`.
- Completed evidence bundles in `archive/`.
- Current operational snapshots in `artifacts/latest/`.
- Deployment evidence in `artifacts/deployment/`.
- Incident evidence in `artifacts/incidents/`.

## 2. Repository Layout

### `src/`
Runtime implementation for the production system, including scheduler logic, pipeline execution, guardrails, observability helpers, and storage behavior.

### `tests/`
Automated tests that protect production contracts, safety invariants, and regression boundaries.

### `ops/`
Operational runners, validation scripts, readiness refresh tasks, and deployment support utilities.

### `config/`
Configuration files and environment-facing settings used by the runtime and operational workflows.

### `docs/`
Current operational documentation, contracts, runbooks, governance notes, and active baseline references.

### `docs/archive/`
Historical documentation that is no longer part of the active operational surface.

### `archive/`
Completed project evidence bundles, organized by project and retention category, with `archive/ARCHIVE_INDEX.md` as the inventory.

### `artifacts/latest/`
Current authoritative operational snapshots, validation outputs, and active evidence still referenced by day-to-day operations.

### `artifacts/deployment/`
Deployment reports, rollout artifacts, smoke evidence, and postdeploy validation records for release activity.

### `artifacts/incidents/`
Incident records, recovery evidence, and lifecycle artifacts for closed or active operational incidents.

## 3. Runtime Architecture

### Scheduler
The scheduler is the main production orchestrator. It loads work, applies guardrails, classifies failures, decides whether to retry or quarantine, and coordinates downstream execution.

### Pipeline
The pipeline generates and prepares content, enriches runtime metadata, enforces topic-domain and upload safety rules, and returns a terminal outcome to the scheduler.

### Upload flow
Upload execution is safety-gated. Terminal content-domain blocks remain non-retryable, upload-precheck failures stop unsafe release paths, and the upload stage must never bypass production contracts.

### Runtime storage
Runtime state is isolated from tracked source and documentation. Production runtime paths are expected to stay outside tracked docs, with protected runtime files and dedicated state locations.

### Incident system
Incident handling records failures and recovery state, preserves lifecycle metadata, and follows fail-open behavior so observability failures do not rewrite business decisions.

### Observability
Observability captures runtime snapshots, dashboard state, telemetry, and validation evidence. It is designed to be noisy enough for operators while preserving redaction, cooldown, and fail-open guarantees.

### Runtime output locations
Primary runtime outputs are expected to land in operational and state-bearing locations such as:
- `artifacts/latest/`
- `artifacts/deployment/`
- `artifacts/incidents/`
- runtime state directories outside the tracked source tree

## 4. Production Contracts

The live production baseline preserves these guarantees:
- Topic-domain protection: terminal topic-domain violations are quarantined and must not fall into generic retry loops.
- Runtime isolation: runtime files, state, and release artifacts stay separate from tracked source and documentation.
- Deployment rollback: release validation must support safe rollback when a deployment is not stable.
- Upload safety: unsafe uploads must be blocked before release paths can produce invalid production output.
- Incident lifecycle: incident state must be recorded, resolved, and retained with lifecycle integrity.
- Observability: notification and telemetry failures must fail open rather than changing scheduler decisions.
- Provider guardrails: provider- and channel-scoped alerting, deduplication, and cooldown behavior must prevent noise and cross-channel leakage.

## 5. Operational Workflow

Future development must follow this sequence:

feature -> tests -> push -> deploy -> smoke validation -> production soak -> archive

No step may be skipped when it is required for a production-facing change.

## 6. Repository Rules

The permanent repository rules are:
- Preserve runtime isolation.
- Preserve production contracts.
- Preserve rollback safety.
- Preserve scheduler safety.
- Preserve upload safety.
- Prefer archive over delete for completed evidence.
- Keep active operational documentation in `docs/`.
- Keep historical documentation in `docs/archive/`.
- Keep current operational snapshots in `artifacts/latest/`.
- Keep completed evidence bundles in `archive/` with an index entry.
- Maintain one canonical active copy for living documentation where possible.
- Do not overwrite historical evidence to simulate current state.
- Keep temporary diagnostics out of the active surface once their purpose is complete.

## 7. Documentation Rules

Documentation placement, retention, and archival rules are governed by [docs/repository_documentation_policy.md](docs/repository_documentation_policy.md).

## 8. Archive Rules

Completed evidence inventories and archive mapping are governed by [archive/2026-07-production-hardening/ARCHIVE_INDEX.md](archive/2026-07-production-hardening/ARCHIVE_INDEX.md).

## 9. Future Development Rules

Every future feature must preserve:
- runtime isolation
- production contracts
- rollback safety
- scheduler safety
- upload safety
- documentation policy compliance

Any change that weakens one of these guarantees must be treated as out of baseline until it is revalidated.

## 10. Baseline Acceptance

This document is the official repository baseline.
All future work must begin from this baseline and must preserve the repository, runtime, deployment, and documentation rules defined here.
