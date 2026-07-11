#!/usr/bin/env python3
"""Production cutover verifier.

Checks:
- scheduler pid exists and process is alive
- process command contains scheduler.py
- process cwd matches canonical repo root
- HEAD sha is readable
- BUILD_INFO line exists in production log and (when present) sha is visible
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PID_FILE = ROOT / "logs" / "production_scheduler.pid"
LOG_FILE = ROOT / "logs" / "production_scheduler.out"
SCHEDULER_LOG_FILE = ROOT / "logs" / "scheduler.log"
EQUIVALENCE_ARTIFACT = ROOT / "logs" / "approved_governance_equivalence_latest.json"
APPROVED_COMMITS = (
    "f184062a5f33b8e2ab11257716e7c7215de5a622",
    "dbe543d8cf70beba2b07198c3fa9f371bf1a3305",
    "bfc62663f099a14412fd2412fda441cb62813046",
    "e2df46a9047c3208ca6a12f13dff2985ce745edc",
)
ALLOWED_EQUIVALENCE = {"EXACT_ANCESTOR", "PATCH_EQUIVALENT", "FUNCTIONALLY_SUPERSEDED"}
MAX_EVIDENCE_AGE_SECONDS = 24 * 60 * 60


def _run(cmd: list[str]) -> tuple[int, str]:
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
        return 0, out.strip()
    except subprocess.CalledProcessError as e:
        return e.returncode, (e.output or "").strip()


def _head_sha() -> str:
    rc, out = _run(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"])
    return out if rc == 0 and out else "unknown"


def _read_pid() -> int | None:
    if not PID_FILE.exists():
        return None
    raw = PID_FILE.read_text(encoding="utf-8").strip()
    if not raw.isdigit():
        return None
    return int(raw)


def _discover_scheduler_pids() -> list[int]:
    rc, out = _run(["pgrep", "-f", "Python.*scheduler.py"])
    if rc != 0 or not out:
        return []
    pids: list[int] = []
    for line in out.splitlines():
        line = line.strip()
        if line.isdigit():
            pids.append(int(line))
    return pids


def _process_info(pid: int) -> dict:
    rc_cmd, cmd = _run(["ps", "-ww", "-p", str(pid), "-o", "command="])
    rc_etime, etime = _run(["ps", "-p", str(pid), "-o", "etime="])
    rc_cwd, cwd_raw = _run(["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"])

    cwd = None
    if rc_cwd == 0:
        for line in cwd_raw.splitlines():
            if line.startswith("n"):
                cwd = line[1:]
                break

    return {
        "command": cmd if rc_cmd == 0 else None,
        "elapsed": etime if rc_etime == 0 else None,
        "cwd": cwd,
    }


def _last_build_info() -> dict:
    candidates: list[tuple[float, str]] = []
    for path in (LOG_FILE, SCHEDULER_LOG_FILE):
        if not path.exists():
            continue
        build_line = None
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "BUILD_INFO scheduler" in line:
                build_line = line
        if build_line:
            try:
                mtime = path.stat().st_mtime
            except Exception:
                mtime = 0.0
            candidates.append((mtime, build_line))

    if not candidates:
        return {"line": None, "sha": None}

    candidates.sort(key=lambda item: item[0])
    build_line = candidates[-1][1]

    sha = None
    if build_line:
        m = re.search(r"git_sha=([a-zA-Z0-9]+)", build_line)
        if m:
            sha = m.group(1)

    return {"line": build_line, "sha": sha}


def _is_ancestor(commit_sha: str) -> bool:
    rc, _ = _run(["git", "-C", str(ROOT), "merge-base", "--is-ancestor", commit_sha, "HEAD"])
    return rc == 0


def _approved_commit_ancestry() -> dict[str, bool]:
    return {commit: _is_ancestor(commit) for commit in APPROVED_COMMITS}


def _artifact_age_seconds(generated_at_utc: str) -> float | None:
    text = str(generated_at_utc or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds()


def _extract_classifications(payload: dict) -> dict[str, str]:
    direct = payload.get("classification_per_commit")
    if isinstance(direct, dict):
        return {str(k): str(v) for k, v in direct.items()}

    as_list = payload.get("approved_equivalence")
    if isinstance(as_list, list):
        out: dict[str, str] = {}
        for row in as_list:
            if isinstance(row, dict):
                sha = str(row.get("commit") or row.get("sha") or "").strip()
                cls = str(row.get("classification") or "").strip()
                if sha and cls:
                    out[sha] = cls
        return out

    return {}


def _tests_passed(payload: dict) -> bool:
    import_ok = str(payload.get("import_integrity") or "").upper() == "PASS"
    governance = payload.get("governance_tests")
    if isinstance(governance, dict):
        governance_ok = bool(governance.get("all_passed"))
    else:
        governance_ok = "PASS" in str(governance or "").upper()

    full_suite = payload.get("full_suite")
    if isinstance(full_suite, dict):
        full_ok = bool(full_suite.get("all_passed"))
    else:
        full_ok = "PASS" in str(full_suite or "").upper()

    return import_ok and governance_ok and full_ok


def _evaluate_governance_equivalence(head_sha: str) -> dict:
    ancestry = _approved_commit_ancestry()
    if ancestry and all(ancestry.values()):
        return {
            "ok": True,
            "mode": "exact_ancestry",
            "ancestry": ancestry,
            "artifact": str(EQUIVALENCE_ARTIFACT),
            "checks": {
                "artifact_present": EQUIVALENCE_ARTIFACT.exists(),
                "artifact_valid": True,
                "artifact_fresh": True,
                "artifact_head_matches": True,
                "artifact_tests_passed": True,
                "classifications_complete": True,
                "classifications_allowed": True,
                "final_decision_allows_equivalence": True,
            },
        }

    checks = {
        "artifact_present": EQUIVALENCE_ARTIFACT.exists(),
        "artifact_valid": False,
        "artifact_fresh": False,
        "artifact_head_matches": False,
        "artifact_tests_passed": False,
        "classifications_complete": False,
        "classifications_allowed": False,
        "final_decision_allows_equivalence": False,
    }

    payload = {}
    if not EQUIVALENCE_ARTIFACT.exists():
        return {
            "ok": False,
            "mode": "artifact_required",
            "ancestry": ancestry,
            "artifact": str(EQUIVALENCE_ARTIFACT),
            "checks": checks,
            "reason": "equivalence_artifact_missing",
        }

    try:
        payload = json.loads(EQUIVALENCE_ARTIFACT.read_text(encoding="utf-8"))
    except Exception:
        return {
            "ok": False,
            "mode": "artifact_required",
            "ancestry": ancestry,
            "artifact": str(EQUIVALENCE_ARTIFACT),
            "checks": checks,
            "reason": "equivalence_artifact_invalid_json",
        }

    checks["artifact_valid"] = isinstance(payload, dict)
    if not checks["artifact_valid"]:
        return {
            "ok": False,
            "mode": "artifact_required",
            "ancestry": ancestry,
            "artifact": str(EQUIVALENCE_ARTIFACT),
            "checks": checks,
            "reason": "equivalence_artifact_invalid_payload",
        }

    age_seconds = _artifact_age_seconds(str(payload.get("generated_at_utc") or ""))
    checks["artifact_fresh"] = age_seconds is not None and age_seconds <= MAX_EVIDENCE_AGE_SECONDS
    checks["artifact_head_matches"] = str(payload.get("current_head") or "") == head_sha
    checks["artifact_tests_passed"] = _tests_passed(payload)

    classifications = _extract_classifications(payload)
    checks["classifications_complete"] = all(commit in classifications for commit in APPROVED_COMMITS)
    checks["classifications_allowed"] = checks["classifications_complete"] and all(
        classifications.get(commit) in ALLOWED_EQUIVALENCE for commit in APPROVED_COMMITS
    )
    checks["final_decision_allows_equivalence"] = str(payload.get("final_equivalence_decision") or "") in {
        "EQUIVALENT",
        "PROVEN_EQUIVALENT",
        "READY_FOR_CUTOVER",
    }

    ok = all(checks.values())
    return {
        "ok": ok,
        "mode": "artifact_required",
        "ancestry": ancestry,
        "artifact": str(EQUIVALENCE_ARTIFACT),
        "checks": checks,
        "artifact_age_seconds": age_seconds,
        "classifications": classifications,
        "final_equivalence_decision": payload.get("final_equivalence_decision"),
    }


def main() -> int:
    pid = _read_pid()
    discovered_pids = _discover_scheduler_pids()
    head = _head_sha()
    build = _last_build_info()
    equivalence = _evaluate_governance_equivalence(head)

    result = {
        "canonical_root": str(ROOT),
        "head_sha": head,
        "pid_file": str(PID_FILE),
        "pid": pid,
        "discovered_scheduler_pids": discovered_pids,
        "process_running": False,
        "process": {"command": None, "elapsed": None, "cwd": None},
        "checks": {
            "pid_present": pid is not None,
            "command_contains_scheduler": False,
            "cwd_matches_root": False,
            "build_info_present": bool(build["line"]),
            "build_sha_matches_head": False,
            "governance_equivalence_proven": bool(equivalence.get("ok")),
        },
        "build_info": build,
        "governance_equivalence": equivalence,
    }

    candidates: list[int] = []
    if pid is not None:
        candidates.append(pid)
    for discovered in discovered_pids:
        if discovered not in candidates:
            candidates.append(discovered)

    selected_pid = None
    selected_info = None
    for candidate in candidates:
        info = _process_info(candidate)
        cmd = info.get("command") or ""
        if cmd and "scheduler.py" in cmd:
            selected_pid = candidate
            selected_info = info
            break

    if selected_pid is not None and selected_info is not None:
        result["process_running"] = True
        result["process"] = selected_info
        result["pid"] = selected_pid
        cwd = selected_info.get("cwd") or ""
        result["checks"]["command_contains_scheduler"] = True
        result["checks"]["cwd_matches_root"] = os.path.normpath(cwd) == os.path.normpath(str(ROOT))
        if pid is not None and pid != selected_pid:
            result["checks"]["pid_present"] = False

    if build.get("sha") and head != "unknown":
        result["checks"]["build_sha_matches_head"] = build["sha"] == head

    required_checks = (
        "pid_present",
        "command_contains_scheduler",
        "cwd_matches_root",
        "build_info_present",
        "build_sha_matches_head",
        "governance_equivalence_proven",
    )
    result["ok"] = all(bool(result["checks"].get(name)) for name in required_checks)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
