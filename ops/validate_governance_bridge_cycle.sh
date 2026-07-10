#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY_BIN="${ROOT_DIR}/.venv-2/bin/python"

if [[ ! -x "${PY_BIN}" ]]; then
  echo "Python interpreter not found: ${PY_BIN}" >&2
  exit 2
fi

cd "${ROOT_DIR}"

echo "[1/4] Refresh governance readiness artifacts"
PYTHONPATH=. "${PY_BIN}" ops/refresh_governance_readiness.py --lookback-rows 500

echo "[2/4] Build daily checklist from bridge artifact"
PYTHONPATH=. "${PY_BIN}" ops/governance_bridge_daily_checklist.py

echo "[3/4] Enforce maturity discipline guard (must stay REPORTED)"
PYTHONPATH=. "${PY_BIN}" - <<'PY'
import json
from pathlib import Path

bridge = Path("logs/governance_dashboard_bridge_latest.json")
if not bridge.exists():
    raise SystemExit("Bridge artifact missing: logs/governance_dashboard_bridge_latest.json")

payload = json.loads(bridge.read_text(encoding="utf-8"))
max_claim = str(payload.get("max_claim_maturity") or "").strip().upper()
if max_claim != "REPORTED":
    raise SystemExit(f"Maturity guard failed: expected REPORTED, got {max_claim or 'UNKNOWN'}")

print(json.dumps({"ok": True, "max_claim_maturity": max_claim}, ensure_ascii=False))
PY

echo "[4/4] Run standardized short-loop tests"
./ops/run_governance_bridge_short_loop.sh

echo "DONE: governance bridge cycle validated"
