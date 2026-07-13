# Smoke Failure Investigation: State Before

Timestamp (UTC): 2026-07-12 21:10:43 UTC

## Production Health Snapshot

- Service: parapusulasi
- systemctl is-active: active
- MainPID: 110773
- ExecStart: /opt/parapusulasi/venv/bin/python /opt/parapusulasi/scheduler.py
- Current production SHA (/opt/parapusulasi): 9de59809f8df6b2f020f9548a1346e781e2b4a8d
- Current symlink target (/opt/parapusulasi-current): /opt/parapusulasi-current

## Scheduler Heartbeat / Recent Activity

Latest scheduler log activity confirms scheduler loop is active (queue/render-related lines observed around 21:00:50-21:04:49 UTC), including:
- queue skip decisions
- render enqueue/start events
- retry warning on content quality block

## Active Job Check (Render/Upload)

Process snapshot at capture time:
- ffmpeg process present
- one defunct ffmpeg helper process present

Verification result:
- Active render/upload job: YES (render in progress at capture time)

## Safety Note

- Production service was not stopped during investigation.
