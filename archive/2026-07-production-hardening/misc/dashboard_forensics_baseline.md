# Dashboard Forensics Baseline

Timestamp (local capture): 2026-07-12
Target file: docs/production_dashboard_latest.md

## Step 1 - Preserved Evidence

### Hashes
- SHA-256: 1a5b1b7469f23a45e451db3e1563e8cc341cf457bdfeb84e93fae2e7fc9c20a6
- SHA-1: 28eedae2f6f811a2415eebb599af1c20026781d2

### File metadata
- size_bytes: 1030
- mtime_epoch: 1783876087
- mtime_local: 2026-07-12 20:08:07 +0300

### Git metadata
- branch: master
- HEAD: d51e31578e3f3bd18674441f2f7545a2dce2dd05
- git status (target): M docs/production_dashboard_latest.md
- git diff --check exit: 0

### Unified diff (HEAD -> working tree)
```diff
diff --git a/docs/production_dashboard_latest.md b/docs/production_dashboard_latest.md
index e2b19e0..9cefd2b 100644
--- a/docs/production_dashboard_latest.md
+++ b/docs/production_dashboard_latest.md
@@ -1,22 +1,30 @@
 # Production Dashboard (Latest)

-- Generated at: 2026-07-11T07:07:35.310746+00:00
-- Scheduler status: pipeline_run
-- Build SHA: b1bee96
-- Scheduler PID: 80600
-- Queue depth: 32
-- Last error: -
+- Generated at: 2026-07-12T17:08:07.464006+00:00
+- Scheduler status: degraded
+- Build SHA: d51e315
+- Scheduler PID: 13358
+- Queue depth: 90
+- Last error: topic_provenance_collision:channels/saglik_pusulasi/output/topic_provenance/saglik_pusulasi/run_629677d82d254b6d949c27f82044029d/content_8f42e0869dde4e85b60a26ecbd4e7d17.json

 ## Last 24h
-- Videos: 3010
+- Videos: 27606
 - Shorts: 0
 - Success rate: 0.0
 - Failure rate: 0.0
-- Avg render duration (s): 84.364
-- Upload success count: 351
+- Avg render duration (s): 5.996
+- Upload success count: 1632
 - Blocked quality items: 0
-- Retries: 28
+- Retries: 54

 ## Channel Health
-- test-channel: total=332 success=0 failed=0
-- test_channel: total=2678 success=0 failed=0
+- borsa_akademi: total=172 success=0 failed=0
+- egitim_rehberi: total=26 success=0 failed=0
+- gayrimenkul_tv: total=426 success=0 failed=0
+- girisim_okulu: total=20 success=0 failed=0
+- kripto_rehber: total=220 success=0 failed=0
+- para_pusulasi: total=48 success=0 failed=0
+- saglik_pusulasi: total=34 success=0 failed=0
+- teknoloji_pusulasi: total=86 success=0 failed=0
+- test-channel: total=6094 success=0 failed=0
+- test_channel: total=20480 success=0 failed=0
```

## Step 2 - Git Evidence

### Last commit touching target
- commit: e8374ff32757d81c67742f3ccd9e32c4e9b6292e
- author: Sahar <klara@Sahars-MacBook-Pro.local>
- date: 2026-07-11 10:09:30 +0300
- subject: feat: add production quality observability and recovery platform

### Recent history for target
- 2026-07-11 10:09:30 +0300 | e8374ff | Sahar | feat: add production quality observability and recovery platform

### Commits touching target today
- none

Conclusion from git history: no new commit changed this file today; change is uncommitted working tree mutation.
