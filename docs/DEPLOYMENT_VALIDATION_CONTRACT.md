# Deployment Validation Contract

Status: CANONICAL_DEPLOYMENT_VALIDATION_SPECIFICATION
Scope: PROJECT004 deployment validation governance
Source SHA reviewed: 1b4893aec6d0f0f3e55f30dce3db51c771a9b666

This document consolidates existing repository deployment validation requirements. It does not change immutable deployment behavior, rollback behavior, scheduler behavior, pipeline behavior, production behavior, test behavior, CI behavior, or deployment scripts.

## 1. Purpose

This contract defines the repository's official validation requirements for production deployment decisions. It records which evidence must be present before a deployment is considered eligible, which checks are deployment blockers, which checks belong to adjacent governance domains, and how deployment acceptance is recorded after production observation.

The contract exists because deployment requirements are distributed across the immutable release runbook, production readiness checklist, production baseline, PROJECT003 safety runbooks, Phase4B and Phase4C analytics documents, deploy implementation, and deployment-related tests. This document makes that governance boundary explicit without redesigning deployment.

## 2. Scope

In scope:

- validation of the deployment source checkout and exact target SHA
- validation of immutable release behavior before invoking production mutation
- validation of production readiness, scheduler safety, upload safety, provider safety, topic-domain safety, startup preflight, smoke evidence, rollback readiness, and acceptance observation
- classification of deployment-related tests in `tests/`
- separation of deployment validation from historical analytics validation, CI validation, research validation, and broad regression validation

Out of scope:

- production deployment execution
- production service restart
- rollback execution
- CI workflow changes
- test implementation changes
- deployment script changes
- application, scheduler, pipeline, uploader, analytics, or runtime implementation changes
- regeneration or backfill of historical analytics files

The canonical deployment entrypoint remains `bash deploy/deploy.sh`, implemented by `deploy/deploy.sh` and delegated to `deploy/internal/immutable_release_v2_impl.sh`.

## 3. Definitions

Deployment Source: The clean Git checkout used by immutable release tooling to resolve target refs and materialize the release payload. The immutable release runbook separates this from the active runtime release, which may contain runtime-owned evidence.

Deployment Validation: The pre-deployment and post-deployment evidence required to decide whether a specific source SHA is eligible for production release, whether release activation succeeded, and whether rollback remains available.

Historical Validation: Validation of frozen analytics baselines, especially Phase4B and Phase4C inputs and invariants. Historical validation can be required for analytics work, but it is not the deployment validation gate unless a deployment explicitly changes the relevant analytics contracts.

Production Readiness: The release go/no-go checklist covering build and test gates, scheduler health, upload credentials, provider safety, telemetry, alerting, rollback plan, and incident readiness.

Smoke Validation: Bounded post-release or pre-cutover safety evidence showing that the production safety smoke path and no-upload smoke expectations pass without mutating production content outside the intended deployment behavior.

Rollback: The immutable release recovery path that restores a prior release. The canonical rollback path resolves the previous release SHA from a completed deployment journal by deployment ID.

Acceptance Window: The post-deployment observation period used by project governance before declaring final acceptance. The current contract treats the 24-hour window as governance acceptance policy, not as an implementation requirement embedded in deploy scripts.

Blocking Test: A test file whose failure blocks PROJECT004 deployment because it protects deployment activation, immutable release mechanics, production readiness, scheduler startup safety, upload safety, provider safety, topic-domain safety, smoke safety, or rollback readiness.

Recommended Test: A test file that is relevant evidence for confidence or adjacent safety but is not part of the mandatory PROJECT004 deployment gate unless the deployment scope touches that area.

## 4. Deployment Validation Philosophy

Deployment validation, production readiness, historical analytics validation, CI validation, research validation, and broad regression validation are independent governance domains.

Deployment validation protects release activation. Its evidence comes from exact SHA validation, clean deployment source validation, immutable release tests, production readiness tests, scheduler startup preflight, production health verification, smoke validation, and rollback readiness.

Production readiness protects live operating conditions. `docs/production_readiness_checklist.md` defines a go/no-go checklist covering targeted smoke tests, critical regression tests, scheduler health, upload credentials, telemetry, alerting, rollback plan, and incident ownership.

Historical analytics validation protects frozen analytical baselines. Phase4B and Phase4C documents define read-only preconditions for `assessment_summary.json`, `logs/channel_performance.jsonl`, and `logs/canonical_content_analytics.jsonl`. Those files are historical analytics inputs, not immutable release activation inputs.

