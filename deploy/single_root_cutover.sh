#!/usr/bin/env bash
set -euo pipefail

MAIN_ROOT="/Users/klara/Downloads/adsız klasör"
OLD_ROOT="/Users/klara/Downloads/para-pusulasi-production"
PYTHON_BIN="$MAIN_ROOT/.venv-2/bin/python"
LOG_FILE="$MAIN_ROOT/logs/production_scheduler.out"
PID_FILE="$MAIN_ROOT/logs/production_scheduler.pid"
MATCH_EXPR="Python.*scheduler.py|python.*scheduler.py|scheduler.py"

resolve_root() {
  local path="$1"
  cd "$path" >/dev/null 2>&1 && pwd -P
}

MAIN_ROOT_REAL="$(resolve_root "$MAIN_ROOT")"
OLD_ROOT_REAL="$(resolve_root "$OLD_ROOT")"

find_scheduler_pids() {
  pgrep -f "$MATCH_EXPR" || true
}

get_pid_cwd() {
  local pid="$1"
  lsof -a -d cwd -p "$pid" 2>/dev/null | awk 'NR==2 {print $NF}'
}

normalize_cwd() {
  local cwd="$1"
  if [[ -z "$cwd" ]]; then
    return 0
  fi
  cd "$cwd" >/dev/null 2>&1 && pwd -P || printf '%s\n' "$cwd"
}

print_scheduler_roots() {
  local found=0
  for pid in $(find_scheduler_pids); do
    found=1
    local cwd
    cwd=$(get_pid_cwd "$pid")
    local normalized_cwd
    normalized_cwd=$(normalize_cwd "$cwd")
    local cmd
    cmd=$(ps -ww -p "$pid" -o command= 2>/dev/null || true)
    echo "pid=$pid cwd=${normalized_cwd:-${cwd:-unknown}} cmd=${cmd:-unknown}"
  done
  if [[ "$found" -eq 0 ]]; then
    echo "no scheduler processes found"
  fi
}

stop_root_schedulers() {
  local target_root="$1"
  local matched=0
  for pid in $(find_scheduler_pids); do
    local cwd
    cwd=$(get_pid_cwd "$pid")
    local normalized_cwd
    normalized_cwd=$(normalize_cwd "$cwd")
    if [[ "$normalized_cwd" == "$target_root" ]]; then
      matched=1
      echo "stopping pid=$pid cwd=$normalized_cwd"
      kill -TERM "$pid"
    fi
  done
  if [[ "$matched" -eq 0 ]]; then
    echo "no scheduler process found for root: $target_root"
  fi
}

assert_no_root_schedulers() {
  local target_root="$1"
  for pid in $(find_scheduler_pids); do
    local cwd
    cwd=$(get_pid_cwd "$pid")
    local normalized_cwd
    normalized_cwd=$(normalize_cwd "$cwd")
    if [[ "$normalized_cwd" == "$target_root" ]]; then
      echo "scheduler still running for root: $target_root (pid=$pid)"
      return 1
    fi
  done
}

wait_for_no_root_schedulers() {
  local target_root="$1"
  local attempts="${2:-10}"
  local delay_seconds="${3:-1}"

  for ((attempt = 1; attempt <= attempts; attempt++)); do
    if assert_no_root_schedulers "$target_root"; then
      return 0
    fi
    echo "waiting for root shutdown: $target_root (attempt $attempt/$attempts)"
    sleep "$delay_seconds"
  done

  assert_no_root_schedulers "$target_root"
}

assert_only_main_root_running() {
  local found=0
  for pid in $(find_scheduler_pids); do
    found=1
    local cwd
    cwd=$(get_pid_cwd "$pid")
    local normalized_cwd
    normalized_cwd=$(normalize_cwd "$cwd")
    if [[ "$normalized_cwd" != "$MAIN_ROOT_REAL" ]]; then
      echo "unexpected scheduler root detected: pid=$pid cwd=${normalized_cwd:-${cwd:-unknown}}"
      return 1
    fi
  done
  if [[ "$found" -eq 0 ]]; then
    echo "no scheduler process is running after cutover"
    return 1
  fi
}

echo "=== preflight: branch/head/status ==="
cd "$MAIN_ROOT"
git branch --show-current
git rev-parse --short HEAD
git status --short

echo "=== preflight: health check with fact bundle enabled ==="
FACT_BUNDLE_PIPELINE_ADAPTER_ENABLED=true "$PYTHON_BIN" scheduler.py --health-check

echo "=== before cutover: live scheduler roots ==="
print_scheduler_roots

echo "=== old root recent log tail ==="
if [[ -f "$OLD_ROOT/logs/production_scheduler.out" ]]; then
  tail -n 40 "$OLD_ROOT/logs/production_scheduler.out"
else
  echo "old production log missing"
fi

echo "=== stopping old-root schedulers ==="
stop_root_schedulers "$OLD_ROOT_REAL"
wait_for_no_root_schedulers "$OLD_ROOT_REAL"

echo "=== starting canonical-root scheduler ==="
mkdir -p "$MAIN_ROOT/logs"
cd "$MAIN_ROOT"
FACT_BUNDLE_PIPELINE_ADAPTER_ENABLED=true nohup "$PYTHON_BIN" scheduler.py > "$LOG_FILE" 2>&1 &
new_pid=$!
echo "$new_pid" > "$PID_FILE"
echo "started new pid=$new_pid"

echo "=== after cutover: live scheduler roots ==="
print_scheduler_roots
assert_only_main_root_running

echo "=== canonical-root log tail ==="
tail -n 80 "$LOG_FILE"

echo "=== cutover complete ==="
echo "canonical root is now: $MAIN_ROOT_REAL"
echo "recorded pid file: $PID_FILE"
echo "note: pid file is informational only; process truth comes from pgrep/lsof"
