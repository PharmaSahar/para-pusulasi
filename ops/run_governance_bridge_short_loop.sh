#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY_BIN="${ROOT_DIR}/.venv-2/bin/python"

if [[ ! -x "${PY_BIN}" ]]; then
  echo "Python interpreter not found: ${PY_BIN}" >&2
  exit 2
fi

cd "${ROOT_DIR}"
PYTHONPATH=. "${PY_BIN}" -m pytest -q \
  tests/test_governance_dashboard_safety.py \
  tests/test_refresh_governance_readiness.py \
  tests/test_executive_runtime_evidence.py
