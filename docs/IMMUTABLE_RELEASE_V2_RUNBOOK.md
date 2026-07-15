# IMMUTABLE RELEASE V2 RUNBOOK

Status: IMPLEMENTED_NOT_DEPLOYED

## 1) Architecture

`deploy/immutable_release_v2.sh` implements a config-preserving immutable release workflow with four modes:

- `plan`: read-only validation and operation preview
- `prepare`: build immutable release directory for exact Git SHA
- `cutover`: atomically switch `/opt/parapusulasi-current` and restart `parapusulasi`
- `rollback`: atomically switch back to an explicit prior release SHA and restart `parapusulasi`

The stable runtime contract is preserved:

- ExecStart: `/opt/parapusulasi-current/venv/bin/python /opt/parapusulasi-current/scheduler.py`
- WorkingDirectory: `/opt/parapusulasi-current`

No systemd unit or drop-in mutation is performed.
No `.env` content editing is performed.

Bootstrap prerequisite:

- `/opt/parapusulasi-shared` must already be provisioned.
- Required shared paths for prepare:
   - `/opt/parapusulasi-shared/.env`
   - `/opt/parapusulasi-shared/logs`
   - `/opt/parapusulasi-shared/runtime/output`
   - `/opt/parapusulasi-shared/state/youtube_playlists.json`
   - `/opt/parapusulasi-shared/state/channel_registry.json`
   - `/opt/parapusulasi-shared/state/channels_tracker.csv`

Status remains: `IMPLEMENTED_NOT_DEPLOYED`.

Git history may still contain runtime-owned evidence payload under `logs/` and `output/`. Prepare sanitizes only the invocation-owned staging export before persistent linking; the final prepared release must not ship Git-exported runtime payload in those paths.

## 2) Threat Model And Prohibitions

The workflow is fail-closed and rejects unsafe deployment attempts.

Explicitly forbidden:

- writing under `/etc/systemd/system`
- `systemctl edit`
- `daemon-reload`
- `.env` appends/edits
- token regeneration or OAuth flow execution
- direct copy of secret content into Git-controlled deployment payload

Allowed service operation only in `cutover` and `rollback`:

- `systemctl restart parapusulasi`

## 3) Production Contract

Repository-discovered contract (read-only evidence from docs/scripts):

1. Immutable Git-controlled content:
   - release payload extracted from exact target SHA under `/opt/parapusulasi/releases/<sha>`
2. Persistent external runtime content:
   - `.env`
   - root/channel credential files and token files
   - runtime queues, logs, runtime state
   - channel registry/tracker and similar runtime governance files
3. Files linked into release (no content copy):
   - `.env`
   - token/secret files (root and channel local where present)
   - runtime directories (`output`, `logs`) linked from shared root in prepared release
   - channel registry/tracker and playlist metadata when externalized
4. Files copied metadata-only:
   - not used by default; linking strategy is preferred to preserve ownership/content
5. Files never copied:
   - secret-bearing token and client-secret contents
6. Files never modified:
   - `/etc/systemd/system/**`
   - service drop-ins
   - production `.env` values
7. Ownership/permission expectations:
   - deployment expects existing runtime ownership to remain authoritative for linked assets
8. Health-check contract:
   - scheduler import and uploader import must pass
   - optional wrapper import validation when file exists
   - scheduler `--health-check` must pass unless explicitly skipped in controlled test mode
   - preflight is executed from staged release working directory (`.staging-<sha>` during prepare)
   - exported `logs/` and `output/` payload is provenance-checked and removed from staging before shared-root symlinks are created
9. Cutover contract:
   - lock acquisition
   - rollback target capture
   - atomic symlink replacement
   - bounded post-switch health loop
10. Rollback contract:
    - explicit rollback SHA required
    - atomic symlink restoration
    - service restart and health verification

## 4) Persistent Asset Classification

Current V2 classifier categories:

- `IMMUTABLE_SOURCE`
- `EXTERNAL_PERSISTENT`
- `RELEASE_SYMLINK`
- `RELEASE_COPY_METADATA_ONLY`
- `RUNTIME_GENERATED`
- `PROHIBITED_SECRET`
- `UNKNOWN_BLOCKER`

Default handled set:

- `.env` -> `PROHIBITED_SECRET | RELEASE_SYMLINK`
- token/secret files (root + `channels/*`) -> `PROHIBITED_SECRET | RELEASE_SYMLINK`
- `logs`, `output*` -> `RUNTIME_GENERATED | RELEASE_SYMLINK`
- `channels/channel_registry.json`, `channels/channels_tracker.csv`, `youtube_playlists.json` -> `EXTERNAL_PERSISTENT | RELEASE_SYMLINK`

Prepare sanitization rule:

- if `logs/` or `output/` is exported from Git into invocation-owned staging, prepare must verify every file in that tree is attributable to the target Git tree before removing the exported copy
- unexpected staging entries under `logs/` or `output/` fail closed
- a correct pre-existing shared-root symlink for `logs/` or `output/` remains idempotent and is not deleted

Prepared-release runtime-link contract:

- `<prepared-release>/output` -> `${SHARED_ROOT}/runtime/output`
- `<prepared-release>/logs` -> `${SHARED_ROOT}/logs`
- Active release must never be edited in place by `prepare`.

