from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def _python_snippet(mode: str) -> str:
    return (
        "import scheduler, time, sys\n"
        "scheduler._acquire_scheduler_singleton_lock()\n"
        "print('LOCKED', flush=True)\n"
        "if '" + mode + "' == 'hold':\n"
        "    time.sleep(30)\n"
        "else:\n"
        "    scheduler._release_scheduler_singleton_lock()\n"
    )


def _run_lock_probe(lock_path: Path, meta_path: Path, mode: str):
    env = os.environ.copy()
    env["SCHEDULER_SINGLETON_LOCK_FILE"] = str(lock_path)
    env["SCHEDULER_SINGLETON_META_FILE"] = str(meta_path)
    return subprocess.Popen(
        [sys.executable, "-c", _python_snippet(mode)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )


def test_scheduler_singleton_lock_blocks_second_process_and_releases_after_exit(tmp_path: Path):
    lock_path = tmp_path / "scheduler_singleton.lock"
    meta_path = tmp_path / "scheduler_singleton_meta.json"

    proc1 = _run_lock_probe(lock_path, meta_path, mode="hold")
    try:
        seen_locked = False
        if proc1.stdout:
            for _ in range(12):
                line = proc1.stdout.readline().strip()
                if line == "LOCKED":
                    seen_locked = True
                    break
                if not line:
                    break
        assert seen_locked is True

        env = os.environ.copy()
        env["SCHEDULER_SINGLETON_LOCK_FILE"] = str(lock_path)
        env["SCHEDULER_SINGLETON_META_FILE"] = str(meta_path)
        probe = subprocess.run(
            [
                sys.executable,
                "-c",
                "import scheduler,sys;\n"
                "try:\n"
                "    scheduler._acquire_scheduler_singleton_lock();\n"
                "except RuntimeError as e:\n"
                "    print(str(e));sys.exit(7)\n"
                "sys.exit(0)\n",
            ],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        assert probe.returncode == 7
        assert "scheduler_singleton_lock_conflict" in probe.stdout
    finally:
        proc1.terminate()
        proc1.wait(timeout=5)

    proc3 = _run_lock_probe(lock_path, meta_path, mode="once")
    out, err = proc3.communicate(timeout=10)
    assert proc3.returncode == 0, err
    assert "LOCKED" in out


def test_scheduler_singleton_lock_ignores_stale_metadata(tmp_path: Path):
    lock_path = tmp_path / "scheduler_singleton.lock"
    meta_path = tmp_path / "scheduler_singleton_meta.json"
    meta_path.write_text(
        '{"pid": 999999, "started_at": "2000-01-01T00:00:00+00:00", "cwd": "/stale"}',
        encoding="utf-8",
    )

    proc = _run_lock_probe(lock_path, meta_path, mode="once")
    out, err = proc.communicate(timeout=10)
    assert proc.returncode == 0, err
    assert "LOCKED" in out