CI validation protects automated repository checks. The presence or absence of CI coverage does not replace the deployment contract unless a CI workflow is explicitly designated as deployment validation evidence.

Research validation protects experiments, recovery audits, or model and analytics exploration. Research validation may inform confidence, but it is not the production deployment gate unless the deployment scope includes the researched component.

Broad regression validation protects general repository health. A full repository suite can be valuable health evidence, but it is not automatically the deployment blocker when it is stopped by a dedicated historical analytics precondition unrelated to deployment activation. When a validation runner explicitly configures a full phase, that runner phase still owns its full test gate; this contract does not redefine that runner phase as the PROJECT004 deployment gate.

These domains are separate because the repository architecture separates immutable release mechanics, runtime production safety, analytics baseline governance, and research workflows. Combining them without scope evidence can false-block deployment or hide the specific failure domain that needs review.

## 5. Official Deployment Validation Matrix

The following classifications apply to PROJECT004 deployment validation at the reviewed SHA. Every path listed here was verified to exist in the repository.

| Test path | Classification | Justification |
| --- | --- | --- |
| `tests/test_immutable_release_v2.py` | BLOCKING | Covers canonical deploy entrypoint support, read-only plan behavior, clean deployment source handling, full SHA requirement, target ref/SHA mismatch rejection, local-only commit rejection, release root enforcement, staging collision rejection, persistent linking, preflight command capture, runtime payload sanitization, lock and transaction behavior, verify, rollback, wrapper compatibility, and safety prohibitions. |
| `tests/test_verify_production_cutover.py` | BLOCKING | Covers production cutover verification, build SHA mismatch, release basename and metadata mismatch, stale evidence, missing capability, and unrelated implementation failure. |
| `tests/test_scheduler_singleton_lock.py` | BLOCKING | Covers duplicate scheduler prevention and stale scheduler singleton metadata handling. |
| `tests/test_preprod_isolation_paths.py` | BLOCKING | Covers preprod isolation fail-closed behavior for missing state roots, missing required latest-writer envs, repository mutable paths, isolated paths, dashboard overrides, governance readiness overrides, activation archive overrides, and unchanged production defaults outside preprod mode. |
| `tests/test_preprod_validation_runner.py` | BLOCKING | Covers validation phase ordering, tracked mutation detection, runtime identity checks, detached launch requirements, wrong scheduler/SHA rejection, environment cleanup, and full-phase mutation enforcement for the preprod validation runner. |
| `tests/test_production_readiness.py` | BLOCKING | Covers production health checks, actionable readiness failures, required settings, key signal summaries, and YouTube DNS failure reporting. |
| `tests/test_production_safety_gate.py` | BLOCKING | Covers safety gate pass/block behavior, missing credentials, invalid authentication, missing required environment, deployment lock ownership, release integrity mismatch, unwritable paths, low disk, invalid clock, queue corruption, duplicate scheduler state, structured events, and containment behavior. |
| `tests/test_production_safety_smoke.py` | BLOCKING | Covers production safety smoke report schema, which is the repository smoke evidence surface referenced by the production safety runbook. |
| `tests/test_scheduler_cli.py` | BLOCKING | Covers scheduler help safety, health check without scheduler start, startup preflight without scheduler start, safety gate blocking before work, safety check command behavior, default startup safety-gate writes, cwd independence, and import cleanliness. |
| `tests/test_scheduler_startup_generation.py` | BLOCKING | Covers no implicit generation on startup, explicit initial-fill behavior, observation-mode blocking, trigger validation, recurrence registration without execution, and catchup behavior that does not create render submissions. |
| `tests/test_scheduler_provider_guardrails.py` | BLOCKING | Covers provider preflight, fail-open behavior where allowed, provider circuit behavior, overload pause, production safety gate blocking, upload-precheck quarantine, retry handling, and channel-scoped notification behavior. |
| `tests/test_scheduler_topic_domain_guard.py` | BLOCKING | Covers terminal topic-domain quarantine, non-retry behavior, upload prevention after blocked content, retry-resume bypass prevention, fail-safe quarantine persistence, and market-language misroute guard behavior. |
| `tests/test_upload_precheck.py` | BLOCKING | Covers upload manifest approval and blocking for missing visual manifests, tuple mismatch, hash mismatch, cross-domain content, missing scripts, missing videos, missing thumbnails, unreadable artifacts, and observation-mode exception behavior. |
| `tests/test_project002_phase4b_precondition_check.py` | RECOMMENDED | Relevant to analytics readiness and Phase4B precondition governance, but not a PROJECT004 deployment blocker unless the deployment changes Phase4B or Phase4C analytics contracts. |
| `tests/test_phase4c_validation_gate_workflow.py` | RECOMMENDED | Relevant to Phase4C historical analytics gate workflow, but not a PROJECT004 deployment blocker unless the deployment changes Phase4C validation behavior. |
| `tests/test_unresolved_analytics_recovery_integration.py` | RECOMMENDED | Historical analytics recovery coverage. It becomes blocking only for deployments that change unresolved analytics recovery behavior or its frozen Phase4B inputs. |
| `tests/test_unresolved_analytics_recovery_manifest.py` | RECOMMENDED | Historical analytics manifest coverage. It becomes blocking only for deployments that change unresolved analytics recovery manifest behavior. |
| `tests/test_unresolved_analytics_recovery_methods.py` | RECOMMENDED | Historical analytics recovery method coverage. It is not deployment-related unless analytics recovery behavior is in deployment scope. |
| `tests/test_unresolved_analytics_recovery_scenarios.py` | RECOMMENDED | Historical analytics recovery scenario coverage. It is not deployment-related unless analytics recovery behavior is in deployment scope. |
| `tests/test_unresolved_analytics_recovery_snapshots.py` | RECOMMENDED | Historical analytics snapshot coverage. It is not deployment-related unless analytics snapshot contracts are in deployment scope. |
| `tests/test_unresolved_analytics_recovery_taxonomy.py` | RECOMMENDED | Historical analytics taxonomy coverage. It is not deployment-related unless analytics taxonomy contracts are in deployment scope. |

