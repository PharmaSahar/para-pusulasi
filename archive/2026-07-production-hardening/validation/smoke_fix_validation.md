# Smoke Fix Validation (Target: c732427)

## Scope
- Objective: confirm the **first smoke-test startup failure** is isolated and removed before a single controlled redeploy.
- Failure under investigation: scheduler abort with `Hiçbir kanalın token'i yok! Önce setup_channel.py çalıştırın.`

## Evidence Sources
- `artifacts/latest/repro_target_startup_service_like.sh` (pre-fix service-like repro)
- `artifacts/latest/validate_fix_isolated.sh` (post-fix isolated validation)
- Validation output snapshot (2026-07-12 21:20 UTC window)

## Maturity Labels
- Root-cause hypothesis status: `PROVEN`
- Minimum fix status (release data-restore token copy): `VALIDATED` (isolated)
- Production rollout status: `REPORTED` (redeploy pending)

## Key Findings
1. First startup failure reproduced pre-fix (`PROVEN`)
- Service-like startup reproduced exact abort text:
  - `Hiçbir kanalın token'i yok! Önce setup_channel.py çalıştırın.`
- This confirms channel readiness failed due to missing channel-scoped token/credential files in fresh release restore path.

2. First startup failure removed post-fix (`VALIDATED` in isolation)
- `grep_scheduler_starting` present:
  - `2026-07-12 21:20:19,570 [INFO] Scheduler: Scheduler starting`
- `grep_config_loaded` present:
  - `Configuration loaded: niche=kisisel_finans language=tr timezone=Europe/Istanbul`
- `grep_token_missing` empty (target failure signature absent).

3. Runtime safety and deployment hygiene checks (`VALIDATED` in isolation)
- Worktree status clean (`[worktree_status]` empty).
- Upload markers absent (`[grep_upload_markers]` empty).
- Target identity observed in startup/build logs:
  - `BUILD_INFO scheduler git_sha=c732427 ...`
- Validation ran under isolated state root:
  - `/tmp/validate_fix_1783891216`

4. Timeout semantics
- `validation_exit_code=124` corresponds to bounded observation timeout, not startup abort.
- During the bounded window, scheduler remained active and progressed into pipeline stages.

## Notes on Remaining Runtime Signals
- Non-startup runtime tracebacks from downstream render/content paths were observed in broader runs, but the first smoke failure under this task was startup readiness abort due to missing token artifacts.
- This artifact only certifies removal of the **first causal startup failure** in isolated validation.

## Decision for Pre-Redeploy Gate
- GO condition for single redeploy attempt: **satisfied for first-failure fix validation**.
- Additional operational gate still required at execution time: no active render/upload worker at switch moment.
