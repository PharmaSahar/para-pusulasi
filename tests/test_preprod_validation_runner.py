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
    res = runner.run_phase(phase=phase, run_id="r1", phase_log=log_path)
    assert res.status == "pass"
    assert res.returncode == 0


def test_run_phase_timeout(tmp_path: Path) -> None:
    log_path = tmp_path / "phase_log.jsonl"
    phase = runner.PhaseSpec(name="slow", command=[sys.executable, "-c", "import time; time.sleep(2)"], timeout_seconds=1)
    res = runner.run_phase(phase=phase, run_id="r1", phase_log=log_path)
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
    out = runner.run_validation(phases, run_id="run1", artifacts_dir=artifacts, state_root=state_root)
    assert out["status"] == "passed"
    state_path = Path(out["state_path"])
    assert state_path.exists()


def test_run_validation_fails_on_nonzero_phase(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _init_git_repo(tmp_path)
    monkeypatch.setattr(runner, "PROJECT_ROOT", tmp_path)
    phases = [
        runner.PhaseSpec(name="bad", command=[sys.executable, "-c", "import sys; sys.exit(5)"], timeout_seconds=2),
    ]
    out = runner.run_validation(phases, run_id="run2", artifacts_dir=tmp_path / "art", state_root=tmp_path / "state")
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
    out = runner.run_validation(phases, run_id="run3", artifacts_dir=tmp_path / "art", state_root=tmp_path / "state")
    assert out["status"] == "failed"
    assert out["reason"] == "tracked_mutation_detected"


def test_run_validation_ignores_preexisting_dirty_baseline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _init_git_repo(tmp_path)
    monkeypatch.setattr(runner, "PROJECT_ROOT", tmp_path)
    (tmp_path / "tracked.txt").write_text("already-dirty\n", encoding="utf-8")
    phases = [
        runner.PhaseSpec(name="noop", command=[sys.executable, "-c", "print('noop')"], timeout_seconds=2),
    ]
    out = runner.run_validation(phases, run_id="run4", artifacts_dir=tmp_path / "art", state_root=tmp_path / "state")
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