No deployment-related test verified for PROJECT004 is classified OPTIONAL or NOT DEPLOYMENT RELATED. Tests outside the listed deployment and analytics paths remain governed by their own feature, research, regression, or analytics domains.

## 6. Official Deployment Sequence

The canonical governance sequence is:

1. Repository validation: confirm the repository branch, remote parity, status, and worktree list before using the source for deployment validation.
2. Source validation: confirm the deployment source checkout is clean. If the primary worktree is dirty, use a clean isolated worktree at the exact target SHA and leave the primary worktree untouched.
3. SHA validation: confirm the target SHA is a full 40-character SHA and equals the expected release SHA and `origin/master` or the approved target ref for the deployment.
4. Clean worktree verification: confirm the deployment source has no modified, staged, deleted, renamed, or untracked files.
5. Required deployment tests: run the BLOCKING test set in Section 5 from the deployment source context and treat any failure as a deployment blocker unless the failing test is proven unrelated to the deployment scope by maintainer review.
6. Deployment plan: use the immutable release plan mode for read-only prerequisite and contract checks before production mutation is authorized.
7. Production preflight: validate startup preflight, production safety gate, upload safety, provider safety, topic-domain safety, runtime isolation, health, observability, and rollback readiness.
8. Deployment: production activation remains governed by the immutable release implementation and runbook; this contract does not authorize or execute deployment by itself.
9. Verification: verify the active release against immutable journal evidence by deployment ID.
10. Smoke validation: confirm no-upload smoke or the approved current smoke package and the production safety smoke evidence required by the readiness checklist and safety runbook.
11. Acceptance window: classify the deployment as provisional until the governance acceptance window completes.
12. Final acceptance: mark final acceptance only after required verification, smoke evidence, and observation evidence are complete.
13. Rollback conditions: authorize rollback when immutable release verification, production health, safety gates, smoke validation, runtime integrity, upload safety, or cross-channel safety fail in a way that cannot be corrected without reverting the active release.

## 7. Source Validation Requirements

The deployment source must be clean and must resolve to the exact reviewed SHA. The immutable release runbook states that deployment Git operations use `DEPLOY_SOURCE_ROOT`, and that an active release is runtime evidence and rollback context rather than a cleanliness boundary.

Required source evidence:

- current branch or detached state
- local HEAD SHA
- target ref SHA
- parity between the expected deployment SHA and the approved source ref
- clean status for the deployment source checkout
- no local-only target commit for deployment release materialization
- no unrelated staged, unstaged, deleted, renamed, or untracked files in the deployment source

When the primary worktree contains unrelated work, deployment validation must use a clean isolated worktree at the exact source SHA. This preserves the dirty primary worktree and prevents unrelated local files from becoming deployment evidence.

