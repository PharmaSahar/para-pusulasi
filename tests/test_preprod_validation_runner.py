from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

import ops.preprod_validation_runner as runner


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init"], cwd=str(path), check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(path), check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=str(path), check=True)
    (path / "tracked.txt").write_text("a\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=str(path), check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(path), check=True, capture_output=True, text=True)


def test_utc_now_has_timezone() -> None:
    value = runner.utc_now()
    assert "T" in value
    assert "+00:00" in value or value.endswith("Z")


def test_tail_returns_last_lines() -> None:
    text = "\n".join(str(i) for i in range(10))
    assert runner._tail(text, max_lines=3) == "7\n8\n9"


def test_atomic_write_json_writes_file(tmp_path: Path) -> None:
    out = tmp_path / "state.json"
    runner._atomic_write_json(out, {"ok": True})
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["ok"] is True


def test_tracked_mutations_ignores_untracked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _init_git_repo(tmp_path)
    (tmp_path / "new.txt").write_text("new\n", encoding="utf-8")
    monkeypatch.setattr(runner, "PROJECT_ROOT", tmp_path)
    assert runner._tracked_mutations(tmp_path) == []


def test_tracked_mutations_detects_tracked_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _init_git_repo(tmp_path)
    (tmp_path / "tracked.txt").write_text("b\n", encoding="utf-8")
    monkeypatch.setattr(runner, "PROJECT_ROOT", tmp_path)
    rows = runner._tracked_mutations(tmp_path)
    assert "tracked.txt" in rows


def test_validate_phase_order_accepts_valid_sequence() -> None:
    phases = [
        runner.PhaseSpec(name="runtime", command=[sys.executable, "-c", "print('ok')"], timeout_seconds=2, category="runtime"),
        runner.PhaseSpec(name="full", command=[sys.executable, "-c", "print('ok')"], timeout_seconds=2, category="full_pytest"),
    ]
    runner._validate_phase_order(phases)


def test_validate_phase_order_rejects_runtime_after_full() -> None:
    phases = [
        runner.PhaseSpec(name="full", command=[sys.executable, "-c", "print('ok')"], timeout_seconds=2, category="full_pytest"),
        runner.PhaseSpec(name="runtime2", command=[sys.executable, "-c", "print('ok')"], timeout_seconds=2, category="runtime"),
    ]
    with pytest.raises(ValueError):
        runner._validate_phase_order(phases)


def test_heartbeat_writer_emits_rows(tmp_path: Path) -> None:
    log_path = tmp_path / "phase_log.jsonl"
    hb = runner.HeartbeatWriter(log_path, run_id="r1", phase_name="p1", interval_seconds=0.2)
    hb.start()
    time.sleep(0.55)
    hb.stop()
    text = log_path.read_text(encoding="utf-8")
    assert "heartbeat" in text
    assert hb.count >= 2


def test_run_phase_success(tmp_path: Path) -> None:
    log_path = tmp_path / "phase_log.jsonl"
    phase = runner.PhaseSpec(name="ok", command=[sys.executable, "-c", "print('ok')"], timeout_seconds=3)
    res = runner.run_phase(phase=phase, run_id="r1", phase_log=log_path, default_cwd=tmp_path)
    assert res.status == "pass"
    assert res.returncode == 0


def test_run_phase_timeout(tmp_path: Path) -> None:
    log_path = tmp_path / "phase_log.jsonl"
    phase = runner.PhaseSpec(name="slow", command=[sys.executable, "-c", "import time; time.sleep(2)"], timeout_seconds=1)
    res = runner.run_phase(phase=phase, run_id="r1", phase_log=log_path, default_cwd=tmp_path)
    assert res.status == "timeout"
    assert res.returncode == 124


def test_run_validation_all_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _init_git_repo(tmp_path)
    monkeypatch.setattr(runner, "PROJECT_ROOT", tmp_path)
    artifacts = tmp_path / "artifacts"
    state_root = tmp_path / "state"
    phases = [
        runner.PhaseSpec(name="a", command=[sys.executable, "-c", "print('a')"], timeout_seconds=2),
        runner.PhaseSpec(name="b", command=[sys.executable, "-c", "print('b')"], timeout_seconds=2),
    ]
    out = runner.run_validation(phases, run_id="run1", artifacts_dir=artifacts, state_root=state_root, repo_root=tmp_path)
    assert out["status"] == "passed"
    state_path = Path(out["state_path"])
    assert state_path.exists()


def test_run_validation_fails_on_nonzero_phase(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _init_git_repo(tmp_path)
    monkeypatch.setattr(runner, "PROJECT_ROOT", tmp_path)
    phases = [
        runner.PhaseSpec(name="bad", command=[sys.executable, "-c", "import sys; sys.exit(5)"], timeout_seconds=2),
    ]
    out = runner.run_validation(phases, run_id="run2", artifacts_dir=tmp_path / "art", state_root=tmp_path / "state", repo_root=tmp_path)
    assert out["status"] == "failed"
    assert out["failed_phase"] == "bad"


def test_run_validation_fails_on_tracked_mutation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _init_git_repo(tmp_path)
    monkeypatch.setattr(runner, "PROJECT_ROOT", tmp_path)
    phases = [
        runner.PhaseSpec(
            name="mutate",
            command=[sys.executable, "-c", "from pathlib import Path; Path('tracked.txt').write_text('mutated\\n', encoding='utf-8')"],
            timeout_seconds=2,
        ),
    ]
    out = runner.run_validation(phases, run_id="run3", artifacts_dir=tmp_path / "art", state_root=tmp_path / "state", repo_root=tmp_path)
    assert out["status"] == "failed"
    assert out["reason"] == "tracked_mutation_detected"


def test_run_validation_ignores_preexisting_dirty_baseline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _init_git_repo(tmp_path)
    monkeypatch.setattr(runner, "PROJECT_ROOT", tmp_path)
    (tmp_path / "tracked.txt").write_text("already-dirty\n", encoding="utf-8")
    phases = [
        runner.PhaseSpec(name="noop", command=[sys.executable, "-c", "print('noop')"], timeout_seconds=2),
    ]
    out = runner.run_validation(phases, run_id="run4", artifacts_dir=tmp_path / "art", state_root=tmp_path / "state", repo_root=tmp_path)
    assert out["status"] == "passed"


def test_audit_external_runner_discovers_subprocess_calls(tmp_path: Path) -> None:
    script = tmp_path / "external.py"
    script.write_text(
        "import subprocess\n"
        "subprocess.run(['echo', 'x'])\n"
        "subprocess.Popen(['echo', 'y'])\n",
        encoding="utf-8",
    )
    audit = runner.audit_external_runner(script)
    assert audit["exists"] is True
    assert len(audit["calls"]) == 2


def test_runtime_identity_phase_has_explicit_detached_cwd() -> None:
    detached = Path("/tmp/preprod_runtime_target6_c5a7d35")
    phase = runner.build_runtime_identity_phase(detached, "c5a7d3573999683e4419793d1724eb59b4ac71c0", sys.executable)
    assert phase.cwd == str(detached)
    assert phase.env_overrides == {"PYTHONPATH": None}


def test_run_phase_clears_canonical_pythonpath(tmp_path: Path) -> None:
    log_path = tmp_path / "phase_log.jsonl"
    phase = runner.PhaseSpec(
        name="py_path_probe",
        command=[sys.executable, "-c", "import os; print(os.environ.get('PYTHONPATH', '<none>'))"],
        timeout_seconds=3,
        env_overrides={"PYTHONPATH": None},
    )
    res = runner.run_phase(phase=phase, run_id="r1", phase_log=log_path, default_cwd=tmp_path)
    assert res.status == "pass"
    assert "<none>" in res.stdout_tail


def test_runtime_identity_blocks_wrong_cwd(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    detached = tmp_path / "detached"
    detached.mkdir(parents=True, exist_ok=True)
    (detached / "scheduler.py").write_text("x=1\n", encoding="utf-8")
    phase = runner.build_runtime_identity_phase(detached, "c5a7d3573999683e4419793d1724eb59b4ac71c0", sys.executable)
    res = runner.run_phase(phase=phase, run_id="r1", phase_log=tmp_path / "log.jsonl", default_cwd=tmp_path)
    assert res.status == "fail"


def test_runtime_identity_blocks_wrong_scheduler_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    _init_git_repo(repo)
    detached = repo / "detached"
    detached.mkdir(parents=True, exist_ok=True)
    (detached / "scheduler.py").write_text("raise RuntimeError('bad scheduler import')\n", encoding="utf-8")
    phase = runner.build_runtime_identity_phase(detached, "c5a7d3573999683e4419793d1724eb59b4ac71c0", sys.executable)
    res = runner.run_phase(phase=phase, run_id="r2", phase_log=repo / "log.jsonl", default_cwd=repo)
    assert res.status == "fail"


def test_runtime_identity_blocks_wrong_sha(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    (tmp_path / "scheduler.py").write_text("x=1\n", encoding="utf-8")
    phase = runner.build_runtime_identity_phase(tmp_path, "0000000000000000000000000000000000000000", sys.executable)
    res = runner.run_phase(phase=phase, run_id="r3", phase_log=tmp_path / "log.jsonl", default_cwd=tmp_path)
    assert res.status == "fail"


def test_runtime_identity_valid_detached_launch_passes(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    (tmp_path / "scheduler.py").write_text("x=1\n", encoding="utf-8")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(tmp_path), text=True).strip()
    phase = runner.build_runtime_identity_phase(tmp_path, head, sys.executable)
    res = runner.run_phase(phase=phase, run_id="r4", phase_log=tmp_path / "log.jsonl", default_cwd=tmp_path)
    assert res.status == "pass"
    assert "BUILD_INFO scheduler" in res.stdout_tail


def test_build_unit_test_env_removes_preprod_runtime_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PREPROD_ISOLATION_MODE", "true")
    monkeypatch.setenv("PREPROD_STATE_ROOT", "/tmp/preprod_state")
    monkeypatch.setenv("PRODUCTION_DASHBOARD_MD_PATH", "/tmp/dashboard.md")
    monkeypatch.setenv("SOME_SAFE_VAR", "keep")

    env = runner.build_unit_test_env()

    assert "PREPROD_ISOLATION_MODE" not in env
    assert "PREPROD_STATE_ROOT" not in env
    assert "PRODUCTION_DASHBOARD_MD_PATH" not in env
    assert env.get("SOME_SAFE_VAR") == "keep"


def test_run_phase_clears_preprod_vars_for_pytest_category(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PREPROD_ISOLATION_MODE", "true")
    log_path = tmp_path / "phase_log.jsonl"
    phase = runner.PhaseSpec(
        name="env_probe_pytest",
        command=[sys.executable, "-c", "import os; print(os.environ.get('PREPROD_ISOLATION_MODE', '<none>'))"],
        timeout_seconds=3,
        category="pytest",
    )

    res = runner.run_phase(phase=phase, run_id="r5", phase_log=log_path, default_cwd=tmp_path)

    assert res.status == "pass"
    assert "<none>" in res.stdout_tail
