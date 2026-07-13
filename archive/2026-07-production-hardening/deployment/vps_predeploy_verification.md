# VPS Pre-Deploy Verification (Read-Only)

Generated at: 2026-07-12 20:42:12 UTC
Scope: Read-only verification only (no deploy/restart/remote mutation requested).
Decision model: GO / WAIT / NO-GO

## 1) Target Release Anchor (Local)

Command summary:
- `git rev-parse --abbrev-ref HEAD`
- `git rev-parse HEAD`
- `git rev-parse origin/master`
- `git log -4 --oneline`

Observed:
- Local branch: `master`
- Local HEAD: `c732427367d782f56c335e52dd063deaa8db3e0d`
- `origin/master`: `c732427367d782f56c335e52dd063deaa8db3e0d`
- Expected release chain:
  - `47a241e` fix: separate runtime storage and harden scheduler observability
  - `6224118` fix: quarantine terminal topic-domain blocks exactly once
  - `1097cc8` fix: harden content fallback and trend metadata contract
  - `c732427` chore: ignore generated runtime artifacts

Classification: PROVEN (local release anchor)

## 2) VPS Repository Identity and Drift Truth

Command summary:
- `git rev-parse --abbrev-ref HEAD`
- `git rev-parse HEAD`
- `git remote -v`
- `git branch -vv`
- `git status --short`
- `git diff --cached --name-status`
- `git ls-files --deleted | wc -l`

Observed:
- VPS branch: `build_identity_fix`
- VPS HEAD: `9de59809f8df6b2f020f9548a1346e781e2b4a8d`
- `git remote -v`: empty (no remote configured)
- `git branch -vv`: `* build_identity_fix 9de5980 fix: isolate production quality gates from unrelated tests`
- Staging area contains mass tracked deletions (`D ...`) across core repo files.
- Simultaneous untracked replacements (`?? ...`) for many of the same paths.
- `git ls-files --deleted` count is `0` (files exist in working tree), confirming an index/worktree mismatch pattern rather than missing filesystem files.

Impact:
- VPS is not on validated release commit `c732427`.
- VPS cannot be compared to `origin/master` because no remote is configured.
- Worktree/index state is unstable for safe deployment assumptions.

Classification: PROVEN (blocking mismatch/drift)

## 3) Service Runtime Snapshot

Command summary:
- `systemctl is-active parapusulasi`
- `systemctl show parapusulasi -p MainPID -p ActiveEnterTimestamp -p ExecStart`
- process snapshot via `ps ... | grep '(scheduler.py|ffmpeg)'`

Observed:
- Service state: `active`
- Main PID: `90873`
- ExecStart: `/opt/parapusulasi/venv/bin/python /opt/parapusulasi/scheduler.py`
- Active since: `2026-07-12 01:06:35 UTC`
- Active workload present (`scheduler.py` and `ffmpeg` processes visible).

Classification: PROVEN (service currently running)

## 4) Environment Readiness Matrix (Presence Metadata Only)

Command summary:
- `systemctl show parapusulasi -p Environment --value`
- `systemctl show parapusulasi -p EnvironmentFiles --value`
- `.env` presence and key-name checks only (no values printed)

Observed systemd sources:
- `Environment`: only `DISPLAY=:99`
- `EnvironmentFiles`: empty
- `.env` file: present

