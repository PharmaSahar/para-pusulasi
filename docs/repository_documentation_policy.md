# Repository Documentation Policy

Effective date: 2026-07-13
Scope: this policy governs where documentation, evidence, validation output, and temporary analysis belong in this repository.

## Purpose

The repository must stay organized so that current operational material is easy to find, historical evidence is preserved, and temporary work does not leak into the active surface.

This policy is mandatory for all future documentation work.

## 1. Active Operational Documents

### What belongs in `docs/`
`docs/` is for living operational references that are part of the current working set and are meant to be found by humans during normal operation.

Examples of acceptable content:
- Architecture overviews that describe the active system design.
- Current ADRs and current runbooks.
- Current contracts and policy documents.
- Current release-facing documentation.
- Operational guides that describe how the system is expected to run now.
- Active checklists that are still used during release, rollout, or operations.

### What belongs in `artifacts/latest/`
`artifacts/latest/` is for the current operational snapshots and the newest authoritative generated outputs.

Examples of acceptable content:
- Current production dashboard snapshots.
- Current governance/readiness snapshots.
- Current cleanup report.
- Current production contract freeze documents.
- Current runtime or validation snapshots that are still actively referenced.

Rules:
- `artifacts/latest/` may contain only current operational references.
- It must not become a general evidence bucket.
- When a document stops being operational, it must be archived.

### What must always stay in the repository root
The repository root is reserved for top-level entrypoints and enduring repository metadata.

Examples:
- `README.md`
- `CHANGELOG.md`
- `CONTRIBUTING.md`
- `DEVELOPMENT.md`
- `pytest.ini`
- `requirements.txt`
- `scheduler.py`
- `main.py`
- other root-level application entrypoints and canonical repository guidance

Rules:
- Root-level files should be rare.
- Root-level documentation should be stable and broadly relevant.
- Generated or transient reports do not belong in the root.

## 2. Historical Documents

### What goes to `docs/archive/`
`docs/archive/` is for historical documentation that was once active but is no longer part of normal operations.

Examples:
- Completed design notes.
- Completed historical investigations.
- Retired planning notes.
- Finished postmortems and retrospective summaries that are no longer current operational references.
- Completed reports that describe a past project state.

Rules:
- No completed investigation remains in `docs/`.
- Once a document is historical, it must move to `docs/archive/`.
- Archived docs must never be edited to simulate current state.

### What goes to `archive/YYYY-MM-<project>/`
Top-level `archive/YYYY-MM-<project>/` is for completed project evidence bundles.

Examples:
- Validation reports.
- Deployment reports.
- Incident bundles.
- Telemetry exports.
- Investigation bundles.
- Temporary test evidence from a completed project.

Rules:
- Archive by project or workstream when the body of evidence is complete.
- Use a dated project folder name that reflects the archival wave.
- Preserve original context in the archive tree.
- Every archive operation must update `archive/ARCHIVE_INDEX.md`.

## 3. Investigations

Temporary investigations belong in the active working area only while they are in progress.

Acceptable temporary locations:
- `artifacts/latest/` while the investigation is still the current working reference.
- A dedicated project archive folder once the investigation is complete.
- A temporary test harness under `tests/` or `ops/` only if it is an explicit, reviewed diagnostic asset.

When to archive investigations:
- After the investigation conclusion is validated.
- After the investigation is no longer the current active reference.
- After the findings are summarized into a durable report.

Rules:
- No completed investigation remains in `docs/`.
- No investigation evidence should linger in the active surface once the investigation is done.
- Keep only the canonical summary in active docs; move evidence bundles to archive.

## 4. Validation Reports

### Naming convention
Validation documents must use one of these patterns:
- `*_validation.md`
- `*_validation.txt`
- `*_validation.json`
- `*_validation.jsonl`

Use a descriptive prefix that reflects the scope, such as:
- `production_contract_validation.md`
- `observability_fail_open_validation.json`
- `runtime_storage_validation_evidence.txt`

### Retention policy
- Keep current validation snapshots in `artifacts/latest/` only while they remain operational references.
- Keep finished validation reports in the project archive.
- If a validation report is superseded, archive the prior copy rather than overwriting history.

### Archive policy
- Archive after project completion.
- Archive after release when the validation is no longer the current operational reference.
- Validation evidence used for current operations may remain in `artifacts/latest/` only if it is still actively referenced.

## 5. Deployment Reports

Deployment reports describe rollout, predeploy, postdeploy, smoke, rollback, and release verification activity.

Rules:
- Current deployment references may live in `artifacts/latest/` only when they are the active operational snapshot.
- Completed deployment evidence belongs in `archive/YYYY-MM-<project>/deployment/` or the equivalent project archive bucket.
- Deployment reports should not remain in `docs/` unless they are part of active operational guidance.

Examples:
- `predeploy_validation.md`
- `production_rollout_plan.md`
- `final_vps_deployment_report.md`
- `push_verification.md`

## 6. Incident Reports

Incident reports capture failures, root cause analysis, recovery plans, and incident lifecycles.

Rules:
- Current incident state may be reflected in operational snapshots if needed.
- Completed incident narratives and evidence belong in archive.
- Incident forensics must not stay in `docs/` once the incident is closed.

Recommended archive destinations:
- `archive/YYYY-MM-<project>/incidents/`
- `archive/YYYY-MM-<project>/investigation/`

## 7. Telemetry Exports

Telemetry exports are machine-generated records intended for audit, validation, or replay.

Rules:
- If telemetry is current operational state, it may remain in `artifacts/latest/`.
- If telemetry is historical, it belongs in the project archive.
- Telemetry exports are append-only by default.
- Do not overwrite historical telemetry just to keep a path short.

