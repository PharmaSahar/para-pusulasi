from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "immutable_release_v2.sh"


def _run(cmd: list[str], cwd: Path, env: dict[str, str], check: bool = False) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    merged.update(env)
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, env=merged, check=check)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _init_repo(
    tmp_path: Path,
    *,
    health_ok: bool = True,
    include_uploader: bool = True,
    include_runtime_payload: bool = False,
    include_asset_subdirs: bool = True,
) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)

    _write(
        repo / "scheduler.py",
        (
            "import json\n"
            "import os\n"
            "from pathlib import Path\n"
            "import sys\n"
            "if '--health-check' in sys.argv or '--startup-preflight' in sys.argv:\n"
            "    lock_dir = os.environ.get('IMMUTABLE_V2_LOCK_DIR', '')\n"
            "    expected_owner = os.environ.get('IMMUTABLE_V2_EXPECTED_LOCK_OWNER_TOKEN', '')\n"
            "    owner_payload = {}\n"
            "    owner_error = ''\n"
            "    self_owned = False\n"
            "    if expected_owner:\n"
            "        try:\n"
            "            owner_payload = json.loads((Path(lock_dir) / '.active_lock' / 'owner.json').read_text(encoding='utf-8'))\n"
            "            self_owned = owner_payload.get('owner_id') == expected_owner\n"
            "        except Exception as exc:\n"
            "            owner_error = exc.__class__.__name__\n"
            "    capture_path = os.environ.get('CAPTURE_HEALTH_ENV_FILE')\n"
            "    if capture_path:\n"
            "        payload = {\n"
            "            'cwd': os.getcwd(),\n"
            "            'argv': sys.argv[1:],\n"
            "            'PREPROD_ISOLATION_MODE': os.environ.get('PREPROD_ISOLATION_MODE', ''),\n"
            "            'PREPROD_STATE_ROOT': os.environ.get('PREPROD_STATE_ROOT', ''),\n"
            "            'IMMUTABLE_V2_LOCK_DIR': lock_dir,\n"
            "            'RUNTIME_OUTPUT_ROOT': os.environ.get('RUNTIME_OUTPUT_ROOT', ''),\n"
            "            'IMMUTABLE_V2_EXPECTED_LOCK_OWNER_TOKEN': os.environ.get('IMMUTABLE_V2_EXPECTED_LOCK_OWNER_TOKEN', ''),\n"
            "            'owner_json_exists': (Path(lock_dir) / '.active_lock' / 'owner.json').exists(),\n"
            "            'owner_id': owner_payload.get('owner_id', ''),\n"
            "            'owner_metadata_error': owner_error,\n"
            "            'active_deployment_lock': {\n"
            "                'reason_code': 'self_owned_deployment_lock' if self_owned else ('active_deployment_lock' if expected_owner else 'no_active_deployment_lock'),\n"
            "                'evidence': {'self_owned': self_owned},\n"
            "            },\n"
            "            'PRODUCTION_DASHBOARD_MD_PATH': os.environ.get('PRODUCTION_DASHBOARD_MD_PATH', ''),\n"
            "            'ACTIVATION_CONTROLLER_REPORT_ARCHIVE_DIR': os.environ.get('ACTIVATION_CONTROLLER_REPORT_ARCHIVE_DIR', ''),\n"
            "        }\n"
            "        with open(capture_path, 'w', encoding='utf-8') as fh:\n"
            "            json.dump(payload, fh, ensure_ascii=False, indent=2)\n"
            "    if expected_owner and not self_owned:\n"
            "        print('Health check: FAIL')\n"
            "        print('- Production safety gate failed: active_deployment_lock')\n"
            "        sys.exit(46)\n"
            "    expected = os.environ.get('EXPECT_SCHEDULER_CWD')\n"
            "    if expected and os.getcwd() != expected:\n"
            "        sys.exit(19)\n"
            "    stderr_text = os.environ.get('SIMULATE_HEALTH_STDERR', '')\n"
            "    forced_exit = int(os.environ.get('SIMULATE_HEALTH_EXIT_CODE', '0'))\n"
            "    if stderr_text:\n"
            "        print(stderr_text, file=sys.stderr)\n"
            "    errors = json.loads(os.environ.get('SIMULATE_HEALTH_ERRORS_JSON', '[]'))\n"
            "    if errors:\n"
            "        print('Health check: FAIL')\n"
            "        for error in errors:\n"
            "            print(f'- {error}')\n"
            "        sys.exit(forced_exit or 1)\n"
            "    if forced_exit:\n"
            "        print('Health check: FAIL')\n"
            "        sys.exit(forced_exit)\n"
            f"    if {0 if health_ok else 1} == 0:\n"
            "        print('Health check: PASS')\n"
            "        sys.exit(0)\n"
            "    print('Health check: FAIL')\n"
            "    sys.exit(1)\n"
            "sys.exit(0)\n"
        ),
    )
    _write(repo / "src" / "__init__.py", "")
    if include_uploader:
        _write(repo / "src" / "youtube_uploader.py", "X = 1\n")
    _write(repo / "src" / "youtube_analytics_smoke.py", "Y = 1\n")
    _write(
        repo / "watchdog.sh",
        (
            "#!/usr/bin/env bash\n"
            "if systemctl is-active --quiet parapusulasi; then\n"
            "  exit 0\n"
            "fi\n"
            "systemctl start parapusulasi\n"
        ),
    )
    (repo / "watchdog.sh").chmod(0o755)
    if include_runtime_payload:
        for path, content in {
            repo / "logs" / "activation_controller_report_latest.json": '{"kind": "activation_controller_report"}\n',
            repo / "logs" / "routing_guard_review_queue_latest.json": '{"kind": "routing_guard_review_queue"}\n',
            repo / "logs" / "runtime_flag_ab_evidence_latest.json": '{"kind": "runtime_flag_ab_evidence"}\n',
            repo / "logs" / "thumbnail_streak_path_latest.json": '{"kind": "thumbnail_streak_path"}\n',
            repo / "logs" / "p0_p1_artifacts_bundle_latest.json": '{"kind": "p0_p1_artifacts_bundle"}\n',
            repo / "logs" / "thumbnail_403_root_cause_latest.json": '{"kind": "thumbnail_403_root_cause"}\n',
            repo / "logs" / "trace_completeness_latest.json": '{"kind": "trace_completeness"}\n',
            repo / "logs" / "p0_validation_metrics_latest.json": '{"kind": "p0_validation_metrics"}\n',
            repo / "output" / "state" / "activation_reports" / "2026-07-09T17-59-04.json": '{"status": "pass"}\n',
            repo / "output" / "state" / "activation_reports" / "2026-07-10T12-36-09.json": '{"status": "pass"}\n',
            repo / "output" / "state" / "activation_reports" / "2026-07-10T09-31-49.json": '{"status": "pass"}\n',
        }.items():
            _write(path, content)
    (repo / "assets" / "branding").mkdir(parents=True, exist_ok=True)
    _write(repo / "assets" / "branding" / ".keep", "\n")
    if include_asset_subdirs:
        for path in [
            repo / "assets" / "backgrounds",
            repo / "assets" / "music",
            repo / "assets" / "fonts",
        ]:
            path.mkdir(parents=True, exist_ok=True)
        _write(repo / "assets" / "backgrounds" / ".keep", "\n")
        _write(repo / "assets" / "music" / ".keep", "\n")
        _write(repo / "assets" / "fonts" / ".keep", "\n")
    _write(repo / "requirements.txt", "")

    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()

    # Create a synthetic remote-tracking ref for deterministic tests.
    subprocess.run(["git", "update-ref", "refs/remotes/origin/release/test", sha], cwd=repo, check=True)
    return repo, sha


def _runtime_layout(tmp_path: Path) -> dict[str, Path]:
    base = tmp_path / "runtime"
    releases = base / "releases"
    current = base / "current"
    shared = base / "shared"
    operator = base / "operator"
    deploy_state = base / "deploy_state"
    lock_dir = base / "deploy.lock"

    active_sha = "a" * 40
    active = releases / active_sha
    shared.mkdir(parents=True, exist_ok=True)
    operator.mkdir(parents=True, exist_ok=True)
    (shared / "runtime" / "output" / "scripts").mkdir(parents=True, exist_ok=True)
    (shared / "runtime" / "output" / "audio").mkdir(parents=True, exist_ok=True)
    (shared / "runtime" / "output" / "videos").mkdir(parents=True, exist_ok=True)
    (shared / "logs").mkdir(parents=True, exist_ok=True)
    (shared / "state").mkdir(parents=True, exist_ok=True)
    (shared / "oauth").mkdir(parents=True, exist_ok=True)
    (shared / "tokens").mkdir(parents=True, exist_ok=True)
    (shared / "oauth" / "channels" / "alpha").mkdir(parents=True, exist_ok=True)
    (shared / "tokens" / "channels" / "alpha").mkdir(parents=True, exist_ok=True)

    _write(shared / ".env", "A=1\n")
    _write(shared / "state" / "youtube_playlists.json", "{}\n")
    _write(shared / "state" / "channel_registry.json", "{}\n")
    _write(shared / "state" / "channels_tracker.csv", "channel\n")
    _write(shared / "oauth" / "client_secrets.root.json", "{}\n")
    _write(shared / "tokens" / "youtube_token.root.pickle", "token\n")
    _write(shared / "oauth" / "channels" / "alpha" / "client_secrets.json", "{}\n")
    _write(shared / "tokens" / "channels" / "alpha" / "youtube_token.pickle", "token\n")
    _write(operator / "channels" / "alpha" / "client_secrets.json", "{}\n")
    _write(operator / "channels" / "alpha" / "youtube_token.pickle", "token\n")

    (active / "channels" / "alpha").mkdir(parents=True, exist_ok=True)
    (active / "output").mkdir(parents=True, exist_ok=True)
    (active / "logs").mkdir(parents=True, exist_ok=True)

    _write(active / ".env", "A=1\n")
    _write(active / "youtube_playlists.json", "{}\n")
    _write(active / "channels" / "channel_registry.json", "{}\n")
    _write(active / "channels" / "channels_tracker.csv", "channel\n")
    _write(active / "channels" / "alpha" / "client_secrets.json", "{}\n")
    _write(active / "channels" / "alpha" / "youtube_token.pickle", "token\n")

    releases.mkdir(parents=True, exist_ok=True)
    if current.exists() or current.is_symlink():
        current.unlink()
    current.symlink_to(active)

    return {
        "base": base,
        "releases": releases,
        "current": current,
        "shared": shared,
        "operator": operator,
        "deploy_state": deploy_state,
        "lock_dir": lock_dir,
        "active": active,
    }


def _replace_active_with_git_checkout(repo: Path, sha: str, layout: dict[str, Path]) -> Path:
    active = layout["active"]
    if active.exists() or active.is_symlink():
        if active.is_symlink() or active.is_file():
            active.unlink()
        else:
            shutil.rmtree(active)

    subprocess.run(["git", "clone", str(repo), str(active)], check=True, capture_output=True, text=True)
    subprocess.run(["git", "checkout", "--detach", sha], cwd=active, check=True, capture_output=True, text=True)
    subprocess.run(["git", "update-ref", "refs/remotes/origin/release/test", sha], cwd=active, check=True)
    return active


def _make_active_release_runtime_dirty(repo: Path, sha: str, layout: dict[str, Path]) -> Path:
    active = _replace_active_with_git_checkout(repo, sha, layout)
    shutil.rmtree(active / "logs")
    shutil.rmtree(active / "output")
    (active / "logs").symlink_to(layout["shared"] / "logs")
    (active / "output").symlink_to(layout["shared"] / "runtime" / "output")
    _write(active / "deployment_preflight.json", '{"status": "pass"}\n')

    status = subprocess.check_output(["git", "status", "--short"], cwd=active, text=True)
    assert " D logs/" in status
    assert " D output/" in status
    assert "?? deployment_preflight.json" in status
    return active


