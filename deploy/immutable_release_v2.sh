#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_NAME="immutable_release_v2"
APPROVED_SERVICE="parapusulasi"
SERVICE_NAME="${APPROVED_SERVICE}"

DEFAULT_RELEASES_ROOT="/opt/parapusulasi/releases"
DEFAULT_CURRENT_LINK="/opt/parapusulasi-current"
DEFAULT_DEPLOY_STATE_ROOT="/opt/parapusulasi/deploy-state"
DEFAULT_SHARED_ROOT="/opt/parapusulasi-shared"
DEFAULT_LOCK_DIR="/opt/parapusulasi/deploy.lock"

RELEASES_ROOT="${IMMUTABLE_V2_RELEASES_ROOT:-$DEFAULT_RELEASES_ROOT}"
CURRENT_LINK="${IMMUTABLE_V2_CURRENT_LINK:-$DEFAULT_CURRENT_LINK}"
DEPLOY_STATE_ROOT="${IMMUTABLE_V2_DEPLOY_STATE_ROOT:-$DEFAULT_DEPLOY_STATE_ROOT}"
SHARED_ROOT="${IMMUTABLE_V2_SHARED_ROOT:-$DEFAULT_SHARED_ROOT}"
LOCK_DIR="${IMMUTABLE_V2_LOCK_DIR:-$DEFAULT_LOCK_DIR}"
MIN_FREE_KB="${IMMUTABLE_V2_MIN_FREE_KB:-1048576}"

TARGET_REF=""
TARGET_SHA=""
ROLLBACK_SHA=""
MODE=""
DRY_RUN="false"

PREPARED_RELEASE=""
ROLLBACK_TARGET_BEFORE_SWITCH=""
LOCK_ACQUIRED="false"
PREPARE_STAGING_DIR=""
PREPARE_TARGET_RELEASE=""
PREPARE_STAGING_CREATED="false"
PREPARE_FINALIZED="false"
PRECHECK_PATH_EVIDENCE_JSON="[]"

usage() {
  cat <<'EOF'
Usage:
  deploy/immutable_release_v2.sh \
    --target-ref <remote-branch-or-tag> \
    --target-sha <full-sha> \
    --mode plan|prepare|cutover|rollback \
    [--rollback-sha <full-sha>] \
    [--dry-run]

Notes:
- This workflow never edits systemd unit/drop-in files.
- This workflow never appends or edits .env content.
- Service restart is allowed only in cutover and rollback modes.
EOF
}

log() {
  printf '[%s] %s\n' "$SCRIPT_NAME" "$*"
}

die() {
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

ensure_parent_dir() {
  local path="$1"
  run_cmd mkdir -p "$(dirname "$path")"
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
    while IFS= read -r src_file; do
      rel="${src_file#$active_root/}"
      class="$(classify_asset "$rel")"
      [[ "$class" != UNKNOWN_BLOCKER* ]] || die "Unknown asset classification: $rel"
      dest="$release_dir/$rel"
      src_file="$(canon_path "$src_file")"
      is_within_root "$src_file" "$SHARED_ROOT" || is_within_root "$src_file" "$active_root" || die "Channel asset source escapes approved roots: $src_file"
      ensure_parent_dir "$dest"
      ensure_symlink_to_source "$dest" "$src_file" "Channel asset"
    done < <(find "$active_root/channels" \( -type f -o -type l \) \( -name 'youtube_token.pickle' -o -name 'youtube_analytics_token.pickle' -o -name 'client_secrets.json' -o -name 'token.json' -o -name 'token_analytics.json' \))
  fi

  # Fail closed on unknown secret-like assets under active root channels.
  if [[ -d "$active_root/channels" ]]; then
    local unknown_secret
    unknown_secret="$(find "$active_root/channels" -type f \( -iname '*token*' -o -iname '*secret*' \) | while read -r f; do rel="${f#$active_root/}"; c="$(classify_asset "$rel")"; [[ "$c" == UNKNOWN_BLOCKER* ]] && echo "$rel"; done | head -n 1 || true)"
    [[ -z "$unknown_secret" ]] || die "UNKNOWN_BLOCKER secret-like asset not classified: $unknown_secret"
  fi
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

  local evidence_tmp
  evidence_tmp="$(mktemp)"
  local rel dest resolved class status
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
    resolved="missing"

    if [[ -e "$dest" || -L "$dest" ]]; then
      resolved="$(canon_path "$dest")"
    else
      status="fail"
      class="missing"
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
      assets|assets/backgrounds|assets/music|assets/fonts)
        class="release_assets"
        [[ "$status" == "pass" ]] && is_within_root "$resolved" "$release_dir" || status="fail"
        ;;
    esac

    printf '%s|%s|%s|%s\n' "$rel" "$resolved" "$class" "$status" >> "$evidence_tmp"
  done

  PRECHECK_PATH_EVIDENCE_JSON="$(python3 - "$TARGET_SHA" "$evidence_tmp" <<'PY'
import json
import sys
from datetime import datetime, timezone

target_sha = sys.argv[1]
evidence_path = sys.argv[2]
now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
items = []
with open(evidence_path, encoding='utf-8') as fh:
    for line in fh:
        rel, resolved, cls, status = line.rstrip('\n').split('|', 3)
        items.append(
            {
                'relative_path': rel,
                'resolved_absolute_path': resolved,
                'classification': cls,
                'status': status,
                'target_sha': target_sha,
                'timestamp_utc': now,
            }
        )
print(json.dumps(items, ensure_ascii=False))
PY
)"
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
  else
    if (
      cd "$release_dir" &&
      PREPROD_ISOLATION_MODE=true \
      SCHEDULE_ENABLED=false \
      UPLOAD_ENABLED=false \
      SHORTS_UPLOAD_ENABLED=false \
      LIVE_COLLECTOR_ENABLED=false \
      YOUTUBE_ANALYTICS_API_GO=false \
      "$pybin" scheduler.py --health-check
    ) >/dev/null 2>&1; then
      health_check="pass"
    else
      health_check="fail"
    fi
  fi

  [[ "$health_check" == "pass" ]] || die "Preflight scheduler health check failed"
  write_preflight_json "$release_dir" "$scheduler_import" "$uploader_import" "$wrapper_import" "$health_check"
}

