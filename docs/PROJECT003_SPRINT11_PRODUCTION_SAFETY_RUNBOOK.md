# PROJECT003 Sprint 11 Production Safety Runbook

## System Purpose

Sprint 11 hardens PROJECT003 production execution with one shared safety platform covering render, upload, analytics append, smoke validation, retry classification, and quarantine visibility.

## Normal Operating State

- Scheduler startup passes startup preflight.
- Production safety gate returns `allowed` or `warning`, not `blocked`.
- Smoke command returns `PASS`.
- Upload precheck returns `allow`.
- Analytics snapshots append without guard rejection.
- No active deployment lock exists outside planned deployment windows.

## Safety-Gate Commands

```bash
cd /Users/klara/Projects/parapusulasi-sprint11
/Users/klara/Projects/parapusulasi/.venv-2/bin/python scheduler.py --startup-preflight
/Users/klara/Projects/parapusulasi/.venv-2/bin/python scheduler.py --safety-check-now
```

## Smoke Command

```bash
cd /Users/klara/Projects/parapusulasi-sprint11
/Users/klara/Projects/parapusulasi/.venv-2/bin/python -m src.production_safety_smoke --channel teknoloji_pusulasi
```

## Analytics Guard Inspection

```bash
cd /Users/klara/Projects/parapusulasi-sprint11
tail -n 20 logs/analytics_quality_rejections.jsonl
```

## Queue Inspection

```bash
cd /Users/klara/Projects/parapusulasi-sprint11
cat output/state/channel_queue.json
```

## Deployment-Lock Inspection

```bash
test -e /opt/parapusulasi/deploy-state/deploy.lock/.active_lock && echo LOCKED || echo CLEAR
```

## Release-Integrity Inspection

```bash
cd /Users/klara/Projects/parapusulasi-sprint11
git rev-parse HEAD
cat .immutable_release_metadata.json
```

## Quarantine Inspection

```bash
cd /Users/klara/Projects/parapusulasi-sprint11
tail -n 50 logs/queue_quarantine_decisions.jsonl
```

## Retry Exhaustion Handling

- Inspect `logs/production_events.jsonl` for `retry_exhausted`.
- Inspect dead-letter telemetry in `telemetry/production_dead_letter_queue.jsonl`.
- Do not manually re-run blocked jobs until the reason code is resolved.

## Duplicate Scheduler Handling

- Inspect `output/state/scheduler_singleton.lock` and `output/state/scheduler_singleton_meta.json`.
- If a stale lock is suspected, capture evidence first.
- Do not remove locks blindly during active production.

## Common Failure Reason Codes

- `api_credentials_missing`
- `youtube_token_invalid`
- `required_env_missing`
- `active_deployment_lock`
- `release_integrity_mismatch`
- `writable_directories_unavailable`
- `disk_space_below_threshold`
- `clock_sanity_failed`
- `queue_file_unreadable`
- `queue_backlog_elevated`
- `rate_limit_approaching`
- `production_safety_gate_blocked`
- `upload_precheck_blocked`
- `analytics_snapshot_negative_metric`
- `analytics_snapshot_duplicate`

## Five-Minute Incident Procedure

1. Run startup preflight.
2. Run the smoke command on the affected channel.
3. Inspect `logs/production_events.jsonl` for the latest safety, retry, and analytics events.
4. Inspect queue and quarantine logs.
5. Confirm deployment-lock and release-integrity status.

## Rollback Decision Criteria

- Repeated safety blocks across healthy inputs.
- Release integrity mismatch.
- Retry exhaustion on core upload path with no operator fix available.
- Cross-channel contamination evidence.

## Evidence To Capture

- latest structured event payload
- safety-gate result JSON
- smoke report JSON
- queue snapshot
- quarantine decision rows
- retry exhaustion event
- current git SHA and release metadata

## Warning

Do not bypass Sprint 11 safety gates manually. Do not invoke uploader or pipeline paths in production with local monkeypatches, ad hoc token changes, or lock removal unless rollback or incident procedure explicitly requires it.