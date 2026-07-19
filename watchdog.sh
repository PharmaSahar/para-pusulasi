#!/bin/bash
# Watchdog: parapusulasi servisi durmussa Telegram'a bildir + guvenli yeniden baslat
set -u

SERVICE_NAME="${WATCHDOG_SERVICE_NAME:-parapusulasi}"
OPERATOR_ROOT="${WATCHDOG_OPERATOR_ROOT:-/opt/parapusulasi}"
APP_ROOT="${WATCHDOG_APP_ROOT:-${IMMUTABLE_V2_CURRENT_LINK:-/opt/parapusulasi-current}}"
LOCK_DIR="${WATCHDOG_LOCK_DIR:-${IMMUTABLE_V2_LOCK_DIR:-/opt/parapusulasi/deploy.lock}}"
STATE_DIR="${WATCHDOG_STATE_DIR:-${OPERATOR_ROOT}/watchdog-state}"
OPEN_INCIDENT_FILE="${STATE_DIR}/open_incident"
ATTEMPT_FILE="${STATE_DIR}/restart_attempts"
EXECUTION_LOCK_DIR="${STATE_DIR}/watchdog.execution.lock"
MAX_RESTART_ATTEMPTS="${WATCHDOG_MAX_RESTART_ATTEMPTS:-1}"
RESTART_SETTLE_SECONDS="${WATCHDOG_RESTART_SETTLE_SECONDS:-5}"
CLASSIFIER_TIMEOUT_SECONDS="${WATCHDOG_CLASSIFIER_TIMEOUT_SECONDS:-10}"
PYTHON_BIN="${WATCHDOG_PYTHON_BIN:-}"

if [ -z "${PYTHON_BIN}" ]; then
    if [ -x "${APP_ROOT}/.venv-2/bin/python" ]; then
        PYTHON_BIN="${APP_ROOT}/.venv-2/bin/python"
    elif [ -x "${APP_ROOT}/.venv/bin/python" ]; then
        PYTHON_BIN="${APP_ROOT}/.venv/bin/python"
    fi
fi

if [ -f "${OPERATOR_ROOT}/.env" ]; then
    BOT_TOKEN=$(grep '^TELEGRAM_BOT_TOKEN=' "${OPERATOR_ROOT}/.env" | cut -d= -f2- | tr -d '"')
    CHAT_ID=$(grep '^TELEGRAM_CHAT_ID=' "${OPERATOR_ROOT}/.env" | cut -d= -f2- | tr -d '"')
else
    BOT_TOKEN=""
    CHAT_ID=""
fi

mkdir -p "${STATE_DIR}" 2>/dev/null || true

if ! mkdir "${EXECUTION_LOCK_DIR}" 2>/dev/null; then
    exit 0
fi
trap 'rmdir "${EXECUTION_LOCK_DIR}" 2>/dev/null || true' EXIT INT TERM

notify() {
    if [ -z "${BOT_TOKEN}" ] || [ -z "${CHAT_ID}" ]; then
        return 0
    fi
    curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
        -d "chat_id=${CHAT_ID}" \
        -d "text=$1" > /dev/null 2>&1
}

notify_once() {
    key="$1"
    message="$2"
    current=""
    if [ -f "${OPEN_INCIDENT_FILE}" ]; then
        current=$(cat "${OPEN_INCIDENT_FILE}" 2>/dev/null || true)
    fi
    if [ "${current}" != "${key}" ]; then
        notify "${message}"
        write_state_file "${OPEN_INCIDENT_FILE}" "${key}"
    fi
}

write_state_file() {
    path="$1"
    value="$2"
    tmp="${path}.tmp.$$"
    if printf '%s\n' "${value}" > "${tmp}" 2>/dev/null; then
        mv -f "${tmp}" "${path}" 2>/dev/null || rm -f "${tmp}" 2>/dev/null || true
    else
        rm -f "${tmp}" 2>/dev/null || true
    fi
}

clear_incident_if_recovered() {
    if [ -f "${OPEN_INCIDENT_FILE}" ]; then
        notify "OK: Scheduler aktif; watchdog olayi kapatildi."
        rm -f "${OPEN_INCIDENT_FILE}" "${ATTEMPT_FILE}" 2>/dev/null || true
    fi
}

