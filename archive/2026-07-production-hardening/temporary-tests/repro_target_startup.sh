#!/usr/bin/env bash
set -Eeuo pipefail
REL="/opt/parapusulasi/releases/c732427367d782f56c335e52dd063deaa8db3e0d"
ISO="/tmp/repro_smoke_fail_$(date +%s)"
mkdir -p "$ISO/state" "$ISO/logs" "$ISO/telemetry" "$ISO/home" "$ISO/cache"
cd "$REL"
export PREPROD_ISOLATION_MODE=true
export PREPROD_STATE_ROOT="$ISO"
export HOME="$ISO/home"
export XDG_CACHE_HOME="$ISO/cache"
export SCHEDULER_LOG_FILE="$ISO/logs/scheduler.log"
export TELEMETRY_SINK_DIR="$ISO/telemetry"
export SCHEDULER_QUEUE_FILE="$ISO/state/channel_queue.json"
export SCHEDULER_PID_FILE="$ISO/state/scheduler.pid"
export ACTIVATION_CONTROLLER_REPORT_ARCHIVE_DIR="$ISO/state/activation_reports"
export GOVERNANCE_READINESS_MD_PATH="$ISO/state/governance_readiness_latest.md"
export PRODUCTION_DASHBOARD_MD_PATH="$ISO/state/production_dashboard_latest.md"
export PRODUCTION_DASHBOARD_JSON_PATH="$ISO/state/production_dashboard_latest.json"
export PRODUCTION_OBSERVABILITY_LATEST_PATH="$ISO/telemetry/production_observability_latest.json"
export INCIDENT_STATE_FILE="$ISO/state/incident_state.json"
export INCIDENT_EVENTS_FILE="$ISO/logs/production_incidents.jsonl"
export INCIDENT_METRICS_FILE="$ISO/state/incident_metrics_latest.json"
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
echo "[scheduler_log_tail]"
if [ -f "$ISO/logs/scheduler.log" ]; then tail -n 120 "$ISO/logs/scheduler.log"; else echo missing; fi
