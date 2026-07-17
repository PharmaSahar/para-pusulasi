#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_NAME="immutable_release_v2"
APPROVED_SERVICE="parapusulasi"
SERVICE_NAME="${APPROVED_SERVICE}"

DEFAULT_RELEASES_ROOT="/opt/parapusulasi/releases"
DEFAULT_CURRENT_LINK="/opt/parapusulasi-current"
DEFAULT_DEPLOY_STATE_ROOT="/opt/parapusulasi/deploy-state"
DEFAULT_SHARED_ROOT="/opt/parapusulasi-shared"
DEFAULT_OPERATOR_ROOT="/opt/parapusulasi"
DEFAULT_LOCK_DIR="/opt/parapusulasi/deploy.lock"
DEFAULT_ENFORCE_GIT_RELEASE_IDENTITY="0"

RELEASES_ROOT="${IMMUTABLE_V2_RELEASES_ROOT:-$DEFAULT_RELEASES_ROOT}"
CURRENT_LINK="${IMMUTABLE_V2_CURRENT_LINK:-$DEFAULT_CURRENT_LINK}"
DEPLOY_STATE_ROOT="${IMMUTABLE_V2_DEPLOY_STATE_ROOT:-$DEFAULT_DEPLOY_STATE_ROOT}"
SHARED_ROOT="${IMMUTABLE_V2_SHARED_ROOT:-$DEFAULT_SHARED_ROOT}"
OPERATOR_ROOT="${IMMUTABLE_V2_OPERATOR_ROOT:-$DEFAULT_OPERATOR_ROOT}"
LOCK_DIR="${IMMUTABLE_V2_LOCK_DIR:-$DEFAULT_LOCK_DIR}"
ENFORCE_GIT_RELEASE_IDENTITY="${IMMUTABLE_V2_ENFORCE_GIT_RELEASE_IDENTITY:-$DEFAULT_ENFORCE_GIT_RELEASE_IDENTITY}"
MIN_FREE_KB="${IMMUTABLE_V2_MIN_FREE_KB:-1048576}"
LOCK_DIR_PREEXISTED="false"

TARGET_REF=""
TARGET_SHA=""
ROLLBACK_SHA=""
MODE=""
DRY_RUN="false"
AUTO_ROLLBACK="false"

PREPARED_RELEASE=""
ROLLBACK_TARGET_BEFORE_SWITCH=""
LOCK_ACQUIRED="false"
PREPARE_STAGING_DIR=""
PREPARE_TARGET_RELEASE=""
PREPARE_STAGING_CREATED="false"
PREPARE_FINALIZED="false"
PRECHECK_PATH_EVIDENCE_JSON="[]"
PREPARE_BOOTSTRAP_CREATED_RELATIVE_PATHS=""
PREPARE_FAILURE_PHASE=""
PREPARE_FAILURE_SUMMARY=""
PREPARE_ACTIVE_TARGET=""
PREPARE_ACTIVE_RELEASE_SHA=""
PRECHECK_ANALYTICS_REPORT_JSON='{}'
PRECHECK_ANALYTICS_COMMAND=""
PRECHECK_ANALYTICS_STDOUT_JSON='""'
PRECHECK_ANALYTICS_STDERR_JSON='""'
PRECHECK_HEALTH_STDOUT_JSON='""'
PRECHECK_HEALTH_STDERR_JSON='""'
PRECHECK_HEALTH_WARNINGS_JSON='[]'
PRECHECK_HEALTH_COMMAND=""

usage() {
  cat <<'EOF'
Usage:
  deploy/immutable_release_v2.sh \
    --target-ref <remote-branch-or-tag> \
    --target-sha <full-sha> \
    --mode plan|prepare|cutover|rollback \
    [--rollback-sha <full-sha>] \
    [--auto-rollback] \
    [--dry-run]

Notes:
- This workflow never edits systemd unit/drop-in files.
- This workflow never appends or edits .env content.
- Service restart is allowed only in cutover and rollback modes.
- Automatic rollback in cutover mode is disabled by default and requires --auto-rollback.
EOF
}

log() {
  printf '[%s] %s\n' "$SCRIPT_NAME" "$*"
}

die() {
  PREPARE_FAILURE_SUMMARY="$(printf '%s' "$*" | tr '\n' ' ' | sed 's/[[:space:]]\+/ /g' | sed 's/^ //; s/ $//')"
  log "ERROR: $*"
  exit 1
}

is_full_sha() {
  [[ "$1" =~ ^[0-9a-f]{40}$ ]]
}

is_approved_target_ref() {
  local ref="$1"
  [[ "$ref" =~ ^origin/(master|release/[A-Za-z0-9._/-]+|hotfix/[A-Za-z0-9._/-]+)$ ]] || [[ "$ref" =~ ^refs/tags/[A-Za-z0-9._-]+$ ]]
}

canon_path() {
  python3 - "$1" <<'PY'
from pathlib import Path
import sys
p = Path(sys.argv[1])
if p.exists():
    print(p.resolve())
else:
    print(p.parent.resolve() / p.name)
PY
}

