# IMMUTABLE RELEASE V2 RUNBOOK

Status: IMPLEMENTED_NOT_EXECUTED

## 1) Architecture

`deploy/immutable_release_v2.sh` implements a config-preserving immutable release workflow with four modes:

- `plan`: read-only validation and operation preview
- `prepare`: build immutable release directory for exact Git SHA
- `cutover`: atomically switch `/opt/parapusulasi-current` and restart `parapusulasi`
- `rollback`: atomically switch back to an explicit prior release SHA and restart `parapusulasi`

Automatic rollback policy:

- Default is disabled for cutover (`AUTO_ROLLBACK=false`).
- Automatic rollback is enabled only with explicit `--auto-rollback`.
- Rollback metadata capture remains standard cutover bookkeeping.

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

### Deployment Source Checkout Boundary

Previous architecture treated the shell's current Git worktree as both the deployment tool source and the cleanliness boundary. When operators launched from `/opt/parapusulasi-current`, the active release repository was checked with `git status --porcelain`. That was unsafe because the active release is runtime state: it intentionally contains `logs` and `output` symlinks, generated `deployment_preflight.json`, and runtime report artifacts.

Current architecture separates those roles:

1. The active release is read-only runtime evidence and rollback context.
2. Deployment Git operations use `DEPLOY_SOURCE_ROOT`, a clean deployment source checkout.
3. If `IMMUTABLE_V2_DEPLOY_SOURCE_ROOT` is set, that configured checkout must be clean and is used as the source of target refs and release materialization.
4. If the script is launched from a normal non-active checkout, that checkout must be clean and becomes `DEPLOY_SOURCE_ROOT`.
5. If the script is launched from the active release, the script creates a temporary clean deployment source checkout under `${DEPLOY_STATE_ROOT}/deploy-source-worktrees`, copies local deployment refs when the source is local, uses that checkout for plan/prepare/cutover validation, and removes the temporary checkout on exit.

Runtime symlinks no longer block `plan` or `prepare` because cleanliness is asserted only for the deployment source checkout. The active release may be dirty relative to Git due to runtime-owned paths, but it is never used as the deployment worktree.

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
   - staged-release preflight runs `scheduler.py --health-check` from staged release CWD with isolated mutable-path env overrides
   - local release-build failures remain blocking
   - optional external DNS resolution warnings may be recorded without blocking prepare
   - preflight is executed from staged release working directory (`.staging-<sha>` during prepare)
   - exported `logs/` and `output/` payload is provenance-checked and removed from staging before shared-root symlinks are created
9. Cutover contract:
   - lock acquisition
   - rollback target capture
   - atomic symlink replacement
   - bounded post-switch health loop
   - post-switch health loop uses the same isolated preprod state root contract as prepare preflight (`PREPROD_ISOLATION_MODE=true` plus `PREPROD_STATE_ROOT` and the mutable path redirects required by scheduler preprod isolation)
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
   [--auto-rollback] \
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

# Optional: enable automatic rollback for cutover
bash deploy/immutable_release_v2.sh \
   --target-ref origin/release/analytics-readonly-smoke-68529058 \
   --target-sha 849fc57265395889fc23dde2986b21428ef03c6c \
   --mode cutover \
   --auto-rollback

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
- per-path classification, action (`existed|created|optional|blocked`), and pass/fail status
- staged health evidence: command, cwd, stdout, stderr, warnings

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
- prepare bootstraps `${SHARED_ROOT}/runtime/output/scripts`, `${SHARED_ROOT}/runtime/output/audio`, `${SHARED_ROOT}/runtime/output/videos` when missing (directory-only, no content write)
- `assets` must exist from immutable release payload; missing `assets` remains fail-closed
- `assets/backgrounds`, `assets/music`, `assets/fonts` are prepare-bootstrapped inside invocation-owned staging when absent

Git empty-directory note:

- Git does not preserve empty directories in commit trees.
- V2 therefore treats the runtime/asset subdirectories above as prepare-time bootstrap targets, not packaged-file requirements.
- No `.gitkeep` or placeholder file injection is required for immutable prepare.

Allowed directory bootstrap list (prepare mode only):

- shared runtime output children: `scripts`, `audio`, `videos`
- staged release asset children: `assets/backgrounds`, `assets/music`, `assets/fonts`

Bootstrap guardrails:

- plan mode and dry-run never mutate filesystem state
- bootstrap validates approved roots and exact relative paths
- bootstrap never deletes existing content and never rewrites ownership/permissions on existing directories
- active release and finalized release are never bootstrap targets

Staged scheduler health contract:

- command runs from staged release CWD, never from the active release CWD
- mutable scheduler/runtime artifact env paths are redirected to an isolated preprod-health state root under deploy-state
- prepare health remains read-only for service state, uploads, OAuth, Analytics, and YouTube mutations
- stdout/stderr are captured into preflight evidence
- `Unable to resolve youtube.googleapis.com ...` is treated as an optional warning during prepare preflight, not a blocking failure
- all other scheduler health failures remain blocking

## 7) Locking Behavior

A lock-holder marker prevents concurrent mutation attempts.
Default lock path:

- `/opt/parapusulasi/deploy.lock`

Active lock representation:

- `/opt/parapusulasi/deploy.lock/.active_lock/`
- owner metadata file: `/opt/parapusulasi/deploy.lock/.active_lock/owner.json`

Lock semantics:

- If `.active_lock` exists, cutover/rollback/prepare abort with `lock exists`.
- If `deploy.lock` exists but is empty, it is treated as unlocked.
- On lock release, `.active_lock` is removed; pre-provisioned `deploy.lock` directories are preserved.

## 8) Auto-Rollback Behavior

If cutover fails after switch attempt and `--auto-rollback` is enabled, V2 restores previous symlink target and restarts service.
If cutover fails after switch attempt and `--auto-rollback` is not enabled, V2 does not perform automatic rollback and exits non-zero for explicit operator diagnosis.
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
- redacted prepare failure report is written atomically under deploy-state
- failure report records target ref/SHA, operator-tool SHA, failed phase, exit code, sanitized summary, staging path, and active release SHA
- prepare failure releases any acquired deployment lock before exiting with the original non-zero code
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

Operational warning for no-auto-rollback cutover failures:

- When cutover fails after symlink switch and `--auto-rollback` is not set, inspect active target and service state before deciding and authorizing a separate rollback command.

## 12) Explicit Non-Claims

- This runbook does not assert any deployment occurred.
- This runbook does not authorize production mutation by itself.
- This runbook does not include or expose secret values.
