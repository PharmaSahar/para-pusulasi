#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shlex
import signal
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACTS_DIR = PROJECT_ROOT / "artifacts" / "deployment"
DEFAULT_STATE_ROOT = Path("/tmp/preprod_validation_state")
DEFAULT_EXTERNAL_RUNNER = Path("/tmp/preprod_runtime_validation.py")


@dataclass(frozen=True)
class PhaseSpec:
    name: str
    command: list[str]
    timeout_seconds: int
    cwd: str | None = None
    category: str = "pytest"


@dataclass
class PhaseResult:
    name: str
    status: str
    returncode: int
    started_at_utc: str
    finished_at_utc: str
    duration_seconds: float
    timeout_seconds: int
    command: list[str]
    cwd: str
    stdout_tail: str
    stderr_tail: str
    heartbeat_count: int


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tail(text: str, max_lines: int = 40) -> str:
    lines = (text or "").splitlines()
    return "\n".join(lines[-max_lines:])


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _tracked_mutations(repo_root: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    rows = []
    for raw in proc.stdout.splitlines():
        row = raw.rstrip("\n")
        if not row:
            continue
        if row.startswith("?? "):
            continue
        if len(row) < 4:
            continue
        rows.append(row[3:])
    return rows


def _validate_phase_order(phases: Iterable[PhaseSpec]) -> None:
    seen_full_pytest = False
    for phase in phases:
        if phase.category == "full_pytest":
            seen_full_pytest = True
        if seen_full_pytest and phase.category == "runtime":
            raise ValueError("phase_order_violation: runtime phase appears after full_pytest")


class StateStore:
    def __init__(self, state_path: Path) -> None:
        self.state_path = state_path
        self.state: dict[str, Any] = {
            "run_id": state_path.parent.name,
            "status": "created",
            "started_at_utc": utc_now(),
            "updated_at_utc": utc_now(),
            "current_phase": None,
            "completed_phases": [],
            "failed_phase": None,
            "phase_results": [],
            "tracked_mutations": [],
            "baseline_tracked_mutations": [],
        }
        self.flush()

    def update(self, **kwargs: Any) -> None:
        self.state.update(kwargs)
        self.state["updated_at_utc"] = utc_now()
        self.flush()

    def append_phase_result(self, result: PhaseResult) -> None:
        self.state["phase_results"].append(asdict(result))
        self.state["completed_phases"].append(result.name)
        self.state["updated_at_utc"] = utc_now()
        self.flush()

    def flush(self) -> None:
        _atomic_write_json(self.state_path, self.state)


class HeartbeatWriter:
    def __init__(self, phase_log: Path, run_id: str, phase_name: str, interval_seconds: float = 1.0) -> None:
        self.phase_log = phase_log
        self.run_id = run_id
        self.phase_name = phase_name
        self.interval_seconds = max(0.2, float(interval_seconds))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.count = 0

    def start(self) -> None:
        self.count += 1
        _append_jsonl(
            self.phase_log,
            {
                "event": "heartbeat",
                "run_id": self.run_id,
                "phase": self.phase_name,
                "heartbeat_index": self.count,
                "ts_utc": utc_now(),
            },
        )
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            self.count += 1
            _append_jsonl(
                self.phase_log,
                {
                    "event": "heartbeat",
                    "run_id": self.run_id,
                    "phase": self.phase_name,
                    "heartbeat_index": self.count,
                    "ts_utc": utc_now(),
                },
            )


def _terminate_process_group(proc: subprocess.Popen[str], grace_seconds: float = 5.0) -> None:
    try:
        pgid = os.getpgid(proc.pid)
    except Exception:
        pgid = None

    if pgid is None:
        try:
            proc.terminate()
        except Exception:
            return
    else:
        try:
            os.killpg(pgid, signal.SIGTERM)
        except Exception:
            pass

    deadline = time.time() + grace_seconds
    while time.time() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.05)

    if pgid is None:
        try:
            proc.kill()
        except Exception:
            pass
    else:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except Exception:
            pass


