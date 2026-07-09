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

## C. Pipeline and Scheduler Gates
- [ ] Scheduler health is OK.
- [ ] Lock/queue race hardening is present or mitigated.
- [ ] Pipeline telemetry writes stage outcomes.
- [ ] Fail-open events emit warning/metric.
- [ ] Channel-level language metadata is correct for upload path.

## D. Infra and Credential Gates
- [ ] Upload credentials validated.
- [ ] Required API keys/tokens are available and not expired.
- [ ] Disk space is sufficient for planned batch.
- [ ] API quota budget is sufficient for planned run.

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

## G. Rollback and Incident Readiness
- [ ] Rollback plan documented and reviewed.
- [ ] Last known good version identified.
- [ ] Data/state implications of rollback checked.
- [ ] Incident commander and escalation path assigned.

## Final Decision
- [ ] GO
- [ ] NO-GO

Decision note:

## Post-Release Verification (First 30-60 Minutes)
- [ ] First scheduled run completed.
- [ ] Upload success ratio within expected range.
- [ ] No spike in validation failures.
- [ ] No spike in provider timeouts/rate limits.
- [ ] Dashboard metrics and logs are normal.
