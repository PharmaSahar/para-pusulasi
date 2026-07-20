#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

printf '%s\n' "[immutable_release_v2] DEPRECATED: use deploy/deploy.sh as the supported deployment entrypoint." >&2

export DEPLOY_SCRIPT_NAME="immutable_release_v2"
export DEPLOY_PUBLIC_COMMAND="deploy/immutable_release_v2.sh"

source "${SCRIPT_DIR}/internal/immutable_release_v2_impl.sh"
immutable_release_v2_main "$@"