assert_prepared_release() {
  local release_dir
  release_dir="$(release_dir_for_sha "$TARGET_SHA")"
  [[ -d "$release_dir" ]] || die "Prepared release not found: $release_dir"
  [[ -f "$(preflight_json_path "$release_dir")" ]] || die "Prepared release missing preflight report"
}

verify_existing_release_identity_or_fail() {
  local release_dir="$1"
  local meta
  meta="$(release_meta_path "$release_dir")"
  if [[ -d "$release_dir" ]]; then
    if [[ ! -f "$meta" ]]; then
      die "Release exists but identity metadata is missing: $meta"
    fi
    local existing_sha
    existing_sha="$(python3 - <<PY
import json
from pathlib import Path
p=Path('$meta')
print(json.loads(p.read_text(encoding='utf-8')).get('release_sha',''))
PY
)"
    [[ "$existing_sha" == "$TARGET_SHA" ]] || die "Existing release mismatch: expected $TARGET_SHA got ${existing_sha:-<empty>}"
    PREPARED_RELEASE="$release_dir"
    return 0
  fi
}

acquire_lock() {
  if [[ "$DRY_RUN" == "true" ]]; then
    log "DRY-RUN: acquire lock $LOCK_DIR"
    return 0
  fi
  mkdir "$LOCK_DIR" 2>/dev/null || die "Another deployment appears active: lock exists at $LOCK_DIR"
  LOCK_ACQUIRED="true"
}

release_lock() {
  if [[ "$DRY_RUN" == "true" ]]; then
    return 0
  fi
  if [[ "$LOCK_ACQUIRED" == "true" ]]; then
    rm -rf "$LOCK_DIR" || true
    LOCK_ACQUIRED="false"
  fi
}