def run_phase(phase: PhaseSpec, run_id: str, phase_log: Path) -> PhaseResult:
    started = time.time()
    started_iso = utc_now()
    cwd = str(PROJECT_ROOT if phase.cwd is None else Path(phase.cwd))

    _append_jsonl(
        phase_log,
        {
            "event": "phase_start",
            "run_id": run_id,
            "phase": phase.name,
            "category": phase.category,
            "timeout_seconds": phase.timeout_seconds,
            "cwd": cwd,
            "command": " ".join(shlex.quote(part) for part in phase.command),
            "ts_utc": started_iso,
        },
    )

    heartbeat = HeartbeatWriter(phase_log=phase_log, run_id=run_id, phase_name=phase.name)
    heartbeat.start()

    proc = subprocess.Popen(
        phase.command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )

    timed_out = False
    out = ""
    err = ""
    try:
        out, err = proc.communicate(timeout=phase.timeout_seconds)
        rc = int(proc.returncode or 0)
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate_process_group(proc)
        out2, err2 = proc.communicate(timeout=2)
        out = (out2 or "") + "\n[timeout] phase exceeded timeout"
        err = err2 or ""
        rc = 124
    finally:
        heartbeat.stop()

    finished_iso = utc_now()
    duration = max(0.0, time.time() - started)
    status = "timeout" if timed_out else ("pass" if rc == 0 else "fail")

    _append_jsonl(
        phase_log,
        {
            "event": "phase_end",
            "run_id": run_id,
            "phase": phase.name,
            "status": status,
            "returncode": rc,
            "duration_seconds": round(duration, 3),
            "heartbeat_count": heartbeat.count,
            "stdout_tail": _tail(out),
            "stderr_tail": _tail(err),
            "ts_utc": finished_iso,
        },
    )

    return PhaseResult(
        name=phase.name,
        status=status,
        returncode=rc,
        started_at_utc=started_iso,
        finished_at_utc=finished_iso,
        duration_seconds=round(duration, 3),
        timeout_seconds=phase.timeout_seconds,
        command=list(phase.command),
        cwd=cwd,
        stdout_tail=_tail(out),
        stderr_tail=_tail(err),
        heartbeat_count=heartbeat.count,
    )


def _default_python() -> str:
    preferred = PROJECT_ROOT / ".venv-2" / "bin" / "python"
    return str(preferred if preferred.exists() else Path(sys.executable))


def default_mini_phases() -> list[PhaseSpec]:
    py = _default_python()
    return [
        PhaseSpec(
            name="identity_probe",
            command=[py, "-c", "import os,sys; print('identity_ok', os.getcwd(), sys.executable)"],
            timeout_seconds=20,
            category="runtime",
        ),
        PhaseSpec(
            name="targeted_preprod_tests",
            command=[
                py,
                "-m",
                "pytest",
                "-q",
                "tests/test_preprod_validation_runner.py",
                "tests/test_upload_precheck.py",
            ],
            timeout_seconds=120,
            category="pytest",
        ),
    ]


def default_full_phases() -> list[PhaseSpec]:
    py = _default_python()
    return [
        PhaseSpec(
            name="runtime_probe",
            command=[py, "-c", "import scheduler; print('runtime_probe_ok')"],
            timeout_seconds=30,
            category="runtime",
        ),
        PhaseSpec(
            name="full_pytest_wdefault",
            command=[py, "-m", "pytest", "-q", "-W", "default"],
            timeout_seconds=900,
            category="full_pytest",
        ),
        PhaseSpec(
            name="full_pytest_normal",
            command=[py, "-m", "pytest", "-q"],
            timeout_seconds=900,
            category="full_pytest",
        ),
    ]