def _fake_bin(tmp_path: Path, *, active_service: bool = True) -> tuple[Path, Path]:
    bindir = tmp_path / "fakebin"
    bindir.mkdir(parents=True, exist_ok=True)
    log = tmp_path / "fakebin.log"

    _write(
        bindir / "systemctl",
        (
            "#!/usr/bin/env bash\n"
            f"echo \"$@\" >> '{log}'\n"
            "if [[ \"$1\" == \"is-active\" ]]; then\n"
            f"  if [[ '{'1' if active_service else '0'}' == '1' ]]; then exit 0; else exit 3; fi\n"
            "fi\n"
            "exit 0\n"
        ),
    )
    _write(
        bindir / "mv",
        (
            "#!/usr/bin/env bash\n"
            "args=()\n"
            "for a in \"$@\"; do\n"
            "  [[ \"$a\" == \"-T\" || \"$a\" == \"-f\" || \"$a\" == \"-Tf\" ]] && continue\n"
            "  args+=(\"$a\")\n"
            "done\n"
            "python3 - \"${args[0]}\" \"${args[1]}\" <<'PY'\n"
            "import os, sys\n"
            "os.replace(sys.argv[1], sys.argv[2])\n"
            "PY\n"
        ),
    )

    for file in bindir.iterdir():
        file.chmod(0o755)

    return bindir, log


def _watchdog_fake_bin(tmp_path: Path, *, active_service: bool = False, start_succeeds: bool = True) -> tuple[Path, Path, Path, Path]:
    bindir = tmp_path / "watchdog-fakebin"
    bindir.mkdir(parents=True, exist_ok=True)
    systemctl_log = tmp_path / "watchdog-systemctl.log"
    curl_log = tmp_path / "watchdog-curl.log"
    service_state = tmp_path / "watchdog-service-state"
    service_state.write_text("active\n" if active_service else "inactive\n", encoding="utf-8")
    _write(
        bindir / "systemctl",
        (
            "#!/usr/bin/env bash\n"
            f"echo \"$@\" >> '{systemctl_log}'\n"
            "if [[ \"$1\" == \"is-active\" ]]; then\n"
            f"  if [[ \"$(cat '{service_state}')\" == \"active\" ]]; then exit 0; else exit 3; fi\n"
            "fi\n"
            "if [[ \"$1\" == \"start\" ]]; then\n"
            f"  if [[ '{'1' if start_succeeds else '0'}' == '1' ]]; then echo active > '{service_state}'; fi\n"
            "  exit 0\n"
            "fi\n"
            "exit 0\n"
        ),
    )
    _write(
        bindir / "curl",
        (
            "#!/usr/bin/env bash\n"
            f"echo \"$@\" >> '{curl_log}'\n"
            "exit 0\n"
        ),
    )
    for file in bindir.iterdir():
        file.chmod(0o755)
    return bindir, systemctl_log, curl_log, service_state


def _watchdog_env(tmp_path: Path, fakebin: Path, *, app_root: Path | None = None) -> dict[str, str]:
    operator = tmp_path / "watchdog-operator"
    operator.mkdir(parents=True, exist_ok=True)
    _write(operator / ".env", 'TELEGRAM_BOT_TOKEN="token"\nTELEGRAM_CHAT_ID="chat"\n')
    return {
        "PATH": f"{fakebin}:{os.environ['PATH']}",
        "WATCHDOG_OPERATOR_ROOT": str(operator),
        "WATCHDOG_APP_ROOT": str(app_root or Path(__file__).resolve().parents[1]),
        "WATCHDOG_LOCK_DIR": str(tmp_path / "watchdog-deploy.lock"),
        "WATCHDOG_STATE_DIR": str(tmp_path / "watchdog-state"),
        "WATCHDOG_PYTHON_BIN": sys.executable,
        "WATCHDOG_RESTART_SETTLE_SECONDS": "0",
        "WATCHDOG_MAX_RESTART_ATTEMPTS": "1",
    }


def _classifier_app(tmp_path: Path, *, classification: str, owner_state: str = "test_owner_state") -> Path:
    app = tmp_path / f"classifier-{classification}"
    _write(app / "src" / "__init__.py", "")
    _write(
        app / "src" / "production_safety_gate.py",
        (
            "import json\n"
            "import sys\n"
            "payload = {\n"
            f"    'lock_classification': '{classification}',\n"
            f"    'owner_state': '{owner_state}',\n"
            "}\n"
            "print(json.dumps(payload))\n"
            "sys.exit(0)\n"
        ),
    )
    return app


def _classifier_app_with_source(tmp_path: Path, name: str, source: str) -> Path:
    app = tmp_path / name
    _write(app / "src" / "__init__.py", "")
    _write(app / "src" / "production_safety_gate.py", source)
    return app


def _install_venv_python(app: Path, log_path: Path) -> None:
    _write(
        app / ".venv-2" / "bin" / "python",
        (
            "#!/usr/bin/env bash\n"
            f"echo \"$@\" >> '{log_path}'\n"
            f"exec '{sys.executable}' \"$@\"\n"
        ),
    )
    (app / ".venv-2" / "bin" / "python").chmod(0o755)


def _base_env(layout: dict[str, Path], fakebin: Path | None = None) -> dict[str, str]:
    env = {
        "IMMUTABLE_V2_ALLOW_NON_OPT_ROOTS": "1",
        "IMMUTABLE_V2_RELEASES_ROOT": str(layout["releases"]),
        "IMMUTABLE_V2_CURRENT_LINK": str(layout["current"]),
        "IMMUTABLE_V2_DEPLOY_STATE_ROOT": str(layout["deploy_state"]),
        "IMMUTABLE_V2_SHARED_ROOT": str(layout["shared"]),
        "IMMUTABLE_V2_OPERATOR_ROOT": str(layout["operator"]),
        "IMMUTABLE_V2_LOCK_DIR": str(layout["lock_dir"]),
        "IMMUTABLE_V2_SKIP_FETCH": "1",
        "IMMUTABLE_V2_SKIP_DEP_INSTALL": "1",
        "IMMUTABLE_V2_SKIP_HEALTHCHECK": "1",
        "IMMUTABLE_V2_SKIP_RUNTIME_HEALTH_LOOP": "1",
        "IMMUTABLE_V2_HEALTH_LOOP_ATTEMPTS": "1",
        "IMMUTABLE_V2_HEALTH_LOOP_SLEEP_SECONDS": "0",
    }
    if fakebin is not None:
        env["PATH"] = f"{fakebin}:{os.environ['PATH']}"
    return env


def _write_owner(active_lock: Path, *, owner_id: str = "owner-123", pid: int = 999999, process_identity: str = "immutable_release_v2.sh") -> None:
    _write(
        active_lock / "owner.json",
        json.dumps(
            {
                "owner_id": owner_id,
                "pid": pid,
                "host": socket.gethostname(),
                "started_at_utc": datetime.now(timezone.utc).isoformat(),
                "mode": "cutover",
                "target_sha": "b" * 40,
                "target_ref": "origin/release/test",
                "process_identity": process_identity,
            }
        ),
    )


def _invoke(repo: Path, sha: str, mode: str, env: dict[str, str], extra: list[str] | None = None) -> subprocess.CompletedProcess[str]:
    args = [
        "bash",
        str(SCRIPT),
        "--target-ref",
        "origin/release/test",
        "--target-sha",
        sha,
        "--mode",
        mode,
    ]
    if extra:
        args.extend(extra)
    return _run(args, cwd=repo, env=env)


def test_plan_mode_is_read_only(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)

    before = layout["current"].readlink()
    res = _invoke(repo, sha, "plan", env)

    assert res.returncode == 0
    assert layout["current"].readlink() == before


def test_plan_from_dirty_active_release_uses_temporary_clean_source(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path, include_runtime_payload=True)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)
    active = _make_active_release_runtime_dirty(repo, sha, layout)

    before = layout["current"].readlink()
    res = _run(
        [
            "bash",
            str(SCRIPT),
            "--target-ref",
            "origin/release/test",
            "--target-sha",
            sha,
            "--mode",
            "plan",
        ],
        cwd=active,
        env=env,
    )

    assert res.returncode == 0, res.stderr + res.stdout
    assert "Using temporary clean deployment source checkout" in (res.stderr + res.stdout)
    assert "Dirty local repository" not in (res.stderr + res.stdout)
    assert layout["current"].readlink() == before
    assert not list((layout["deploy_state"] / "deploy-source-worktrees").glob("source.*"))


def test_prepare_from_dirty_active_release_uses_temporary_clean_source(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path, include_runtime_payload=True)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)
    active = _make_active_release_runtime_dirty(repo, sha, layout)

    res = _run(
        [
            "bash",
            str(SCRIPT),
            "--target-ref",
            "origin/release/test",
            "--target-sha",
            sha,
            "--mode",
            "prepare",
        ],
        cwd=active,
        env=env,
    )

    assert res.returncode == 0, res.stderr + res.stdout
    assert "Using temporary clean deployment source checkout" in (res.stderr + res.stdout)
    release = layout["releases"] / sha
    assert (release / "logs").is_symlink()
    assert (release / "logs").resolve() == (layout["shared"] / "logs").resolve()
    assert (release / "output").is_symlink()
    assert (release / "output").resolve() == (layout["shared"] / "runtime" / "output").resolve()
    assert (release / "deployment_preflight.json").is_file()
    assert not list((layout["deploy_state"] / "deploy-source-worktrees").glob("source.*"))


def test_dirty_non_active_deployment_checkout_is_rejected(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)
    _write(repo / "operator-note.txt", "dirty\n")

    res = _invoke(repo, sha, "plan", env)

    assert res.returncode != 0
    assert "Deployment source checkout must be clean" in (res.stderr + res.stdout)


def test_dry_run_prepare_is_read_only(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)

    res = _invoke(repo, sha, "prepare", env, ["--dry-run"])

    assert res.returncode == 0
    assert not (layout["releases"] / sha).exists()


def test_full_sha_required(tmp_path: Path) -> None:
    repo, _ = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)

    res = _run(
        [
            "bash",
            str(SCRIPT),
            "--target-ref",
            "origin/release/test",
            "--target-sha",
            "abc123",
            "--mode",
            "plan",
        ],
        cwd=repo,
        env=env,
    )

    assert res.returncode != 0
    assert "full 40-char SHA" in (res.stderr + res.stdout)


