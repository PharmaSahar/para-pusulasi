# Single-root operations

## Canonical root
- Canonical repository root: /Users/klara/Downloads/adsız klasör
- Active working branch: feature/regeneration-on-planning
- Canonical live scheduler log: logs/production_scheduler.out
- Canonical live scheduler pid record: logs/production_scheduler.pid

## Branch rule
- Continue all development from feature/regeneration-on-planning.
- Do not continue work from feature/fact-check-regeneration-policy.

## Worktree rule
- Auxiliary worktrees are temporary only.
- Keep /Users/klara/Downloads/para-pusulasi-production until post-cutover monitoring is satisfactory.
- Keep /Users/klara/Downloads/para-pusulasi-merge-regeneration until integration cleanup is explicitly approved.

## Cutover script
- Persistent cutover script: deploy/single_root_cutover.sh
- Use pgrep and lsof as process truth.
- Treat pid files as informational only.

## Post-cutover checklist
Remove auxiliary worktrees only after all checks below are true.

### Canonical root
- Canonical root is /Users/klara/Downloads/adsız klasör.
- Active branch is feature/regeneration-on-planning.
- Main scheduler process cwd resolves to /Users/klara/Downloads/adsız klasör.

### Runtime health
- Scheduler health check passes from the canonical root.
- Fact Bundle pipeline adapter is enabled in the live process.
- logs/production_scheduler.out is actively receiving new lines in the canonical root.
- At least one real render continues successfully after cutover.

### Production safety
- No live scheduler process cwd resolves to /Users/klara/Downloads/para-pusulasi-production.
- Old production worktree is no longer receiving new production log lines.
- The current queue and upload flow remain healthy after cutover.

### Before deletion
- Delete auxiliary worktrees only after a final manual confirmation.

## Current production note
- Single-root cutover completed successfully.
- Fact Bundle runs enabled from the canonical root.
- Retry regeneration for unverifiable volatile claims remains fail-closed if the second pass still violates fact-check rules.
- Retry generation was hardened to avoid repeating speculative crypto and market-price target framing.