def run_validation(phases: list[PhaseSpec], run_id: str, artifacts_dir: Path, state_root: Path, stop_on_tracked_mutation: bool = True) -> dict[str, Any]:
    _validate_phase_order(phases)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    run_state_dir = state_root / run_id
    run_state_dir.mkdir(parents=True, exist_ok=True)
    state_path = run_state_dir / "state.json"
    phase_log = artifacts_dir / "preprod_runner_phase_log.jsonl"

    store = StateStore(state_path)
    baseline_tracked = set(_tracked_mutations(PROJECT_ROOT))
    store.update(
        status="running",
        current_phase=None,
        baseline_tracked_mutations=sorted(baseline_tracked),
    )

    all_results: list[PhaseResult] = []
    for phase in phases:
        store.update(current_phase=phase.name)
        result = run_phase(phase=phase, run_id=run_id, phase_log=phase_log)
        store.append_phase_result(result)
        all_results.append(result)

        tracked_now = set(_tracked_mutations(PROJECT_ROOT))
        new_tracked = sorted(tracked_now - baseline_tracked)
        if new_tracked:
            store.update(tracked_mutations=new_tracked)
            _append_jsonl(
                phase_log,
                {
                    "event": "tracked_mutation_detected",
                    "run_id": run_id,
                    "phase": phase.name,
                    "tracked_files": new_tracked,
                    "ts_utc": utc_now(),
                },
            )
            if stop_on_tracked_mutation:
                store.update(status="failed", failed_phase=phase.name)
                return {
                    "status": "failed",
                    "reason": "tracked_mutation_detected",
                    "failed_phase": phase.name,
                    "tracked_mutations": new_tracked,
                    "state_path": str(state_path),
                    "phase_log": str(phase_log),
                    "results": [asdict(r) for r in all_results],
                }

        if result.status != "pass":
            store.update(status="failed", failed_phase=phase.name)
            return {
                "status": "failed",
                "reason": result.status,
                "failed_phase": phase.name,
                "tracked_mutations": store.state.get("tracked_mutations", []),
                "state_path": str(state_path),
                "phase_log": str(phase_log),
                "results": [asdict(r) for r in all_results],
            }

    store.update(status="passed", current_phase=None, failed_phase=None)
    return {
        "status": "passed",
        "reason": "all_phases_passed",
        "failed_phase": None,
        "tracked_mutations": store.state.get("tracked_mutations", []),
        "state_path": str(state_path),
        "phase_log": str(phase_log),
        "results": [asdict(r) for r in all_results],
    }