Path distinction (must not be conflated):

- `/opt/parapusulasi/output` is a root compatibility path.
- `/opt/parapusulasi-current/output` points to the active immutable release path.
- `/opt/parapusulasi/releases/<sha>/output` in a newly prepared release must be a shared-root symlink.
- Same distinction applies to `logs`.

Any unclassified secret-like file results in `UNKNOWN_BLOCKER` and abort.

## 5) CLI

```bash
deploy/immutable_release_v2.sh \
  --target-ref <remote-branch-or-tag> \
  --target-sha <full-sha> \
  --mode plan|prepare|cutover|rollback \
  [--rollback-sha <full-sha>] \
  [--dry-run]
```

Examples:

```bash
# Read-only plan
bash deploy/immutable_release_v2.sh \
  --target-ref origin/release/analytics-readonly-smoke-68529058 \
  --target-sha 849fc57265395889fc23dde2986b21428ef03c6c \
  --mode plan

# Prepare immutable release (no symlink switch)
bash deploy/immutable_release_v2.sh \
  --target-ref origin/release/analytics-readonly-smoke-68529058 \
  --target-sha 849fc57265395889fc23dde2986b21428ef03c6c \
  --mode prepare

# Dry-run cutover preview (no mutation)
bash deploy/immutable_release_v2.sh \
  --target-ref origin/release/analytics-readonly-smoke-68529058 \
  --target-sha 849fc57265395889fc23dde2986b21428ef03c6c \
  --mode cutover \
  --dry-run

# Rollback to explicit SHA
bash deploy/immutable_release_v2.sh \
  --target-ref origin/release/analytics-readonly-smoke-68529058 \
  --target-sha 849fc57265395889fc23dde2986b21428ef03c6c \
  --mode rollback \
  --rollback-sha 68529058e386661d19eaa2dfe510523d7c6cd47a
```

## 6) Preflight Artifact

Prepare mode writes:

- `<release>/deployment_preflight.json`

Contains:

- release SHA
- target ref
- UTC timestamp
- validation names and pass/fail statuses
- resolved path evidence for required runtime and asset paths
- per-path classification and pass/fail status

No secrets are stored.

Prepare sequence for runtime-owned payload:

1. Export exact target SHA into invocation-owned staging.
2. Provenance-check exported `logs/` and `output/` trees against the target Git tree.
3. Remove only the exported staging copies of `logs/` and `output/`.
4. Create or verify shared-root symlinks to `${SHARED_ROOT}/logs` and `${SHARED_ROOT}/runtime/output`.
5. Continue preflight from the staged release working directory.

Preflight validates before scheduler health-check:

- `output` resolves to `${SHARED_ROOT}/runtime/output`
- `logs` resolves to `${SHARED_ROOT}/logs`
- `output/scripts`, `output/audio`, `output/videos` exist under shared runtime output
- `assets`, `assets/backgrounds`, `assets/music`, `assets/fonts` exist in staged release

## 7) Locking Behavior

A lock directory prevents concurrent mutation attempts.
Default lock path:

- `/opt/parapusulasi/deploy.lock`

If lock exists, cutover/rollback abort.

## 8) Auto-Rollback Behavior

If cutover fails after switch attempt, V2 restores previous symlink target and restarts service.
Failure remains non-zero and rollback metadata is preserved under deploy-state.

## 9) Failure Classes

Common fail-closed blockers:

- target ref/SHA mismatch
- unapproved target ref
- non-full SHA
- local-only commit
- missing releases root/current symlink
- symlink target outside approved release root
- staging collision
- non-empty staging `output` or `logs` directory (fail-closed, no deletion)
- Git-exported runtime-owned payload under `logs/` or `output/` is removed only after provenance verification; unexpected entries remain fail-closed
- runtime symlink target mismatch in staging
- insufficient disk
- missing persistent asset
- unknown asset classification
- import or health-check failure

Prepare cleanup guarantees on failure:

- cleanup is guarded and invocation-owned only
- only `.staging-<target-sha>` created by current invocation may be removed
- finalized release directories are never removed
- active release target is never removed
- shared-root content is never removed
- redacted prepare failure report is written under deploy-state
- missing prepared release for cutover
- missing rollback target release
- concurrent lock present

## 10) Audit Evidence To Capture During Real Operation

- `deployment_preflight.json` from prepared release
- deploy-state rollback metadata
- symlink target before/after
- service restart timestamps and status
- bounded health loop result

## 11) Recovery Commands

- Inspect active target:

```bash
readlink -f /opt/parapusulasi-current
```

- Inspect release existence:

```bash
ls -la /opt/parapusulasi/releases/<sha>
```

- Controlled rollback with explicit SHA:

```bash
bash deploy/immutable_release_v2.sh \
  --target-ref origin/release/analytics-readonly-smoke-68529058 \
  --target-sha 849fc57265395889fc23dde2986b21428ef03c6c \
  --mode rollback \
  --rollback-sha 68529058e386661d19eaa2dfe510523d7c6cd47a
```

## 12) Explicit Non-Claims

- This runbook does not assert any deployment occurred.
- This runbook does not authorize production mutation by itself.
- This runbook does not include or expose secret values.
