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
   - runtime directories (`output`, `logs`)
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

No secrets are stored.

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
- insufficient disk
- missing persistent asset
- unknown asset classification
- import or health-check failure
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
