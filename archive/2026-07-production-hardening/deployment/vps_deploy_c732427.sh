#!/usr/bin/env bash
set -Eeuo pipefail

TARGET_SHA="c732427367d782f56c335e52dd063deaa8db3e0d"
REMOTE_REPO="https://github.com/PharmaSahar/para-pusulasi.git"
SERVICE="parapusulasi"
CURRENT_DIR="/opt/parapusulasi"
RELEASES_DIR="/opt/parapusulasi/releases"
RELEASE_DIR="${RELEASES_DIR}/${TARGET_SHA}"
TMP_RELEASE="${RELEASE_DIR}.tmp"
SYMLINK_PATH="/opt/parapusulasi-current"
BACKUP_DIR="/opt/parapusulasi-backups/predeploy-$(date +%Y%m%d-%H%M%S)"
ROLLBACK_ENV="/root/parapusulasi_deploy_rollback.env"
RESULT_ENV="/root/parapusulasi_deploy_result.env"

DEPLOYMENT_RESULT="FAILED"
ROLLBACK_EXECUTED="NO"
SMOKE_TEST="FAIL"
RUNTIME_PATHS_STATUS="FAIL"
SERVICE_ACTIVE="NO"
TARGET_SHA_MATCH="NO"
FRESH_CLEAN="NO"
FINAL_PRODUCTION_STATUS="UNHEALTHY"
ROLLBACK_BACKUP_CREATED="NO"
PREVIOUS_SHA="unknown"
DEPLOYED_SHA="unknown"
SERVICE_MAINPID="0"
PREV_SYMLINK_TARGET=""
SERVICE_SWITCH_ATTEMPTED="NO"

log() { echo "[deploy] $*"; }

write_result() {
  : > "${RESULT_ENV}"
  {
    echo "DEPLOYMENT_RESULT=${DEPLOYMENT_RESULT}"
    echo "PREVIOUS_VPS_SHA=${PREVIOUS_SHA}"
    echo "DEPLOYED_VPS_SHA=${DEPLOYED_SHA}"
    echo "TARGET_SHA_MATCH=${TARGET_SHA_MATCH}"
    echo "SERVICE_ACTIVE=${SERVICE_ACTIVE}"
    echo "SERVICE_MAINPID=${SERVICE_MAINPID}"
    echo "FRESH_RELEASE_WORKTREE_CLEAN=${FRESH_CLEAN}"
    echo "RUNTIME_PATHS_OUTSIDE_TRACKED_DOCS=${RUNTIME_PATHS_STATUS}"
    echo "SMOKE_TEST=${SMOKE_TEST}"
    echo "ROLLBACK_BACKUP_CREATED=${ROLLBACK_BACKUP_CREATED}"
    echo "ROLLBACK_EXECUTED=${ROLLBACK_EXECUTED}"
    echo "FINAL_PRODUCTION_STATUS=${FINAL_PRODUCTION_STATUS}"
    echo "BACKUP_DIR=${BACKUP_DIR}"
    echo "RELEASE_DIR=${RELEASE_DIR}"
    echo "TARGET_SHA=${TARGET_SHA}"
  } >> "${RESULT_ENV}"
}

rollback() {
  local reason="$1"
  log "rollback triggered: ${reason}"
  ROLLBACK_EXECUTED="YES"
  DEPLOYMENT_RESULT="ROLLED BACK"

  systemctl stop "${SERVICE}" >/dev/null 2>&1 || true

  if [[ -n "${PREV_SYMLINK_TARGET}" ]]; then
    ln -sfn "${PREV_SYMLINK_TARGET}" "${SYMLINK_PATH}"
  elif [[ -L "${SYMLINK_PATH}" ]]; then
    rm -f "${SYMLINK_PATH}"
  fi

  mkdir -p /etc/systemd/system/${SERVICE}.service.d
  if [[ -f "${BACKUP_DIR}/service/override.conf.bak" ]]; then
    cp -a "${BACKUP_DIR}/service/override.conf.bak" "/etc/systemd/system/${SERVICE}.service.d/override.conf"
  else
    rm -f "/etc/systemd/system/${SERVICE}.service.d/override.conf"
  fi

  systemctl daemon-reload >/dev/null 2>&1 || true
  systemctl start "${SERVICE}" >/dev/null 2>&1 || true

  if [[ "$(systemctl is-active ${SERVICE} 2>/dev/null || true)" == "active" ]]; then
    SERVICE_ACTIVE="YES"
    SERVICE_MAINPID="$(systemctl show ${SERVICE} -p MainPID --value 2>/dev/null || echo 0)"
  else
    SERVICE_ACTIVE="NO"
    SERVICE_MAINPID="0"
  fi

  if [[ "${SERVICE_ACTIVE}" == "YES" ]]; then
    FINAL_PRODUCTION_STATUS="HEALTHY"
  else
    FINAL_PRODUCTION_STATUS="UNHEALTHY"
  fi

  write_result
  exit 0
}

