#!/usr/bin/env bash
set -Eeuo pipefail
REL="/opt/parapusulasi/releases/c732427367d782f56c335e52dd063deaa8db3e0d"
ISO="/tmp/repro_service_like_$(date +%s)"
mkdir -p "$ISO"
cd "$REL"
export UPLOAD_ENABLED=false
export SHORTS_UPLOAD_ENABLED=false
export SCHEDULE_ENABLED=false
set +e
timeout 120s "$REL/venv/bin/python" "$REL/scheduler.py" >"$ISO/stdout.log" 2>"$ISO/stderr.log"
EC=$?
set -e
echo "[repro_exit_code]$EC"
echo "[repro_iso]$ISO"
echo "[stderr_tail]"
tail -n 120 "$ISO/stderr.log" || true
echo "[stdout_tail]"
tail -n 120 "$ISO/stdout.log" || true
echo "[release_scheduler_log_tail]"
if [ -f "$REL/logs/scheduler.log" ]; then tail -n 120 "$REL/logs/scheduler.log"; else echo missing; fi