Examples:
- JSONL traces.
- Dashboard write traces.
- Production events streams.
- Metrics snapshots.

## 8. Temporary Tests

Temporary tests are one-off repro scripts, diagnostic shell scripts, and short-lived harnesses that exist to validate a specific issue or state.

Rules:
- Keep them only while the investigation or fix is active.
- Once complete, archive them in the project archive.
- Do not leave completed repro scripts in the active surface if they are no longer needed.

Recommended archive destinations:
- `archive/YYYY-MM-<project>/temporary-tests/`
- `archive/YYYY-MM-<project>/reproduction/`

## 9. Experiments

Experiments are explicit trial artifacts used to compare behavior, variants, or policy choices.

Rules:
- Experimental outputs belong in archive when the experiment is finished.
- Active experiment definitions may remain in `docs/` only if they still define the current policy surface.
- Experimental evidence should be separate from canonical operational documentation.

Recommended archive destinations:
- `archive/YYYY-MM-<project>/experiments/`
- `archive/YYYY-MM-<project>/validation/` when the experiment is primarily a verification record.

## 10. Duplicate File Policy

Duplicates are allowed only when they serve a documented compatibility or rollout purpose.

Rules:
- Prefer one canonical active copy per document.
- If both a latest snapshot and a history copy must exist, the latest snapshot must be clearly named and the historical copy must be archived.
- Exact duplicates should be retained only when there is a deliberate compatibility reason.
- Obsolete copies should be archived, not left scattered across active directories.

Required action for duplicates:
- Inventory them.
- Assign one canonical owner.
- Document the recommendation in the archive index or cleanup report.

## 11. Retention Policy

### Keep forever
Keep forever when the file is a canonical repository anchor or a permanent historical record.

Examples:
- Root README and core repository guides.
- Current active contracts if they define the live operational baseline.
- Archived project evidence once moved into the archive.
- ADRs that define enduring design decisions.

### Archive after project completion
Archive after project completion for:
- Validation reports.
- Investigation bundles.
- Postmortems.
- Temporary tests.
- Experimental outputs.
- Historical snapshots no longer used operationally.

### Archive after release
Archive after release for:
- Release verification bundles.
- Rollout notes.
- Deployment smoke evidence.
- Postdeploy summaries.

### Safe to delete after explicit approval
Only the following may ever be deleted, and only after explicit approval:
- Temporary scratch files.
- Editor backup files.
- Obvious accidental duplicates that are not evidence and are not referenced anywhere.
- Throwaway files outside production, tests, docs, config, ops, and archive surfaces.

Default rule:
- When in doubt, archive rather than delete.

## 12. Directory Responsibilities

### `docs/`
Purpose: active documentation surface for current architecture, ADRs, runbooks, contracts, and operational guidance.

Rules:
- Keep it current.
- Remove completed investigations and historical reports from the active surface.
- Use `docs/archive/` for retired documentation.

### `archive/`
Purpose: permanent evidence store for completed work.

Rules:
- Store project-based archival bundles here.
- Preserve historical context.
- Update `archive/ARCHIVE_INDEX.md` whenever archive contents change.

### `artifacts/latest/`
Purpose: current operational snapshots and the newest generated references.

Rules:
- Keep only the latest operational version of a snapshot.
- Remove completed historical material from this surface by archiving it.
- Do not let it become a general history bucket.

### `artifacts/deployment/`
Purpose: deployment and release evidence bundle store.

Rules:
- Use for completed rollout and validation evidence.
- Keep release artifacts separate from active operational snapshots.
- Archive completed items at the end of the release wave.

### `artifacts/incidents/`
Purpose: incident evidence, forensic notes, and recovery materials.

Rules:
- Store incident bundles here while they are part of the active evidence set.
- Move completed incident bundles into the project archive when the incident is closed.
- Keep the evidence chain intact.

### `src/`
Purpose: production source code.

Rules:
- No documentation artifacts belong here.
- Do not use `src/` for reports, notes, or generated evidence.

### `tests/`
Purpose: automated test code and test-only fixtures.

Rules:
- Tests belong here only when they are executable and part of the validation suite.
- Reproduction scripts used as test assets belong here only if they are intentionally maintained.
- Do not store one-off evidence reports here.

### `ops/`
Purpose: operational tooling, maintenance scripts, and explicit admin utilities.

Rules:
- Keep operational scripts here.
- Do not store completed reports here.
- If a script is only a temporary diagnostic asset, archive it after the work is done.

### `config/`
Purpose: configuration and configuration-like runtime inputs.

Rules:
- Keep canonical configuration here.
- Do not place reports or evidence bundles here.
- Generated runtime manifest files must not be committed unless explicitly intended.

## 13. Future Rules

These rules are mandatory for future repository maintenance:

1. No completed investigation remains in `docs/`.
2. `artifacts/latest/` contains only current operational references.
3. Historical evidence must be archived after project completion.
4. Runtime-generated files must never be committed unless explicitly intended.
5. Every archive operation must update `archive/ARCHIVE_INDEX.md`.
6. Every cleanup pass must produce or update a cleanup report.
7. Every completed validation wave must have one canonical archived evidence bundle.
8. Temporary test harnesses must be either promoted to maintained tests or archived.
9. Duplicate files must be documented with a canonical-owner recommendation.
10. When retention is unclear, archive rather than delete.

## 14. Enforcement Notes

- This policy is descriptive and prescriptive: it defines where files belong and how they age out of active use.
- The repository may contain legacy material that predates this policy. That material should be normalized over time, not rewritten casually.
- Future cleanup work should be conservative and should preserve evidence history.
- Any exception to this policy must be documented in the relevant archive index or cleanup report.