is_within_root() {
  local path="$1"
  local root="$2"
  local path_real root_real
  path_real="$(canon_path "$path")"
  root_real="$(canon_path "$root")"
  case "$path_real" in
    "$root_real"|"$root_real"/*) return 0 ;;
    *) return 1 ;;
  esac
}

run_cmd() {
  if [[ "$DRY_RUN" == "true" ]]; then
    log "DRY-RUN: $*"
    return 0
  fi
  "$@"
}

require_binary() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required binary: $1"
}

assert_local_repo_clean_if_present() {
  if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    local status
    status="$(git status --porcelain)"
    [[ -z "$status" ]] || die "Dirty local repository is not allowed"
  fi
}

assert_policy_prohibitions() {
  # Enforce explicit runtime policy in one place.
  [[ "$MODE" == "plan" || "$MODE" == "prepare" || "$MODE" == "cutover" || "$MODE" == "rollback" ]] || die "Unsupported mode"
}

assert_service_name() {
  [[ "$SERVICE_NAME" == "$APPROVED_SERVICE" ]] || die "Service name must be '$APPROVED_SERVICE'"
}

assert_paths_approved() {
  if [[ "${IMMUTABLE_V2_ALLOW_NON_OPT_ROOTS:-0}" == "1" ]]; then
    return 0
  fi
  is_within_root "$RELEASES_ROOT" "/opt/parapusulasi/releases" || {
    [[ "$RELEASES_ROOT" == /tmp/* ]] || die "Releases root must be under /opt/parapusulasi/releases (or /tmp/* for tests)"
  }
  is_within_root "$CURRENT_LINK" "/opt" || {
    [[ "$CURRENT_LINK" == /tmp/* ]] || die "Current symlink must be under /opt (or /tmp/* for tests)"
  }
  is_within_root "$DEPLOY_STATE_ROOT" "/opt/parapusulasi" || {
    [[ "$DEPLOY_STATE_ROOT" == /tmp/* ]] || die "Deploy state root must be under /opt/parapusulasi (or /tmp/* for tests)"
  }
}

fetch_remote_if_needed() {
  if [[ "${IMMUTABLE_V2_SKIP_FETCH:-0}" == "1" ]]; then
    log "Skipping remote fetch due to IMMUTABLE_V2_SKIP_FETCH=1"
    return 0
  fi
  run_cmd git fetch --all --prune
}

assert_target_ref_and_sha() {
  is_full_sha "$TARGET_SHA" || die "--target-sha must be a full 40-char SHA"
  is_approved_target_ref "$TARGET_REF" || die "Unapproved target ref: $TARGET_REF"

  git rev-parse --verify "$TARGET_SHA^{commit}" >/dev/null 2>&1 || die "Target SHA not found locally: $TARGET_SHA"
  git rev-parse --verify "$TARGET_REF^{commit}" >/dev/null 2>&1 || die "Target ref not found locally after fetch: $TARGET_REF"

  local ref_tip
  ref_tip="$(git rev-parse "$TARGET_REF^{commit}")"
  git merge-base --is-ancestor "$TARGET_SHA" "$ref_tip" || die "Target SHA $TARGET_SHA is not reachable from $TARGET_REF"

  # Reject local-only commits: must exist in at least one origin/* ref.
  local contains
  contains="$(git branch -r --contains "$TARGET_SHA" | tr -d '[:space:]')"
  [[ -n "$contains" ]] || die "Target SHA appears local-only (not contained in any remote branch)"
}

release_dir_for_sha() {
  printf '%s/%s\n' "$RELEASES_ROOT" "$1"
}

staging_dir_for_sha() {
  printf '%s/.staging-%s\n' "$RELEASES_ROOT" "$1"
}

preflight_json_path() {
  printf '%s/deployment_preflight.json\n' "$1"
}

release_meta_path() {
  printf '%s/.immutable_release_metadata.json\n' "$1"
}

capture_active_target() {
  [[ -L "$CURRENT_LINK" ]] || die "Missing active symlink: $CURRENT_LINK"
  local target
  target="$(readlink "$CURRENT_LINK")"
  [[ -n "$target" ]] || die "Failed to read active symlink target"
  if [[ "$target" != /* ]]; then
    target="$(dirname "$CURRENT_LINK")/$target"
  fi
  target="$(canon_path "$target")"
  is_within_root "$target" "$RELEASES_ROOT" || die "Active symlink target escapes approved release root: $target"
  printf '%s\n' "$target"
}

check_disk_space() {
  local avail
  avail="$(df -Pk "$RELEASES_ROOT" | awk 'NR==2 {print $4}')"
  [[ "$avail" =~ ^[0-9]+$ ]] || die "Unable to resolve free disk space"
  (( avail >= MIN_FREE_KB )) || die "Insufficient disk space: ${avail}KB available, need ${MIN_FREE_KB}KB"
}

write_release_metadata() {
  local release_dir="$1"
  local path
  path="$(release_meta_path "$release_dir")"
  if [[ "$DRY_RUN" == "true" ]]; then
    log "DRY-RUN: write metadata to $path"
    return 0
  fi
  cat > "$path" <<EOF
{
  "release_sha": "$TARGET_SHA",
  "target_ref": "$TARGET_REF",
  "created_at_utc": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "status": "prepared"
}
EOF
}

is_truthy() {
  local raw
  raw="$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')"
  [[ "$raw" == "1" || "$raw" == "true" || "$raw" == "yes" || "$raw" == "on" ]]
}

release_metadata_sha() {
  local release_dir="$1"
  local meta
  meta="$(release_meta_path "$release_dir")"
  [[ -f "$meta" ]] || return 1
  python3 - <<PY
import json
from pathlib import Path
p = Path('$meta')
print(json.loads(p.read_text(encoding='utf-8')).get('release_sha', ''))
PY
}

assert_release_integrity_contract() {
  local release_dir="$1"
  local expected_sha="$2"
  local basename meta_sha
  local head_sha status

  [[ -d "$release_dir" ]] || die "FAIL_RELEASE_INTEGRITY: release directory missing: $release_dir"

  basename="$(basename "$release_dir")"
  [[ "$basename" == "$expected_sha" ]] || die "FAIL_RELEASE_INTEGRITY: release basename ($basename) != expected sha ($expected_sha)"

  meta_sha="$(release_metadata_sha "$release_dir" || true)"
  [[ -n "$meta_sha" ]] || die "FAIL_RELEASE_INTEGRITY: deployment manifest missing release_sha: $(release_meta_path "$release_dir")"
  [[ "$meta_sha" == "$expected_sha" ]] || die "FAIL_RELEASE_INTEGRITY: deployment manifest sha ($meta_sha) != expected sha ($expected_sha)"

  if git -C "$release_dir" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    head_sha="$(git -C "$release_dir" rev-parse HEAD)"
    [[ "$head_sha" == "$expected_sha" ]] || die "FAIL_RELEASE_INTEGRITY: release git HEAD ($head_sha) != expected sha ($expected_sha)"
    [[ "$basename" == "$head_sha" ]] || die "FAIL_RELEASE_INTEGRITY: release basename ($basename) != release git HEAD ($head_sha)"

    status="$(git -C "$release_dir" status --short)"
    [[ -z "$status" ]] || die "FAIL_RELEASE_INTEGRITY: release git worktree dirty"

    git -C "$release_dir" diff-index --quiet HEAD -- || die "FAIL_RELEASE_INTEGRITY: release has tracked modifications"
    git -C "$release_dir" cat-file -e "$expected_sha^{commit}" >/dev/null 2>&1 || die "FAIL_RELEASE_INTEGRITY: expected commit object missing in release git object store"
    git -C "$release_dir" merge-base --is-ancestor "$expected_sha" HEAD || die "FAIL_RELEASE_INTEGRITY: expected sha is not ancestor of release HEAD"
    return 0
  fi

  if is_truthy "$ENFORCE_GIT_RELEASE_IDENTITY"; then
    die "FAIL_RELEASE_INTEGRITY: release git identity missing for $release_dir"
  fi
}

write_preflight_json() {
  local release_dir="$1"
  local scheduler_import="$2"
  local uploader_import="$3"
  local wrapper_import="$4"
  local health_check="$5"
  local path
  path="$(preflight_json_path "$release_dir")"
  if [[ "$DRY_RUN" == "true" ]]; then
    log "DRY-RUN: write preflight report to $path"
    return 0
  fi
  cat > "$path" <<EOF
{
  "release_sha": "$TARGET_SHA",
  "target_ref": "$TARGET_REF",
  "timestamp_utc": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "path_evidence": $PRECHECK_PATH_EVIDENCE_JSON,
  "analytics_credential_evidence": {
    "command": $(python3 -c 'import json,sys; print(json.dumps(sys.argv[1], ensure_ascii=False))' "$PRECHECK_ANALYTICS_COMMAND"),
    "stdout": $PRECHECK_ANALYTICS_STDOUT_JSON,
    "stderr": $PRECHECK_ANALYTICS_STDERR_JSON,
    "report": $PRECHECK_ANALYTICS_REPORT_JSON
  },
  "health_evidence": {
    "command": $(python3 -c 'import json,sys; print(json.dumps(sys.argv[1], ensure_ascii=False))' "$PRECHECK_HEALTH_COMMAND"),
    "cwd": $(python3 -c 'import json,sys; print(json.dumps(sys.argv[1], ensure_ascii=False))' "$release_dir"),
    "stdout": $PRECHECK_HEALTH_STDOUT_JSON,
    "stderr": $PRECHECK_HEALTH_STDERR_JSON,
    "warnings": $PRECHECK_HEALTH_WARNINGS_JSON
  },
  "validations": [
    {"name": "python_syntax", "status": "pass"},
    {"name": "scheduler_import", "status": "$scheduler_import"},
    {"name": "uploader_import", "status": "$uploader_import"},
    {"name": "wrapper_import", "status": "$wrapper_import"},
    {"name": "scheduler_health_check", "status": "$health_check"}
  ]
}
EOF
}

assert_no_forbidden_payload() {
  local release_dir="$1"
  local forbidden
  forbidden="$(find "$release_dir" -maxdepth 3 -type f \( -name '*.log' -o -name '*.jsonl' -o -name '*.sqlite' \) | head -n 1 || true)"
  [[ -z "$forbidden" ]] || die "Unexpected deployment payload file in release source: $forbidden"
}

remove_exported_runtime_payload() {
  local staging_root="$1"
  local active_target="$2"
  local rel candidate src expected_resolved actual_resolved tracked_paths tracked_rel entry entry_type

  is_within_root "$staging_root" "$RELEASES_ROOT" || die "Staging root escapes approved releases root: $staging_root"
  [[ "$staging_root" != "$active_target" ]] || die "Active release cannot be sanitized as staging payload: $staging_root"
  [[ "$PREPARE_STAGING_CREATED" == "true" ]] || die "Runtime payload sanitization requires invocation-owned staging"
  [[ ! -e "$PREPARE_TARGET_RELEASE" ]] || die "Prepared release unexpectedly exists before runtime payload sanitization: $PREPARE_TARGET_RELEASE"

  for rel in logs output; do
    candidate="$staging_root/$rel"
    src="$(resolve_asset_source "$rel" "$active_target")"
    expected_resolved="$(canon_path "$src")"

    [[ -e "$candidate" ]] || continue
    is_within_root "$(dirname "$candidate")" "$staging_root" || die "Staging runtime payload escapes staging root: $candidate"

    if [[ -L "$candidate" ]]; then
      actual_resolved="$(canon_path "$candidate")"
      [[ "$actual_resolved" == "$expected_resolved" ]] || die "Staging destination symlink mismatch for $rel: $actual_resolved (expected $expected_resolved)"
      continue
    fi

    [[ -d "$candidate" ]] || die "Exported runtime payload is not a directory: $candidate"

    tracked_paths="$(git ls-tree -r --name-only "$TARGET_SHA" -- "$rel")"
    if [[ -z "$tracked_paths" ]]; then
      if find "$candidate" -mindepth 1 -print -quit | grep -q .; then
        local entries
        entries="$(find "$candidate" -mindepth 1 -maxdepth 2 -print | head -n 20 | sed 's|^|  - |')"
        die "Unexpected staging payload for untracked runtime directory: $candidate\n$entries"
      fi
      continue
    fi

    local normalized_tracked_paths=""

    while IFS= read -r tracked_rel; do
      [[ -n "$tracked_rel" ]] || continue
      tracked_rel="${tracked_rel#"$rel"/}"
      normalized_tracked_paths+="$tracked_rel"
      normalized_tracked_paths+=$'\n'
      [[ -e "$candidate/$tracked_rel" ]] || die "Exported runtime payload missing tracked entry: $candidate/$tracked_rel"
    done <<< "$tracked_paths"

    while IFS= read -r entry; do
      [[ -n "$entry" ]] || continue
      [[ "$entry" != "$candidate" ]] || continue
          entry_type="$(python3 -c 'from pathlib import Path; import stat, sys; mode = Path(sys.argv[1]).lstat().st_mode; print("directory" if stat.S_ISDIR(mode) else "regular file" if stat.S_ISREG(mode) else "symbolic link" if stat.S_ISLNK(mode) else "fifo" if stat.S_ISFIFO(mode) else "socket" if stat.S_ISSOCK(mode) else "block special file" if stat.S_ISBLK(mode) else "character special file" if stat.S_ISCHR(mode) else "unknown")' "$entry")"
      case "$entry_type" in
        "directory")
          continue
          ;;
        "regular file")
          tracked_rel="${entry#"$candidate"/}"
          grep -Fxq -- "$tracked_rel" <<< "$normalized_tracked_paths" || die "Unexpected exported runtime payload entry: $entry"
          ;;
        "symbolic link")
          die "Unexpected symlink in exported runtime payload: $entry"
          ;;
        "fifo"|"socket"|"block special file"|"character special file")
          die "Unexpected special file in exported runtime payload: $entry"
          ;;
        *)
          die "Unexpected exported runtime payload entry type: $entry_type ($entry)"
          ;;
      esac
    done < <(find "$candidate" -mindepth 1 -print)

    if [[ "$DRY_RUN" == "true" ]]; then
      log "DRY-RUN: rm -rf $candidate"
    else
      rm -rf -- "$candidate"
    fi
    [[ ! -e "$candidate" ]] || die "Failed to remove exported runtime payload: $candidate"
  done
}

assert_python_and_deps() {
  local release_dir="$1"
  local pybin="$release_dir/venv/bin/python"

  if [[ "$DRY_RUN" == "true" ]]; then
    log "DRY-RUN: validate python/dependency setup prerequisites for $release_dir"
    return 0
  fi

  require_binary python3
  if [[ "${IMMUTABLE_V2_SKIP_DEP_INSTALL:-0}" == "1" ]]; then
    mkdir -p "$release_dir/venv/bin"
    cat > "$pybin" <<'EOF'
#!/usr/bin/env bash
exec python3 "$@"
EOF
    chmod +x "$pybin"
    return 0
  fi

  run_cmd python3 -m venv "$release_dir/venv"
  [[ -x "$pybin" ]] || die "Failed to create Python interpreter in release venv"

  if [[ -f "$release_dir/requirements.txt" ]]; then
    run_cmd "$release_dir/venv/bin/pip" install -r "$release_dir/requirements.txt"
  fi
}

run_analytics_credential_preflight() {
  local release_dir="$1"
  local pybin="$release_dir/venv/bin/python"
  local stdout_file stderr_file rc

  stdout_file="$(mktemp)"
  stderr_file="$(mktemp)"
  PRECHECK_ANALYTICS_COMMAND="$pybin ops/analytics_credential_preflight.py --json"

  set +e
  (
    cd "$release_dir" &&
    "$pybin" ops/analytics_credential_preflight.py --json
  ) >"$stdout_file" 2>"$stderr_file"
  rc=$?
  set -e

  PRECHECK_ANALYTICS_STDOUT_JSON="$(json_string_from_file "$stdout_file")"
  PRECHECK_ANALYTICS_STDERR_JSON="$(json_string_from_file "$stderr_file")"
  PRECHECK_ANALYTICS_REPORT_JSON="$(python3 - "$stdout_file" <<'PY'
import json
import pathlib
import sys

text = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8').strip()
try:
    payload = json.loads(text) if text else {}
except Exception:
    payload = {}
print(json.dumps(payload, ensure_ascii=False))
PY
)"

  rm -f "$stdout_file" "$stderr_file"

  if [[ "$rc" -eq 0 ]]; then
    return 0
  fi

  PREPARE_FAILURE_SUMMARY="ANALYTICS_CREDENTIAL_PREFLIGHT_FAILED"
  return 1
}

classify_asset() {
  local rel="$1"
  case "$rel" in
    .env) echo "PROHIBITED_SECRET|RELEASE_SYMLINK" ;;
    client_secrets.json|youtube_token.pickle|youtube_analytics_token.pickle|token.json|token_analytics.json) echo "PROHIBITED_SECRET|RELEASE_SYMLINK" ;;
    channels/*/client_secrets.json|channels/*/youtube_token.pickle|channels/*/youtube_analytics_token.pickle|channels/*/token.json|channels/*/token_analytics.json) echo "PROHIBITED_SECRET|RELEASE_SYMLINK" ;;
    logs|output|output/runtime|output/state|output/queue|output/runtime/state|output/runtime/logs|output/runtime/telemetry) echo "RUNTIME_GENERATED|RELEASE_SYMLINK" ;;
    channels/channel_registry.json|channels/channels_tracker.csv|youtube_playlists.json) echo "EXTERNAL_PERSISTENT|RELEASE_SYMLINK" ;;
    *) echo "UNKNOWN_BLOCKER|UNKNOWN_BLOCKER" ;;
  esac
}

