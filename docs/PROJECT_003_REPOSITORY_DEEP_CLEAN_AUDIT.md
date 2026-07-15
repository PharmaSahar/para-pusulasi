# PROJECT 003 — Repository Deep Clean Audit

## Scope

Read-only deep-clean audit of repository structure, Git hygiene, Python/dependency hygiene, operational hygiene, and documentation hygiene.

## Repository Hygiene Findings

### CLEAN
- [src/model_registry.py](src/model_registry.py)
- [src/model_registry_projection.py](src/model_registry_projection.py)
- [src/policy_registry.py](src/policy_registry.py)
- [src/policy_registry_projection.py](src/policy_registry_projection.py)
- [src/prompt_governance_registry.py](src/prompt_governance_registry.py)
- [src/prompt_governance_registry_projection.py](src/prompt_governance_registry_projection.py)
- [src/run_registry_audit.py](src/run_registry_audit.py)
- [tests/test_model_registry.py](tests/test_model_registry.py)
- [tests/test_policy_registry.py](tests/test_policy_registry.py)
- [tests/test_prompt_governance_registry.py](tests/test_prompt_governance_registry.py)
- [tests/test_registry_backward_compat.py](tests/test_registry_backward_compat.py)
- [tests/test_registry_projection.py](tests/test_registry_projection.py)
- [docs/PROJECT_003_SPRINT9_REGISTRY_GOVERNANCE.md](docs/PROJECT_003_SPRINT9_REGISTRY_GOVERNANCE.md)
- [docs/PROJECT_003_SPRINT9_PUBLICATION_EVIDENCE.md](docs/PROJECT_003_SPRINT9_PUBLICATION_EVIDENCE.md)

### DOCUMENTATION_STALE
- [docs/PRODUCTION_BASELINE_v1.md](docs/PRODUCTION_BASELINE_v1.md): still states the repository baseline around SHA `c732427367d782f56c335e52dd063deaa8db3e0d` and describes a "last validated deployment" that is older than the current published documentation commit. This is not automatically wrong, but it is stale relative to the newly published Sprint 9 documentation trail.
- [docs/production_dashboard_latest.md](docs/production_dashboard_latest.md): generated `2026-07-11T07:07:35.310746+00:00`, which is older than the current repository evidence window and should be treated as historical unless refreshed.
- [docs/production_readiness_checklist.md](docs/production_readiness_checklist.md): checklist format is still active, but several gates remain unchecked and the document reads as an operational gate rather than a completed baseline.
- [docs/activation_controller_runbook.md](docs/activation_controller_runbook.md): contains documentation-only cron/systemd examples with placeholder paths; should remain clearly labeled as examples.
- [docs/PROJECT_003_SPRINT9_PUBLICATION_EVIDENCE.md](docs/PROJECT_003_SPRINT9_PUBLICATION_EVIDENCE.md): publication evidence is archival and should not be interpreted as live activation proof.

### DUPLICATE_BUT_REFERENCED
- [src/prompt_registry.py](src/prompt_registry.py) and [tests/test_prompt_registry.py](tests/test_prompt_registry.py) are pre-existing anchors that remain referenced and intentionally unchanged; Sprint 9 introduced additive prompt-governance variants instead of replacing them.
- [docs/archive/architecture_audit_2026-07-09.md](docs/archive/architecture_audit_2026-07-09.md) and [archive/ARCHIVE_INDEX.md](archive/ARCHIVE_INDEX.md) serve as historical reference material and should remain preserved.

### ARCHITECTURAL_DEBT
- [src/scheduler.py](src/scheduler.py): remains a central runtime orchestrator, which is expected, but it concentrates production behavior and therefore needs careful boundary discipline.
- [src/youtube_uploader.py](src/youtube_uploader.py) and [src/youtube_analytics.py](src/youtube_analytics.py): still encode production-facing provider behavior and must remain separated from advisory governance modules.
- [src/production_quality_platform.py](src/production_quality_platform.py) and [src/production_readiness.py](src/production_readiness.py): validate production safety but also reveal that production activation remains coupled to environment and service state.
- [ops/verify_production_cutover.py](ops/verify_production_cutover.py): useful governance tool, but it codifies the gap between repository HEAD and deployed runtime SHA, so it should stay read-only and audit-only.
- [ops/session_start.sh](ops/session_start.sh): useful for operator visibility, but it embeds live SSH and queue inspection behavior and should be treated as an operational helper rather than a repository-clean core module.