write_prepare_failure_report() {
  local code="$1"
  local file="$DEPLOY_STATE_ROOT/prepare_failure_latest.json"

  if [[ "$DRY_RUN" == "true" ]]; then
    return 0
  fi

  mkdir -p "$DEPLOY_STATE_ROOT"
  cat > "$file" <<EOF
{
  "timestamp_utc": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "mode": "prepare",
  "target_sha": "$TARGET_SHA",
  "target_ref": "$TARGET_REF",
  "exit_code": $code,
  "staging_dir": "${PREPARE_STAGING_DIR}",
  "staging_created": "${PREPARE_STAGING_CREATED}",
  "finalized": "${PREPARE_FINALIZED}"
}
EOF
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

on_error_rollback() {
  local code="$1"
  if [[ "$MODE" == "cutover" && -n "$ROLLBACK_TARGET_BEFORE_SWITCH" ]]; then
    log "Cutover failed, attempting automatic rollback to $ROLLBACK_TARGET_BEFORE_SWITCH"
    rollback_to_target "$ROLLBACK_TARGET_BEFORE_SWITCH" || true
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
  local i

  if [[ "$DRY_RUN" == "true" ]]; then
    log "DRY-RUN: bounded service health loop"
    return 0
  fi

  if [[ "${IMMUTABLE_V2_SKIP_RUNTIME_HEALTH_LOOP:-0}" == "1" ]]; then
    log "Skipping runtime health loop due to IMMUTABLE_V2_SKIP_RUNTIME_HEALTH_LOOP=1"
    return 0
  fi

  for ((i=1; i<=attempts; i++)); do
    if systemctl is-active "$SERVICE_NAME" >/dev/null 2>&1; then
      if (
        cd "$release_dir" &&
        PREPROD_ISOLATION_MODE=true \
        SCHEDULE_ENABLED=false \
        UPLOAD_ENABLED=false \
        SHORTS_UPLOAD_ENABLED=false \
        LIVE_COLLECTOR_ENABLED=false \
        YOUTUBE_ANALYTICS_API_GO=false \
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
  trap 'on_prepare_failure $?' ERR

  verify_existing_release_identity_or_fail "$release_dir"
  if [[ -n "$PREPARED_RELEASE" ]]; then
    log "Release already prepared and matching target SHA: $PREPARED_RELEASE"
    return 0
  fi

  [[ ! -e "$staging_dir" ]] || die "Staging collision: $staging_dir already exists"

  check_disk_space

  if [[ "$DRY_RUN" == "true" ]]; then
    log "DRY-RUN: would export $TARGET_SHA to $staging_dir"
    log "DRY-RUN: would link persistent assets from $active_target"
    log "DRY-RUN: would run preflight and finalize release at $release_dir"
    return 0
  fi

  run_cmd mkdir -p "$RELEASES_ROOT"
  run_cmd mkdir -p "$staging_dir"
  PREPARE_STAGING_CREATED="true"

  if [[ "$DRY_RUN" == "true" ]]; then
    log "DRY-RUN: export git archive for $TARGET_SHA into $staging_dir"
  else
    git archive "$TARGET_SHA" | tar -x -C "$staging_dir"
  fi

  if [[ -n "${IMMUTABLE_V2_TEST_HOOK_AFTER_EXPORT:-}" ]]; then
    (cd "$staging_dir" && bash -c "$IMMUTABLE_V2_TEST_HOOK_AFTER_EXPORT")
  fi

  assert_no_forbidden_payload "$staging_dir"

  assert_python_and_deps "$staging_dir"
  link_persistent_assets "$staging_dir" "$active_target"
  run_preflight "$staging_dir"

  if [[ -n "${IMMUTABLE_V2_TEST_HOOK_BEFORE_FINALIZE:-}" ]]; then
    (cd "$staging_dir" && bash -c "$IMMUTABLE_V2_TEST_HOOK_BEFORE_FINALIZE")
  fi

  write_release_metadata "$staging_dir"

  if [[ "$DRY_RUN" == "true" ]]; then
    log "DRY-RUN: mv $staging_dir $release_dir"
  else
    mv "$staging_dir" "$release_dir"
  fi
  PREPARE_FINALIZED="true"
  trap - ERR

  log "Prepared immutable release: $release_dir"
}

mode_cutover() {
  local release_dir active_target
  release_dir="$(release_dir_for_sha "$TARGET_SHA")"
  assert_prepared_release
  active_target="$(capture_active_target)"
  ROLLBACK_TARGET_BEFORE_SWITCH="$active_target"

  acquire_lock
  trap 'on_error_rollback $?' ERR

  record_rollback_metadata "$active_target" "$release_dir"
  run_preflight "$release_dir"
  atomic_switch_symlink "$release_dir"
  restart_service_if_allowed "cutover"
  if ! wait_for_service_health "$release_dir"; then
    rollback_to_target "$ROLLBACK_TARGET_BEFORE_SWITCH" || true
    die "Post-cutover health check failed"
  fi

  local now_target
  now_target="$(capture_active_target)"
  if [[ "$DRY_RUN" == "true" ]]; then
    now_target="$(canon_path "$release_dir")"
  fi
  if [[ "$now_target" != "$(canon_path "$release_dir")" ]]; then
    rollback_to_target "$ROLLBACK_TARGET_BEFORE_SWITCH" || true
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
