# Production Readiness Checklist

## Purpose
Single release gate for go/no-go decisions before production rollout.

## Release Metadata
- Release version:
- Release owner:
- Planned rollout date/time:
- Rollback owner:

## A. Build and Test Gates
- [ ] Build completed successfully.
- [ ] Targeted smoke tests passed.
- [ ] Critical regression tests passed.
- [ ] No new blocker-level lint/type/syntax issues.

## B. Content and Quality Gates
- [ ] Fact-check path is active.
- [ ] Fact-check regeneration policy is active and bounded.
- [ ] Snapshot validation guard is active.
- [ ] Thumbnail diversity guard is active.
- [ ] Thumbnail readability guard is active.
- [ ] Thumbnail Intelligence metadata gate: `thumbnail_variants` exists.
- [ ] Thumbnail Intelligence metadata gate: `selected_thumbnail_variant` exists.
- [ ] Thumbnail Intelligence metadata gate: `experiment_id` is preserved across pipeline result fields.
- [ ] Audio Intelligence metadata gate: `loudness_target` exists.
- [ ] Audio Intelligence metadata gate: `ducking_applied` exists and is boolean.
- [ ] Audio Intelligence metadata gate: `music_track_id` exists and is non-empty.
- [ ] Audio Intelligence metadata gate: if `audio_warning` exists, reason code is in standard allowed set.

## C. Pipeline and Scheduler Gates
- [ ] Scheduler health is OK.
- [ ] Running scheduler PID is alive and command is `scheduler.py`.
- [ ] Running scheduler cwd matches canonical root.
- [ ] Runtime build info is visible in logs (`BUILD_INFO scheduler git_sha=...`).
- [ ] Lock/queue race hardening is present or mitigated.
- [ ] Pipeline telemetry writes stage outcomes.
- [ ] Fail-open events emit warning/metric.
- [ ] Channel-level language metadata is correct for upload path.

## D. Infra and Credential Gates
- [ ] Upload credentials validated.
- [ ] Thumbnail upload risk is mitigated (403 storm control/cache active).
- [ ] Thumbnail upload is resolved: thumbnail-only probe shows 3 consecutive successful `thumbnails.set` calls on the target channel.
- [ ] Required API keys/tokens are available and not expired.
- [ ] Disk space is sufficient for planned batch.
- [ ] API quota budget is sufficient for planned run.
- [ ] Analytics live rollout gate: without YouTube Analytics API Go decision, live collector must NOT be connected to production pipeline.

## E. External Provider and Fallback Gates
- [ ] TTS default path is healthy.
- [ ] ElevenLabs fallback behavior is validated.
- [ ] Premium provider paths are non-blocking or safely isolated.
- [ ] HeyGen path is async/background-only and disabled on default synchronous production pipeline.
- [ ] Free-first fallback path is validated.

## F. Operability and Safety Gates
- [ ] Telemetry sink is writable and monitored.
- [ ] Error classification is visible in logs/metrics.
- [ ] Alerting routes for critical failures are ready.
- [ ] Runbook links are up to date.
- [ ] No-upload smoke requirement: 80-test targeted regression (or approved current smoke package) passes before cutover.
- [ ] Working tree hygiene: unrelated music/media files are not mixed into reliability/performance cutover commits.

## G. Rollback and Incident Readiness
- [ ] Rollback plan documented and reviewed.
- [ ] Last known good version identified.
- [ ] Data/state implications of rollback checked.
- [ ] Incident commander and escalation path assigned.

## Final Decision
- [ ] GO
- [ ] NO-GO

Decision note:

## Gate-6 Status (Metadata Observability)
- [x] Scheduler cutover: PASS.
- [ ] Metadata visibility verification: PENDING.
- Reason: no new pipeline telemetry event observed after scheduler restart/cutover.
- Required closure: re-run Gate-6 checks on first new natural pipeline run and verify `experiment_id`, `thumbnail_variants`, `selected_thumbnail_variant`, audio metadata (`loudness_target`, `ducking_applied`, `music_track_id`) and `audio_warning` visibility.

## Post-Release Verification (First 30-60 Minutes)
- [ ] First scheduled run completed.
- [ ] Upload success ratio within expected range.
- [ ] Experiment trace completeness >= 99% (target 100%).
- [ ] Daily metrics coverage >= 95% for CTR, impressions, watch_time_hours, average_view_duration_seconds.
- [ ] No spike in validation failures.
- [ ] No spike in provider timeouts/rate limits.
- [ ] Dashboard metrics and logs are normal.
