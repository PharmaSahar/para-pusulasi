# Development Guide

This document captures the current development and operations model for the repository.

## Canonical Repository Structure

- The repository root is the single canonical working root for code, tests, logs, and production operations.
- Production scheduler logs are tracked in `logs/production_scheduler.out`.
- The production scheduler pid record is tracked in `logs/production_scheduler.pid`.
- Operational scripts live under `deploy/`.
- Longer-form architecture and operational notes live under `docs/`.

## Branch Strategy

- Use `feature/<topic>` for new capabilities.
- Use `fix/<topic>` for bug fixes.
- Use `docs/<topic>` for documentation-only changes.
- Use `chore/<topic>` for maintenance.
- For the current operating model, continue active work from `feature/regeneration-on-planning` unless a new branch is explicitly needed.
- Do not continue work from retired auxiliary branches once a canonical replacement branch is established.

## Production Deploy Flow

- Develop and validate changes from the canonical repository root.
- Run targeted tests before opening a PR.
- Push the branch and open a PR against `v0.2.0-planning`.
- For operational cutovers, use the documented single-root procedure rather than ad hoc worktree switching.
- Keep production fail-closed where factual verification or external provider safety requires it.

## Scheduler Start Procedure

- Preferred scheduler entrypoint: `scheduler.py` from the repository root.
- Run health checks before cutover or restart.
- Enable Fact Bundle in live runs with `FACT_BUNDLE_PIPELINE_ADAPTER_ENABLED=true` when intended.
- Use `pgrep` and `lsof -a -d cwd -p <pid>` as process truth.
- Treat pid files as informational only.

## Fact-check Regeneration Flow

- The pipeline performs a fact-check before TTS.
- If the failure reason is `unverifiable_volatile_claim`, the pipeline retries content generation once.
- The retry path uses stricter safe-mode guidance to reduce speculative prices, targets, percentages, and date claims.
- The retry path remains fail-closed: if the second fact-check still fails, the pipeline aborts rather than publishing unverifiable content.
- Regression coverage for this path lives in `tests/test_factual_freshness.py`.

## Fact-check Failure Audit

- Use `python -m src.run_fact_check_audit --pretty` from the repository root to summarize failed fact-check events from `logs/production_scheduler.out`.
- The audit groups failures by failure kind, claim type, and channel.
- Current primary categories are stale FX claims and unverifiable volatile claims.
- Treat this audit output as the starting point for prompt-level prevention work, not as a reason to weaken fail-closed behavior.

## Operational Rules

- Keep a single canonical repository root for development and production operations.
- Avoid auxiliary worktrees as permanent operating roots.
- Record operational procedures in-repo so they survive beyond a single terminal session.
- Prefer small, reversible changes with targeted validation.
- Do not treat observed production behavior as stronger evidence than the logs and tests actually support.

## Related Documents

- `docs/architecture.md`
- `docs/single_root_operations.md`
- `deploy/single_root_cutover.sh`
- `CONTRIBUTING.md`