resolve_asset_source() {
  local rel="$1"
  local active_root="$2"
  local mapped
  if mapped="$(source_for_root_asset "$rel" 2>/dev/null)"; then
    if [[ -e "$mapped" ]]; then
      printf '%s\n' "$mapped"
      return 0
    fi
  fi
  local shared_candidate="$SHARED_ROOT/$rel"
  if [[ -e "$shared_candidate" ]]; then
    printf '%s\n' "$shared_candidate"
    return 0
  fi
  printf '%s/%s\n' "$active_root" "$rel"
}

resolve_channel_asset_source() {
  local rel="$1"
  local active_root="$2"
  local operator_candidate="$OPERATOR_ROOT/$rel"
  local active_candidate="$active_root/$rel"
  local shared_candidate="$SHARED_ROOT/$rel"

  if [[ -e "$operator_candidate" ]]; then
    printf '%s\n' "$operator_candidate"
    return 0
  fi

  if [[ -e "$active_candidate" ]]; then
    printf '%s\n' "$active_candidate"
    return 0
  fi

  if [[ -e "$shared_candidate" ]]; then
    printf '%s\n' "$shared_candidate"
    return 0
  fi

  return 1
}

ensure_parent_dir() {
  local path="$1"
  run_cmd mkdir -p "$(dirname "$path")"
}

json_string_from_file() {
  local file="$1"
  python3 -c 'import json, pathlib, sys; print(json.dumps(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"), ensure_ascii=False))' "$file"
}

set_prepare_failure_phase() {
  PREPARE_FAILURE_PHASE="$1"
}

record_prepare_bootstrap_created_path() {
  local rel="$1"
  PREPARE_BOOTSTRAP_CREATED_RELATIVE_PATHS+="$rel"
  PREPARE_BOOTSTRAP_CREATED_RELATIVE_PATHS+=$'\n'
}

prepare_bootstrap_path_was_created() {
  local rel="$1"
  grep -Fxq -- "$rel" <<< "$PREPARE_BOOTSTRAP_CREATED_RELATIVE_PATHS"
}

