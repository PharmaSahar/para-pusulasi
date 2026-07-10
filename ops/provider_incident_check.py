#!/usr/bin/env python3
"""Provider incident diagnostic helper for Anthropic availability issues."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import dotenv_values

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.scheduler_utils import PROVIDER_HEALTH_FILE, run_anthropic_preflight


def _load_provider_state() -> dict:
    path = Path(PROVIDER_HEALTH_FILE)
    if not path.exists():
        return {"providers": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"providers": {}}


def _has_key() -> bool:
    for env_path in (".env", "/opt/parapusulasi/.env"):
        p = Path(env_path)
        if p.exists():
            env = dotenv_values(str(p))
            if str(env.get("ANTHROPIC_API_KEY") or "").strip():
                return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Anthropic incident check")
    parser.add_argument("--live", action="store_true", help="Run a live Anthropic preflight request")
    args = parser.parse_args()

    state = _load_provider_state()
    provider = state.get("providers", {}).get("anthropic", {})

    print("Provider Incident Check")
    print("======================")
    print(f"key_present: {'yes' if _has_key() else 'no'}")
    print(f"consecutive_failures: {provider.get('consecutive_failures', 0)}")
    print(f"last_error_type: {provider.get('last_error_type', '')}")
    print(f"last_request_id: {provider.get('last_request_id', '')}")
    print(f"open_until: {provider.get('open_until', '')}")
    print(f"last_failed_at: {provider.get('last_failed_at', '')}")
    print(f"last_success_at: {provider.get('last_success_at', '')}")

    if args.live:
        ok, detail = run_anthropic_preflight()
        print("live_preflight:", "ok" if ok else "fail")
        print("live_detail:", detail)
        return 0 if ok else 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
