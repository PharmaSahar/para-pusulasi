#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

export DEPLOY_SCRIPT_NAME="deploy"
export DEPLOY_PUBLIC_COMMAND="deploy/deploy.sh"

source "${SCRIPT_DIR}/internal/immutable_release_v2_impl.sh"
immutable_release_v2_main "$@"