assert_relative_path_safe() {
  local rel="$1"
  [[ -n "$rel" ]] || die "Relative path must not be empty"
  [[ "$rel" != /* ]] || die "Absolute paths are not allowed: $rel"
  [[ "$rel" != *".."* ]] || die "Path traversal is not allowed: $rel"
}

ensure_symlink_to_source() {
  local dest="$1"
  local src="$2"
  local context="$3"
  local expected_resolved actual_resolved
  expected_resolved="$(canon_path "$src")"

  if [[ -L "$dest" ]]; then
    actual_resolved="$(canon_path "$dest")"
    if [[ "$actual_resolved" == "$expected_resolved" ]]; then
      return 0
    fi
    die "$context symlink target mismatch: $dest -> $actual_resolved (expected $expected_resolved)"
  fi

  if [[ -e "$dest" ]]; then
    if [[ -d "$dest" ]]; then
      die "$context destination is a directory and cannot be replaced automatically: $dest"
    fi
    run_cmd rm -f "$dest"
  fi

  if [[ "$DRY_RUN" == "true" ]]; then
    log "DRY-RUN: ln -s $src $dest"
    return 0
  fi

  ln -s "$src" "$dest"
  actual_resolved="$(canon_path "$dest")"
  [[ "$actual_resolved" == "$expected_resolved" ]] || die "$context symlink verification failed: $dest"
}

replace_empty_staging_path_with_link() {
  local staging_root="$1"
  local rel="$2"
  local src="$3"
  local dest expected_resolved actual_resolved

  is_within_root "$staging_root" "$RELEASES_ROOT" || die "Staging root escapes approved releases root: $staging_root"
  assert_relative_path_safe "$rel"
  is_within_root "$src" "$SHARED_ROOT" || die "Shared source escapes approved shared root: $src"
  [[ -e "$src" ]] || die "Missing shared source for staging link: $src"

  dest="$staging_root/$rel"
  is_within_root "$(dirname "$dest")" "$staging_root" || die "Staging destination escapes staging root: $dest"

  expected_resolved="$(canon_path "$src")"

  if [[ -L "$dest" ]]; then
    actual_resolved="$(canon_path "$dest")"
    if [[ "$actual_resolved" == "$expected_resolved" ]]; then
      return 0
    fi
    die "Staging destination symlink mismatch for $rel: $actual_resolved (expected $expected_resolved)"
  fi

  if [[ ! -e "$dest" ]]; then
    if [[ "$DRY_RUN" == "true" ]]; then
      log "DRY-RUN: ln -s $src $dest"
      return 0
    fi
    ln -s "$src" "$dest"
    [[ "$(canon_path "$dest")" == "$expected_resolved" ]] || die "Staging link verification failed for $dest"
    return 0
  fi

  if [[ -d "$dest" ]]; then
    if find "$dest" -mindepth 1 -print -quit | grep -q .; then
      local entries
      entries="$(find "$dest" -mindepth 1 -maxdepth 2 -print | head -n 20 | sed 's|^|  - |')"
      die "Non-empty staging directory blocks link replacement: $dest\n$entries"
    fi
    if [[ "$DRY_RUN" == "true" ]]; then
      log "DRY-RUN: rmdir $dest && ln -s $src $dest"
      return 0
    fi
    rmdir "$dest"
    ln -s "$src" "$dest"
    [[ "$(canon_path "$dest")" == "$expected_resolved" ]] || die "Staging link verification failed for $dest"
    return 0
  fi

  die "Unsupported staging destination type for $rel: $dest"
}

source_for_root_asset() {
  local rel="$1"
  case "$rel" in
    .env) printf '%s/.env\n' "$SHARED_ROOT" ;;
    youtube_playlists.json) printf '%s/state/youtube_playlists.json\n' "$SHARED_ROOT" ;;
    channels/channel_registry.json) printf '%s/state/channel_registry.json\n' "$SHARED_ROOT" ;;
    channels/channels_tracker.csv) printf '%s/state/channels_tracker.csv\n' "$SHARED_ROOT" ;;
    logs) printf '%s/logs\n' "$SHARED_ROOT" ;;
    output) printf '%s/runtime/output\n' "$SHARED_ROOT" ;;
    client_secrets.json) printf '%s/oauth/client_secrets.root.json\n' "$SHARED_ROOT" ;;
    youtube_token.pickle) printf '%s/tokens/youtube_token.root.pickle\n' "$SHARED_ROOT" ;;
    youtube_analytics_token.pickle) printf '%s/tokens/youtube_analytics_token.root.pickle\n' "$SHARED_ROOT" ;;
    token.json) printf '%s/tokens/token.root.json\n' "$SHARED_ROOT" ;;
    token_analytics.json) printf '%s/tokens/token_analytics.root.json\n' "$SHARED_ROOT" ;;
    *) return 1 ;;
  esac
}

asset_requires_shared_root() {
  local rel="$1"
  case "$rel" in
    .env|youtube_playlists.json|channels/channel_registry.json|channels/channels_tracker.csv|logs|output)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

link_persistent_assets() {
  local release_dir="$1"
  local active_root="$2"
  local assets
  assets=(
    ".env"
    "client_secrets.json"
    "youtube_token.pickle"
    "youtube_analytics_token.pickle"
    "token.json"
    "token_analytics.json"
    "youtube_playlists.json"
    "channels/channel_registry.json"
    "channels/channels_tracker.csv"
    "logs"
    "output"
  )

  local rel class src dest
  for rel in "${assets[@]}"; do
    class="$(classify_asset "$rel")"
    [[ "$class" != UNKNOWN_BLOCKER* ]] || die "Unknown asset classification: $rel"

    src="$(resolve_asset_source "$rel" "$active_root")"
    dest="$release_dir/$rel"

    if [[ ! -e "$src" ]]; then
      case "$rel" in
        client_secrets.json|youtube_token.pickle|youtube_analytics_token.pickle|token.json|token_analytics.json)
          # Optional root-level credentials; channel-local credentials may be used.
          continue
          ;;
        *)
          die "Missing persistent asset source: $src"
          ;;
      esac
    fi

    if asset_requires_shared_root "$rel"; then
      is_within_root "$src" "$SHARED_ROOT" || die "Mandatory shared asset is not sourced from shared root: $rel -> $src"
    fi

    is_within_root "$src" "$active_root" || is_within_root "$src" "$SHARED_ROOT" || die "Persistent asset source escapes approved roots: $src"
    ensure_parent_dir "$dest"

    case "$rel" in
      output|logs)
        replace_empty_staging_path_with_link "$release_dir" "$rel" "$src"
        ;;
      *)
        ensure_symlink_to_source "$dest" "$src" "Persistent asset"
        ;;
    esac
  done

  # Channel-local secret assets: never copy content; only symlink exact files if present.
  if [[ -d "$active_root/channels" ]]; then
    local channel_secret_scan_root="$active_root"
    if [[ -d "$OPERATOR_ROOT/channels" ]]; then
      channel_secret_scan_root="$OPERATOR_ROOT"
    fi

    while IFS= read -r src_file; do
      rel="${src_file#$channel_secret_scan_root/}"
      class="$(classify_asset "$rel")"
      [[ "$class" != UNKNOWN_BLOCKER* ]] || die "Unknown asset classification: $rel"
      dest="$release_dir/$rel"
      src_file="$(resolve_channel_asset_source "$rel" "$active_root")"
      [[ -e "$src_file" ]] || continue
      is_within_root "$src_file" "$SHARED_ROOT" || is_within_root "$src_file" "$active_root" || is_within_root "$src_file" "$OPERATOR_ROOT" || die "Channel asset source escapes approved roots: $src_file"
      ensure_parent_dir "$dest"
      ensure_symlink_to_source "$dest" "$src_file" "Channel asset"
    done < <(find "$channel_secret_scan_root/channels" \( -type f -o -type l \) \( -name 'youtube_token.pickle' -o -name 'youtube_analytics_token.pickle' -o -name 'client_secrets.json' -o -name 'token.json' -o -name 'token_analytics.json' \))
  fi

  # Fail closed on unknown secret-like assets under active root channels.
  if [[ -d "$active_root/channels" ]]; then
    local unknown_secret
    unknown_secret="$(find "$active_root/channels" -type f \( -iname '*token*' -o -iname '*secret*' \) | while read -r f; do rel="${f#$active_root/}"; c="$(classify_asset "$rel")"; [[ "$c" == UNKNOWN_BLOCKER* ]] && echo "$rel"; done | head -n 1 || true)"
    [[ -z "$unknown_secret" ]] || die "UNKNOWN_BLOCKER secret-like asset not classified: $unknown_secret"
  fi
}

bootstrap_prepare_release_directories() {
  local release_dir="$1"
  local active_root="$2"
  local shared_output_root output_link output_resolved rel dest

  is_within_root "$release_dir" "$RELEASES_ROOT" || die "Release bootstrap root escapes approved releases root: $release_dir"
  [[ "$PREPARE_STAGING_CREATED" == "true" ]] || die "Directory bootstrap requires invocation-owned staging"
  [[ "$release_dir" != "$active_root" ]] || die "Active release cannot be bootstrapped as staging payload: $release_dir"
  [[ ! -e "$PREPARE_TARGET_RELEASE" ]] || die "Finalized release cannot be bootstrapped as staging payload: $PREPARE_TARGET_RELEASE"

  shared_output_root="$(canon_path "$SHARED_ROOT/runtime/output")"
  output_link="$release_dir/output"
  [[ -L "$output_link" ]] || die "Runtime output link missing before directory bootstrap: $output_link"
  output_resolved="$(canon_path "$output_link")"
  [[ "$output_resolved" == "$shared_output_root" ]] || die "Runtime output symlink target mismatch before directory bootstrap: $output_resolved (expected $shared_output_root)"
  [[ -d "$shared_output_root" ]] || die "Shared runtime output missing before directory bootstrap: $shared_output_root"

  for rel in output/scripts output/audio output/videos; do
    assert_relative_path_safe "$rel"
    dest="$shared_output_root/${rel#output/}"
    is_within_root "$dest" "$shared_output_root" || die "Runtime directory bootstrap escapes shared output root: $dest"

    if [[ -e "$dest" ]]; then
      [[ -d "$dest" ]] || die "Runtime output child path is not a directory: $dest"
      continue
    fi

    if [[ "$DRY_RUN" == "true" ]]; then
      log "DRY-RUN: mkdir -p $dest"
    else
      mkdir -p "$dest"
    fi
    record_prepare_bootstrap_created_path "$rel"
  done

  [[ -d "$release_dir/assets" ]] || die "Required packaged asset directory missing: $release_dir/assets"
  for rel in assets/backgrounds assets/music assets/fonts; do
    assert_relative_path_safe "$rel"
    dest="$release_dir/$rel"
    is_within_root "$(dirname "$dest")" "$release_dir" || die "Asset directory bootstrap escapes staging release root: $dest"

    if [[ -e "$dest" ]]; then
      [[ -d "$dest" ]] || die "Asset directory bootstrap target is not a directory: $dest"
      continue
    fi

    if [[ "$DRY_RUN" == "true" ]]; then
      log "DRY-RUN: mkdir -p $dest"
    else
      mkdir -p "$dest"
    fi
    record_prepare_bootstrap_created_path "$rel"
  done
}

prepare_preprod_state_root() {
  printf '%s/preprod-health/%s\n' "$DEPLOY_STATE_ROOT" "$TARGET_SHA"
}

run_prepare_scheduler_health_check() {
  local release_dir="$1"
  local pybin="$release_dir/venv/bin/python"
  local state_root stdout_file stderr_file rc

  state_root="$(prepare_preprod_state_root)"
  stdout_file="$(mktemp)"
  stderr_file="$(mktemp)"
  PRECHECK_HEALTH_COMMAND="PREPROD_ISOLATION_MODE=true PREPROD_STATE_ROOT=$state_root SCHEDULE_ENABLED=false UPLOAD_ENABLED=false SHORTS_UPLOAD_ENABLED=false LIVE_COLLECTOR_ENABLED=false YOUTUBE_ANALYTICS_API_GO=false $pybin scheduler.py --startup-preflight"

  mkdir -p "$state_root/state" "$state_root/telemetry" "$state_root/logs"

  set +e
  (
    cd "$release_dir" &&
    PREPROD_ISOLATION_MODE=true \
    PREPROD_STATE_ROOT="$state_root" \
    SCHEDULE_ENABLED=false \
    UPLOAD_ENABLED=false \
    SHORTS_UPLOAD_ENABLED=false \
    LIVE_COLLECTOR_ENABLED=false \
    YOUTUBE_ANALYTICS_API_GO=false \
    SCHEDULER_LOG_FILE="$state_root/logs/scheduler.log" \
    SCHEDULER_QUEUE_FILE="$state_root/state/channel_queue.json" \
    SCHEDULER_PID_FILE="$state_root/state/production_scheduler.pid" \
    SCHEDULER_SINGLETON_LOCK_FILE="$state_root/state/scheduler_singleton.lock" \
    SCHEDULER_SINGLETON_META_FILE="$state_root/state/scheduler_singleton_meta.json" \
    RUNTIME_EVIDENCE_LATEST_FILE="$state_root/state/runtime_optimization_evidence_latest.json" \
    SAFETY_GATE_LATEST_FILE="$state_root/state/production_safety_gate_latest.json" \
    ACTIVATION_CONTROLLER_REPORT_PATH="$state_root/state/activation_controller_report.json" \
    ACTIVATION_CONTROLLER_REPORT_ARCHIVE_DIR="$state_root/state/activation_reports" \
    ACTIVATION_FLAGS_PATH="$state_root/state/learning_activation_flags.json" \
    GOVERNANCE_REFRESH_LATEST_PATH="$state_root/state/governance_refresh_run_latest.json" \
    GOVERNANCE_READINESS_MD_PATH="$state_root/state/governance_readiness_latest.md" \
    PRODUCTION_DASHBOARD_JSON_PATH="$state_root/state/production_dashboard_latest.json" \
    PRODUCTION_DASHBOARD_MD_PATH="$state_root/state/production_dashboard_latest.md" \
    PRODUCTION_EVENTS_PATH="$state_root/telemetry/production_events.jsonl" \
    PRODUCTION_OBSERVABILITY_LATEST_PATH="$state_root/telemetry/production_observability_latest.json" \
    JOB_STORE_DB_PATH="$state_root/state/jobs.db" \
    "$pybin" scheduler.py --startup-preflight
  ) >"$stdout_file" 2>"$stderr_file"
  rc=$?
  set -e

  PRECHECK_HEALTH_STDOUT_JSON="$(json_string_from_file "$stdout_file")"
  PRECHECK_HEALTH_STDERR_JSON="$(json_string_from_file "$stderr_file")"
  PRECHECK_HEALTH_WARNINGS_JSON="$(python3 - "$stdout_file" "$stderr_file" <<'PY'
import json
import pathlib
import sys

warnings = []
for path in sys.argv[1:]:
    text = pathlib.Path(path).read_text(encoding='utf-8')
    for line in text.splitlines():
        entry = line.strip()
        if entry.startswith('- '):
            entry = entry[2:]
        if entry.startswith('Unable to resolve youtube.googleapis.com') and entry not in warnings:
            warnings.append(entry)
print(json.dumps(warnings, ensure_ascii=False))
PY
)"

  if [[ "$rc" -eq 0 ]]; then
    rm -f "$stdout_file" "$stderr_file"
    return 0
  fi

  if [[ -s "$stderr_file" ]]; then
    PREPARE_FAILURE_SUMMARY="$(python3 - "$stderr_file" <<'PY'
import pathlib
import sys
text = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8').strip().splitlines()
print((text[-1] if text else 'staged scheduler health stderr present')[:500])
PY
)"
    rm -f "$stdout_file" "$stderr_file"
    return 1
  fi

  local blocking_errors
  blocking_errors="$(python3 - "$stdout_file" <<'PY'
import pathlib
import sys
errors = []
for line in pathlib.Path(sys.argv[1]).read_text(encoding='utf-8').splitlines():
    entry = line.strip()
    if entry.startswith('- '):
        entry = entry[2:]
    if not entry or entry == 'Health check: FAIL':
        continue
    if entry.startswith('Unable to resolve youtube.googleapis.com'):
        continue
    if entry.startswith('202') or entry.startswith('Health check: PASS'):
        continue
    errors.append(entry)
print('\n'.join(errors))
PY
)"

  if [[ -z "$blocking_errors" ]]; then
    if [[ "$PRECHECK_HEALTH_WARNINGS_JSON" == "[]" ]]; then
      PREPARE_FAILURE_SUMMARY="staged scheduler health returned non-zero without a blocking detail"
      rm -f "$stdout_file" "$stderr_file"
      return 1
    fi
    rm -f "$stdout_file" "$stderr_file"
    return 0
  fi

  PREPARE_FAILURE_SUMMARY="$(printf '%s' "$blocking_errors" | head -n 1 | tr '\n' ' ' | sed 's/[[:space:]]\+/ /g' | sed 's/^ //; s/ $//')"
  rm -f "$stdout_file" "$stderr_file"
  return 1
}

run_preflight() {
  local release_dir="$1"
  local pybin="$release_dir/venv/bin/python"

  local scheduler_import="fail"
  local uploader_import="fail"
  local wrapper_import="skip"
  local health_check="fail"
  local shared_output_root shared_logs_root

  [[ -x "$pybin" ]] || die "Python interpreter missing in prepared release"
  [[ -f "$release_dir/scheduler.py" ]] || die "scheduler.py missing in prepared release"

  shared_output_root="$(canon_path "$SHARED_ROOT/runtime/output")"
  shared_logs_root="$(canon_path "$SHARED_ROOT/logs")"
  [[ -d "$shared_output_root" ]] || die "Shared runtime output missing: $shared_output_root"
  [[ -d "$shared_logs_root" ]] || die "Shared logs missing: $shared_logs_root"

  if ! run_analytics_credential_preflight "$release_dir"; then
    die "$PREPARE_FAILURE_SUMMARY"
  fi

  local evidence_tmp
  evidence_tmp="$(mktemp)"
  local rel dest resolved class status action
  local -a required_paths=(
    "output"
    "logs"
    "output/scripts"
    "output/audio"
    "output/videos"
    "assets"
    "assets/backgrounds"
    "assets/music"
    "assets/fonts"
  )

  for rel in "${required_paths[@]}"; do
    dest="$release_dir/$rel"
    status="pass"
    class="release_required"
    action="blocked"
    resolved="missing"

    if [[ -e "$dest" || -L "$dest" ]]; then
      resolved="$(canon_path "$dest")"
      if prepare_bootstrap_path_was_created "$rel"; then
        action="created"
      else
        action="existed"
      fi
    else
      status="fail"
      class="missing"
      action="blocked"
    fi

    case "$rel" in
      output)
        class="runtime_output_link"
        [[ "$resolved" == "$shared_output_root" ]] || status="fail"
        ;;
      logs)
        class="runtime_logs_link"
        [[ "$resolved" == "$shared_logs_root" ]] || status="fail"
        ;;
      output/scripts|output/audio|output/videos)
        class="runtime_output_child"
        [[ "$status" == "pass" ]] && is_within_root "$resolved" "$shared_output_root" || status="fail"
        ;;
      assets)
        class="release_assets"
        [[ "$status" == "pass" ]] && is_within_root "$resolved" "$release_dir" || status="fail"
        ;;
      assets/backgrounds|assets/music|assets/fonts)
        class="release_asset_optional_dir"
        if [[ "$status" == "fail" ]]; then
          status="pass"
          action="optional"
        else
          is_within_root "$resolved" "$release_dir" || status="fail"
        fi
        ;;
    esac

    printf '%s|%s|%s|%s|%s\n' "$rel" "$resolved" "$class" "$action" "$status" >> "$evidence_tmp"
  done

    PRECHECK_PATH_EVIDENCE_JSON="$(python3 -c 'import json,sys; from datetime import datetime, timezone; target_sha=sys.argv[1]; evidence_path=sys.argv[2]; now=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"); rows=(line.rstrip("\n").split("|", 4) for line in open(evidence_path, encoding="utf-8")); items=[{"relative_path": rel, "resolved_absolute_path": resolved, "classification": cls, "action": action, "status": status, "target_sha": target_sha, "timestamp_utc": now} for rel, resolved, cls, action, status in rows]; print(json.dumps(items, ensure_ascii=False))' "$TARGET_SHA" "$evidence_tmp")"
  rm -f "$evidence_tmp"

  if PRECHECK_PATH_EVIDENCE_JSON="$PRECHECK_PATH_EVIDENCE_JSON" python3 - <<'PY'
import json
import os
import sys

items = json.loads(os.environ['PRECHECK_PATH_EVIDENCE_JSON'])
sys.exit(0 if all(item.get('status') == 'pass' for item in items) else 1)
PY
  then
    :
  else
    die "Preflight required path validation failed"
  fi

  # Syntax and imports must pass from the staged release root.
  (cd "$release_dir" && "$pybin" -m py_compile scheduler.py src/*.py >/dev/null 2>&1) || die "Python syntax validation failed"

  if (cd "$release_dir" && "$pybin" - <<'PY'
import scheduler
PY
  ) >/dev/null 2>&1; then
    scheduler_import="pass"
  fi

  if (cd "$release_dir" && "$pybin" - <<'PY'
import src.youtube_uploader
PY
  ) >/dev/null 2>&1; then
    uploader_import="pass"
  fi

  if [[ -f "$release_dir/src/youtube_analytics_smoke.py" ]]; then
    if (cd "$release_dir" && "$pybin" - <<'PY'
import src.youtube_analytics_smoke
PY
    ) >/dev/null 2>&1; then
      wrapper_import="pass"
    else
      wrapper_import="fail"
    fi
  fi

  if [[ "$scheduler_import" != "pass" || "$uploader_import" != "pass" || "$wrapper_import" == "fail" ]]; then
    die "Preflight import validation failed"
  fi

  if [[ "${IMMUTABLE_V2_SKIP_HEALTHCHECK:-0}" == "1" ]]; then
    health_check="pass"
    PRECHECK_HEALTH_STDOUT_JSON='"health_check_skipped"'
    PRECHECK_HEALTH_STDERR_JSON='""'
    PRECHECK_HEALTH_WARNINGS_JSON='[]'
    PRECHECK_HEALTH_COMMAND='health_check_skipped'
  else
    if run_prepare_scheduler_health_check "$release_dir"; then
      health_check="pass"
    else
      health_check="fail"
    fi
  fi

  if [[ "$health_check" != "pass" ]]; then
    if [[ -n "$PREPARE_FAILURE_SUMMARY" ]]; then
      die "Preflight scheduler health check failed: $PREPARE_FAILURE_SUMMARY"
    fi
    die "Preflight scheduler health check failed"
  fi
  write_preflight_json "$release_dir" "$scheduler_import" "$uploader_import" "$wrapper_import" "$health_check"
}

assert_prepared_release() {
  local release_dir
  release_dir="$(release_dir_for_sha "$TARGET_SHA")"
  [[ -d "$release_dir" ]] || die "Prepared release not found: $release_dir"
  assert_release_integrity_contract "$release_dir" "$TARGET_SHA"
  [[ -f "$(preflight_json_path "$release_dir")" ]] || die "Prepared release missing preflight report"
}

verify_existing_release_identity_or_fail() {
  local release_dir="$1"
  if [[ -d "$release_dir" ]]; then
    assert_release_integrity_contract "$release_dir" "$TARGET_SHA"
    PREPARED_RELEASE="$release_dir"
    return 0
  fi
}

acquire_lock() {
  if [[ "$DRY_RUN" == "true" ]]; then
    log "DRY-RUN: acquire lock $LOCK_DIR"
    return 0
  fi

  if [[ -e "$LOCK_DIR" && ! -d "$LOCK_DIR" ]]; then
    die "Invalid lock path: $LOCK_DIR is not a directory"
  fi

  if [[ -d "$LOCK_DIR" ]]; then
    LOCK_DIR_PREEXISTED="true"
  fi

  mkdir -p "$LOCK_DIR"

  local marker_dir owner_file owner_payload
  marker_dir="$LOCK_DIR/.active_lock"
  owner_file="$marker_dir/owner.json"

  mkdir "$marker_dir" 2>/dev/null || die "Another deployment appears active: lock exists at $LOCK_DIR"

  owner_payload="$(python3 - <<PY
import json
import os
import socket
from datetime import datetime, timezone

print(json.dumps({
    "pid": os.getpid(),
    "host": socket.gethostname(),
    "started_at_utc": datetime.now(timezone.utc).isoformat(),
    "mode": "${MODE}",
    "target_sha": "${TARGET_SHA}",
    "target_ref": "${TARGET_REF}",
}, ensure_ascii=False))
PY
)"
  printf '%s\n' "$owner_payload" > "$owner_file"
  LOCK_ACQUIRED="true"
}

release_lock() {
  if [[ "$DRY_RUN" == "true" ]]; then
    return 0
  fi
  if [[ "$LOCK_ACQUIRED" == "true" ]]; then
    local marker_dir
    marker_dir="$LOCK_DIR/.active_lock"
    rm -rf "$marker_dir" || true
    if [[ "$LOCK_DIR_PREEXISTED" != "true" ]]; then
      rmdir "$LOCK_DIR" 2>/dev/null || true
    fi
    LOCK_ACQUIRED="false"
  fi
}

write_prepare_failure_report() {
  local code="$1"
  local file="$DEPLOY_STATE_ROOT/prepare_failure_latest.json"
  local tmp_file operator_tool_sha summary_json phase_json target_ref_json target_sha_json staging_json active_sha_json

  if [[ "$DRY_RUN" == "true" ]]; then
    return 0
  fi

  mkdir -p "$DEPLOY_STATE_ROOT"
  tmp_file="${file}.tmp.$$"
  operator_tool_sha="$(git rev-parse HEAD 2>/dev/null || printf 'unknown')"
  summary_json="$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1], ensure_ascii=False))' "${PREPARE_FAILURE_SUMMARY:-prepare failed}")"
  phase_json="$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1], ensure_ascii=False))' "${PREPARE_FAILURE_PHASE:-unknown}")"
  target_ref_json="$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1], ensure_ascii=False))' "$TARGET_REF")"
  target_sha_json="$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1], ensure_ascii=False))' "$TARGET_SHA")"
  staging_json="$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1], ensure_ascii=False))' "$PREPARE_STAGING_DIR")"
  active_sha_json="$(python3 -c 'import json,sys; print(json.dumps(sys.argv[1], ensure_ascii=False))' "$PREPARE_ACTIVE_RELEASE_SHA")"
  cat > "$tmp_file" <<EOF
{
  "timestamp_utc": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "mode": "prepare",
  "target_ref": $target_ref_json,
  "target_sha": $target_sha_json,
  "operator_tool_sha": "${operator_tool_sha}",
  "failed_phase": $phase_json,
  "exit_code": $code,
  "error_summary": $summary_json,
  "staging_path": $staging_json,
  "active_release_sha": $active_sha_json,
  "staging_created": "${PREPARE_STAGING_CREATED}",
  "finalized": "${PREPARE_FINALIZED}"
}
EOF
  mv "$tmp_file" "$file"
}

cleanup_prepare_staging_if_owned() {
  [[ "$PREPARE_STAGING_CREATED" == "true" ]] || return 0
  [[ "$PREPARE_FINALIZED" != "true" ]] || return 0
  [[ -n "$PREPARE_STAGING_DIR" ]] || return 0
  [[ -d "$PREPARE_STAGING_DIR" ]] || return 0

  is_within_root "$PREPARE_STAGING_DIR" "$RELEASES_ROOT" || {
    log "Skip prepare cleanup: staging path escapes releases root: $PREPARE_STAGING_DIR"
    return 0
  }

  local expected_base
  expected_base=".staging-$TARGET_SHA"
  if [[ "$(basename "$PREPARE_STAGING_DIR")" != "$expected_base" ]]; then
    log "Skip prepare cleanup: staging basename mismatch"
    return 0
  fi

  if [[ -n "$PREPARE_TARGET_RELEASE" && -d "$PREPARE_TARGET_RELEASE" ]]; then
    log "Skip prepare cleanup: target release already finalized"
    return 0
  fi

  rm -rf "$PREPARE_STAGING_DIR"
}

on_prepare_failure() {
  local code="$1"
  set +e
  write_prepare_failure_report "$code"
  cleanup_prepare_staging_if_owned
  release_lock
  trap - ERR
  exit "$code"
}

on_prepare_exit() {
  local code="$1"
  trap - EXIT
  if [[ "$code" -eq 0 ]]; then
    return 0
  fi
  set +e
  if [[ -z "$PREPARE_FAILURE_SUMMARY" ]]; then
    PREPARE_FAILURE_SUMMARY="prepare failed during ${PREPARE_FAILURE_PHASE:-unknown}"
  fi
  write_prepare_failure_report "$code"
  cleanup_prepare_staging_if_owned
  release_lock
  exit "$code"
}

on_error_rollback() {
  local code="$1"
  if [[ "$MODE" == "cutover" && "$AUTO_ROLLBACK" == "true" && -n "$ROLLBACK_TARGET_BEFORE_SWITCH" ]]; then
    log "Cutover failed, attempting automatic rollback to $ROLLBACK_TARGET_BEFORE_SWITCH"
    rollback_to_target "$ROLLBACK_TARGET_BEFORE_SWITCH" || true
  elif [[ "$MODE" == "cutover" ]]; then
    log "Automatic rollback disabled; explicit rollback authorization required"
  fi
  release_lock
  exit "$code"
}

record_rollback_metadata() {
  local previous_target="$1"
  local target_release="$2"
  local file="$DEPLOY_STATE_ROOT/last_rollback_target.json"

  if [[ "$DRY_RUN" == "true" ]]; then
    log "DRY-RUN: write rollback metadata to $file"
    return 0
  fi

  mkdir -p "$DEPLOY_STATE_ROOT"
  cat > "$file" <<EOF
{
  "timestamp_utc": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "previous_target": "$previous_target",
  "new_target": "$target_release",
  "service": "$SERVICE_NAME"
}
EOF
}

atomic_switch_symlink() {
  local target="$1"
  local link_tmp
  link_tmp="${CURRENT_LINK}.next.$$"

  is_within_root "$target" "$RELEASES_ROOT" || die "Symlink target escapes release root: $target"

  if [[ "$DRY_RUN" == "true" ]]; then
    log "DRY-RUN: ln -sfn $target $link_tmp && mv -Tf $link_tmp $CURRENT_LINK"
    return 0
  fi

  ln -sfn "$target" "$link_tmp"
  mv -Tf "$link_tmp" "$CURRENT_LINK"
}

restart_service_if_allowed() {
  local requested_mode="$1"
  if [[ "$requested_mode" != "cutover" && "$requested_mode" != "rollback" ]]; then
    die "Service restart is only permitted in cutover or rollback mode"
  fi

  if [[ "$DRY_RUN" == "true" ]]; then
    log "DRY-RUN: systemctl restart $SERVICE_NAME"
    return 0
  fi

  run_cmd systemctl restart "$SERVICE_NAME"
}

wait_for_service_health() {
  local release_dir="$1"
  local pybin="$release_dir/venv/bin/python"
  local attempts="${IMMUTABLE_V2_HEALTH_LOOP_ATTEMPTS:-12}"
  local sleep_seconds="${IMMUTABLE_V2_HEALTH_LOOP_SLEEP_SECONDS:-5}"
  local state_root
  local i

  if [[ "$DRY_RUN" == "true" ]]; then
    log "DRY-RUN: bounded service health loop"
    return 0
  fi

  if [[ "${IMMUTABLE_V2_SKIP_RUNTIME_HEALTH_LOOP:-0}" == "1" ]]; then
    log "Skipping runtime health loop due to IMMUTABLE_V2_SKIP_RUNTIME_HEALTH_LOOP=1"
    return 0
  fi

  state_root="$(prepare_preprod_state_root)"
  mkdir -p "$state_root/state" "$state_root/telemetry" "$state_root/logs"

  for ((i=1; i<=attempts; i++)); do
    if systemctl is-active "$SERVICE_NAME" >/dev/null 2>&1; then
      if (
        cd "$release_dir" &&
        PREPROD_ISOLATION_MODE=true \
        PREPROD_STATE_ROOT="$state_root" \
        RUNTIME_OUTPUT_ROOT="$state_root" \
        SCHEDULE_ENABLED=false \
        UPLOAD_ENABLED=false \
        SHORTS_UPLOAD_ENABLED=false \
        LIVE_COLLECTOR_ENABLED=false \
        YOUTUBE_ANALYTICS_API_GO=false \
        SCHEDULER_LOG_FILE="$state_root/logs/scheduler.log" \
        SCHEDULER_QUEUE_FILE="$state_root/state/channel_queue.json" \
        SCHEDULER_PID_FILE="$state_root/state/production_scheduler.pid" \
        SCHEDULER_SINGLETON_LOCK_FILE="$state_root/state/scheduler_singleton.lock" \
        SCHEDULER_SINGLETON_META_FILE="$state_root/state/scheduler_singleton_meta.json" \
        RUNTIME_EVIDENCE_LATEST_FILE="$state_root/state/runtime_optimization_evidence_latest.json" \
        SAFETY_GATE_LATEST_FILE="$state_root/state/production_safety_gate_latest.json" \
        ACTIVATION_CONTROLLER_REPORT_PATH="$state_root/state/activation_controller_report.json" \
        ACTIVATION_CONTROLLER_REPORT_ARCHIVE_DIR="$state_root/state/activation_reports" \
        ACTIVATION_FLAGS_PATH="$state_root/state/learning_activation_flags.json" \
        GOVERNANCE_REFRESH_LATEST_PATH="$state_root/state/governance_refresh_run_latest.json" \
        GOVERNANCE_READINESS_MD_PATH="$state_root/state/governance_readiness_latest.md" \
        PRODUCTION_DASHBOARD_JSON_PATH="$state_root/state/production_dashboard_latest.json" \
        PRODUCTION_DASHBOARD_MD_PATH="$state_root/state/production_dashboard_latest.md" \
        PRODUCTION_EVENTS_PATH="$state_root/telemetry/production_events.jsonl" \
        PRODUCTION_OBSERVABILITY_LATEST_PATH="$state_root/telemetry/production_observability_latest.json" \
        JOB_STORE_DB_PATH="$state_root/state/jobs.db" \
        "$pybin" scheduler.py --health-check
      ) >/dev/null 2>&1; then
        return 0
      fi
    fi
    sleep "$sleep_seconds"
  done

  return 1
}

rollback_to_target() {
  local target="$1"
  atomic_switch_symlink "$target"
  restart_service_if_allowed "rollback"
  local target_dir
  target_dir="$(canon_path "$target")"
  wait_for_service_health "$target_dir" || die "Rollback health verification failed"
}

mode_plan() {
  log "Plan mode: read-only prerequisite and contract checks"

  [[ -d "$RELEASES_ROOT" ]] || die "Missing releases root: $RELEASES_ROOT"
  [[ -L "$CURRENT_LINK" ]] || die "Missing active symlink: $CURRENT_LINK"

  local active_target
  active_target="$(capture_active_target)"

  log "target_ref=$TARGET_REF"
  log "target_sha=$TARGET_SHA"
  log "active_target=$active_target"
  log "release_dir=$(release_dir_for_sha "$TARGET_SHA")"
  log "No filesystem mutation will be performed in plan mode"
}

mode_prepare() {
  local release_dir staging_dir active_target
  release_dir="$(release_dir_for_sha "$TARGET_SHA")"
  staging_dir="$(staging_dir_for_sha "$TARGET_SHA")"
  active_target="$(capture_active_target)"

  PREPARE_STAGING_DIR="$staging_dir"
  PREPARE_TARGET_RELEASE="$release_dir"
  PREPARE_STAGING_CREATED="false"
  PREPARE_FINALIZED="false"
  PREPARE_BOOTSTRAP_CREATED_RELATIVE_PATHS=""
  PREPARE_FAILURE_PHASE="prepare_initialization"
  PREPARE_FAILURE_SUMMARY=""
  PRECHECK_HEALTH_STDOUT_JSON='""'
  PRECHECK_HEALTH_STDERR_JSON='""'
  PRECHECK_HEALTH_WARNINGS_JSON='[]'
  PRECHECK_HEALTH_COMMAND=""
  PREPARE_ACTIVE_TARGET="$active_target"
  PREPARE_ACTIVE_RELEASE_SHA="$(basename "$active_target")"
  trap 'on_prepare_exit $?' EXIT

  set_prepare_failure_phase "verify_existing_release"
  verify_existing_release_identity_or_fail "$release_dir"
  if [[ -n "$PREPARED_RELEASE" ]]; then
    trap - EXIT
    log "Release already prepared and matching target SHA: $PREPARED_RELEASE"
    return 0
  fi

  set_prepare_failure_phase "staging_collision_check"
  [[ ! -e "$staging_dir" ]] || die "Staging collision: $staging_dir already exists"

  set_prepare_failure_phase "disk_space_check"
  check_disk_space

  if [[ "$DRY_RUN" == "true" ]]; then
    log "DRY-RUN: would export $TARGET_SHA to $staging_dir"
    log "DRY-RUN: would link persistent assets from $active_target"
    log "DRY-RUN: would ensure shared runtime output directories: output/scripts output/audio output/videos"
    log "DRY-RUN: would ensure release asset directories when needed: assets/backgrounds assets/music assets/fonts"
    log "DRY-RUN: would run preflight and finalize release at $release_dir"
    return 0
  fi

  run_cmd mkdir -p "$RELEASES_ROOT"
  set_prepare_failure_phase "staging_create"
  run_cmd mkdir -p "$staging_dir"
  PREPARE_STAGING_CREATED="true"

  set_prepare_failure_phase "git_export"
  if [[ "$DRY_RUN" == "true" ]]; then
    log "DRY-RUN: export git archive for $TARGET_SHA into $staging_dir"
  else
    git archive "$TARGET_SHA" | tar -x -C "$staging_dir"
  fi

  if [[ -n "${IMMUTABLE_V2_TEST_HOOK_AFTER_EXPORT:-}" ]]; then
    (cd "$staging_dir" && bash -c "$IMMUTABLE_V2_TEST_HOOK_AFTER_EXPORT")
  fi

  set_prepare_failure_phase "runtime_payload_sanitization"
  remove_exported_runtime_payload "$staging_dir" "$active_target"
  set_prepare_failure_phase "forbidden_payload_guard"
  assert_no_forbidden_payload "$staging_dir"

  set_prepare_failure_phase "dependency_setup"
  assert_python_and_deps "$staging_dir"
  set_prepare_failure_phase "persistent_linking"
  link_persistent_assets "$staging_dir" "$active_target"
  set_prepare_failure_phase "directory_bootstrap"
  bootstrap_prepare_release_directories "$staging_dir" "$active_target"
  set_prepare_failure_phase "preflight"
  run_preflight "$staging_dir"

  if [[ -n "${IMMUTABLE_V2_TEST_HOOK_BEFORE_FINALIZE:-}" ]]; then
    (cd "$staging_dir" && bash -c "$IMMUTABLE_V2_TEST_HOOK_BEFORE_FINALIZE")
  fi

  set_prepare_failure_phase "metadata_write"
  write_release_metadata "$staging_dir"

  set_prepare_failure_phase "finalization"
  if [[ "$DRY_RUN" == "true" ]]; then
    log "DRY-RUN: mv $staging_dir $release_dir"
  else
    mv "$staging_dir" "$release_dir"
  fi
  set_prepare_failure_phase "release_integrity_contract"
  assert_release_integrity_contract "$release_dir" "$TARGET_SHA"
  PREPARE_FINALIZED="true"
  trap - EXIT

  log "Prepared immutable release: $release_dir"
}

mode_cutover() {
  local release_dir active_target
  release_dir="$(release_dir_for_sha "$TARGET_SHA")"
  assert_prepared_release
  assert_release_integrity_contract "$release_dir" "$TARGET_SHA"
  active_target="$(capture_active_target)"
  ROLLBACK_TARGET_BEFORE_SWITCH="$active_target"

  log "Cutover policy: AUTO_ROLLBACK=$AUTO_ROLLBACK"

  acquire_lock
  trap 'on_error_rollback $?' ERR

  record_rollback_metadata "$active_target" "$release_dir"
  run_preflight "$release_dir"
  atomic_switch_symlink "$release_dir"
  restart_service_if_allowed "cutover"
  if ! wait_for_service_health "$release_dir"; then
    if [[ "$AUTO_ROLLBACK" == "true" ]]; then
      rollback_to_target "$ROLLBACK_TARGET_BEFORE_SWITCH" || true
    else
      log "Automatic rollback disabled; explicit rollback authorization required"
    fi
    release_lock
    trap - ERR
    die "Post-cutover health check failed"
  fi

  local now_target
  now_target="$(capture_active_target)"
  if [[ "$DRY_RUN" == "true" ]]; then
    now_target="$(canon_path "$release_dir")"
  fi
  assert_release_integrity_contract "$now_target" "$TARGET_SHA"
  if [[ "$now_target" != "$(canon_path "$release_dir")" ]]; then
    if [[ "$AUTO_ROLLBACK" == "true" ]]; then
      rollback_to_target "$ROLLBACK_TARGET_BEFORE_SWITCH" || true
    else
      log "Automatic rollback disabled; explicit rollback authorization required"
    fi
    release_lock
    trap - ERR
    die "Cutover target mismatch after switch"
  fi

  release_lock
  trap - ERR
  log "Cutover successful: $release_dir"
}

mode_rollback() {
  is_full_sha "$ROLLBACK_SHA" || die "--rollback-sha must be a full 40-char SHA in rollback mode"
  local rollback_release
  rollback_release="$(release_dir_for_sha "$ROLLBACK_SHA")"
  [[ -d "$rollback_release" ]] || die "Rollback target release not found: $rollback_release"

  acquire_lock
  trap 'release_lock; exit 1' ERR

  atomic_switch_symlink "$rollback_release"
  restart_service_if_allowed "rollback"
  wait_for_service_health "$rollback_release" || die "Rollback post-switch health check failed"

  release_lock
  trap - ERR
  log "Rollback successful: $rollback_release"
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --target-ref)
        TARGET_REF="${2:-}"
        shift 2
        ;;
      --target-sha)
        TARGET_SHA="${2:-}"
        shift 2
        ;;
      --mode)
        MODE="${2:-}"
        shift 2
        ;;
      --rollback-sha)
        ROLLBACK_SHA="${2:-}"
        shift 2
        ;;
      --dry-run)
        DRY_RUN="true"
        shift
        ;;
      --auto-rollback)
        AUTO_ROLLBACK="true"
        shift
        ;;
      --help|-h)
        usage
        exit 0
        ;;
      *)
        die "Unknown argument: $1"
        ;;
    esac
  done

  [[ -n "$TARGET_REF" ]] || die "Missing --target-ref"
  [[ -n "$TARGET_SHA" ]] || die "Missing --target-sha"
  [[ -n "$MODE" ]] || die "Missing --mode"

  case "$MODE" in
    plan|prepare|cutover|rollback) ;;
    *) die "Invalid --mode: $MODE" ;;
  esac

  if [[ "$MODE" == "rollback" && -z "$ROLLBACK_SHA" ]]; then
    die "--rollback-sha is required in rollback mode"
  fi
}

main() {
  parse_args "$@"

  require_binary git
  require_binary tar
  require_binary python3

  assert_service_name
  assert_policy_prohibitions
  assert_paths_approved
  assert_local_repo_clean_if_present

  fetch_remote_if_needed
  assert_target_ref_and_sha

  case "$MODE" in
    plan) mode_plan ;;
    prepare) mode_prepare ;;
    cutover) mode_cutover ;;
    rollback) mode_rollback ;;
  esac
}

main "$@"