def test_target_ref_sha_mismatch_rejected(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)

    subprocess.run(["git", "checkout", "-b", "local-only"], cwd=repo, check=True)
    _write(repo / "local.txt", "x\n")
    subprocess.run(["git", "add", "local.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "local"], cwd=repo, check=True, capture_output=True, text=True)
    local_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()

    res = _invoke(repo, local_sha, "plan", env)

    assert sha != local_sha
    assert res.returncode != 0
    assert "not reachable" in (res.stderr + res.stdout) or "local-only" in (res.stderr + res.stdout)


def test_local_only_commit_rejected(tmp_path: Path) -> None:
    repo, _ = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)

    subprocess.run(["git", "checkout", "-b", "local-only-2"], cwd=repo, check=True)
    _write(repo / "local2.txt", "x\n")
    subprocess.run(["git", "add", "local2.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "local2"], cwd=repo, check=True, capture_output=True, text=True)
    local_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()

    res = _invoke(repo, local_sha, "plan", env)

    assert res.returncode != 0
    assert "not reachable" in (res.stderr + res.stdout) or "local-only" in (res.stderr + res.stdout)


def test_allowed_release_root_enforced(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)
    env.pop("IMMUTABLE_V2_ALLOW_NON_OPT_ROOTS")
    env["IMMUTABLE_V2_RELEASES_ROOT"] = "/Users/invalid/root"

    res = _invoke(repo, sha, "plan", env)

    assert res.returncode != 0
    assert "Releases root" in (res.stderr + res.stdout)


def test_path_traversal_rejected(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)
    env["IMMUTABLE_V2_CURRENT_LINK"] = str(layout["base"] / ".." / ".." / "bad")

    res = _invoke(repo, sha, "plan", env)

    assert res.returncode != 0


def test_symlink_escape_rejected(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)

    layout["current"].unlink()
    layout["current"].symlink_to(tmp_path / "outside")

    res = _invoke(repo, sha, "plan", env)

    assert res.returncode != 0


def test_existing_matching_release_is_idempotent(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)

    release = layout["releases"] / sha
    subprocess.run(["git", "clone", str(repo), str(release)], check=True, capture_output=True, text=True)
    subprocess.run(["git", "checkout", "--detach", sha], cwd=release, check=True, capture_output=True, text=True)
    _write(release / ".immutable_release_metadata.json", json.dumps({"release_sha": sha}, ensure_ascii=False))
    exclude = release / ".git" / "info" / "exclude"
    _write(exclude, exclude.read_text(encoding="utf-8") + "\n/.immutable_release_metadata.json\n")

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode == 0
    assert "already prepared" in (res.stderr + res.stdout)


def test_existing_mismatched_release_rejected(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)

    release = layout["releases"] / sha
    release.mkdir(parents=True, exist_ok=True)
    _write(release / ".immutable_release_metadata.json", json.dumps({"release_sha": "f" * 40}, ensure_ascii=False))

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode != 0
    assert "FAIL_RELEASE_INTEGRITY" in (res.stderr + res.stdout)


def test_staging_collision_rejected(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)

    (layout["releases"] / f".staging-{sha}").mkdir(parents=True, exist_ok=True)

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode != 0
    assert "Staging collision" in (res.stderr + res.stdout)


def test_insufficient_disk_rejected(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)
    env["IMMUTABLE_V2_MIN_FREE_KB"] = str(10**12)

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode != 0
    assert "Insufficient disk space" in (res.stderr + res.stdout)


def test_prepare_creates_shared_output_symlink_when_absent(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode == 0
    output_link = layout["releases"] / sha / "output"
    assert output_link.is_symlink()
    assert output_link.resolve() == (layout["shared"] / "runtime" / "output").resolve()


def test_prepare_creates_shared_logs_symlink_when_absent(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode == 0
    logs_link = layout["releases"] / sha / "logs"
    assert logs_link.is_symlink()
    assert logs_link.resolve() == (layout["shared"] / "logs").resolve()


def test_prepare_links_channel_tokens_from_operator_root(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)

    # The active release tree intentionally lacks channel token files.
    target = layout["releases"] / sha / "channels" / "alpha" / "youtube_token.pickle"

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode == 0
    assert target.is_symlink()
    assert target.resolve() == (layout["operator"] / "channels" / "alpha" / "youtube_token.pickle").resolve()


@pytest.mark.parametrize("child", ["scripts", "audio", "videos"])
def test_missing_shared_runtime_child_is_created_during_prepare(tmp_path: Path, child: str) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)

    target_dir = layout["shared"] / "runtime" / "output" / child
    shutil.rmtree(target_dir)

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode == 0
    assert target_dir.exists() and target_dir.is_dir()


def test_existing_shared_runtime_children_and_contents_are_preserved(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)

    scripts_dir = layout["shared"] / "runtime" / "output" / "scripts"
    audio_dir = layout["shared"] / "runtime" / "output" / "audio"
    videos_dir = layout["shared"] / "runtime" / "output" / "videos"
    _write(scripts_dir / "sentinel.txt", "scripts\n")
    _write(audio_dir / "sentinel.txt", "audio\n")
    _write(videos_dir / "sentinel.txt", "videos\n")

    scripts_ino = scripts_dir.stat().st_ino
    audio_ino = audio_dir.stat().st_ino
    videos_ino = videos_dir.stat().st_ino

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode == 0
    assert (scripts_dir / "sentinel.txt").read_text(encoding="utf-8") == "scripts\n"
    assert (audio_dir / "sentinel.txt").read_text(encoding="utf-8") == "audio\n"
    assert (videos_dir / "sentinel.txt").read_text(encoding="utf-8") == "videos\n"
    assert scripts_dir.stat().st_ino == scripts_ino
    assert audio_dir.stat().st_ino == audio_ino
    assert videos_dir.stat().st_ino == videos_ino


@pytest.mark.parametrize("mode", ["prepare", "plan"])
def test_dry_modes_do_not_create_missing_runtime_children(tmp_path: Path, mode: str) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)

    target_dir = layout["shared"] / "runtime" / "output" / "scripts"
    shutil.rmtree(target_dir)

    extra = ["--dry-run"] if mode == "prepare" else None
    res = _invoke(repo, sha, mode, env, extra)

    assert res.returncode == 0
    assert not target_dir.exists()


def test_runtime_directory_bootstrap_rejects_output_outside_shared_root(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)
    outside = tmp_path / "outside-output"
    outside.mkdir(parents=True, exist_ok=True)

    real_output = layout["shared"] / "runtime" / "output"
    backup_output = layout["shared"] / "runtime" / "output.bak"
    real_output.rename(backup_output)
    real_output.symlink_to(outside)

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode != 0
    assert "Mandatory shared asset is not sourced from shared root" in (res.stderr + res.stdout)


def test_missing_asset_subdirectories_are_created_in_staging(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path, include_asset_subdirs=False)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode == 0
    release = layout["releases"] / sha
    assert (release / "assets" / "backgrounds").is_dir()
    assert (release / "assets" / "music").is_dir()
    assert (release / "assets" / "fonts").is_dir()


def test_prepare_records_startup_preflight_command(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)
    env.pop("IMMUTABLE_V2_SKIP_HEALTHCHECK")

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode == 0
    preflight = json.loads((layout["releases"] / sha / "deployment_preflight.json").read_text(encoding="utf-8"))
    assert "scheduler.py --startup-preflight" in preflight["health_evidence"]["command"]


def test_existing_asset_subdirectory_is_preserved(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path, include_asset_subdirs=False)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)
    env["IMMUTABLE_V2_TEST_HOOK_AFTER_EXPORT"] = "mkdir -p assets/backgrounds && printf keep > assets/backgrounds/sentinel.txt"

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode == 0
    assert (layout["releases"] / sha / "assets" / "backgrounds" / "sentinel.txt").read_text(encoding="utf-8") == "keep"


def test_missing_required_packaged_assets_root_blocks_prepare(tmp_path: Path) -> None:
    repo, _ = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)

    subprocess.run(["git", "rm", "-r", "assets"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", "remove-assets-root"], cwd=repo, check=True, capture_output=True, text=True)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    subprocess.run(["git", "update-ref", "refs/remotes/origin/release/test", sha], cwd=repo, check=True)

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode != 0
    assert "Required packaged asset directory missing" in (res.stderr + res.stdout)


def test_exported_runtime_payload_is_sanitized_before_linking(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path, include_runtime_payload=True)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode == 0
    release = layout["releases"] / sha
    logs_link = release / "logs"
    output_link = release / "output"
    assert logs_link.is_symlink()
    assert output_link.is_symlink()
    assert logs_link.resolve() == (layout["shared"] / "logs").resolve()
    assert output_link.resolve() == (layout["shared"] / "runtime" / "output").resolve()
    assert not (logs_link / "activation_controller_report_latest.json").exists()
    assert not (output_link / "state" / "activation_reports").exists()


@pytest.mark.parametrize("rel", ["logs", "output"])
def test_untracked_file_inside_exported_runtime_payload_blocks_sanitization(tmp_path: Path, rel: str) -> None:
    repo, sha = _init_repo(tmp_path, include_runtime_payload=True)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)
    env["IMMUTABLE_V2_TEST_HOOK_AFTER_EXPORT"] = f'mkdir -p {rel} && printf x > {rel}/unexpected.txt'

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode != 0
    assert "Unexpected exported runtime payload entry" in (res.stderr + res.stdout)


@pytest.mark.parametrize("rel", ["logs", "output"])
def test_external_symlink_inside_exported_runtime_payload_blocks_sanitization(tmp_path: Path, rel: str) -> None:
    repo, sha = _init_repo(tmp_path, include_runtime_payload=True)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)
    env["IMMUTABLE_V2_TEST_HOOK_AFTER_EXPORT"] = f'ln -s /tmp/outside {rel}/unexpected-link'

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode != 0
    assert "Unexpected symlink in exported runtime payload" in (res.stderr + res.stdout)


@pytest.mark.parametrize("rel", ["logs", "output"])
@pytest.mark.parametrize("special_kind", ["fifo", "socket", "device"])
def test_special_file_inside_exported_runtime_payload_blocks_sanitization(tmp_path: Path, rel: str, special_kind: str) -> None:
    if special_kind == "device" and os.geteuid() != 0:
        pytest.skip("device nodes require elevated privileges")

    repo, sha = _init_repo(tmp_path, include_runtime_payload=True)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)

    if special_kind == "fifo":
        hook = f"mkfifo {rel}/special-fifo"
    elif special_kind == "socket":
        hook = (
            "python3 - <<'PY'\n"
            "import socket\n"
            "from pathlib import Path\n"
            f"path = Path('{rel}/special-socket')\n"
            "sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)\n"
            "sock.bind(str(path))\n"
            "sock.close()\n"
            "PY"
        )
    else:
        hook = (
            "python3 - <<'PY'\n"
            "import os\n"
            "import stat\n"
            "from pathlib import Path\n"
            f"path = Path('{rel}/special-device')\n"
            "os.mknod(path, stat.S_IFCHR | 0o600, os.makedev(1, 7))\n"
            "PY"
        )

    env["IMMUTABLE_V2_TEST_HOOK_AFTER_EXPORT"] = hook

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode != 0
    assert "Unexpected special file in exported runtime payload" in (res.stderr + res.stdout)


def test_empty_staging_output_directory_replaced(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)
    env["IMMUTABLE_V2_TEST_HOOK_AFTER_EXPORT"] = "mkdir -p output"

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode == 0
    output_link = layout["releases"] / sha / "output"
    assert output_link.is_symlink()
    assert output_link.resolve() == (layout["shared"] / "runtime" / "output").resolve()


def test_empty_staging_logs_directory_replaced(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)
    env["IMMUTABLE_V2_TEST_HOOK_AFTER_EXPORT"] = "mkdir -p logs"

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode == 0
    logs_link = layout["releases"] / sha / "logs"
    assert logs_link.is_symlink()
    assert logs_link.resolve() == (layout["shared"] / "logs").resolve()


def test_non_empty_staging_output_blocks_prepare(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path, include_runtime_payload=True)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)
    env["IMMUTABLE_V2_TEST_HOOK_AFTER_EXPORT"] = "mkdir -p output && printf x > output/marker.txt"

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode != 0
    assert "Unexpected exported runtime payload entry" in (res.stderr + res.stdout)


def test_non_empty_staging_logs_blocks_prepare(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path, include_runtime_payload=True)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)
    env["IMMUTABLE_V2_TEST_HOOK_AFTER_EXPORT"] = "mkdir -p logs && printf x > logs/marker.txt"

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode != 0
    assert "Unexpected exported runtime payload entry" in (res.stderr + res.stdout)


def test_wrong_runtime_symlink_target_blocks_prepare(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path, include_runtime_payload=True)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)
    env["IMMUTABLE_V2_TEST_HOOK_AFTER_EXPORT"] = "rm -rf output && ln -s /tmp/wrong-target output"

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode != 0
    assert "symlink mismatch" in (res.stderr + res.stdout)


def test_correct_runtime_symlink_is_idempotent(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path, include_runtime_payload=True)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)
    env["IMMUTABLE_V2_TEST_HOOK_AFTER_EXPORT"] = (
        f"rm -rf output logs && ln -s '{layout['shared'] / 'runtime' / 'output'}' output && "
        f"ln -s '{layout['shared'] / 'logs'}' logs"
    )

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode == 0


