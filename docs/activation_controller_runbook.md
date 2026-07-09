# Activation Controller Runbook

## Purpose
`ops/activation_controller.py` evaluates learning activation gates from operational evidence.

This controller is intentionally independent from scheduler runtime.
It must not auto-change production behavior without explicit operator action.

## Scope and Safety
- Reads probe/cache evidence.
- Produces gate decision report and archive history.
- Can write activation flags only with explicit command.
- Does not write new code.
- Does not trigger uploads.
- Does not modify scheduler lifecycle.

## Recommended Periodic Mode (Read-only)
Run every 6 hours in report-only mode:

```bash
PYTHONPATH=. .venv-2/bin/python ops/activation_controller.py \
  --channel egitim_rehberi
```

Optional faster health check cadence:
- every 6 hours for production
- daily if probe quota/cost should be minimized

## Example Cron (Documentation Only)
Do not auto-install from application code; apply manually on production host.

```cron
# Every 6 hours: run read-only activation evaluation
0 */6 * * * cd /path/to/repo && PYTHONPATH=. .venv-2/bin/python ops/activation_controller.py --channel egitim_rehberi >> logs/activation_controller_cron.log 2>&1
```

## Example systemd timer (Documentation Only)
`/etc/systemd/system/activation-controller.service`

```ini
[Unit]
Description=Activation Controller Read-only Evaluation
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=/path/to/repo
ExecStart=/path/to/repo/.venv-2/bin/python ops/activation_controller.py --channel egitim_rehberi
Environment=PYTHONPATH=.
StandardOutput=append:/path/to/repo/logs/activation_controller_cron.log
StandardError=append:/path/to/repo/logs/activation_controller_cron.log
```

`/etc/systemd/system/activation-controller.timer`

```ini
[Unit]
Description=Run Activation Controller every 6 hours

[Timer]
OnCalendar=*-*-* 00,06,12,18:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

## Generated Files
Primary report path:
- `logs/activation_controller_report.json`

History archive:
- `output/state/activation_reports/YYYY-MM-DDTHH-MM-SS.json`
- `output/state/activation_reports/latest.json`

Optional flags output (explicit activation only):
- `output/state/learning_activation_flags.json`

## Exit Code Semantics
- `0`: command completed successfully
- `1`: runtime failure (unexpected execution error)
- `2`: explicit activation requested but blocked by gate status (`--activate-learning` + No-Go)

## Gate Interpretation
Analytics gate is GO when:
- analytics probe succeeds
- OAuth is OK
- token scope/status is ready

Thumbnail gate is GO when:
- `thumbnail_permission_cache` shows `can_upload_thumbnail=true`
- `success_streak >= required_thumbnail_streak` (default 3)

System status:
- `ready_for_learning_activation`: both gates are GO
- `blocked_for_learning_activation`: at least one gate is No-Go

## Why Learning Did Not Activate
Check `activation.reason` and gate reasons in latest report:
- `analytics_probe_skipped`
- `analytics_probe_execution_failed`
- `analytics_api_not_ready`
- `thumbnail_set_streak_below_threshold`
- `blocked_by_no_go`

## Pre-activation Checklist (Operator)
- Confirm latest report exists and is recent.
- Confirm `system_status=ready_for_learning_activation`.
- Confirm analytics gate reason indicates GO.
- Confirm thumbnail gate streak is at least 3.
- Confirm no concurrent incident in upload/thumbnail pipeline.

Then run explicit activation command:

```bash
PYTHONPATH=. .venv-2/bin/python ops/activation_controller.py \
  --channel egitim_rehberi \
  --activate-learning
```

## Current Operational Policy
Until external blockers are resolved:
- Analytics learning remains disabled if YouTube Analytics API is not enabled.
- Thumbnail learning remains disabled until 3 consecutive successful `thumbnails.set` probe results are verified.