def audit_external_runner(external_runner_path: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    if not external_runner_path.exists():
        return {"exists": False, "path": str(external_runner_path), "calls": rows}

    text = external_runner_path.read_text(encoding="utf-8", errors="ignore")
    for line_no, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if "subprocess.run(" in stripped or "subprocess.Popen(" in stripped:
            call = "subprocess.run" if "subprocess.run(" in stripped else "subprocess.Popen"
            rows.append(
                {
                    "line": line_no,
                    "call": call,
                    "snippet": stripped[:220],
                    "captures_output": "capture_output=True" in stripped or "stdout=" in stripped,
                    "has_timeout_literal": "timeout=" in stripped,
                    "process_group_strategy": "start_new_session=True" if "start_new_session=True" in stripped else "none",
                }
            )

    findings: list[str] = []
    if rows and all(r["process_group_strategy"] == "none" for r in rows):
        findings.append("No process-group isolation on subprocess calls; child cleanup may be incomplete on timeout.")
    if rows and any(r["call"] == "subprocess.run" and not r["has_timeout_literal"] for r in rows):
        findings.append("At least one subprocess.run call has no explicit timeout in-call.")
    if "ThreadPoolExecutor" in text and "run([py, '-m', 'pytest', '-q', '-W', 'default']" in text:
        findings.append("Long full-suite pytest is coupled into the same long-lived workflow, increasing observability ambiguity.")

    return {
        "exists": True,
        "path": str(external_runner_path),
        "calls": rows,
        "findings": findings,
    }


def write_diagnosis_markdown(path: Path, audit: dict[str, Any]) -> None:
    lines = [
        "# Preprod Runner Diagnosis",
        "",
        f"- External runner path: {audit.get('path')}",
        f"- External runner exists: {audit.get('exists')}",
        f"- Subprocess call count: {len(audit.get('calls', []))}",
        "",
        "## Subprocess Call Table",
        "",
        "| line | call | captures_output | has_timeout_literal | process_group_strategy | snippet |",
        "| --- | --- | --- | --- | --- | --- |",
    ]

    calls = audit.get("calls", [])
    if calls:
        for row in calls:
            snippet = str(row.get("snippet", "")).replace("|", "\\|")
            lines.append(
                f"| {row.get('line')} | {row.get('call')} | {row.get('captures_output')} | {row.get('has_timeout_literal')} | {row.get('process_group_strategy')} | {snippet} |"
            )
    else:
        lines.append("| - | - | - | - | - | no subprocess calls discovered |")

    lines.extend(["", "## Findings", ""])
    findings = audit.get("findings", [])
    if findings:
        lines.extend(f"- {item}" for item in findings)
    else:
        lines.append("- No high-confidence defects discovered by static call scan.")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_validation_markdown(path: Path, title: str, result: dict[str, Any]) -> None:
    lines = [
        f"# {title}",
        "",
        f"- status: {result.get('status')}",
        f"- reason: {result.get('reason')}",
        f"- failed_phase: {result.get('failed_phase')}",
        f"- state_path: {result.get('state_path')}",
        f"- phase_log: {result.get('phase_log')}",
        "",
        "## Phase Results",
        "",
        "| phase | status | rc | duration_seconds | heartbeats |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in result.get("results", []):
        lines.append(
            f"| {row.get('name')} | {row.get('status')} | {row.get('returncode')} | {row.get('duration_seconds')} | {row.get('heartbeat_count')} |"
        )
    tracked = result.get("tracked_mutations") or []
    lines.extend(["", "## Tracked Mutations", ""])
    if tracked:
        lines.extend(f"- {item}" for item in tracked)
    else:
        lines.append("- none")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Stabilized preprod validation runner")
    sub = parser.add_subparsers(dest="command", required=True)

    p_diag = sub.add_parser("diagnose", help="Audit external runner and write diagnosis artifact")
    p_diag.add_argument("--external-runner", default=str(DEFAULT_EXTERNAL_RUNNER))
    p_diag.add_argument("--artifacts-dir", default=str(DEFAULT_ARTIFACTS_DIR))

    p_self = sub.add_parser("selftest", help="Run synthetic self-tests and write artifact")
    p_self.add_argument("--artifacts-dir", default=str(DEFAULT_ARTIFACTS_DIR))

    p_mini = sub.add_parser("mini", help="Run mini validation")
    p_mini.add_argument("--run-id", default=f"mini_{uuid.uuid4().hex[:8]}")
    p_mini.add_argument("--artifacts-dir", default=str(DEFAULT_ARTIFACTS_DIR))
    p_mini.add_argument("--state-root", default=str(DEFAULT_STATE_ROOT))

    p_full = sub.add_parser("full", help="Run full validation")
    p_full.add_argument("--run-id", default=f"full_{uuid.uuid4().hex[:8]}")
    p_full.add_argument("--artifacts-dir", default=str(DEFAULT_ARTIFACTS_DIR))
    p_full.add_argument("--state-root", default=str(DEFAULT_STATE_ROOT))

    return parser.parse_args(argv)


def _run_selftests(artifacts_dir: Path) -> dict[str, Any]:
    py = _default_python()
    proc = subprocess.run(
        [py, "-m", "pytest", "-q", "tests/test_preprod_validation_runner.py"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    result = {
        "status": "PASS" if proc.returncode == 0 else "FAIL",
        "returncode": proc.returncode,
        "stdout_tail": _tail(proc.stdout, 80),
        "stderr_tail": _tail(proc.stderr, 80),
        "generated_at_utc": utc_now(),
    }
    out = artifacts_dir / "preprod_runner_selftest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.command == "diagnose":
        artifacts_dir = Path(args.artifacts_dir)
        audit = audit_external_runner(Path(args.external_runner))
        out_path = artifacts_dir / "preprod_runner_diagnosis.md"
        write_diagnosis_markdown(out_path, audit)
        print(json.dumps({"status": "ok", "artifact": str(out_path), "calls": len(audit.get("calls", []))}, indent=2))
        return 0

    if args.command == "selftest":
        artifacts_dir = Path(args.artifacts_dir)
        result = _run_selftests(artifacts_dir)
        print(json.dumps(result, indent=2))
        return 0 if result["status"] == "PASS" else 1

    if args.command in {"mini", "full"}:
        artifacts_dir = Path(args.artifacts_dir)
        state_root = Path(args.state_root)
        run_id = args.run_id
        phases = default_mini_phases() if args.command == "mini" else default_full_phases()
        result = run_validation(phases=phases, run_id=run_id, artifacts_dir=artifacts_dir, state_root=state_root)
        if args.command == "mini":
            write_validation_markdown(artifacts_dir / "preprod_runner_mini_validation.md", "Preprod Runner Mini Validation", result)
        else:
            write_validation_markdown(artifacts_dir / "preprod_runner_final_validation.md", "Preprod Runner Final Validation", result)
        print(json.dumps(result, indent=2))
        return 0 if result["status"] == "passed" else 1

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