def test_runtime_regular_file_destination_blocks_prepare(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path, include_runtime_payload=True)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)
    env["IMMUTABLE_V2_TEST_HOOK_AFTER_EXPORT"] = "rm -rf output && printf x > output"

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode != 0
    assert "Exported runtime payload is not a directory" in (res.stderr + res.stdout)


def test_missing_shared_output_source_blocks_prepare(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)

    (layout["shared"] / "runtime" / "output").rename(layout["shared"] / "runtime" / "output.bak")

    res = _invoke(repo, sha, "prepare", env)
    assert res.returncode != 0
    assert "Mandatory shared asset is not sourced from shared root" in (res.stderr + res.stdout) or "Missing persistent asset source" in (res.stderr + res.stdout)


def test_missing_shared_logs_source_blocks_prepare(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)

    (layout["shared"] / "logs").rename(layout["shared"] / "logs.bak")

    res = _invoke(repo, sha, "prepare", env)
    assert res.returncode != 0
    assert "Mandatory shared asset is not sourced from shared root" in (res.stderr + res.stdout) or "Missing persistent asset source" in (res.stderr + res.stdout)


def test_shared_source_outside_approved_root_rejected(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)
    outside = tmp_path / "outside"
    outside.mkdir(parents=True, exist_ok=True)
    _write(outside / "youtube_playlists.json", "{}\n")
    target = layout["shared"] / "state" / "youtube_playlists.json"
    target.unlink()
    target.symlink_to(outside / "youtube_playlists.json")

    res = _invoke(repo, sha, "prepare", env)
    assert res.returncode != 0
    assert "escapes approved roots" in (res.stderr + res.stdout) or "Mandatory shared asset" in (res.stderr + res.stdout)


def test_prepare_does_not_modify_active_output_and_logs(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)
    active_output = layout["active"] / "output"
    active_logs = layout["active"] / "logs"

    out_before = active_output.stat().st_ino
    logs_before = active_logs.stat().st_ino
    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode == 0
    assert active_output.exists() and active_output.is_dir() and not active_output.is_symlink()
    assert active_logs.exists() and active_logs.is_dir() and not active_logs.is_symlink()
    assert active_output.stat().st_ino == out_before
    assert active_logs.stat().st_ino == logs_before


def test_prepare_does_not_modify_shared_output_and_logs(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path, include_runtime_payload=True)
    layout = _runtime_layout(tmp_path)
    _write(layout["shared"] / "logs" / "shared-sentinel.log", "keep\n")
    _write(layout["shared"] / "runtime" / "output" / "scripts" / "shared-sentinel.txt", "keep\n")
    env = _base_env(layout)

    shared_logs_before = (layout["shared"] / "logs").stat().st_ino
    shared_output_before = (layout["shared"] / "runtime" / "output").stat().st_ino

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode == 0
    assert (layout["shared"] / "logs" / "shared-sentinel.log").read_text(encoding="utf-8") == "keep\n"
    assert (layout["shared"] / "runtime" / "output" / "scripts" / "shared-sentinel.txt").read_text(encoding="utf-8") == "keep\n"
    assert (layout["shared"] / "logs").stat().st_ino == shared_logs_before
    assert (layout["shared"] / "runtime" / "output").stat().st_ino == shared_output_before


def test_preflight_health_check_runs_from_staging_cwd(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)
    env.pop("IMMUTABLE_V2_SKIP_HEALTHCHECK")
    env["EXPECT_SCHEDULER_CWD"] = str(layout["releases"] / f".staging-{sha}")

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode == 0


def test_preflight_json_contains_shared_path_evidence(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)

    res = _invoke(repo, sha, "prepare", env)
    assert res.returncode == 0

    payload = json.loads((layout["releases"] / sha / "deployment_preflight.json").read_text(encoding="utf-8"))
    evidence = {item["relative_path"]: item for item in payload.get("path_evidence", [])}
    assert evidence["output"]["status"] == "pass"
    assert evidence["logs"]["status"] == "pass"
    assert evidence["output"]["action"] == "existed"
    assert evidence["logs"]["action"] == "existed"
    assert evidence["output"]["resolved_absolute_path"] == str((layout["shared"] / "runtime" / "output").resolve())
    assert evidence["logs"]["resolved_absolute_path"] == str((layout["shared"] / "logs").resolve())


def test_preflight_json_records_created_paths(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path, include_asset_subdirs=False)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)
    shutil.rmtree(layout["shared"] / "runtime" / "output" / "scripts")
    shutil.rmtree(layout["shared"] / "runtime" / "output" / "audio")
    shutil.rmtree(layout["shared"] / "runtime" / "output" / "videos")

    res = _invoke(repo, sha, "prepare", env)
    assert res.returncode == 0

    payload = json.loads((layout["releases"] / sha / "deployment_preflight.json").read_text(encoding="utf-8"))
    evidence = {item["relative_path"]: item for item in payload.get("path_evidence", [])}
    assert evidence["output/scripts"]["status"] == "pass"
    assert evidence["output/scripts"]["action"] == "created"
    assert evidence["output/audio"]["action"] == "created"
    assert evidence["output/videos"]["action"] == "created"
    assert evidence["assets/backgrounds"]["action"] == "created"
    assert evidence["assets/music"]["action"] == "created"
    assert evidence["assets/fonts"]["action"] == "created"


def test_preflight_health_check_runs_after_directory_bootstrap(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path, include_asset_subdirs=False)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)
    env.pop("IMMUTABLE_V2_SKIP_HEALTHCHECK")
    env["EXPECT_SCHEDULER_CWD"] = str(layout["releases"] / f".staging-{sha}")
    shutil.rmtree(layout["shared"] / "runtime" / "output" / "scripts")
    shutil.rmtree(layout["shared"] / "runtime" / "output" / "audio")
    shutil.rmtree(layout["shared"] / "runtime" / "output" / "videos")

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode == 0


def test_preflight_health_warning_does_not_block_prepare(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path, include_asset_subdirs=False)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)
    env.pop("IMMUTABLE_V2_SKIP_HEALTHCHECK")
    env["EXPECT_SCHEDULER_CWD"] = str(layout["releases"] / f".staging-{sha}")
    env["SIMULATE_HEALTH_ERRORS_JSON"] = json.dumps(["Unable to resolve youtube.googleapis.com: temporary dns failure"])

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode == 0
    payload = json.loads((layout["releases"] / sha / "deployment_preflight.json").read_text(encoding="utf-8"))
    assert payload["validations"][-1]["status"] == "pass"
    assert payload["health_evidence"]["warnings"] == ["Unable to resolve youtube.googleapis.com: temporary dns failure"]
    assert "scheduler.py --startup-preflight" in payload["health_evidence"]["command"]


def test_preflight_health_blocking_error_writes_report_and_cleans(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)
    env.pop("IMMUTABLE_V2_SKIP_HEALTHCHECK")
    env["EXPECT_SCHEDULER_CWD"] = str(layout["releases"] / f".staging-{sha}")
    env["SIMULATE_HEALTH_ERRORS_JSON"] = json.dumps([
        "Missing Telegram configuration. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env."
    ])

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode != 0
    assert not (layout["releases"] / f".staging-{sha}").exists()
    report = json.loads((layout["deploy_state"] / "prepare_failure_latest.json").read_text(encoding="utf-8"))
    assert report["failed_phase"] == "preflight"
    assert "Missing Telegram configuration" in report["error_summary"]
    assert report["exit_code"] == res.returncode
    assert not layout["lock_dir"].exists()


def test_preflight_health_stderr_is_captured_and_blocks(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)
    env.pop("IMMUTABLE_V2_SKIP_HEALTHCHECK")
    env["EXPECT_SCHEDULER_CWD"] = str(layout["releases"] / f".staging-{sha}")
    env["SIMULATE_HEALTH_STDERR"] = "RuntimeError: simulated preflight crash"
    env["SIMULATE_HEALTH_EXIT_CODE"] = "1"
    env["SIMULATE_HEALTH_ERRORS_JSON"] = json.dumps([])

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode != 0
    report = json.loads((layout["deploy_state"] / "prepare_failure_latest.json").read_text(encoding="utf-8"))
    assert "simulated preflight crash" in report["error_summary"]
    assert not (layout["releases"] / f".staging-{sha}").exists()


def test_existing_prepared_release_is_left_untouched(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path, include_runtime_payload=True)
    layout = _runtime_layout(tmp_path)
    release = layout["releases"] / sha
    subprocess.run(["git", "clone", str(repo), str(release)], check=True, capture_output=True, text=True)
    subprocess.run(["git", "checkout", "--detach", sha], cwd=release, check=True, capture_output=True, text=True)
    _write(release / ".immutable_release_metadata.json", json.dumps({"release_sha": sha}))
    exclude = release / ".git" / "info" / "exclude"
    _write(exclude, exclude.read_text(encoding="utf-8") + "\n/.immutable_release_metadata.json\n")
    _write(release / "logs" / "release-sentinel.log", "keep\n")
    _write(release / "output" / "state" / "release-sentinel.json", "{}\n")
    env = _base_env(layout)

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode == 0
    assert (release / "logs" / "release-sentinel.log").read_text(encoding="utf-8") == "keep\n"
    assert (release / "output" / "state" / "release-sentinel.json").read_text(encoding="utf-8") == "{}\n"


def test_fresh_prepare_creates_git_backed_release_identity(tmp_path: Path) -> None:
    repo, _ = _init_repo(tmp_path)
    _write(repo / ".gitignore", "*.tmp\n")
    subprocess.run(["git", "add", ".gitignore"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "add gitignore"], cwd=repo, check=True, capture_output=True, text=True)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    subprocess.run(["git", "update-ref", "refs/remotes/origin/release/test", sha], cwd=repo, check=True)

    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode == 0
    release = layout["releases"] / sha
    assert (release / ".git").is_dir()
    assert subprocess.check_output(["git", "rev-parse", "--show-toplevel"], cwd=release, text=True).strip() == str(release)
    assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=release, text=True).strip() == sha
    assert json.loads((release / ".immutable_release_metadata.json").read_text(encoding="utf-8"))["release_sha"] == sha
    assert subprocess.check_output(["git", "status", "--short", "--untracked-files=no"], cwd=release, text=True).strip() == ""
    assert subprocess.run(["git", "diff-index", "--quiet", "HEAD", "--"], cwd=release).returncode == 0


def test_prepare_under_parent_git_repo_still_uses_release_git_metadata(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)

    parent = layout["base"]
    subprocess.run(["git", "init"], cwd=parent, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "parent@example.com"], cwd=parent, check=True)
    subprocess.run(["git", "config", "user.name", "Parent User"], cwd=parent, check=True)
    _write(parent / "PARENT_MARKER.txt", "parent\n")
    subprocess.run(["git", "add", "PARENT_MARKER.txt"], cwd=parent, check=True)
    subprocess.run(["git", "commit", "-m", "parent-init"], cwd=parent, check=True, capture_output=True, text=True)

    env = _base_env(layout)
    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode == 0
    release = layout["releases"] / sha
    assert subprocess.check_output(["git", "rev-parse", "--show-toplevel"], cwd=release, text=True).strip() == str(release)
    assert subprocess.check_output(["git", "rev-parse", "--git-dir"], cwd=release, text=True).strip() == ".git"
    assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=release, text=True).strip() == sha