## 8. Production Readiness Requirements

Production readiness is mandatory before production activation. The readiness checklist identifies build and test gates, scheduler and pipeline gates, infrastructure and credential gates, external provider and fallback gates, operability and safety gates, rollback readiness, incident readiness, and post-release verification.

Mandatory readiness requirements for PROJECT004:

- scheduler health is OK
- scheduler PID and command identity are correct when validating a running production scheduler
- runtime build information is visible where production logs expose it
- lock and queue race hardening is present or mitigated
- upload credentials are validated before upload-capable production operation
- required API keys and tokens are available to production without exposing secret values
- disk and quota budget are sufficient for planned operation
- live analytics collector remains disconnected from the production pipeline unless its governance gate is approved
- telemetry sink, error classification, alerting route, and runbook links are ready
- rollback plan, rollback owner, last known good version, and data/state implications are reviewed
- incident commander and escalation path are assigned when the deployment is production-facing

Production readiness does not replace immutable release validation. It is an additional mandatory gate.

## 9. Startup Preflight Requirements

Startup preflight is mandatory. The immutable release implementation records and executes staged scheduler startup preflight from the release working directory with preprod isolation enabled.

The preflight contract uses isolated mutable paths and disables production side effects by setting preprod isolation and disabling scheduling, uploads, Shorts uploads, live collector behavior, and YouTube Analytics API mutation during the staged check. It redirects scheduler log, queue, PID, singleton lock, runtime evidence, safety gate, activation, governance, dashboard, production events, observability, and job store paths under the preprod state root.

`tests/test_scheduler_cli.py`, `tests/test_preprod_isolation_paths.py`, and `tests/test_preprod_validation_runner.py` are blocking because they protect this startup preflight and isolation contract.

## 10. Smoke Validation Requirements

Smoke validation is mandatory. The production readiness checklist requires targeted smoke tests and a no-upload smoke requirement. The PROJECT003 production safety runbook defines the normal state as startup preflight passing, production safety gate returning allowed or warning, smoke command returning PASS, upload precheck returning allow, analytics append avoiding guard rejection, and no active deployment lock outside planned deployment windows.

Smoke validation evidence must distinguish:

- pre-cutover no-upload smoke or approved current smoke package
- production safety smoke schema evidence
- post-deployment smoke behavior during the observation period
- failures that require rollback from warnings that require monitoring

Smoke validation does not permit bypassing upload safety or provider safety.

## 11. Historical Analytics Policy

The following files belong to historical analytics validation governance:

- `artifacts/latest/project002_sprint1e_phase4b_studio_export_learning/assessment_summary.json`
- `logs/channel_performance.jsonl`
- `logs/canonical_content_analytics.jsonl`

Ownership: These files are owned by Phase4B and Phase4C analytics governance. They are not owned by immutable deployment activation.

Purpose: Phase4C uses the Phase4B assessment summary, the first 788 rows of `logs/channel_performance.jsonl`, and canonical analytics rows filtered by the frozen source hash to reconstruct unresolved historical analytics rows.

Generation: The Phase4B and Phase4C documents state that their precondition checks are read-only and do not generate, backfill, copy, or rewrite historical analytics inputs.

Consumption: `tests/conftest.py` only triggers the Phase4B precondition gate when Phase4C baseline-dependent tests are collected. The gate exits with `PHASE4B ENVIRONMENT PRECONDITION FAILED` when historical inputs are missing or inconsistent.

Deployment boundary: These files do not belong to deployment validation because `deploy/deploy.sh`, `deploy/internal/immutable_release_v2_impl.sh`, the immutable release runbook, and the production readiness checklist do not require them for plan, prepare, cutover, verify, rollback, startup preflight, or smoke validation.

Mandatory condition: Historical analytics files become mandatory when running Phase4B or Phase4C validation, or when a deployment explicitly changes the relevant analytics contracts, unresolved analytics recovery behavior, frozen baseline reconstruction, or analytics precondition checker behavior.

## 12. Deployment Success Criteria

Successful deployment means the approved source SHA passes required deployment validation, immutable release activation completes under the immutable release implementation, a deployment journal is written, the active release matches the target deployment journal, production health verification passes, and rollback evidence remains available.

Successful smoke validation means the required no-upload or approved current smoke package passes, the production safety smoke evidence is valid, upload safety remains enforced, and no smoke failure indicates unsafe render, upload, scheduler, provider, topic-domain, or cross-channel behavior.