Required key matrix (`name|present|empty|source`):
- `ANTHROPIC_API_KEY|PRESENT|NON-EMPTY|.env`
- `OPENAI_API_KEY|PRESENT|NON-EMPTY|.env`
- `YOUTUBE_CLIENT_ID|PRESENT|NON-EMPTY|.env`
- `YOUTUBE_CLIENT_SECRET|PRESENT|NON-EMPTY|.env`
- `TELEGRAM_BOT_TOKEN|PRESENT|NON-EMPTY|.env`
- `YOUTUBE_TOKEN_FILE|MISSING|-|.env`
- `YOUTUBE_ANALYTICS_TOKEN_FILE|MISSING|-|.env`
- `CHANNEL_CONFIG_PATH|MISSING|-|.env`
- `RUNTIME_OUTPUT_ROOT|MISSING|-|.env`
- `PRODUCTION_DASHBOARD_MD_PATH|MISSING|-|.env`
- `PRODUCTION_DASHBOARD_JSON_PATH|MISSING|-|.env`
- `PRODUCTION_OBSERVABILITY_LATEST_PATH|MISSING|-|.env`
- `GOVERNANCE_READINESS_MD_PATH|MISSING|-|.env`
- `INCIDENT_STATE_FILE|MISSING|-|.env`
- `INCIDENT_EVENTS_FILE|MISSING|-|.env`
- `INCIDENT_METRICS_FILE|MISSING|-|.env`
- `SCHEDULE_ENABLED|PRESENT|NON-EMPTY|.env`
- `UPLOAD_ENABLED|MISSING|-|.env`
- `SHORTS_UPLOAD_ENABLED|MISSING|-|.env`
- `PREPROD_ISOLATION_MODE|MISSING|-|.env`

Classification: REPORTED/PROVEN (presence evidence captured; many required keys absent)

## 5) Runtime Path Contract and Filesystem Readiness

Command summary:
- VPS path constants grep from `src/production_quality_platform.py`
- Runtime directory/permission checks under `/opt/parapusulasi`

Observed code constants on VPS:
- `PRODUCTION_OBSERVABILITY_LATEST_PATH = Path("logs/production_observability_latest.json")`
- `PRODUCTION_DASHBOARD_JSON_PATH = Path("logs/production_dashboard_latest.json")`
- `PRODUCTION_DASHBOARD_MD_PATH = Path("docs/production_dashboard_latest.md")`

Observed filesystem:
- `output/runtime` missing
- `output/runtime/state` missing
- `output/runtime/logs` missing
- `output/runtime/telemetry` missing
- `output/state/activation_reports` missing
- `output` exists and writable; `output/state` exists and writable

Impact:
- VPS code path contract does not match release intent that moved artifacts to runtime storage.
- Runtime storage directories expected by the validated release are not provisioned.

Classification: PROVEN (contract mismatch and readiness gap)

## 6) Release Delta + Deploy Plan (Prepared, Not Executed)

Requested comparison (`HEAD..origin/master`) cannot be completed on VPS because:
- no `origin` remote configured
- branch is `build_identity_fix`, not `master`

Prepared command sequence (NOT executed):
1. `cd /opt/parapusulasi`
2. `git remote add origin <repo-url>` (if absent)
3. `git fetch origin --prune`
4. `git checkout master`
5. `git reset --hard c732427367d782f56c335e52dd063deaa8db3e0d` (or clean re-clone to pinned SHA)
6. verify clean tree and remote parity
7. validate env/runtime path contract
8. controlled service restart only after above validations

Note: Steps above are intentionally not run in this report due to read-only scope.

Classification: PLANNED (not executed)

## Final Recommendation

Decision: NO-GO

Blocking reasons:
1. VPS is not on the validated release (`c732427`); it is on `build_identity_fix` at `9de5980`.
2. VPS has no configured remote, so authoritative release parity cannot be proven.
3. VPS git index/worktree state is severely inconsistent (mass staged deletions plus untracked replacements).
4. Environment matrix is missing multiple required deployment-governance/runtime keys.
5. Runtime path contract on VPS still points to legacy `docs/` and `logs/` targets instead of runtime storage expectations.

Governance status by maturity:
- PLANNED: remediation/deploy sequence documented.
- REPORTED: raw evidence captured in this report.
- PROVEN: branch/commit mismatch, remote absence, drift state, env gaps, and path-contract mismatch observed directly.
- VALIDATED: not achieved.
- ROLLED_OUT: not applicable (no deploy performed).
