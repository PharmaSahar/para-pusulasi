# Post-Deploy Soak and Natural Job Report

## 1. Baseline
- UTC baseline: 2026-07-13T00:13:46Z
- Service: active
- MainPID: 115936
- ActiveEnterTimestamp: Mon 2026-07-13 00:00:12 UTC
- ExecStart: /opt/parapusulasi-current/venv/bin/python /opt/parapusulasi-current/scheduler.py
- Deployed SHA: c732427367d782f56c335e52dd063deaa8db3e0d
- Release directory: /opt/parapusulasi/releases/c732427367d782f56c335e52dd063deaa8db3e0d
- Symlink target: /opt/parapusulasi/releases/c732427367d782f56c335e52dd063deaa8db3e0d
- Fresh release git status: clean
- Disk usage: 46% used on /dev/sda1
- Memory usage: 7.6Gi total, 5.2Gi available
- Queue summary: queue depth reported as 0 in dashboard; runtime queue contains only quarantined entries plus one active teknoloji_pusulasi slot
- Provider circuit: overall_ok=true, health_check_ok=true, provider_preflight_ok=true
- Latest heartbeat: production_dashboard_latest.json generated_at=2026-07-13T00:06:30.275645+00:00
- Latest successful job before soak: Teknoloji Pusulasi upload resolved successfully
- Latest failed job before soak: Kripto Rehber topic_provenance_collision quarantine

## 2. 30-Minute Soak Checkpoints
- Checkpoints recorded: baseline at 00:13:46Z and follow-up at 00:17:11Z
- Service remained active across observed window
- MainPID remained stable at 115936 during the observed window
- No restart loop observed
- No fatal traceback observed in the live dashboard snapshot or recent log tail
- No disk emergency observed
- No memory emergency observed
- No tracked source/docs mutation observed
- Runtime outputs stayed outside tracked docs
- Telegram alert behavior stayed within the guarded pattern already present in the incident log

## 3. Service Stability
- The scheduler stayed up and the service process remained healthy during the observed window.
- The runtime dashboard remained degraded because of guarded provenance collisions, not because of a crash or restart loop.

## 4. Resource Stability
- Disk remained well above the emergency threshold.
- Memory remained well above the emergency threshold.
- No queue corruption was observed.

## 5. Alert Hygiene
- INCIDENT_OPEN: 12
- INCIDENT_UPDATED: 0
- INCIDENT_RESOLVED: 2
- CRITICAL: 0
- ERROR: 0
- WARNING: 12
- suppressed cooldown / guarded skip count: 12
- topic_provenance_collision count: 8
- duplicate incident count: 0
- duplicate RESOLVED count: 0
- Result: PASS

## 6. Observed Job Identity
- Channel: kripto_rehber
- run_id: run_2d0e08edd72f4cb8a16d1a8978c5da97
- content_id: content_e6f45ab4401941f68bc3c557762d0693
- Selected topic: Bitcoin 2026'da Kaç Dolar? Hesabı Yapınca Şok Oldum
- Topic source: natural production generation with guarded provenance validation
- Planner result: content generation completed, then provenance guard tripped
- Guard result: topic_provenance_collision -> topic_domain_blocked quarantine
- Retry count: 1
- Regeneration count: 0

## 7. Topic / Guard Result
- Topic-channel alignment did not pass to publication.
- The provenance guard correctly stopped cross-channel contamination before upload.
- Final classification: guarded quarantine, not a wrong-channel publish.

## 8. Render Result
- Render start observed in scheduler log.
- Render completion did not produce a publishable asset; the job ended in guarded quarantine.
- Final classification: guarded failure / quarantine.

## 9. Upload Result
- Main upload: skipped by guard
- Upload result: no video_id produced for the observed job

## 10. Shorts Result
- Shorts upload: skipped by guard
- Shorts policy: prevented because the job was quarantined before publish

## 11. State / Analytics Result
- Queue state updated consistently to quarantined
- Incident record written with stable incident_id
- No duplicate incident lifecycle was observed
- Runtime telemetry captured the job stages and quarantine outcome

## 12. Incident Lifecycle Result
- INCIDENT_OPEN recorded for the provenance collision
- No duplicate RESOLVED event was observed for this job
- Lifecycle policy behaved as expected for a guarded collision

## 13. Remaining Risks
- Dashboard still reports scheduler_status=degraded due to guarded collisions in the recent window.
- One active teknoloji_pusulasi slot remained present in the runtime queue snapshot during the observation.
- The live dashboard snapshot had not refreshed past 00:06:30Z at the time of the last check, so later progression was not visible in the exported dashboard JSON.

## 14. Final Production Verdict
- Service healthy: yes
- Safety gates intact: yes
- Publication safety preserved: yes
- Production verdict: HEALTHY