on_error() {
  local line="$1"
  log "error at line ${line}"
  if [[ "${SERVICE_SWITCH_ATTEMPTED}" == "YES" ]]; then
    rollback "failure after service switch attempt"
  else
    DEPLOYMENT_RESULT="FAILED"
    if [[ "$(systemctl is-active ${SERVICE} 2>/dev/null || true)" == "active" ]]; then
      SERVICE_ACTIVE="YES"
      SERVICE_MAINPID="$(systemctl show ${SERVICE} -p MainPID --value 2>/dev/null || echo 0)"
    fi
    write_result
    exit 0
  fi
}
trap 'on_error $LINENO' ERR

# Phase 1: wait for safe window
log "phase1 wait for safe window"
start_ts="$(date +%s)"
deadline="$((start_ts + 1200))"
while true; do
  reasons=()
  if pgrep -af 'ffmpeg|imageio_ffmpeg' >/dev/null 2>&1; then reasons+=("ffmpeg"); fi
  if pgrep -af 'render|video_creator|shorts_creator' >/dev/null 2>&1; then reasons+=("render"); fi
  if pgrep -af 'youtube_uploader|upload|shorts.*upload' >/dev/null 2>&1; then reasons+=("upload"); fi
  for qf in "${CURRENT_DIR}/output/state/channel_queue.json" "${CURRENT_DIR}/output/runtime/state/channel_queue.json"; do
    if [[ -f "${qf}" ]] && lsof "${qf}" >/dev/null 2>&1; then reasons+=("queue_transaction"); fi
  done
  for lf in /tmp/scheduler_singleton.lock /tmp/production_scheduler.pid; do
    if [[ -e "${lf}" ]]; then reasons+=("critical_lock"); fi
  done

  if [[ ${#reasons[@]} -eq 0 ]]; then
    break
  fi

  now_ts="$(date +%s)"
  if (( now_ts >= deadline )); then
    DEPLOYMENT_RESULT="WAIT"
    PREVIOUS_SHA="$(git -C "${CURRENT_DIR}" rev-parse HEAD 2>/dev/null || echo unknown)"
    DEPLOYED_SHA="${PREVIOUS_SHA}"
    TARGET_SHA_MATCH="NO"
    SERVICE_ACTIVE="$([[ "$(systemctl is-active ${SERVICE} 2>/dev/null || true)" == "active" ]] && echo YES || echo NO)"
    SERVICE_MAINPID="$(systemctl show ${SERVICE} -p MainPID --value 2>/dev/null || echo 0)"
    FRESH_CLEAN="NO"
    FINAL_PRODUCTION_STATUS="$([[ "${SERVICE_ACTIVE}" == "YES" ]] && echo HEALTHY || echo UNHEALTHY)"
    write_result
    exit 0
  fi

  sleep 30

done

# Phase 2: capture rollback state
log "phase2 capture rollback state"
mkdir -p "${BACKUP_DIR}" "${BACKUP_DIR}/service" "${BACKUP_DIR}/env" "${BACKUP_DIR}/meta" "${BACKUP_DIR}/state"
ROLLBACK_BACKUP_CREATED="YES"

PREVIOUS_SHA="$(git -C "${CURRENT_DIR}" rev-parse HEAD 2>/dev/null || echo unknown)"
PREV_BRANCH="$(git -C "${CURRENT_DIR}" rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
MAINPID="$(systemctl show ${SERVICE} -p MainPID --value 2>/dev/null || echo 0)"
EXECSTART="$(systemctl show ${SERVICE} -p ExecStart --value 2>/dev/null || true)"
WORKINGDIR="$(systemctl show ${SERVICE} -p WorkingDirectory --value 2>/dev/null || true)"
FRAGMENT_PATH="$(systemctl show ${SERVICE} -p FragmentPath --value 2>/dev/null || true)"
ENV_FILES_RAW="$(systemctl show ${SERVICE} -p EnvironmentFiles --value 2>/dev/null || true)"

if [[ -L "${SYMLINK_PATH}" ]]; then
  PREV_SYMLINK_TARGET="$(readlink -f "${SYMLINK_PATH}" || true)"
fi

if [[ -f "/etc/systemd/system/${SERVICE}.service.d/override.conf" ]]; then
  cp -a "/etc/systemd/system/${SERVICE}.service.d/override.conf" "${BACKUP_DIR}/service/override.conf.bak"
fi
if [[ -n "${FRAGMENT_PATH}" && -f "${FRAGMENT_PATH}" ]]; then
  cp -a "${FRAGMENT_PATH}" "${BACKUP_DIR}/service/$(basename "${FRAGMENT_PATH}").bak"
fi

git -C "${CURRENT_DIR}" status --short > "${BACKUP_DIR}/meta/current_git_status_short.txt" 2>&1 || true
git -C "${CURRENT_DIR}" diff --name-status > "${BACKUP_DIR}/meta/current_git_diff_name_status.txt" 2>&1 || true
git -C "${CURRENT_DIR}" diff --cached --name-status > "${BACKUP_DIR}/meta/current_git_diff_cached_name_status.txt" 2>&1 || true

cat > "${ROLLBACK_ENV}" <<EOF
TARGET_SHA=${TARGET_SHA}
SERVICE=${SERVICE}
CURRENT_DIR=${CURRENT_DIR}
PREVIOUS_SHA=${PREVIOUS_SHA}
PREVIOUS_BRANCH=${PREV_BRANCH}
MAINPID=${MAINPID}
EXECSTART=${EXECSTART}
WORKINGDIR=${WORKINGDIR}
FRAGMENT_PATH=${FRAGMENT_PATH}
ENV_FILES_RAW=${ENV_FILES_RAW}
PREV_SYMLINK_TARGET=${PREV_SYMLINK_TARGET}
BACKUP_DIR=${BACKUP_DIR}
EOF

if [[ -f "${CURRENT_DIR}/.env" ]]; then cp -a "${CURRENT_DIR}/.env" "${BACKUP_DIR}/env/.env"; fi
if [[ -f "${CURRENT_DIR}/client_secrets.json" ]]; then cp -a "${CURRENT_DIR}/client_secrets.json" "${BACKUP_DIR}/env/client_secrets.json"; fi
for p in $(echo "${ENV_FILES_RAW}" | grep -Eo '/[^ ]+' || true); do
  if [[ -f "${p}" ]]; then cp -a "${p}" "${BACKUP_DIR}/env/"; fi
done

mkdir -p "${BACKUP_DIR}/state/channels"
if [[ -f "${CURRENT_DIR}/channels/channel_registry.json" ]]; then cp -a "${CURRENT_DIR}/channels/channel_registry.json" "${BACKUP_DIR}/state/channels/"; fi
if [[ -f "${CURRENT_DIR}/channels/channels_tracker.csv" ]]; then cp -a "${CURRENT_DIR}/channels/channels_tracker.csv" "${BACKUP_DIR}/state/channels/"; fi
if [[ -d "${CURRENT_DIR}/channels/_pending" ]]; then cp -a "${CURRENT_DIR}/channels/_pending" "${BACKUP_DIR}/state/channels/"; fi

if [[ -d "${CURRENT_DIR}/output/state" ]]; then cp -a "${CURRENT_DIR}/output/state" "${BACKUP_DIR}/state/output_state"; fi
if [[ -d "${CURRENT_DIR}/output/runtime" ]]; then cp -a "${CURRENT_DIR}/output/runtime" "${BACKUP_DIR}/state/output_runtime"; fi
if [[ -d "${CURRENT_DIR}/logs" ]]; then cp -a "${CURRENT_DIR}/logs" "${BACKUP_DIR}/state/logs"; fi
if [[ -f "${CURRENT_DIR}/BUILD_INFO" ]]; then cp -a "${CURRENT_DIR}/BUILD_INFO" "${BACKUP_DIR}/meta/BUILD_INFO"; fi

# Phase 3: create fresh release
log "phase3 fresh checkout"
mkdir -p "${RELEASES_DIR}"
rm -rf "${TMP_RELEASE}"

git clone "${REMOTE_REPO}" "${TMP_RELEASE}"
git -C "${TMP_RELEASE}" fetch --all --tags --prune
git -C "${TMP_RELEASE}" checkout --detach "${TARGET_SHA}"

if [[ "$(git -C "${TMP_RELEASE}" rev-parse HEAD)" != "${TARGET_SHA}" ]]; then
  rollback "target sha mismatch in tmp release"
fi

if [[ -n "$(git -C "${TMP_RELEASE}" status --short)" ]]; then
  rollback "tmp release worktree not clean"
fi

if [[ -e "${RELEASE_DIR}" ]]; then
  mv "${RELEASE_DIR}" "${RELEASE_DIR}.prev.$(date +%s)"
fi
mv "${TMP_RELEASE}" "${RELEASE_DIR}"

# Phase 4: restore production-only data
log "phase4 restore production data"
mkdir -p "${RELEASE_DIR}/output/runtime/state" "${RELEASE_DIR}/output/runtime/logs" "${RELEASE_DIR}/output/runtime/telemetry" "${RELEASE_DIR}/output/state" "${RELEASE_DIR}/logs"

if [[ -f "${CURRENT_DIR}/.env" ]]; then cp -a "${CURRENT_DIR}/.env" "${RELEASE_DIR}/.env"; fi
if [[ -f "${CURRENT_DIR}/client_secrets.json" ]]; then cp -a "${CURRENT_DIR}/client_secrets.json" "${RELEASE_DIR}/client_secrets.json"; fi
if [[ -f "${CURRENT_DIR}/youtube_token.pickle" ]]; then cp -a "${CURRENT_DIR}/youtube_token.pickle" "${RELEASE_DIR}/youtube_token.pickle"; fi
if [[ -f "${CURRENT_DIR}/token.json" ]]; then cp -a "${CURRENT_DIR}/token.json" "${RELEASE_DIR}/token.json"; fi
if [[ -f "${CURRENT_DIR}/token_analytics.json" ]]; then cp -a "${CURRENT_DIR}/token_analytics.json" "${RELEASE_DIR}/token_analytics.json"; fi
if [[ -f "${CURRENT_DIR}/youtube_playlists.json" ]]; then cp -a "${CURRENT_DIR}/youtube_playlists.json" "${RELEASE_DIR}/youtube_playlists.json"; fi

mkdir -p "${RELEASE_DIR}/channels"
if [[ -f "${CURRENT_DIR}/channels/channel_registry.json" ]]; then cp -a "${CURRENT_DIR}/channels/channel_registry.json" "${RELEASE_DIR}/channels/channel_registry.json"; fi
if [[ -d "${CURRENT_DIR}/channels/_pending" ]]; then
  rm -rf "${RELEASE_DIR}/channels/_pending"
  cp -a "${CURRENT_DIR}/channels/_pending" "${RELEASE_DIR}/channels/_pending"
fi

# Restore channel-scoped credentials/tokens required by ready-channel discovery.
if [[ -d "${CURRENT_DIR}/channels" ]]; then
  while IFS= read -r src_file; do
    rel_path="${src_file#${CURRENT_DIR}/}"
    dst_file="${RELEASE_DIR}/${rel_path}"
    mkdir -p "$(dirname "${dst_file}")"
    cp -a "${src_file}" "${dst_file}"
  done < <(find "${CURRENT_DIR}/channels" -type f \( -name 'youtube_token.pickle' -o -name 'token.json' -o -name 'token_analytics.json' -o -name 'client_secrets.json' \))
fi

if [[ -d "${CURRENT_DIR}/output/state" ]]; then cp -a "${CURRENT_DIR}/output/state/." "${RELEASE_DIR}/output/state/"; fi
if [[ -d "${CURRENT_DIR}/output/runtime" ]]; then cp -a "${CURRENT_DIR}/output/runtime/." "${RELEASE_DIR}/output/runtime/"; fi
if [[ -d "${CURRENT_DIR}/logs" ]]; then cp -a "${CURRENT_DIR}/logs/." "${RELEASE_DIR}/logs/"; fi

if [[ -f "${RELEASE_DIR}/.env" ]]; then
  grep -q '^RUNTIME_OUTPUT_ROOT=' "${RELEASE_DIR}/.env" || echo 'RUNTIME_OUTPUT_ROOT=output/runtime' >> "${RELEASE_DIR}/.env"
  grep -q '^PRODUCTION_DASHBOARD_MD_PATH=' "${RELEASE_DIR}/.env" || echo 'PRODUCTION_DASHBOARD_MD_PATH=output/runtime/state/production_dashboard_latest.md' >> "${RELEASE_DIR}/.env"
  grep -q '^PRODUCTION_DASHBOARD_JSON_PATH=' "${RELEASE_DIR}/.env" || echo 'PRODUCTION_DASHBOARD_JSON_PATH=output/runtime/state/production_dashboard_latest.json' >> "${RELEASE_DIR}/.env"
  grep -q '^PRODUCTION_OBSERVABILITY_LATEST_PATH=' "${RELEASE_DIR}/.env" || echo 'PRODUCTION_OBSERVABILITY_LATEST_PATH=output/runtime/telemetry/production_observability_latest.json' >> "${RELEASE_DIR}/.env"
  grep -q '^GOVERNANCE_READINESS_MD_PATH=' "${RELEASE_DIR}/.env" || echo 'GOVERNANCE_READINESS_MD_PATH=output/runtime/state/governance_readiness_latest.md' >> "${RELEASE_DIR}/.env"
  grep -q '^INCIDENT_STATE_FILE=' "${RELEASE_DIR}/.env" || echo 'INCIDENT_STATE_FILE=output/state/incident_state.json' >> "${RELEASE_DIR}/.env"
  grep -q '^INCIDENT_EVENTS_FILE=' "${RELEASE_DIR}/.env" || echo 'INCIDENT_EVENTS_FILE=logs/production_incidents.jsonl' >> "${RELEASE_DIR}/.env"
  grep -q '^INCIDENT_METRICS_FILE=' "${RELEASE_DIR}/.env" || echo 'INCIDENT_METRICS_FILE=output/state/incident_metrics_latest.json' >> "${RELEASE_DIR}/.env"
  grep -q '^CHANNEL_CONFIG_PATH=' "${RELEASE_DIR}/.env" || echo 'CHANNEL_CONFIG_PATH=channels/channel_registry.json' >> "${RELEASE_DIR}/.env"
  grep -q '^YOUTUBE_TOKEN_FILE=' "${RELEASE_DIR}/.env" || echo 'YOUTUBE_TOKEN_FILE=youtube_token.pickle' >> "${RELEASE_DIR}/.env"
  grep -q '^YOUTUBE_ANALYTICS_TOKEN_FILE=' "${RELEASE_DIR}/.env" || echo 'YOUTUBE_ANALYTICS_TOKEN_FILE=youtube_token.pickle' >> "${RELEASE_DIR}/.env"
  grep -q '^UPLOAD_ENABLED=' "${RELEASE_DIR}/.env" || echo 'UPLOAD_ENABLED=true' >> "${RELEASE_DIR}/.env"
  grep -q '^SHORTS_UPLOAD_ENABLED=' "${RELEASE_DIR}/.env" || echo 'SHORTS_UPLOAD_ENABLED=true' >> "${RELEASE_DIR}/.env"
  grep -q '^PREPROD_ISOLATION_MODE=' "${RELEASE_DIR}/.env" || echo 'PREPROD_ISOLATION_MODE=false' >> "${RELEASE_DIR}/.env"
fi

SERVICE_USER="$(systemctl show ${SERVICE} -p User --value 2>/dev/null || true)"
SERVICE_GROUP="$(systemctl show ${SERVICE} -p Group --value 2>/dev/null || true)"
[[ -z "${SERVICE_USER}" ]] && SERVICE_USER="root"
[[ -z "${SERVICE_GROUP}" ]] && SERVICE_GROUP="${SERVICE_USER}"
chown -R "${SERVICE_USER}:${SERVICE_GROUP}" "${RELEASE_DIR}/output" "${RELEASE_DIR}/logs"

# Phase 5: python environment
log "phase5 python setup and tests"
python3 -m venv "${RELEASE_DIR}/venv"
PYBIN="${RELEASE_DIR}/venv/bin/python"
PIPBIN="${RELEASE_DIR}/venv/bin/pip"

if [[ -f "${RELEASE_DIR}/requirements.txt" ]]; then
  "${PIPBIN}" install -r "${RELEASE_DIR}/requirements.txt"
fi

if ! "${RELEASE_DIR}/venv/bin/python" -m pytest --version >/dev/null 2>&1; then
  "${PIPBIN}" install pytest
fi

cd "${RELEASE_DIR}"
for mod in scheduler.py src/scheduler_utils.py src/production_quality_platform.py src/pipeline.py src/content_generator.py; do
  if [[ -f "${mod}" ]]; then
    "${PYBIN}" -m py_compile "${mod}"
  fi
done

PREPROD_ISOLATION_MODE=false SCHEDULE_ENABLED=false UPLOAD_ENABLED=false SHORTS_UPLOAD_ENABLED=false \
PREPROD_STATE_ROOT="${RELEASE_DIR}/output/runtime" HOME="${RELEASE_DIR}/output/runtime/home" XDG_CACHE_HOME="${RELEASE_DIR}/output/runtime/cache" \
SCHEDULER_LOG_FILE="${RELEASE_DIR}/output/runtime/logs/scheduler.log" TELEMETRY_SINK_DIR="${RELEASE_DIR}/output/runtime/telemetry" \
SCHEDULER_QUEUE_FILE="${RELEASE_DIR}/output/runtime/state/channel_queue.json" SCHEDULER_PID_FILE="${RELEASE_DIR}/output/runtime/state/scheduler.pid" \
ACTIVATION_CONTROLLER_REPORT_ARCHIVE_DIR="${RELEASE_DIR}/output/state/activation_reports" \
GOVERNANCE_READINESS_MD_PATH="${RELEASE_DIR}/output/runtime/state/governance_readiness_latest.md" \
PRODUCTION_DASHBOARD_MD_PATH="${RELEASE_DIR}/output/runtime/state/production_dashboard_latest.md" \
YOUTUBE_CLIENT_ID=preprod-disabled YOUTUBE_CLIENT_SECRET=preprod-disabled ANTHROPIC_API_KEY=preprod-disabled \
ELEVENLABS_API_KEY=preprod-disabled TELEGRAM_BOT_TOKEN=preprod-disabled \
"${PYBIN}" -m pytest -q \
  tests/test_scheduler_provider_guardrails.py \
  tests/test_scheduler_topic_domain_guard.py \
  tests/test_ops_runtime_layers.py \
  tests/test_observability_incident_safety.py || rollback "targeted safe tests failed"

# Phase 6: pre-start validation
log "phase6 pre-start validation"
if [[ "$(git -C "${RELEASE_DIR}" rev-parse HEAD)" == "${TARGET_SHA}" ]]; then TARGET_SHA_MATCH="YES"; else rollback "prestart target sha mismatch"; fi
if [[ -z "$(git -C "${RELEASE_DIR}" status --short)" ]]; then FRESH_CLEAN="YES"; else rollback "release worktree dirty before start"; fi

RUNTIME_CHECK="$(${PYBIN} - <<'PY'
from src import production_quality_platform as p
from ops import refresh_governance_readiness as r
print(str(p.PRODUCTION_DASHBOARD_MD_PATH))
print(str(r._resolve_readiness_markdown()))
PY
)"
RUNTIME_DASH_PATH="$(echo "${RUNTIME_CHECK}" | sed -n '1p')"
GOV_PATH="$(echo "${RUNTIME_CHECK}" | sed -n '2p')"
if [[ "${RUNTIME_DASH_PATH}" == docs/* || "${RUNTIME_DASH_PATH}" == */docs/* ]]; then rollback "runtime dashboard path under docs"; fi
if [[ "${GOV_PATH}" == docs/* || "${GOV_PATH}" == */docs/* ]]; then rollback "governance path under docs"; fi
RUNTIME_PATHS_STATUS="PASS"

for req in ANTHROPIC_API_KEY OPENAI_API_KEY YOUTUBE_CLIENT_ID YOUTUBE_CLIENT_SECRET TELEGRAM_BOT_TOKEN YOUTUBE_TOKEN_FILE YOUTUBE_ANALYTICS_TOKEN_FILE CHANNEL_CONFIG_PATH RUNTIME_OUTPUT_ROOT PRODUCTION_DASHBOARD_MD_PATH PRODUCTION_DASHBOARD_JSON_PATH PRODUCTION_OBSERVABILITY_LATEST_PATH GOVERNANCE_READINESS_MD_PATH INCIDENT_STATE_FILE INCIDENT_EVENTS_FILE INCIDENT_METRICS_FILE SCHEDULE_ENABLED UPLOAD_ENABLED SHORTS_UPLOAD_ENABLED PREPROD_ISOLATION_MODE; do
  if ! grep -q "^${req}=" "${RELEASE_DIR}/.env"; then rollback "missing required env key ${req}"; fi
  val="$(grep "^${req}=" "${RELEASE_DIR}/.env" | tail -n1 | cut -d= -f2-)"
  if [[ -z "${val}" ]]; then rollback "empty required env key ${req}"; fi
done

for cred in client_secrets.json "$(grep '^YOUTUBE_TOKEN_FILE=' .env | tail -n1 | cut -d= -f2-)" "$(grep '^YOUTUBE_ANALYTICS_TOKEN_FILE=' .env | tail -n1 | cut -d= -f2-)"; do
  [[ -z "${cred}" ]] && continue
  if [[ ! -f "${RELEASE_DIR}/${cred}" ]]; then rollback "missing credential file ${cred}"; fi
done

"${PYBIN}" - <<'PY'
import json
from pathlib import Path
p = Path('channels/channel_registry.json')
json.loads(p.read_text(encoding='utf-8'))
print('channel_config_ok')
PY

avail_kb="$(df -Pk "${RELEASE_DIR}" | awk 'NR==2{print $4}')"
if (( avail_kb < 1048576 )); then rollback "insufficient disk space"; fi

for rp in output/runtime/state/production_dashboard_latest.md output/runtime/state/governance_readiness_latest.md; do
  if git -C "${RELEASE_DIR}" ls-files --error-unmatch "${rp}" >/dev/null 2>&1; then rollback "runtime output path tracked by git: ${rp}"; fi
done

if grep -RIn 'export_runtime_dashboard_to_docs\(' scheduler.py src >/dev/null 2>&1; then
  if grep -RIn 'export_runtime_dashboard_to_docs\(' scheduler.py src | grep -v '^ops/' >/dev/null 2>&1; then
    rollback "unexpected automatic docs dashboard export call found"
  fi
fi

mkdir -p /tmp/predeploy_preflight_artifacts
PREPROD_ISOLATION_MODE=true SCHEDULE_ENABLED=false UPLOAD_ENABLED=false SHORTS_UPLOAD_ENABLED=false \
YOUTUBE_CLIENT_ID=preprod-disabled YOUTUBE_CLIENT_SECRET=preprod-disabled ANTHROPIC_API_KEY=preprod-disabled \
ELEVENLABS_API_KEY=preprod-disabled TELEGRAM_BOT_TOKEN=preprod-disabled \
"${PYBIN}" ops/preprod_validation_runner.py diagnose --artifacts-dir /tmp/predeploy_preflight_artifacts >/tmp/predeploy_diagnose.json || rollback "preflight diagnose failed"

# Phase 7: atomic service switch
log "phase7 service switch"
SERVICE_SWITCH_ATTEMPTED="YES"
mkdir -p /etc/systemd/system/${SERVICE}.service.d
cat > "/etc/systemd/system/${SERVICE}.service.d/override.conf" <<EOF
[Service]
WorkingDirectory=/opt/parapusulasi-current
ExecStart=
ExecStart=/opt/parapusulasi-current/venv/bin/python /opt/parapusulasi-current/scheduler.py
EOF

ln -sfn "${RELEASE_DIR}" "${SYMLINK_PATH}"
systemctl stop "${SERVICE}"
for _ in $(seq 1 60); do
  mp="$(systemctl show ${SERVICE} -p MainPID --value 2>/dev/null || echo 0)"
  [[ "${mp}" == "0" ]] && break
  sleep 1
done
systemctl daemon-reload
systemctl start "${SERVICE}"

# Phase 8: post-deploy smoke
log "phase8 smoke checks"
smoke_deadline="$(( $(date +%s) + 120 ))"
while true; do
  state="$(systemctl is-active ${SERVICE} 2>/dev/null || true)"
  pid="$(systemctl show ${SERVICE} -p MainPID --value 2>/dev/null || echo 0)"
  cmd="$(ps -p "${pid}" -o args= 2>/dev/null || true)"
  if [[ "${state}" == "active" && "${pid}" != "0" && "${cmd}" == *"/opt/parapusulasi-current"* ]]; then
    break
  fi
  if (( $(date +%s) >= smoke_deadline )); then rollback "service failed 120s smoke startup checks"; fi
  sleep 5
done

journalctl -u "${SERVICE}" -n 200 --no-pager > /tmp/parapusulasi_post_start.log || true
if grep -Ei 'Traceback|fatal|segmentation fault|panic' /tmp/parapusulasi_post_start.log >/dev/null 2>&1; then
  rollback "fatal errors found in journal after start"
fi

mkdir -p "${RELEASE_DIR}/output/runtime/state"
cat > "${RELEASE_DIR}/output/runtime/state/BUILD_INFO" <<EOF
TARGET_SHA=${TARGET_SHA}
DEPLOYED_AT_UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)
RELEASE_DIR=${RELEASE_DIR}
EOF

if [[ "$(git -C "${RELEASE_DIR}" rev-parse HEAD)" != "${TARGET_SHA}" ]]; then rollback "deployed head mismatch after start"; fi
if [[ -n "$(git -C "${RELEASE_DIR}" status --short)" ]]; then rollback "release worktree mutated after start"; fi

if grep -Ei 'youtube.*upload|upload.*youtube|shorts.*upload' /tmp/parapusulasi_post_start.log >/dev/null 2>&1; then
  rollback "live upload activity detected during smoke window"
fi

end_wait="$(( $(date +%s) + 300 ))"
base_pid="$(systemctl show ${SERVICE} -p MainPID --value 2>/dev/null || echo 0)"
while (( $(date +%s) < end_wait )); do
  st="$(systemctl is-active ${SERVICE} 2>/dev/null || true)"
  mp="$(systemctl show ${SERVICE} -p MainPID --value 2>/dev/null || echo 0)"
  [[ "${st}" == "active" && "${mp}" != "0" ]] || rollback "service not stable in 5 minute window"
  sleep 10
done

journalctl -u "${SERVICE}" -n 400 --no-pager > /tmp/parapusulasi_post_wait.log || true
if grep -Ei 'Traceback|fatal|segmentation fault|panic' /tmp/parapusulasi_post_wait.log >/dev/null 2>&1; then
  rollback "fatal errors in extended smoke window"
fi
if grep -Ei 'telegram.*(exception|traceback|failed)' /tmp/parapusulasi_post_wait.log >/dev/null 2>&1; then
  rollback "telegram notifier stability check failed"
fi

SMOKE_TEST="PASS"
SERVICE_ACTIVE="YES"
SERVICE_MAINPID="$(systemctl show ${SERVICE} -p MainPID --value 2>/dev/null || echo 0)"
DEPLOYED_SHA="$(git -C "${RELEASE_DIR}" rev-parse HEAD 2>/dev/null || echo unknown)"
TARGET_SHA_MATCH="$([[ "${DEPLOYED_SHA}" == "${TARGET_SHA}" ]] && echo YES || echo NO)"
FRESH_CLEAN="$([[ -z "$(git -C "${RELEASE_DIR}" status --short)" ]] && echo YES || echo NO)"
RUNTIME_PATHS_STATUS="PASS"
DEPLOYMENT_RESULT="SUCCESS"
FINAL_PRODUCTION_STATUS="HEALTHY"

write_result
exit 0
