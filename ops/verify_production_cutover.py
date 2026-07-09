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
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PID_FILE = ROOT / "logs" / "production_scheduler.pid"
LOG_FILE = ROOT / "logs" / "production_scheduler.out"


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
    if not LOG_FILE.exists():
        return {"line": None, "sha": None}

    build_line = None
    for line in LOG_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "BUILD_INFO scheduler" in line:
            build_line = line

    sha = None
    if build_line:
        m = re.search(r"git_sha=([a-zA-Z0-9]+)", build_line)
        if m:
            sha = m.group(1)

    return {"line": build_line, "sha": sha}


def main() -> int:
    pid = _read_pid()
    discovered_pids = _discover_scheduler_pids()
    head = _head_sha()
    build = _last_build_info()

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
        },
        "build_info": build,
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

    result["ok"] = all(
        [
            bool(result["pid"]),
            result["process_running"],
            result["checks"]["command_contains_scheduler"],
            result["checks"]["cwd_matches_root"],
            result["checks"]["build_info_present"],
        ]
    )

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
