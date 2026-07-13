#!/usr/bin/env bash
set -Eeuo pipefail
REL="/opt/parapusulasi/releases/c732427367d782f56c335e52dd063deaa8db3e0d"
ISO="/tmp/validate_fix_$(date +%s)"
mkdir -p "$ISO/state" "$ISO/logs" "$ISO/telemetry" "$ISO/home" "$ISO/cache"
cd "$REL"

export PREPROD_ISOLATION_MODE=true
export PREPROD_STATE_ROOT="$ISO"
export HOME="$ISO/home"
export XDG_CACHE_HOME="$ISO/cache"
export SCHEDULER_LOG_FILE="$ISO/logs/scheduler.log"
export SCHEDULER_QUEUE_FILE="$ISO/state/channel_queue.json"
export SCHEDULER_PID_FILE="$ISO/state/scheduler.pid"
export SCHEDULER_SINGLETON_LOCK_FILE="$ISO/state/scheduler_singleton.lock"
export SCHEDULER_SINGLETON_META_FILE="$ISO/state/scheduler_singleton_meta.json"
export RUNTIME_EVIDENCE_LATEST_FILE="$ISO/state/runtime_optimization_evidence_latest.json"
export SAFETY_GATE_LATEST_FILE="$ISO/state/production_safety_gate_latest.json"
export ACTIVATION_CONTROLLER_REPORT_PATH="$ISO/state/activation_controller_report.json"
export ACTIVATION_CONTROLLER_REPORT_ARCHIVE_DIR="$ISO/state/activation_reports"
export ACTIVATION_FLAGS_PATH="$ISO/state/learning_activation_flags.json"
export GOVERNANCE_REFRESH_LATEST_PATH="$ISO/state/governance_refresh_run_latest.json"
export GOVERNANCE_READINESS_MD_PATH="$ISO/state/governance_readiness_latest.md"
export PRODUCTION_DASHBOARD_JSON_PATH="$ISO/state/production_dashboard_latest.json"
export PRODUCTION_DASHBOARD_MD_PATH="$ISO/state/production_dashboard_latest.md"
export PRODUCTION_EVENTS_PATH="$ISO/telemetry/production_events.jsonl"
export PRODUCTION_OBSERVABILITY_LATEST_PATH="$ISO/telemetry/production_observability_latest.json"
export TELEMETRY_SINK_DIR="$ISO/telemetry"
export INCIDENT_STATE_FILE="$ISO/state/incident_state.json"
export INCIDENT_EVENTS_FILE="$ISO/logs/production_incidents.jsonl"
export INCIDENT_METRICS_FILE="$ISO/state/incident_metrics_latest.json"

export UPLOAD_ENABLED=false
export SHORTS_UPLOAD_ENABLED=false
export SCHEDULE_ENABLED=false

set +e
timeout 330s "$REL/venv/bin/python" "$REL/scheduler.py" >"$ISO/stdout.log" 2>"$ISO/stderr.log"
EC=$?
set -e

echo "[validation_exit_code]$EC"
echo "[validation_iso]$ISO"

echo "[grep_scheduler_starting]"
grep -n "Scheduler starting" "$ISO/stdout.log" || true

echo "[grep_config_loaded]"
grep -n "Configuration loaded" "$ISO/stdout.log" || true

echo "[grep_token_missing]"
grep -n "Hiçbir kanalın token'i yok" "$ISO/stdout.log" "$ISO/stderr.log" || true

echo "[grep_fatal]"
grep -nEi "Traceback|RuntimeError|Exception|fatal" "$ISO/stdout.log" "$ISO/stderr.log" "$ISO/logs/scheduler.log" || true

echo "[grep_upload_markers]"
grep -nEi "youtube.*upload|upload.*youtube|shorts.*upload" "$ISO/stdout.log" "$ISO/stderr.log" "$ISO/logs/scheduler.log" || true

echo "[worktree_status]"
git status --short

echo "[stderr_tail]"
tail -n 80 "$ISO/stderr.log" || true

echo "[stdout_tail]"
tail -n 120 "$ISO/stdout.log" || true
