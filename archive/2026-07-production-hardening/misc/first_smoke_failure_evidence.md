# First Smoke Failure Evidence

## Scope

This captures the first failing post-start check from the previous redeploy attempt that ended in rollback.

## Chronological First Failure

1. Target service start (new release) occurred at 2026-07-12 21:00:26 UTC.
2. New target process exited at 2026-07-12 21:00:29 UTC with code 1.
3. Smoke phase later failed with "service not stable in 5 minute window" and triggered rollback.

## Exact First Failing Check

- Check: post-start service stability condition (service must remain active with MainPID > 0 during extended smoke window)
- Expected: service stays active throughout smoke interval
- Actual: service process exited almost immediately after start
- Exit code: 1 (systemd: status=1/FAILURE)

## Primary Evidence

### A) Deployment result artifact
From /root/parapusulasi_deploy_result.env:
- DEPLOYMENT_RESULT=ROLLED BACK
- SMOKE_TEST=FAIL
- ROLLBACK_EXECUTED=YES
- BACKUP_DIR=/opt/parapusulasi-backups/predeploy-20260712-205959

### B) systemd journal (failed target start)
Window: 2026-07-12 21:00:20 .. 21:00:32 UTC
- Started Para Pusulasi YouTube Otomasyonu.
- parapusulasi.service: Main process exited, code=exited, status=1/FAILURE
- parapusulasi.service: Failed with result 'exit-code'.

### C) Target release startup log right before crash
File:
- /opt/parapusulasi/releases/c732427367d782f56c335e52dd063deaa8db3e0d/output/runtime/logs/scheduler.log

Last lines before exit:
- Scheduler singleton lock acquired
- JOB_STORE_MODE json
- Configuration loaded
- Health check result: PASS
- Startup provider preflight result: PASS

No "Scheduler starting" line was emitted in that failed start instance.

### D) Isolated reproduction of same startup failure (without switching production)
Reproduction command used target release runtime directly with safe no-upload flags:
- release: /opt/parapusulasi/releases/c732427367d782f56c335e52dd063deaa8db3e0d
- UPLOAD_ENABLED=false
- SHORTS_UPLOAD_ENABLED=false
- SCHEDULE_ENABLED=false

Observed:
- [repro_exit_code]1
- stdout ended with:
  - "Hiçbir kanalın token'i yok! Önce setup_channel.py çalıştırın."
- source line:
  - scheduler.py:2075 (no ready channels because no channel token detected)

## First Failure Record (Required Fields)

- Timestamp: 2026-07-12 21:00:29 UTC (service process exit)
- Command/check: post-start service stability check in smoke phase
- Expected result: active service remains running
- Actual result: process exited status=1
- Exit code: 1
- Traceback/log line: "Hiçbir kanalın token'i yok! Önce setup_channel.py çalıştırın."
- Target process state: started, passed health+provider preflight, exited before scheduler main loop start
- Files/env involved:
  - target release dir: /opt/parapusulasi/releases/c732427367d782f56c335e52dd063deaa8db3e0d
  - channel token discovery path via scheduler ready-channel logic
  - channel credential/token files under channels/* (missing in fresh release snapshot)