def test_prepare_metadata_file_is_excluded_locally_without_tracked_gitignore_change(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode == 0
    release = layout["releases"] / sha
    exclude_path = release / ".git" / "info" / "exclude"
    exclude_text = exclude_path.read_text(encoding="utf-8")
    assert "/.immutable_release_metadata.json" in exclude_text
    assert subprocess.check_output(["git", "status", "--short", "--untracked-files=no"], cwd=release, text=True).strip() == ""
    assert subprocess.run(["git", "diff-index", "--quiet", "HEAD", "--"], cwd=release).returncode == 0
    assert subprocess.run(["git", "status", "--short", "--", ".gitignore"], cwd=release, text=True, capture_output=True).stdout.strip() == ""


def test_existing_release_without_git_identity_is_rejected(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)
    env["IMMUTABLE_V2_ENFORCE_GIT_RELEASE_IDENTITY"] = "1"

    release = layout["releases"] / sha
    release.mkdir(parents=True, exist_ok=True)
    _write(release / ".immutable_release_metadata.json", json.dumps({"release_sha": sha}, ensure_ascii=False))

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode != 0
    assert "FAIL_RELEASE_INTEGRITY" in (res.stderr + res.stdout)


def test_existing_release_parent_git_discovery_is_rejected(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)

    parent = layout["base"]
    subprocess.run(["git", "init"], cwd=parent, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "parent@example.com"], cwd=parent, check=True)
    subprocess.run(["git", "config", "user.name", "Parent User"], cwd=parent, check=True)
    _write(parent / "PARENT_MARKER.txt", "parent\n")
    subprocess.run(["git", "add", "PARENT_MARKER.txt"], cwd=parent, check=True)
    subprocess.run(["git", "commit", "-m", "parent-init"], cwd=parent, check=True, capture_output=True, text=True)

    release = layout["releases"] / sha
    release.mkdir(parents=True, exist_ok=True)
    _write(release / ".immutable_release_metadata.json", json.dumps({"release_sha": sha}, ensure_ascii=False))

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode != 0
    assert "FAIL_RELEASE_INTEGRITY" in (res.stderr + res.stdout)


def test_existing_release_basename_sha_mismatch_is_rejected(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)

    wrong_sha = "f" * 40
    release = layout["releases"] / wrong_sha
    release.mkdir(parents=True, exist_ok=True)
    _write(release / ".immutable_release_metadata.json", json.dumps({"release_sha": sha}, ensure_ascii=False))

    res = _invoke(repo, sha, "cutover", env)

    assert res.returncode != 0
    assert "Prepared release not found" in (res.stderr + res.stdout)


def test_existing_git_release_head_mismatch_rejected(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)
    env["IMMUTABLE_V2_ENFORCE_GIT_RELEASE_IDENTITY"] = "1"

    release = layout["releases"] / sha
    release.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", str(repo), str(release)], check=True, capture_output=True, text=True)
    subprocess.run(["git", "checkout", "-b", "mutate-head"], cwd=release, check=True, capture_output=True, text=True)
    _write(release / "head_mismatch.txt", "x\n")
    subprocess.run(["git", "add", "head_mismatch.txt"], cwd=release, check=True)
    subprocess.run(["git", "commit", "-m", "mutate head"], cwd=release, check=True, capture_output=True, text=True)
    _write(release / ".immutable_release_metadata.json", json.dumps({"release_sha": sha}, ensure_ascii=False))

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode != 0
    assert "FAIL_RELEASE_INTEGRITY" in (res.stderr + res.stdout)
    assert "git HEAD" in (res.stderr + res.stdout)


def test_existing_git_release_dirty_tree_rejected(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)
    env["IMMUTABLE_V2_ENFORCE_GIT_RELEASE_IDENTITY"] = "1"

    release = layout["releases"] / sha
    release.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", str(repo), str(release)], check=True, capture_output=True, text=True)
    subprocess.run(["git", "checkout", sha], cwd=release, check=True, capture_output=True, text=True)
    _write(release / ".immutable_release_metadata.json", json.dumps({"release_sha": sha}, ensure_ascii=False))
    _write(release / "scheduler.py", "print('dirty')\n")

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode != 0
    assert "FAIL_RELEASE_INTEGRITY" in (res.stderr + res.stdout)
    assert "worktree dirty" in (res.stderr + res.stdout)


def test_existing_git_release_missing_expected_commit_rejected(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)
    env["IMMUTABLE_V2_ENFORCE_GIT_RELEASE_IDENTITY"] = "1"

    release = layout["releases"] / sha
    release.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "master"], cwd=release, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=release, check=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=release, check=True)
    _write(release / "README.md", "foreign\n")
    subprocess.run(["git", "add", "README.md"], cwd=release, check=True)
    subprocess.run(["git", "commit", "-m", "foreign"], cwd=release, check=True, capture_output=True, text=True)
    _write(release / ".immutable_release_metadata.json", json.dumps({"release_sha": sha}, ensure_ascii=False))

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode != 0
    assert "FAIL_RELEASE_INTEGRITY" in (res.stderr + res.stdout)
    assert "git HEAD" in (res.stderr + res.stdout) or "expected commit object missing" in (res.stderr + res.stdout)


def test_prepare_failure_cleans_invocation_owned_staging(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)
    env["IMMUTABLE_V2_TEST_HOOK_BEFORE_FINALIZE"] = "exit 23"

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode != 0
    assert not (layout["releases"] / f".staging-{sha}").exists()
    assert not (layout["releases"] / sha).exists()
    assert (layout["deploy_state"] / "prepare_failure_latest.json").exists()


def test_prepare_failure_preserves_preexisting_staging(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)
    staging = layout["releases"] / f".staging-{sha}"
    staging.mkdir(parents=True, exist_ok=True)
    _write(staging / "sentinel.txt", "keep\n")

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode != 0
    assert staging.exists()
    assert (staging / "sentinel.txt").exists()


def test_prepare_failure_does_not_modify_shared_assets(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)
    env["IMMUTABLE_V2_TEST_HOOK_BEFORE_FINALIZE"] = "exit 77"
    shared_file = layout["shared"] / "state" / "youtube_playlists.json"
    before = shared_file.read_text(encoding="utf-8")

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode != 0
    assert shared_file.read_text(encoding="utf-8") == before


def test_prepare_failure_report_is_redacted(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)
    env.pop("IMMUTABLE_V2_SKIP_HEALTHCHECK")
    env["EXPECT_SCHEDULER_CWD"] = str(layout["releases"] / f".staging-{sha}")
    env["SIMULATE_HEALTH_ERRORS_JSON"] = json.dumps(["Missing Telegram configuration. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env."])

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode != 0
    report_text = (layout["deploy_state"] / "prepare_failure_latest.json").read_text(encoding="utf-8")
    assert "ANTHROPIC_API_KEY" not in report_text
    assert "token\n" not in report_text


def test_sanitization_failure_writes_report_and_cleans(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path, include_runtime_payload=True)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)
    env["IMMUTABLE_V2_TEST_HOOK_AFTER_EXPORT"] = "mkdir -p output && printf x > output/unexpected.txt"

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode != 0
    assert not (layout["releases"] / f".staging-{sha}").exists()
    report = json.loads((layout["deploy_state"] / "prepare_failure_latest.json").read_text(encoding="utf-8"))
    assert report["failed_phase"] == "runtime_payload_sanitization"


def test_linking_failure_writes_report_and_cleans(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)
    (layout["shared"] / "state" / "channel_registry.json").unlink()

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode != 0
    assert not (layout["releases"] / f".staging-{sha}").exists()
    report = json.loads((layout["deploy_state"] / "prepare_failure_latest.json").read_text(encoding="utf-8"))
    assert report["failed_phase"] == "persistent_linking"


def test_directory_bootstrap_failure_writes_report_and_cleans(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)
    shutil.rmtree(layout["shared"] / "runtime" / "output" / "scripts")
    _write(layout["shared"] / "runtime" / "output" / "scripts", "not-a-dir\n")

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode != 0
    assert not (layout["releases"] / f".staging-{sha}").exists()
    report = json.loads((layout["deploy_state"] / "prepare_failure_latest.json").read_text(encoding="utf-8"))
    assert report["failed_phase"] == "directory_bootstrap"


def test_import_failure_writes_report_and_cleans(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path, include_uploader=False)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode != 0
    assert not (layout["releases"] / f".staging-{sha}").exists()
    report = json.loads((layout["deploy_state"] / "prepare_failure_latest.json").read_text(encoding="utf-8"))
    assert report["failed_phase"] == "preflight"