### OPERATIONAL_RISK
- [deploy/setup_vps.sh](deploy/setup_vps.sh), [deploy/transfer.sh](deploy/transfer.sh), and [deploy/single_root_cutover.sh](deploy/single_root_cutover.sh): still contain live deployment and systemd cutover instructions and therefore remain sensitive operational surfaces.
- [ops/session_start.sh](ops/session_start.sh): contains direct SSH-based production probing against a real host and should be treated as high-trust operational tooling.
- [docs/PRODUCTION_BASELINE_v1.md](docs/PRODUCTION_BASELINE_v1.md): states a production baseline and rollout guarantees that can be misunderstood as current activation proof if read without runtime evidence.

### SECURITY_RISK
- [.env](.env) exists in the repository root listing, but it is ignored by policy and should never be committed.
- [ops/client_secrets_bulk_map_template.csv](ops/client_secrets_bulk_map_template.csv) and [ops/client_secrets_bulk_map_template.json](ops/client_secrets_bulk_map_template.json) are sensitive in nature even as templates and require careful handling.
- [deploy/transfer.sh](deploy/transfer.sh) references `.env` transfer and root SSH usage; this is acceptable as an operational script only if it remains out of source-controlled secrets.

### PRODUCTION_BLOCKER
- [docs/production_readiness_checklist.md](docs/production_readiness_checklist.md): live analytics rollout gate remains explicitly unchecked and says that without a YouTube Analytics API go-decision the live collector must not be connected to production.
- [docs/PRODUCTION_BASELINE_v1.md](docs/PRODUCTION_BASELINE_v1.md): current baseline SHA is older than the currently deployed runtime SHA observed from the live host, indicating production drift that must be understood before any activation claims.
- [src/run_registry_audit.py](src/run_registry_audit.py): good governance code, but it should not be mistaken for an execution path; the project still needs explicit approval boundaries before recommendation evaluation becomes live.

### TEST_DEBT
- [tests/test_verify_production_cutover.py](tests/test_verify_production_cutover.py): proves the cutover verifier can validate an approved ancestry path, but it also shows the repository relies on evidence artifacts for equivalence logic.
- [tests/test_production_readiness.py](tests/test_production_readiness.py): indicates production readiness is environment-dependent and should not be inferred from Git publication alone.

### DEPENDENCY_DEBT
- [requirements.txt](requirements.txt): should be periodically reconciled against actual imports because the repository spans runtime, ops, and audit concerns.
- [.venv-2/pyvenv.cfg](.venv-2/pyvenv.cfg): local environment metadata exists and should not be used as a portable runtime truth source.
- [pytest.ini](pytest.ini): test discovery is broad and includes many modules that are not part of Sprint 9, so suite targeting must stay explicit.

### SAFE_TO_REMOVE_LATER
- [__pycache__/scheduler.cpython-313.pyc](__pycache__/scheduler.cpython-313.pyc): generated bytecode cache.
- [.pytest_cache/](.pytest_cache/): generated test cache.
- [tests/__pycache__/](tests/__pycache__/): generated test caches.
- [src/__pycache__/](src/__pycache__/): generated test caches.

### UNKNOWN_REQUIRES_REVIEW
- [archive/2026-07-production-hardening/](archive/2026-07-production-hardening/): historical evidence bundle is valuable, but a full reachability review is needed before any retirement decision.
- [artifacts/latest/](artifacts/latest/): contains active runtime evidence and validation outputs; safe removal cannot be assumed.
- [logs/](logs/): ignored runtime evidence; contents are operationally important and should not be deleted without a retention decision.
- [channels/channel_registry.json](channels/channel_registry.json): active channel inventory and production identity mapping; review required before any structural cleanup.

## Git Hygiene Findings

- A pre-existing stash exists: `stash@{0}: On master: preserve-unrelated-before-smoke-push: ROOT_CAUSE_ANALYSIS.md`.
- No unexpected staged or untracked files were present in the primary worktree during baseline checks.
- The quarantine worktree [wip/project002-phase4b-precondition-quarantine-20260715](wip/project002-phase4b-precondition-quarantine-20260715) remains isolated and unpushed.

## Summary

No automatic deletion is recommended in this audit. Safe cleanup is limited to generated caches and other disposable local artifacts that are already ignored or clearly regenerated. Most operational and documentation items require governance review rather than immediate removal.
