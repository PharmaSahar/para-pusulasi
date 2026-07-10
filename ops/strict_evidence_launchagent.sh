#!/usr/bin/env bash
set -euo pipefail

# Manage a macOS LaunchAgent that generates strict evidence reports daily.

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON_BIN="$ROOT_DIR/.venv-2/bin/python"
REPORT_SCRIPT="$ROOT_DIR/ops/generate_strict_evidence_report.py"
PLIST_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$PLIST_DIR/com.parapusulasi.strict-evidence-report.plist"
LABEL="com.parapusulasi.strict-evidence-report"
STDOUT_LOG="$ROOT_DIR/logs/launchagent_strict_evidence_out.log"
STDERR_LOG="$ROOT_DIR/logs/launchagent_strict_evidence_err.log"

HOUR="03"
MINUTE="15"

usage() {
  cat <<'USAGE'
Usage:
  ops/strict_evidence_launchagent.sh install [--hour HH] [--minute MM]
  ops/strict_evidence_launchagent.sh status
  ops/strict_evidence_launchagent.sh run-now
  ops/strict_evidence_launchagent.sh uninstall

Notes:
  - install: creates plist under ~/Library/LaunchAgents and loads it with launchctl
  - run-now: triggers immediate execution via launchctl kickstart
USAGE
}

require_runtime() {
  if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "ERROR: Python runtime not found at: $PYTHON_BIN" >&2
    exit 1
  fi
  if [[ ! -f "$REPORT_SCRIPT" ]]; then
    echo "ERROR: Report script not found at: $REPORT_SCRIPT" >&2
    exit 1
  fi
}

write_plist() {
  mkdir -p "$PLIST_DIR"
  cat > "$PLIST_PATH" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>

  <key>ProgramArguments</key>
  <array>
    <string>$PYTHON_BIN</string>
    <string>$REPORT_SCRIPT</string>
    <string>--latest-only</string>
  </array>

  <key>WorkingDirectory</key>
  <string>$ROOT_DIR</string>

  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key>
    <integer>$HOUR</integer>
    <key>Minute</key>
    <integer>$MINUTE</integer>
  </dict>

  <key>StandardOutPath</key>
  <string>$STDOUT_LOG</string>
  <key>StandardErrorPath</key>
  <string>$STDERR_LOG</string>

  <key>RunAtLoad</key>
  <false/>
</dict>
</plist>
PLIST
}

unload_if_present() {
  local gui
  gui="gui/$(id -u)"
  launchctl bootout "$gui" "$PLIST_PATH" >/dev/null 2>&1 || true
}

install_agent() {
  require_runtime
  write_plist
  mkdir -p "$ROOT_DIR/logs"
  unload_if_present
  launchctl bootstrap "gui/$(id -u)" "$PLIST_PATH"
  echo "Installed: $PLIST_PATH"
  echo "Schedule: daily ${HOUR}:${MINUTE} (local time)"
}

status_agent() {
  local gui
  gui="gui/$(id -u)"
  echo "Plist: $PLIST_PATH"
  if [[ -f "$PLIST_PATH" ]]; then
    echo "Plist exists: yes"
  else
    echo "Plist exists: no"
  fi
  echo
  launchctl print "$gui/$LABEL" >/dev/null 2>&1 && echo "Loaded: yes" || echo "Loaded: no"
  echo
  launchctl print "$gui/$LABEL" 2>/dev/null | grep -E "state =|last exit code =|path =|program =" || true
}

run_now() {
  local gui
  gui="gui/$(id -u)"
  launchctl print "$gui/$LABEL" >/dev/null 2>&1 || {
    echo "ERROR: Agent not loaded. Run install first." >&2
    exit 1
  }
  launchctl kickstart -k "$gui/$LABEL"
  echo "Triggered run-now for $LABEL"
}

uninstall_agent() {
  unload_if_present
  if [[ -f "$PLIST_PATH" ]]; then
    rm -f "$PLIST_PATH"
    echo "Removed: $PLIST_PATH"
  else
    echo "Plist not found: $PLIST_PATH"
  fi
}

parse_install_args() {
  shift
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --hour)
        HOUR="$2"
        shift 2
        ;;
      --minute)
        MINUTE="$2"
        shift 2
        ;;
      *)
        echo "Unknown option: $1" >&2
        usage
        exit 1
        ;;
    esac
  done

  [[ "$HOUR" =~ ^[0-9]{1,2}$ ]] || { echo "Invalid hour: $HOUR" >&2; exit 1; }
  [[ "$MINUTE" =~ ^[0-9]{1,2}$ ]] || { echo "Invalid minute: $MINUTE" >&2; exit 1; }

  if (( 10#$HOUR < 0 || 10#$HOUR > 23 )); then
    echo "Hour must be 0-23" >&2
    exit 1
  fi
  if (( 10#$MINUTE < 0 || 10#$MINUTE > 59 )); then
    echo "Minute must be 0-59" >&2
    exit 1
  fi

  HOUR=$(printf "%02d" "$HOUR")
  MINUTE=$(printf "%02d" "$MINUTE")
}

main() {
  if [[ $# -lt 1 ]]; then
    usage
    exit 1
  fi

  case "$1" in
    install)
      parse_install_args "$@"
      install_agent
      ;;
    status)
      status_agent
      ;;
    run-now)
      run_now
      ;;
    uninstall)
      uninstall_agent
      ;;
    *)
      usage
      exit 1
      ;;
  esac
}

main "$@"