def test_dependency_setup_failure_writes_report_and_cleans(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)
    env.pop("IMMUTABLE_V2_SKIP_DEP_INSTALL")
    _write(repo / "requirements.txt", "definitely-not-a-real-package-for-tests-12345\n")
    subprocess.run(["git", "add", "requirements.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "break-deps"], cwd=repo, check=True, capture_output=True, text=True)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    subprocess.run(["git", "update-ref", "refs/remotes/origin/release/test", sha], cwd=repo, check=True)

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode != 0
    assert not (layout["releases"] / f".staging-{sha}").exists()
    report = json.loads((layout["deploy_state"] / "prepare_failure_latest.json").read_text(encoding="utf-8"))
    assert report["failed_phase"] == "dependency_setup"


def test_temporary_topology_integration_simulation(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path, include_runtime_payload=True, include_asset_subdirs=False)
    layout = _runtime_layout(tmp_path)

    shutil.rmtree(layout["shared"] / "runtime" / "output" / "scripts")
    shutil.rmtree(layout["shared"] / "runtime" / "output" / "audio")
    shutil.rmtree(layout["shared"] / "runtime" / "output" / "videos")

    active_output = layout["active"] / "output"
    active_logs = layout["active"] / "logs"
    active_output_ino = active_output.stat().st_ino
    active_logs_ino = active_logs.stat().st_ino

    env = _base_env(layout)
    env.pop("IMMUTABLE_V2_SKIP_HEALTHCHECK")
    env["EXPECT_SCHEDULER_CWD"] = str(layout["releases"] / f".staging-{sha}")

    prepare_ok = _invoke(repo, sha, "prepare", env)
    assert prepare_ok.returncode == 0

    release = layout["releases"] / sha
    assert (release / "output").is_symlink()
    assert (release / "logs").is_symlink()
    assert (release / "output").resolve() == (layout["shared"] / "runtime" / "output").resolve()
    assert (release / "logs").resolve() == (layout["shared"] / "logs").resolve()

    payload = json.loads((release / "deployment_preflight.json").read_text(encoding="utf-8"))
    evidence = {item["relative_path"]: item for item in payload.get("path_evidence", [])}
    assert evidence["output"]["status"] == "pass"
    assert evidence["logs"]["status"] == "pass"
    assert evidence["output/scripts"]["action"] == "created"
    assert evidence["output/audio"]["action"] == "created"
    assert evidence["output/videos"]["action"] == "created"
    assert evidence["assets/backgrounds"]["action"] == "created"
    assert evidence["assets/music"]["action"] == "created"
    assert evidence["assets/fonts"]["action"] == "created"

    assert active_output.is_dir() and not active_output.is_symlink()
    assert active_logs.is_dir() and not active_logs.is_symlink()
    assert active_output.stat().st_ino == active_output_ino
    assert active_logs.stat().st_ino == active_logs_ino

    repo2, sha2 = _init_repo(tmp_path / "second")
    layout2 = _runtime_layout(tmp_path / "second")
    env2 = _base_env(layout2)
    env2["IMMUTABLE_V2_TEST_HOOK_BEFORE_FINALIZE"] = "exit 31"
    fail_res = _invoke(repo2, sha2, "prepare", env2)
    assert fail_res.returncode != 0
    assert not (layout2["releases"] / f".staging-{sha2}").exists()


def test_systemd_file_writes_impossible_by_contract() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "systemctl edit" not in text
    assert "daemon-reload" not in text
    assert "/etc/systemd/system" not in text


def test_env_append_write_impossible_by_contract() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert ">> .env" not in text
    assert ".env" in text  # referenced only as linked persistent asset


def test_token_copy_rejected_via_symlink_strategy(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode == 0
    linked = layout["releases"] / sha / "channels" / "alpha" / "youtube_token.pickle"
    assert linked.is_symlink()


def test_missing_persistent_asset_rejected(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)

    (layout["shared"] / "state" / "channel_registry.json").unlink()

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode != 0
    assert "Missing persistent asset source" in (res.stderr + res.stdout) or "Mandatory shared asset" in (res.stderr + res.stdout)


def test_prepare_keeps_tracked_external_persistent_files_clean(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    _write(repo / "youtube_playlists.json", "{}\n")
    _write(repo / "channels" / "channel_registry.json", "{}\n")
    _write(repo / "channels" / "channels_tracker.csv", "channel\n")
    subprocess.run(["git", "add", "youtube_playlists.json", "channels/channel_registry.json", "channels/channels_tracker.csv"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "add tracked external persistent files"], cwd=repo, check=True, capture_output=True, text=True)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    subprocess.run(["git", "update-ref", "refs/remotes/origin/release/test", sha], cwd=repo, check=True)

    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)
    env["IMMUTABLE_V2_TEST_HOOK_AFTER_EXPORT"] = f"cp -a {repo / '.git'} .git"

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode == 0
    release = layout["releases"] / sha
    assert not (release / "youtube_playlists.json").is_symlink()
    assert not (release / "channels" / "channel_registry.json").is_symlink()
    assert not (release / "channels" / "channels_tracker.csv").is_symlink()
    assert (release / "client_secrets.json").is_symlink()


def test_unknown_asset_classification_rejected(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)

    _write(layout["active"] / "channels" / "alpha" / "mystery_secret.bin", "x\n")

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode != 0
    assert "UNKNOWN_BLOCKER" in (res.stderr + res.stdout)


def test_preflight_import_failure_blocks_prepare(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path, include_uploader=False)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode != 0
    assert "import validation failed" in (res.stderr + res.stdout)


def test_health_check_failure_blocks_prepare(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path, health_ok=False)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)
    env.pop("IMMUTABLE_V2_SKIP_HEALTHCHECK")

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode != 0
    assert "health check failed" in (res.stderr + res.stdout)


def test_cutover_requires_prepared_release(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    fakebin, _ = _fake_bin(tmp_path)
    env = _base_env(layout, fakebin)

    res = _invoke(repo, sha, "cutover", env)

    assert res.returncode != 0
    assert "Prepared release not found" in (res.stderr + res.stdout)


def test_atomic_symlink_switch_command_present_in_dry_run(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    fakebin, _ = _fake_bin(tmp_path)
    env = _base_env(layout, fakebin)

    prep = _invoke(repo, sha, "prepare", env)
    assert prep.returncode == 0

    res = _invoke(repo, sha, "cutover", env, ["--dry-run"])

    assert res.returncode == 0
    assert "mv -Tf" in (res.stderr + res.stdout)


def test_cutover_defaults_auto_rollback_false(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    fakebin, _ = _fake_bin(tmp_path)
    env = _base_env(layout, fakebin)

    prep = _invoke(repo, sha, "prepare", env)
    assert prep.returncode == 0

    res = _invoke(repo, sha, "cutover", env, ["--dry-run"])

    assert res.returncode == 0
    assert "Cutover policy: AUTO_ROLLBACK=false" in (res.stderr + res.stdout)


def test_usage_documents_auto_rollback_flag(tmp_path: Path) -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "--auto-rollback" in text


def test_cutover_dry_run_without_flag_only_prints_rollback_metadata(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    fakebin, _ = _fake_bin(tmp_path)
    env = _base_env(layout, fakebin)

    prep = _invoke(repo, sha, "prepare", env)
    assert prep.returncode == 0

    metadata_file = layout["deploy_state"] / "last_rollback_target.json"
    assert not metadata_file.exists()

    res = _invoke(repo, sha, "cutover", env, ["--dry-run"])

    output = res.stderr + res.stdout
    assert res.returncode == 0
    assert "DRY-RUN: write rollback metadata" in output
    assert "attempting automatic rollback" not in output
    assert not metadata_file.exists()


def test_cutover_dry_run_with_flag_still_performs_no_real_rollback(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    fakebin, _ = _fake_bin(tmp_path)
    env = _base_env(layout, fakebin)

    prep = _invoke(repo, sha, "prepare", env)
    assert prep.returncode == 0

    before = layout["current"].readlink()
    metadata_file = layout["deploy_state"] / "last_rollback_target.json"

    res = _invoke(repo, sha, "cutover", env, ["--auto-rollback", "--dry-run"])

    output = res.stderr + res.stdout
    assert res.returncode == 0
    assert "Cutover policy: AUTO_ROLLBACK=true" in output
    assert "attempting automatic rollback" not in output
    assert layout["current"].readlink() == before
    assert not metadata_file.exists()


def test_service_restart_only_in_cutover_or_rollback(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    fakebin, log = _fake_bin(tmp_path)
    env = _base_env(layout, fakebin)

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode == 0
    assert not log.exists() or "restart parapusulasi" not in log.read_text(encoding="utf-8")


def test_post_cutover_failure_without_flag_does_not_trigger_rollback(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path, health_ok=False)
    layout = _runtime_layout(tmp_path)
    fakebin, _ = _fake_bin(tmp_path, active_service=True)
    env = _base_env(layout, fakebin)
    env.pop("IMMUTABLE_V2_SKIP_HEALTHCHECK")
    env["IMMUTABLE_V2_SKIP_HEALTHCHECK"] = "1"  # preflight passes
    env.pop("IMMUTABLE_V2_SKIP_RUNTIME_HEALTH_LOOP")  # runtime loop runs and fails
    env["IMMUTABLE_V2_HEALTH_LOOP_ATTEMPTS"] = "1"
    env["IMMUTABLE_V2_HEALTH_LOOP_SLEEP_SECONDS"] = "0"

    before = layout["current"].readlink()
    prep = _invoke(repo, sha, "prepare", env)
    assert prep.returncode == 0

    cut = _invoke(repo, sha, "cutover", env)

    assert cut.returncode != 0
    assert layout["current"].resolve() == (layout["releases"] / sha).resolve()
    assert not layout["lock_dir"].exists()
    assert "Automatic rollback disabled; explicit rollback authorization required" in (cut.stderr + cut.stdout)


def test_post_cutover_failure_with_auto_rollback_restores_previous_release(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path, health_ok=False)
    layout = _runtime_layout(tmp_path)
    fakebin, _ = _fake_bin(tmp_path, active_service=True)
    env = _base_env(layout, fakebin)
    env.pop("IMMUTABLE_V2_SKIP_HEALTHCHECK")
    env["IMMUTABLE_V2_SKIP_HEALTHCHECK"] = "1"
    env.pop("IMMUTABLE_V2_SKIP_RUNTIME_HEALTH_LOOP")
    env["IMMUTABLE_V2_HEALTH_LOOP_ATTEMPTS"] = "1"
    env["IMMUTABLE_V2_HEALTH_LOOP_SLEEP_SECONDS"] = "0"

    before = layout["current"].readlink()
    prep = _invoke(repo, sha, "prepare", env)
    assert prep.returncode == 0

    cut = _invoke(repo, sha, "cutover", env, ["--auto-rollback"])

    assert cut.returncode != 0
    assert layout["current"].readlink() == before


def test_rollback_restores_previous_release(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    fakebin, _ = _fake_bin(tmp_path, active_service=True)
    env = _base_env(layout, fakebin)

    prep = _invoke(repo, sha, "prepare", env)
    assert prep.returncode == 0

    # Simulate current target switched to the new release, then rollback back to active sha.
    (layout["current"]).unlink()
    (layout["current"]).symlink_to(layout["releases"] / sha)

    old_sha = layout["active"].name
    res = _invoke(repo, sha, "rollback", env, ["--rollback-sha", old_sha])

    assert res.returncode == 0
    assert layout["current"].resolve() == layout["active"].resolve()


def test_cutover_target_mismatch_without_flag_does_not_trigger_rollback(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    fakebin, _ = _fake_bin(tmp_path, active_service=True)
    env = _base_env(layout, fakebin)

    unexpected = tmp_path / "unexpected-target"
    unexpected.mkdir(parents=True, exist_ok=True)
    mv_count = tmp_path / "mv.count"
    _write(
        fakebin / "mv",
        (
            "#!/usr/bin/env bash\n"
            "args=()\n"
            "for a in \"$@\"; do\n"
            "  [[ \"$a\" == \"-T\" || \"$a\" == \"-f\" || \"$a\" == \"-Tf\" ]] && continue\n"
            "  args+=(\"$a\")\n"
            "done\n"
            "src=\"${args[0]}\"\n"
            "dst=\"${args[1]}\"\n"
            f"count_file='{mv_count}'\n"
            "n=0\n"
            "if [[ -f \"$count_file\" ]]; then n=$(cat \"$count_file\"); fi\n"
            "n=$((n+1))\n"
            "printf '%s' \"$n\" > \"$count_file\"\n"
            f"if [[ \"$dst\" == \"{layout['current']}\" ]]; then\n"
            "  if [[ \"$n\" -eq 1 ]]; then\n"
            "    rm -f \"$dst\"\n"
            f"    ln -s \"{unexpected}\" \"$dst\"\n"
            "    rm -f \"$src\"\n"
            "    exit 0\n"
            "  fi\n"
            "fi\n"
            "python3 - \"$src\" \"$dst\" <<'PY'\n"
            "import os, sys\n"
            "os.replace(sys.argv[1], sys.argv[2])\n"
            "PY\n"
        ),
    )
    (fakebin / "mv").chmod(0o755)

    prep = _invoke(repo, sha, "prepare", env)
    assert prep.returncode == 0
    if mv_count.exists():
        mv_count.unlink()

    cut = _invoke(repo, sha, "cutover", env)

    assert cut.returncode != 0
    assert layout["current"].resolve() == unexpected.resolve()
    assert "Automatic rollback disabled; explicit rollback authorization required" in (cut.stderr + cut.stdout)


def test_cutover_target_mismatch_with_auto_rollback_restores_previous_release(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    fakebin, _ = _fake_bin(tmp_path, active_service=True)
    env = _base_env(layout, fakebin)

    unexpected = tmp_path / "unexpected-target"
    unexpected.mkdir(parents=True, exist_ok=True)
    mv_count = tmp_path / "mv.count"
    _write(
        fakebin / "mv",
        (
            "#!/usr/bin/env bash\n"
            "args=()\n"
            "for a in \"$@\"; do\n"
            "  [[ \"$a\" == \"-T\" || \"$a\" == \"-f\" || \"$a\" == \"-Tf\" ]] && continue\n"
            "  args+=(\"$a\")\n"
            "done\n"
            "src=\"${args[0]}\"\n"
            "dst=\"${args[1]}\"\n"
            f"count_file='{mv_count}'\n"
            "n=0\n"
            "if [[ -f \"$count_file\" ]]; then n=$(cat \"$count_file\"); fi\n"
            "n=$((n+1))\n"
            "printf '%s' \"$n\" > \"$count_file\"\n"
            f"if [[ \"$dst\" == \"{layout['current']}\" ]]; then\n"
            "  if [[ \"$n\" -eq 1 ]]; then\n"
            "    rm -f \"$dst\"\n"
            f"    ln -s \"{unexpected}\" \"$dst\"\n"
            "    rm -f \"$src\"\n"
            "    exit 0\n"
            "  fi\n"
            "fi\n"
            "python3 - \"$src\" \"$dst\" <<'PY'\n"
            "import os, sys\n"
            "os.replace(sys.argv[1], sys.argv[2])\n"
            "PY\n"
        ),
    )
    (fakebin / "mv").chmod(0o755)

    before = layout["current"].readlink()
    prep = _invoke(repo, sha, "prepare", env)
    assert prep.returncode == 0
    if mv_count.exists():
        mv_count.unlink()

    cut = _invoke(repo, sha, "cutover", env, ["--auto-rollback"])

    assert cut.returncode != 0
    assert layout["current"].readlink() == before


def test_cutover_writes_rollback_metadata_file(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    fakebin, _ = _fake_bin(tmp_path)
    env = _base_env(layout, fakebin)

    prep = _invoke(repo, sha, "prepare", env)
    assert prep.returncode == 0

    cut = _invoke(repo, sha, "cutover", env)
    assert cut.returncode == 0

    metadata_file = layout["deploy_state"] / "last_rollback_target.json"
    assert metadata_file.exists()
    payload = json.loads(metadata_file.read_text(encoding="utf-8"))
    assert payload["previous_target"].endswith(layout["active"].name)
    assert payload["new_target"].endswith(sha)


def test_prepare_startup_preflight_does_not_receive_owner_token(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)
    env.pop("IMMUTABLE_V2_SKIP_HEALTHCHECK")
    capture_file = tmp_path / "prepare_health_env.json"
    env["CAPTURE_HEALTH_ENV_FILE"] = str(capture_file)

    prep = _invoke(repo, sha, "prepare", env)

    assert prep.returncode == 0
    payload = json.loads(capture_file.read_text(encoding="utf-8"))
    expected_state_root = layout["deploy_state"] / "preprod-health" / sha
    assert payload["argv"][-1] == "--startup-preflight"
    assert payload["IMMUTABLE_V2_LOCK_DIR"] == str(expected_state_root / "state" / "deploy.lock")
    assert payload["IMMUTABLE_V2_EXPECTED_LOCK_OWNER_TOKEN"] == ""
    assert payload["owner_json_exists"] is False


def test_cutover_startup_preflight_validates_real_owner_token_and_cleans_lock(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    fakebin, _ = _fake_bin(tmp_path)
    env = _base_env(layout, fakebin)
    env.pop("IMMUTABLE_V2_SKIP_HEALTHCHECK")
    capture_file = tmp_path / "cutover_health_env.json"
    env["CAPTURE_HEALTH_ENV_FILE"] = str(capture_file)

    prep = _invoke(repo, sha, "prepare", env)
    assert prep.returncode == 0

    cut = _invoke(repo, sha, "cutover", env)

    assert cut.returncode == 0
    payload = json.loads(capture_file.read_text(encoding="utf-8"))
    assert payload["argv"][-1] == "--startup-preflight"
    assert payload["IMMUTABLE_V2_LOCK_DIR"] == str(layout["lock_dir"])
    assert payload["owner_json_exists"] is True
    assert payload["owner_id"]
    assert payload["IMMUTABLE_V2_EXPECTED_LOCK_OWNER_TOKEN"] == payload["owner_id"]
    assert payload["active_deployment_lock"]["reason_code"] == "self_owned_deployment_lock"
    assert payload["active_deployment_lock"]["evidence"]["self_owned"] is True
    assert not layout["lock_dir"].exists()


def test_cutover_startup_preflight_blocks_owner_token_mismatch_and_cleans_lock(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    fakebin, _ = _fake_bin(tmp_path)
    env = _base_env(layout, fakebin)
    env.pop("IMMUTABLE_V2_SKIP_HEALTHCHECK")
    capture_file = tmp_path / "cutover_mismatch_health_env.json"
    env["CAPTURE_HEALTH_ENV_FILE"] = str(capture_file)
    owner_file = layout["lock_dir"] / ".active_lock" / "owner.json"
    env["IMMUTABLE_V2_TEST_HOOK_AFTER_LOCK_ACQUIRE"] = (
        "python3 -c "
        + repr(
            "import json; "
            f"from pathlib import Path; Path({str(owner_file)!r}).write_text(json.dumps({{'owner_id': 'foreign-owner'}}), encoding='utf-8')"
        )
    )

    prep = _invoke(repo, sha, "prepare", env)
    assert prep.returncode == 0

    cut = _invoke(repo, sha, "cutover", env)

    assert cut.returncode != 0
    payload = json.loads(capture_file.read_text(encoding="utf-8"))
    assert payload["IMMUTABLE_V2_LOCK_DIR"] == str(layout["lock_dir"])
    assert payload["owner_json_exists"] is True
    assert payload["owner_id"] == "foreign-owner"
    assert payload["IMMUTABLE_V2_EXPECTED_LOCK_OWNER_TOKEN"]
    assert payload["IMMUTABLE_V2_EXPECTED_LOCK_OWNER_TOKEN"] != payload["owner_id"]
    assert payload["active_deployment_lock"]["reason_code"] == "active_deployment_lock"
    assert payload["active_deployment_lock"]["evidence"]["self_owned"] is False
    assert not (layout["lock_dir"] / ".active_lock").exists()


def test_cutover_preflight_failure_cleans_owned_lock(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    fakebin, _ = _fake_bin(tmp_path)
    env = _base_env(layout, fakebin)
    env.pop("IMMUTABLE_V2_SKIP_HEALTHCHECK")
    env["SIMULATE_HEALTH_ERRORS_JSON"] = json.dumps(["forced startup preflight failure"])

    prep_env = dict(env)
    prep_env["IMMUTABLE_V2_SKIP_HEALTHCHECK"] = "1"
    prep = _invoke(repo, sha, "prepare", prep_env)
    assert prep.returncode == 0

    cut = _invoke(repo, sha, "cutover", env)

    assert cut.returncode != 0
    assert not layout["lock_dir"].exists()
    assert "Preflight scheduler health check failed" in (cut.stderr + cut.stdout)


def test_cutover_partial_lock_initialization_failure_removes_self_created_marker(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    fakebin, _ = _fake_bin(tmp_path)
    env = _base_env(layout, fakebin)
    env["IMMUTABLE_V2_TEST_HOOK_FAIL_AFTER_LOCK_MARKER"] = "1"

    prep = _invoke(repo, sha, "prepare", env)
    assert prep.returncode == 0

    cut = _invoke(repo, sha, "cutover", env)

    assert cut.returncode != 0
    assert "Deployment lock initialization failed after marker creation" in (cut.stderr + cut.stdout)
    assert not (layout["lock_dir"] / ".active_lock").exists()


def test_cutover_partial_lock_initialization_failure_never_removes_foreign_lock(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    fakebin, _ = _fake_bin(tmp_path)
    env = _base_env(layout, fakebin)
    env["IMMUTABLE_V2_TEST_HOOK_FAIL_AFTER_LOCK_MARKER"] = "1"
    foreign_owner = layout["lock_dir"] / ".active_lock" / "owner.json"
    foreign_owner.parent.mkdir(parents=True, exist_ok=True)
    foreign_owner.write_text(json.dumps({"owner_id": "foreign-owner"}), encoding="utf-8")

    prep = _invoke(repo, sha, "prepare", env)
    assert prep.returncode == 0

    cut = _invoke(repo, sha, "cutover", env)

    assert cut.returncode != 0
    assert "classification=malformed_lock" in (cut.stderr + cut.stdout)
    assert foreign_owner.exists()
    assert json.loads(foreign_owner.read_text(encoding="utf-8"))["owner_id"] == "foreign-owner"


def test_watchdog_is_tracked_executable_in_prepared_release(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode == 0
    release = layout["releases"] / sha
    mode = subprocess.check_output(["git", "ls-files", "--stage", "watchdog.sh"], cwd=release, text=True).split()[0]
    assert mode == "100755"
    assert os.access(release / "watchdog.sh", os.X_OK)


def test_prepare_rejects_non_executable_watchdog(tmp_path: Path) -> None:
    repo, _ = _init_repo(tmp_path)
    subprocess.run(["chmod", "0644", "watchdog.sh"], cwd=repo, check=True)
    subprocess.run(["git", "add", "watchdog.sh"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "make watchdog non executable"], cwd=repo, check=True, capture_output=True, text=True)
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    subprocess.run(["git", "update-ref", "refs/remotes/origin/release/test", sha], cwd=repo, check=True)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode != 0
    assert "watchdog.sh must be executable" in (res.stderr + res.stdout)


def test_cutover_links_operator_watchdog_to_managed_release(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    fakebin, _ = _fake_bin(tmp_path)
    env = _base_env(layout, fakebin)
    legacy = layout["operator"] / "watchdog.sh"
    _write(legacy, "#!/usr/bin/env bash\nexit 99\n")
    legacy.chmod(0o644)

    prep = _invoke(repo, sha, "prepare", env)
    assert prep.returncode == 0
    cut = _invoke(repo, sha, "cutover", env)

    assert cut.returncode == 0
    target = layout["releases"] / sha / "watchdog.sh"
    assert legacy.is_symlink()
    assert legacy.resolve() == target.resolve()
    assert os.access(legacy, os.X_OK)


def test_watchdog_exits_without_restart_when_service_healthy(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    fakebin, log = _fake_bin(tmp_path, active_service=True)
    env = _base_env(layout, fakebin)

    prep = _invoke(repo, sha, "prepare", env)
    assert prep.returncode == 0
    cut = _invoke(repo, sha, "cutover", env)
    assert cut.returncode == 0
    log.write_text("", encoding="utf-8")

    res = _run([str(layout["operator"] / "watchdog.sh")], cwd=repo, env=env)

    assert res.returncode == 0
    calls = log.read_text(encoding="utf-8")
    assert "is-active --quiet parapusulasi" in calls
    assert "start parapusulasi" not in calls


def test_watchdog_restarts_normal_crash_when_no_deployment_lock(tmp_path: Path) -> None:
    fakebin, systemctl_log, curl_log, service_state = _watchdog_fake_bin(tmp_path, active_service=False, start_succeeds=True)
    env = _watchdog_env(tmp_path, fakebin)

    res = _run([str(Path(__file__).resolve().parents[1] / "watchdog.sh")], cwd=Path(__file__).resolve().parents[1], env=env)

    assert res.returncode == 0
    calls = systemctl_log.read_text(encoding="utf-8")
    notifications = curl_log.read_text(encoding="utf-8")
    assert "is-active --quiet parapusulasi" in calls
    assert "start parapusulasi" in calls
    assert service_state.read_text(encoding="utf-8").strip() == "active"
    assert "deployment lock yok" in notifications
    assert "Scheduler yeniden baslatildi" in notifications


def test_watchdog_uses_release_virtualenv_without_python_override(tmp_path: Path) -> None:
    app = _classifier_app(tmp_path, classification="no_lock")
    python_log = tmp_path / "venv-python.log"
    _install_venv_python(app, python_log)
    fakebin, systemctl_log, _curl_log, _service_state = _watchdog_fake_bin(tmp_path, active_service=False, start_succeeds=True)
    env = _watchdog_env(tmp_path, fakebin, app_root=app)
    env.pop("WATCHDOG_PYTHON_BIN")

    res = _run([str(Path(__file__).resolve().parents[1] / "watchdog.sh")], cwd=Path(__file__).resolve().parents[1], env=env)

    assert res.returncode == 0
    assert "start parapusulasi" in systemctl_log.read_text(encoding="utf-8")
    python_calls = python_log.read_text(encoding="utf-8")
    assert "src.production_safety_gate" in python_calls
    assert str(app / ".venv-2" / "bin" / "python") in python_calls


def test_watchdog_classifier_timeout_fails_closed(tmp_path: Path) -> None:
    app = _classifier_app_with_source(
        tmp_path,
        "classifier-timeout",
        "import time\ntime.sleep(2)\nprint('{\"lock_classification\":\"no_lock\"}')\n",
    )
    fakebin, systemctl_log, curl_log, _service_state = _watchdog_fake_bin(tmp_path, active_service=False)
    env = _watchdog_env(tmp_path, fakebin, app_root=app)
    env["WATCHDOG_CLASSIFIER_TIMEOUT_SECONDS"] = "0.1"

    res = _run([str(Path(__file__).resolve().parents[1] / "watchdog.sh")], cwd=Path(__file__).resolve().parents[1], env=env)

    assert res.returncode == 0
    assert "start parapusulasi" not in systemctl_log.read_text(encoding="utf-8")
    assert "owner_state=classifier_timeout" in curl_log.read_text(encoding="utf-8")


def test_watchdog_revalidates_lock_immediately_before_restart(tmp_path: Path) -> None:
    counter = tmp_path / "classifier-count"
    app = _classifier_app_with_source(
        tmp_path,
        "classifier-revalidate",
        (
            "import json\n"
            "from pathlib import Path\n"
            f"counter = Path({str(counter)!r})\n"
            "count = int(counter.read_text() or '0') if counter.exists() else 0\n"
            "counter.write_text(str(count + 1))\n"
            "classification = 'no_lock' if count == 0 else 'foreign_active_lock'\n"
            "owner_state = 'none' if count == 0 else 'lock_created_after_initial_check'\n"
            "print(json.dumps({'lock_classification': classification, 'owner_state': owner_state}))\n"
        ),
    )
    fakebin, systemctl_log, curl_log, _service_state = _watchdog_fake_bin(tmp_path, active_service=False)
    env = _watchdog_env(tmp_path, fakebin, app_root=app)

    res = _run([str(Path(__file__).resolve().parents[1] / "watchdog.sh")], cwd=Path(__file__).resolve().parents[1], env=env)

    assert res.returncode == 0
    assert "start parapusulasi" not in systemctl_log.read_text(encoding="utf-8")
    notifications = curl_log.read_text(encoding="utf-8")
    assert "restart revalidation ile bastirildi" in notifications
    assert "classification=foreign_active_lock" in notifications


def test_watchdog_execution_lock_prevents_concurrent_restart_race(tmp_path: Path) -> None:
    app = _classifier_app_with_source(
        tmp_path,
        "classifier-slow-no-lock",
        "import json, time\ntime.sleep(1)\nprint(json.dumps({'lock_classification': 'no_lock', 'owner_state': 'none'}))\n",
    )
    fakebin, systemctl_log, _curl_log, _service_state = _watchdog_fake_bin(tmp_path, active_service=False, start_succeeds=True)
    env = _watchdog_env(tmp_path, fakebin, app_root=app)
    watchdog = str(Path(__file__).resolve().parents[1] / "watchdog.sh")

    first = subprocess.Popen([watchdog], cwd=Path(__file__).resolve().parents[1], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env={**os.environ, **env})
    time.sleep(0.2)
    second = _run([watchdog], cwd=Path(__file__).resolve().parents[1], env=env)
    first_stdout, first_stderr = first.communicate(timeout=10)

    assert first.returncode == 0, first_stdout + first_stderr
    assert second.returncode == 0
    calls = systemctl_log.read_text(encoding="utf-8")
    assert calls.count("start parapusulasi") == 1


def test_watchdog_state_writes_are_atomic() -> None:
    text = (Path(__file__).resolve().parents[1] / "watchdog.sh").read_text(encoding="utf-8")

    assert "write_state_file" in text
    assert 'mv -f "${tmp}" "${path}"' in text
    assert '> "${OPEN_INCIDENT_FILE}"' not in text
    assert '> "${ATTEMPT_FILE}"' not in text


@pytest.mark.parametrize(
    "classification",
    [
        "self_owned_active_lock",
        "foreign_active_lock",
        "stale_lock",
        "malformed_lock",
        "unreadable_lock",
        "ambiguous_lock",
    ],
)
def test_watchdog_suppresses_restart_for_deployment_lock_classifier_states(tmp_path: Path, classification: str) -> None:
    fakebin, systemctl_log, curl_log, _service_state = _watchdog_fake_bin(tmp_path, active_service=False)
    env = _watchdog_env(tmp_path, fakebin, app_root=_classifier_app(tmp_path, classification=classification))

    res = _run([str(Path(__file__).resolve().parents[1] / "watchdog.sh")], cwd=Path(__file__).resolve().parents[1], env=env)

    assert res.returncode == 0
    calls = systemctl_log.read_text(encoding="utf-8")
    notifications = curl_log.read_text(encoding="utf-8")
    assert "is-active --quiet parapusulasi" in calls
    assert "start parapusulasi" not in calls
    assert f"classification={classification}" in notifications
    assert "restart bastirildi" in notifications


def test_watchdog_suppresses_duplicate_deployment_lock_incidents(tmp_path: Path) -> None:
    fakebin, systemctl_log, curl_log, _service_state = _watchdog_fake_bin(tmp_path, active_service=False)
    env = _watchdog_env(tmp_path, fakebin, app_root=_classifier_app(tmp_path, classification="malformed_lock", owner_state="owner_metadata_invalid_json"))
    watchdog = str(Path(__file__).resolve().parents[1] / "watchdog.sh")

    first = _run([watchdog], cwd=Path(__file__).resolve().parents[1], env=env)
    second = _run([watchdog], cwd=Path(__file__).resolve().parents[1], env=env)

    assert first.returncode == 0
    assert second.returncode == 0
    assert "start parapusulasi" not in systemctl_log.read_text(encoding="utf-8")
    notifications = [line for line in curl_log.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(notifications) == 1
    assert "classification=malformed_lock" in notifications[0]


def test_watchdog_emits_single_recovery_notification(tmp_path: Path) -> None:
    fakebin, _systemctl_log, curl_log, _service_state = _watchdog_fake_bin(tmp_path, active_service=True)
    env = _watchdog_env(tmp_path, fakebin)
    state_dir = Path(env["WATCHDOG_STATE_DIR"])
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "open_incident").write_text("deployment_lock:stale_lock:dead_pid\n", encoding="utf-8")
    watchdog = str(Path(__file__).resolve().parents[1] / "watchdog.sh")

    first = _run([watchdog], cwd=Path(__file__).resolve().parents[1], env=env)
    second = _run([watchdog], cwd=Path(__file__).resolve().parents[1], env=env)

    assert first.returncode == 0
    assert second.returncode == 0
    assert not (state_dir / "open_incident").exists()
    notifications = [line for line in curl_log.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(notifications) == 1
    assert "watchdog olayi kapatildi" in notifications[0]


def test_watchdog_consumes_shared_classifier_without_lock_parsing() -> None:
    text = (Path(__file__).resolve().parents[1] / "watchdog.sh").read_text(encoding="utf-8")

    assert "--classify-deployment-lock" in text
    assert "src.production_safety_gate" in text
    assert "owner.json" not in text
    assert ".active_lock" not in text


def test_deploy_lock_classifier_bootstrap_exception_is_documented_and_aligned() -> None:
    deploy_text = SCRIPT.read_text(encoding="utf-8")
    safety_gate_text = (Path(__file__).resolve().parents[1] / "src" / "production_safety_gate.py").read_text(encoding="utf-8")
    classifications = {
        "no_lock",
        "self_owned_active_lock",
        "foreign_active_lock",
        "stale_lock",
        "malformed_lock",
        "unreadable_lock",
        "ambiguous_lock",
    }

    assert "Bootstrap exception" in deploy_text
    assert "Keep classifications aligned with src.production_safety_gate.classify_deployment_lock" in deploy_text
    for classification in classifications:
        assert classification in deploy_text
        assert classification in safety_gate_text


def test_rollback_failure_reported_clearly(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    fakebin, _ = _fake_bin(tmp_path, active_service=True)
    env = _base_env(layout, fakebin)

    res = _invoke(repo, sha, "rollback", env, ["--rollback-sha", "b" * 40])

    assert res.returncode != 0
    assert "Rollback target release not found" in (res.stderr + res.stdout)


def test_deployment_lock_prevents_concurrent_runs(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    fakebin, _ = _fake_bin(tmp_path)
    env = _base_env(layout, fakebin)

    prep = _invoke(repo, sha, "prepare", env)
    assert prep.returncode == 0
    (layout["lock_dir"] / ".active_lock").mkdir(parents=True, exist_ok=True)

    res = _invoke(repo, sha, "cutover", env)

    assert res.returncode != 0
    assert "classification=malformed_lock" in (res.stderr + res.stdout)


def test_deployment_precheck_refuses_stale_lock_without_auto_removal(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    fakebin, _ = _fake_bin(tmp_path)
    env = _base_env(layout, fakebin)

    prep = _invoke(repo, sha, "prepare", env)
    assert prep.returncode == 0
    active_lock = layout["lock_dir"] / ".active_lock"
    _write_owner(active_lock, owner_id="stale-owner", pid=999999)

    res = _invoke(repo, sha, "cutover", env)

    output = res.stderr + res.stdout
    assert res.returncode != 0
    assert "Stale deployment lock detected" in output
    assert "explicit operator confirmation required" in output
    assert active_lock.exists()
    assert (active_lock / "owner.json").exists()
    forensic_files = list((layout["deploy_state"] / "lock_forensics").glob("deployment_lock_stale_lock_*.json"))
    assert forensic_files


def test_empty_lock_directory_does_not_block_cutover(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    fakebin, _ = _fake_bin(tmp_path)
    env = _base_env(layout, fakebin)

    prep = _invoke(repo, sha, "prepare", env)
    assert prep.returncode == 0

    # A pre-provisioned empty lock directory is not an active lock holder.
    layout["lock_dir"].mkdir(parents=True, exist_ok=True)

    cut = _invoke(repo, sha, "cutover", env)

    assert cut.returncode == 0


def test_cutover_health_loop_uses_preprod_isolation_contract(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    fakebin, _ = _fake_bin(tmp_path, active_service=True)
    env = _base_env(layout, fakebin)
    env.pop("IMMUTABLE_V2_SKIP_HEALTHCHECK")
    env.pop("IMMUTABLE_V2_SKIP_RUNTIME_HEALTH_LOOP")
    capture_file = tmp_path / "health_env.json"
    env["CAPTURE_HEALTH_ENV_FILE"] = str(capture_file)

    prep = _invoke(repo, sha, "prepare", env)
    assert prep.returncode == 0

    cut = _invoke(repo, sha, "cutover", env)
    assert cut.returncode == 0

    payload = json.loads(capture_file.read_text(encoding="utf-8"))
    expected_state_root = layout["deploy_state"] / "preprod-health" / sha
    assert payload["PREPROD_ISOLATION_MODE"] == "true"
    assert payload["PREPROD_STATE_ROOT"] == str(expected_state_root)
    assert payload["RUNTIME_OUTPUT_ROOT"] == str(expected_state_root)
    assert payload["PRODUCTION_DASHBOARD_MD_PATH"] == str(expected_state_root / "state" / "production_dashboard_latest.md")
    assert payload["ACTIVATION_CONTROLLER_REPORT_ARCHIVE_DIR"] == str(expected_state_root / "state" / "activation_reports")
    assert payload["argv"][-1] == "--health-check"


def test_wrapper_never_executes_automatically(tmp_path: Path) -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "youtube_analytics_smoke" in text
    assert "--sync-analytics-now" not in text


def test_no_analytics_api_call_command_present(tmp_path: Path) -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "youtubeAnalytics" not in text
    assert "collect_analytics" not in text


def test_no_oauth_action_present(tmp_path: Path) -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "run_local_server" not in text
    assert "token refresh" not in text.lower()


def test_no_youtube_mutation_command_present(tmp_path: Path) -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "youtube.upload" not in text
    assert "videos().insert" not in text


def test_prepare_writes_preflight_json(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode == 0
    report = layout["releases"] / sha / "deployment_preflight.json"
    assert report.exists()
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["release_sha"] == sha


def test_plan_mode_rejects_unapproved_ref(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)

    res = _run(
        [
            "bash",
            str(SCRIPT),
            "--target-ref",
            "feature/unsafe",
            "--target-sha",
            sha,
            "--mode",
            "plan",
        ],
        cwd=repo,
        env=env,
    )

    assert res.returncode != 0
    assert "Unapproved target ref" in (res.stderr + res.stdout)


def test_rollback_mode_requires_explicit_sha(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    env = _base_env(layout)

    res = _invoke(repo, sha, "rollback", env)

    assert res.returncode != 0
    assert "--rollback-sha is required" in (res.stderr + res.stdout)
