# Final VPS Deployment Report

Deployment timestamp: 2026-07-12 21:01:06 UTC
Previous SHA: 9de59809f8df6b2f020f9548a1346e781e2b4a8d
Target SHA: c732427367d782f56c335e52dd063deaa8db3e0d
Release directory: /opt/parapusulasi/releases/c732427367d782f56c335e52dd063deaa8db3e0d
Backup directory: /opt/parapusulasi-backups/predeploy-20260712-205959

## Summary

- Deployment script executed all phases through service switch and post-deploy smoke checks.
- Pre-start validation passed with:
  - target SHA exact match in fresh release
  - fresh release worktree clean
  - runtime paths outside tracked docs
  - targeted production-safe tests passing (39 passed)
- Post-deploy extended smoke failed stability condition during 5-minute window.
- Automatic rollback executed successfully.
- Service restored and active on previous installation.

## Final Runtime State

- Deployment result: ROLLED BACK
- Service active: YES
- Service MainPID: 110773
- Current ExecStart: /opt/parapusulasi/venv/bin/python /opt/parapusulasi/scheduler.py
- Current production SHA: 9de59809f8df6b2f020f9548a1346e781e2b4a8d
- Fresh release SHA at target path: c732427367d782f56c335e52dd063deaa8db3e0d
- Fresh release worktree clean: YES
- Runtime paths outside tracked docs: PASS
- Smoke test: FAIL
- Rollback backup created: YES
- Rollback executed: YES
- Final production status: HEALTHY

## Notes

- No live YouTube upload command was used for validation steps.
- Dirty repository at /opt/parapusulasi was preserved in place (no reset).
- Fresh checkout deployment source remained isolated under /opt/parapusulasi/releases/.
