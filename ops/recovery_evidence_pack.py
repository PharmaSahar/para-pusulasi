#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class CommandResult:
    command: str
    working_directory: str
    python_executable: str
    exit_code: int
    stdout: str
    stderr: str
    started_at: str
    finished_at: str


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_command(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> CommandResult:
    started = utc_now_iso()
    proc = subprocess.run(command, cwd=str(cwd), capture_output=True, text=True, env=env, check=False)
    finished = utc_now_iso()
    return CommandResult(
        command=" ".join(shlex.quote(part) for part in command),
        working_directory=str(cwd),
        python_executable=sys.executable,
        exit_code=int(proc.returncode),
        stdout=proc.stdout or "",
        stderr=proc.stderr or "",
        started_at=started,
        finished_at=finished,
    )


def run_command_bytes(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> tuple[CommandResult, bytes, bytes]:
    started = utc_now_iso()
    proc = subprocess.run(command, cwd=str(cwd), capture_output=True, text=False, env=env, check=False)
    finished = utc_now_iso()
    stdout_bytes = proc.stdout or b""
    stderr_bytes = proc.stderr or b""
    result = CommandResult(
        command=" ".join(shlex.quote(part) for part in command),
        working_directory=str(cwd),
        python_executable=sys.executable,
        exit_code=int(proc.returncode),
        stdout=stdout_bytes.decode("utf-8", errors="replace"),
        stderr=stderr_bytes.decode("utf-8", errors="replace"),
        started_at=started,
        finished_at=finished,
    )
    return result, stdout_bytes, stderr_bytes


def safe_read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def file_meta(path: Path) -> dict[str, Any]:
    exists = path.exists()
    mtime = None
    if exists:
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()
    return {
        "path": str(path),
        "exists": exists,
        "modified_at_utc": mtime,
    }


def to_canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_git_status_porcelain(status_stdout: str) -> tuple[list[str], list[str]]:
    untracked_files: list[str] = []
    tracked_modified_files: list[str] = []
    for raw_line in status_stdout.splitlines():
        line = raw_line.rstrip("\n")
        if not line:
            continue
        if line.startswith("?? "):
            untracked_files.append(line[3:])
            continue
        if len(line) < 4:
            continue
        path = line[3:]
        tracked_modified_files.append(path)
    return untracked_files, tracked_modified_files


def git_mode_for_path(path: Path) -> str:
    if path.is_symlink():
        return "120000"
    st_mode = path.stat().st_mode
    return f"{(0o100000 | (st_mode & 0o777)):06o}"


def file_sha256(path: Path) -> str | None:
    if not path.exists() or path.is_dir():
        return None
    if path.is_symlink():
        target = os.readlink(path)
        return sha256_hex(target.encode("utf-8"))
    return sha256_hex(path.read_bytes())


def build_untracked_manifest(root: Path, untracked_files: list[str]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for rel in sorted(set(untracked_files)):
        candidate = root / rel
        if not candidate.exists() and not candidate.is_symlink():
            entries.append(
                {
                    "path": rel,
                    "exists": False,
                    "mode": None,
                    "size_bytes": None,
                    "sha256": None,
                }
            )
            continue
        if candidate.is_dir():
            for nested in sorted(p for p in candidate.rglob("*") if p.is_file() or p.is_symlink()):
                rel_nested = nested.relative_to(root).as_posix()
                size_bytes = None if nested.is_symlink() else nested.stat().st_size
                entries.append(
                    {
                        "path": rel_nested,
                        "exists": True,
                        "mode": git_mode_for_path(nested),
                        "size_bytes": size_bytes,
                        "sha256": file_sha256(nested),
                    }
                )
            continue
        size_bytes = None if candidate.is_symlink() else candidate.stat().st_size
        entries.append(
            {
                "path": rel,
                "exists": True,
                "mode": git_mode_for_path(candidate),
                "size_bytes": size_bytes,
                "sha256": file_sha256(candidate),
            }
        )
    return sorted(entries, key=lambda item: item["path"])


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    logs = root / "logs"
    docs = root / "docs"
    logs.mkdir(parents=True, exist_ok=True)
    docs.mkdir(parents=True, exist_ok=True)

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    script_path = Path(__file__).resolve()
    script_sha256_before = sha256_hex(script_path.read_bytes())

    head_cmd = run_command(["git", "rev-parse", "HEAD"], root)
    branch_cmd = run_command(["git", "branch", "--show-current"], root)
    status_cmd = run_command(["git", "status", "--short", "--untracked-files=all"], root)
    diff_check_cmd = run_command(["git", "--no-pager", "diff", "--check"], root)
    git_diff_cmd, git_diff_stdout_bytes, _ = run_command_bytes(["git", "--no-pager", "diff", "--binary", "--no-ext-diff"], root)
    git_diff_cached_cmd, git_diff_cached_stdout_bytes, _ = run_command_bytes(
        ["git", "--no-pager", "diff", "--cached", "--binary", "--no-ext-diff"],
        root,
    )
    git_diff_sha256 = sha256_hex(git_diff_stdout_bytes)
    git_diff_cached_sha256 = sha256_hex(git_diff_cached_stdout_bytes)
    untracked_files, tracked_modified_files = parse_git_status_porcelain(status_cmd.stdout)
    untracked_manifest = build_untracked_manifest(root, untracked_files)
    untracked_manifest_sha256 = sha256_hex(to_canonical_json_bytes({"entries": untracked_manifest}))
    working_tree_manifest_payload = {
        "base_commit_sha": head_cmd.stdout.strip(),
        "unstaged_diff_sha256": git_diff_sha256,
        "staged_diff_sha256": git_diff_cached_sha256,
        "untracked_manifest_sha256": untracked_manifest_sha256,
        "tracked_modified_files": tracked_modified_files,
    }
    working_tree_manifest_sha256 = sha256_hex(to_canonical_json_bytes(working_tree_manifest_payload))

    pytest_cmd = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "tests/test_refresh_governance_readiness.py",
        "tests/test_p0_validation_metrics_report.py",
        "tests/test_governance_dashboard_safety.py",
        "tests/test_executive_runtime_evidence.py",
        "tests/test_ops_runtime_layers.py",
    ]
    pytest_env = dict(os.environ)
    pytest_env["PYTHONPATH"] = "."
    tests_run_cmd = run_command(pytest_cmd, root, env=pytest_env)

    wrapper_summary_path = logs / f"governance_refresh_run_evidence_{run_id}.json"

    for path in [
        logs / "p0_validation_metrics_latest.json",
        logs / "p0_p1_artifacts_bundle_latest.json",
        logs / "executive_dashboard.json",
        docs / "governance_readiness_latest.md",
        logs / "proven_validated_status_latest.json",
    ]:
        try:
            if path.exists():
                path.unlink()
        except Exception:
            pass

    wrapper_cmd = [
        sys.executable,
        "ops/refresh_governance_readiness.py",
        "--lookback-rows",
        "500",
        "--freshness-max-minutes",
        "180",
        "--run-gate",
        "--summary-output",
        str(wrapper_summary_path),
    ]
    wrapper_run_cmd = run_command(wrapper_cmd, root, env=pytest_env)

    wrapper_summary = safe_read_json(wrapper_summary_path)
    script_sha256_after_prewrite = sha256_hex(script_path.read_bytes())
    script_unchanged_prewrite = script_sha256_after_prewrite == script_sha256_before

    artifacts = {
        "p0_metrics": file_meta(logs / "p0_validation_metrics_latest.json"),
        "bundle": file_meta(logs / "p0_p1_artifacts_bundle_latest.json"),
        "executive_dashboard": file_meta(logs / "executive_dashboard.json"),
        "readiness_markdown": file_meta(docs / "governance_readiness_latest.md"),
        "wrapper_summary": file_meta(wrapper_summary_path),
    }

    producer_steps = []
    for step in wrapper_summary.get("steps", []):
        if not isinstance(step, dict):
            continue
        producer_steps.append(
            {
                "name": step.get("name"),
                "command": step.get("command"),
                "exit_code": step.get("exit_code"),
                "duration_ms": step.get("duration_ms"),
                "artifact_path": step.get("artifact"),
                "artifact_exists": ((step.get("artifact_validation") or {}).get("exists")),
                "produced_in_step": ((step.get("artifact_validation") or {}).get("produced_in_step")),
            }
        )

    evidence = {
        "schema_version": "v1",
        "run_id": run_id,
        "context": {
            "git_head": head_cmd.stdout.strip(),
            "git_branch": branch_cmd.stdout.strip(),
            "root": str(root),
            "script_path": str(script_path),
            "measurement_exclusions": [
                "logs/recovery_evidence_pack_*.json",
                "logs/recovery_evidence_pack_*.json.sha256",
            ],
            "state_fingerprint_captured_before_execution": True,
        },
        "commands": {
            "git_rev_parse_head": asdict(head_cmd),
            "git_branch_show_current": asdict(branch_cmd),
            "git_status_short": asdict(status_cmd),
            "git_diff_check": asdict(diff_check_cmd),
            "git_diff": asdict(git_diff_cmd),
            "git_diff_cached": asdict(git_diff_cached_cmd),
            "recovery_test_set": asdict(tests_run_cmd),
            "wrapper_only_run": asdict(wrapper_run_cmd),
        },
        "wrapper_summary": wrapper_summary,
        "control_fields": {
            "git_head": head_cmd.stdout.strip(),
            "git_branch": branch_cmd.stdout.strip(),
            "git_status": status_cmd.stdout,
            "base_commit_sha": head_cmd.stdout.strip(),
            "unstaged_diff_sha256": git_diff_sha256,
            "staged_diff_sha256": git_diff_cached_sha256,
            "git_diff_check_exit_code": diff_check_cmd.exit_code,
            "test_exit_code": tests_run_cmd.exit_code,
            "wrapper_exit_code": wrapper_run_cmd.exit_code,
            "wrapper_summary_path": str(wrapper_summary_path),
            "gate_exit_code": wrapper_summary.get("gate_exit_code"),
            "evidence_script_sha256": script_sha256_before,
            "git_diff_sha256": git_diff_sha256,
            "git_diff_cached_sha256": git_diff_cached_sha256,
            "untracked_files": untracked_files,
            "tracked_modified_files": tracked_modified_files,
            "untracked_manifest": untracked_manifest,
            "untracked_manifest_sha256": untracked_manifest_sha256,
            "working_tree_manifest_sha256": working_tree_manifest_sha256,
            "script_sha256_before": script_sha256_before,
            "script_sha256_after": script_sha256_after_prewrite,
            "script_unchanged_during_run": script_unchanged_prewrite,
        },
        "producer_steps": producer_steps,
        "gate": {
            "command_completed": wrapper_summary.get("gate_command_completed"),
            "exit_code": wrapper_summary.get("gate_exit_code"),
            "maturity": wrapper_summary.get("gate_maturity"),
            "gate_passed": wrapper_summary.get("gate_passed"),
            "blockers": wrapper_summary.get("gate_blockers"),
        },
        "reproducibility_flags": {
            "review_test_set_passed": tests_run_cmd.exit_code == 0,
            "review_diff_check_passed": diff_check_cmd.exit_code == 0 and not diff_check_cmd.stdout.strip(),
            "review_refresh_chain_reproduced": bool(wrapper_summary.get("required_chain_reproduced")),
            "review_wrapper_only_run_reverified_in_latest_step": wrapper_run_cmd.exit_code == 0,
            "tracked_working_tree_state_fingerprinted": True,
            "untracked_file_names_recorded": len(untracked_files) > 0,
            "untracked_file_contents_fingerprinted": all(item.get("sha256") for item in untracked_manifest if item.get("exists")),
            "full_working_tree_reproducibility": "not_yet_proven",
            "canonical_repository_reproduced": False,
            "commit_reproducibility_proven": False,
            "production_ready": False,
        },
        "artifacts": artifacts,
        "integrity": {
            "strategy": "external_sidecar",
            "algorithm": "sha256",
            "algorithm_version": "sha256-v1",
            "serialization_version": "json-canonical-v1",
            "canonicalization": {
                "encoding": "utf-8",
                "sort_keys": True,
                "separators": [",", ":"],
                "ensure_ascii": False,
            },
            "evidence_script_sha256": script_sha256_before,
            "script_hash_scope": "sha256(exact bytes of executing script at startup)",
            "script_sha256_before": script_sha256_before,
            "script_sha256_after": script_sha256_after_prewrite,
            "script_unchanged_during_run": script_unchanged_prewrite,
            "evidence_file_sha256": None,
            "sha256_sidecar": f"recovery_evidence_pack_{run_id}.json.sha256",
            "verification": "Recompute sha256 of exact JSON bytes and compare with sidecar.",
        },
        "generated_at_utc": utc_now_iso(),
    }

    out_path = logs / f"recovery_evidence_pack_{run_id}.json"
    sidecar_path = logs / f"recovery_evidence_pack_{run_id}.json.sha256"
    if out_path.exists():
        print(f"Evidence file already exists: {out_path}")
        return 2

    payload_bytes = to_canonical_json_bytes(evidence)
    file_sha256 = sha256_hex(payload_bytes)
    out_path.write_bytes(payload_bytes)
    sidecar_path.write_text(f"{file_sha256}  {out_path.name}\n", encoding="utf-8")

    verify_sha256 = sha256_hex(out_path.read_bytes())
    if verify_sha256 != file_sha256:
        print(json.dumps({"ok": False, "reason": "sha256_mismatch_after_write", "expected": file_sha256, "actual": verify_sha256}, ensure_ascii=False, indent=2))
        return 3

    script_sha256_after = sha256_hex(script_path.read_bytes())
    script_unchanged_during_run = script_sha256_after == script_sha256_before
    if not script_unchanged_during_run:
        print(
            json.dumps(
                {
                    "ok": False,
                    "reason": "script_bytes_changed_during_execution",
                    "expected": script_sha256_before,
                    "actual": script_sha256_after,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 4

    print(
        json.dumps(
            {
                "ok": True,
                "evidence_file": str(out_path),
                "evidence_file_sha256": file_sha256,
                "evidence_sha256_sidecar": str(sidecar_path),
                "evidence_script_sha256": script_sha256_before,
                "script_sha256_before": script_sha256_before,
                "script_sha256_after": script_sha256_after,
                "script_unchanged_during_run": script_unchanged_during_run,
                "git_diff_sha256": git_diff_sha256,
                "git_diff_cached_sha256": git_diff_cached_sha256,
                "untracked_manifest_sha256": untracked_manifest_sha256,
                "working_tree_manifest_sha256": working_tree_manifest_sha256,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