classify_lock() {
    if [ -z "${PYTHON_BIN}" ] || [ ! -x "${PYTHON_BIN}" ]; then
        printf '%s\n' '{"lock_classification":"ambiguous_lock","owner_state":"classifier_python_missing"}'
        return 0
    fi
    if [ ! -d "${APP_ROOT}" ]; then
        printf '%s\n' '{"lock_classification":"ambiguous_lock","owner_state":"app_root_missing"}'
        return 0
    fi
    output=$(
        cd "${APP_ROOT}" && \
        IMMUTABLE_V2_LOCK_DIR="${LOCK_DIR}" "${PYTHON_BIN}" -c '
import subprocess
import sys

python_bin, lock_dir, timeout_seconds = sys.argv[1:4]
try:
    timeout = float(timeout_seconds)
except ValueError:
    timeout = 10.0
try:
    completed = subprocess.run(
        [python_bin, "-m", "src.production_safety_gate", "--classify-deployment-lock", lock_dir],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        timeout=timeout,
        check=False,
    )
except subprocess.TimeoutExpired:
    raise SystemExit(124)
sys.stdout.write(completed.stdout)
raise SystemExit(completed.returncode)
' "${PYTHON_BIN}" "${LOCK_DIR}" "${CLASSIFIER_TIMEOUT_SECONDS}"
    )
    rc=$?
    if [ "${rc}" -eq 0 ]; then
        printf '%s\n' "${output}"
    elif [ "${rc}" -eq 124 ]; then
        printf '%s\n' '{"lock_classification":"ambiguous_lock","owner_state":"classifier_timeout"}'
    else
        printf '%s\n' '{"lock_classification":"ambiguous_lock","owner_state":"classifier_failed"}'
    fi
}

json_field() {
    if [ -z "${PYTHON_BIN}" ] || [ ! -x "${PYTHON_BIN}" ]; then
        return 0
    fi
    "${PYTHON_BIN}" -c 'import json,sys; print(str(json.load(sys.stdin).get(sys.argv[1], "")))' "$1" 2>/dev/null || true
}

restart_attempts() {
    if [ -f "${ATTEMPT_FILE}" ]; then
        cat "${ATTEMPT_FILE}" 2>/dev/null || printf '0\n'
    else
        printf '0\n'
    fi
}

if systemctl is-active --quiet "${SERVICE_NAME}"; then
    clear_incident_if_recovered
    exit 0
fi

lock_json=$(classify_lock)
classification=$(printf '%s' "${lock_json}" | json_field lock_classification)
owner_state=$(printf '%s' "${lock_json}" | json_field owner_state)
[ -n "${classification}" ] || classification="ambiguous_lock"

case "${classification}" in
    no_lock)
        attempts=$(restart_attempts)
        case "${attempts}" in
            ''|*[!0-9]*) attempts=0 ;;
        esac
        if [ "${attempts}" -ge "${MAX_RESTART_ATTEMPTS}" ]; then
            notify_once "restart_exhausted:${classification}" "KRITIK: Scheduler inactive; restart hakki tükendi. classification=${classification}"
            exit 0
        fi
        pre_start_json=$(classify_lock)
        pre_start_classification=$(printf '%s' "${pre_start_json}" | json_field lock_classification)
        pre_start_owner_state=$(printf '%s' "${pre_start_json}" | json_field owner_state)
        [ -n "${pre_start_classification}" ] || pre_start_classification="ambiguous_lock"
        if [ "${pre_start_classification}" != "no_lock" ]; then
            notify_once "deployment_lock:${pre_start_classification}:${pre_start_owner_state}" "KRITIK: Scheduler inactive ancak restart revalidation ile bastirildi. classification=${pre_start_classification} owner_state=${pre_start_owner_state}"
            exit 0
        fi
        write_state_file "${ATTEMPT_FILE}" "$((attempts + 1))"
        notify_once "normal_crash:${classification}" "ALARM: Para Pusulasi scheduler inactive; deployment lock yok, yeniden baslatiliyor."
        systemctl start "${SERVICE_NAME}"
        if [ "${RESTART_SETTLE_SECONDS}" != "0" ]; then
            sleep "${RESTART_SETTLE_SECONDS}"
        fi
        if systemctl is-active --quiet "${SERVICE_NAME}"; then
            notify "OK: Scheduler yeniden baslatildi."
            rm -f "${OPEN_INCIDENT_FILE}" "${ATTEMPT_FILE}" 2>/dev/null || true
        else
            notify_once "restart_failed:${classification}" "KRITIK: Scheduler baslatilamadi; manuel mudahale gerekiyor. classification=${classification}"
        fi
        ;;
    self_owned_active_lock|foreign_active_lock|stale_lock|malformed_lock|unreadable_lock|ambiguous_lock)
        notify_once "deployment_lock:${classification}:${owner_state}" "KRITIK: Scheduler inactive ancak restart bastirildi. classification=${classification} owner_state=${owner_state}"
        ;;
    *)
        notify_once "deployment_lock:ambiguous:${classification}" "KRITIK: Scheduler inactive ancak bilinmeyen lock classification nedeniyle restart bastirildi. classification=${classification}"
        ;;
esac