Successful production verification means the active release identity, release metadata, scheduler health, safety gate state, production health, and observability evidence are consistent with the deployed SHA and do not expose a rollback condition.

Successful acceptance means deployment status has moved from provisional to accepted after the governance acceptance window, with required smoke evidence, production verification evidence, and observation evidence complete.

## 13. Deployment Failure Criteria

Deployment blockers:

- dirty deployment source checkout
- source SHA does not match the approved target SHA
- non-full target SHA
- target ref/SHA mismatch
- local-only target commit
- required BLOCKING test failure
- immutable release plan, prepare, cutover, deploy, verify, or rollback contract failure
- missing or inconsistent release metadata
- deployment lock conflict in a mutating phase
- staging collision or unsafe release root/symlink target
- exported runtime payload under `logs/` or `output/` that fails provenance or safety checks
- missing persistent asset required by immutable release preparation
- startup preflight failure that is not an explicitly documented optional warning
- production readiness NO-GO
- rollback readiness failure

Runtime blockers:

- scheduler startup preflight failure
- production safety gate blocked state
- duplicate scheduler state that is not stale metadata
- upload precheck blocked state for upload-capable operation
- provider circuit or overload condition that blocks production operation
- terminal topic-domain block that would otherwise render or upload content
- release integrity mismatch
- writable path, disk, clock, queue, or credential failure that blocks safe production operation
- smoke failure indicating unsafe production behavior

Analytics blockers:

- Phase4B environment not prepared when Phase4B or Phase4C historical validation is in scope
- Phase4B environment inconsistent when Phase4B or Phase4C historical validation is in scope
- missing or inconsistent `assessment_summary.json`, `logs/channel_performance.jsonl`, or `logs/canonical_content_analytics.jsonl` when analytics validation is in scope
- unresolved analytics recovery invariant failure when analytics recovery is in scope

Documentation blockers:

- deployment contract contradicts deploy implementation
- deployment contract references nonexistent deployment tests or files
- deployment contract makes unsupported production, rollback, scheduler, pipeline, or analytics claims
- runbook references are stale enough to prevent a maintainer from determining the official deployment gate

## 14. Rollback Policy

Rollback behavior is unchanged by this contract. The immutable release runbook defines rollback as an immutable release operation that restores the previous release by deployment ID. The deployment journal records the prior release SHA, and rollback resolves that SHA from the completed deployment journal.

Canonical rollback properties:

- rollback is a separate transaction with its own deployment ID, journal, and events
- rollback acquires the deployment lock before mutating the active symlink or service
- rollback performs atomic symlink restoration
- rollback restarts the approved service only in rollback mode
- rollback verifies post-switch health
- rollback failure is finalized with failed journal evidence and non-zero exit behavior
- explicit rollback SHA remains a deprecated compatibility path, not the preferred operator path

Cutover automatic rollback remains disabled by default and requires explicit `--auto-rollback`. Without automatic rollback, failed cutover requires explicit operator diagnosis and separate rollback authorization.

## 15. Operator Responsibilities

Pre-deployment responsibilities:

- verify primary repository state, remote parity, source SHA, and worktree cleanliness
- use a clean isolated worktree when unrelated primary worktree changes exist
- verify exact deployment-related test paths before referencing them in release evidence
- run the BLOCKING deployment validation test set
- complete production readiness review
- confirm rollback owner, incident owner, and escalation path

Deployment responsibilities:

- use the canonical immutable release entrypoint and modes documented by the immutable release runbook
- preserve deployment source cleanliness
- preserve runtime isolation and secret handling rules
- capture immutable release transaction evidence, deployment ID, preflight evidence, and verification evidence
- do not bypass production safety gates, upload safety, scheduler locks, deployment locks, or provider/topic-domain guardrails

Post-deployment responsibilities:

- verify active release identity by deployment ID
- collect smoke validation evidence
- monitor production health, scheduler state, upload safety, provider state, topic-domain guardrails, observability, and incident signals
- keep deployment status provisional until acceptance evidence is complete

Acceptance responsibilities:

- evaluate the governance acceptance window
- record final acceptance only after verification, smoke, and observation evidence are complete
- avoid claiming VALIDATED or accepted status from tests alone when runtime observation evidence is required

Incident handling responsibilities:

- capture evidence before removing locks or changing runtime state
- follow rollback decision criteria when release integrity, safety gates, smoke validation, upload safety, or cross-channel safety fail
- treat rollback as an explicit production operation governed by the immutable release runbook

## 16. Acceptance and 24-Hour Observation Policy

The production baseline defines the operational workflow as `feature -> tests -> push -> deploy -> smoke validation -> production soak -> archive`. The readiness checklist defines post-release verification for the first 30-60 minutes, including first scheduled run completion, upload success ratio, experiment trace completeness, daily metrics coverage, validation failures, provider failures, and dashboard/log normality.

For PROJECT004, a 24-hour observation period is an acceptance governance policy. It is not an implementation requirement encoded in `deploy/deploy.sh` or `deploy/internal/immutable_release_v2_impl.sh` at the reviewed SHA.

During the acceptance window, deployment status is provisional. Final acceptance requires completed deployment verification, smoke validation, production health evidence, observability evidence, and no unresolved rollback condition. If rollback criteria are met during the acceptance window, the deployment does not reach final acceptance.

## 17. Relationship to Existing Documents

`docs/IMMUTABLE_RELEASE_V2_RUNBOOK.md`: Defines immutable release architecture, public entrypoint, supported modes, deployment source boundary, transaction artifacts, production contract, preflight artifact, locking behavior, verify behavior, rollback behavior, auto-rollback behavior, failure classes, and operator evidence. This contract relies on it for deployment implementation behavior.

`docs/production_readiness_checklist.md`: Defines production release go/no-go readiness requirements, including build/test gates, scheduler/pipeline gates, infrastructure and credential gates, provider and fallback gates, operability and safety gates, rollback readiness, incident readiness, and post-release verification.

`docs/PRODUCTION_BASELINE_v1.md`: Defines baseline repository architecture and production contracts: runtime isolation, deployment rollback, upload safety, incident lifecycle, observability, provider guardrails, and the workflow from feature through production soak and archive.

`docs/PROJECT003_SPRINT11_PRODUCTION_SAFETY_RUNBOOK.md`: Defines startup preflight, safety check, smoke command, deployment-lock inspection, release-integrity inspection, duplicate scheduler handling, rollback decision criteria, evidence capture, and the warning not to bypass safety gates.

`docs/PROJECT_003_POST_CLEAN_HEALTH_BASELINE.md`: Records historical static health evidence, including targeted production verification, production-safety/scheduler/upload baseline, and a prior full repository suite result. This is evidence of repository health, not an unconditional deployment gate.

`docs/PROJECT_002_SPRINT1E_PHASE4B_STUDIO_EXPORT_LEARNING.md`: Defines Phase4B analytics learning scope and the Phase4C precondition gate. It states that Phase4C depends on frozen historical Phase4B state and that the checker is read-only and does not generate, backfill, copy, or rewrite historical analytics inputs.

`docs/PROJECT_002_SPRINT1E_PHASE4C_UNRESOLVED_ANALYTICS_RECOVERY.md`: Defines Phase4C unresolved analytics recovery scope, frozen input, reconstruction rule, precondition lifecycle, and historical analytics safety invariants.

## 18. Future Maintenance

This contract should be updated when repository evidence changes one of the governed surfaces: deploy implementation, immutable release runbook, production readiness checklist, production baseline, production safety runbook, deployment-related tests, or Phase4B/Phase4C analytics policy.

New deployment tests are added to the BLOCKING set when they protect immutable release mechanics, deployment source integrity, cutover, verify, rollback, startup preflight, production readiness, production safety, scheduler singleton behavior, upload safety, provider safety, topic-domain safety, smoke validation, or acceptance-critical observability.

New tests are classified as RECOMMENDED when they provide adjacent confidence but do not block deployment unless their component is in scope. They are OPTIONAL when they are useful operator evidence but not required for a deployment decision. They are NOT DEPLOYMENT RELATED when they protect unrelated feature, research, analytics, or broad regression behavior.

Historical analytics validation evolves under Phase4B and Phase4C governance. If future deployments change analytics baseline files, frozen reconstruction rules, analytics precondition checks, unresolved analytics recovery, or analytics promotion criteria, the relevant analytics tests become deployment blockers for that scoped deployment. Otherwise, their failures remain analytics blockers rather than PROJECT004 deployment blockers.

Any future contract change must preserve repository evidence labels, avoid unsupported production claims, verify referenced paths exist, and keep deployment validation distinct from historical analytics validation, CI validation, research validation, and broad regression validation.