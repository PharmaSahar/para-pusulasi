from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "immutable_release_v2.sh"


def _run(cmd: list[str], cwd: Path, env: dict[str, str], check: bool = False) -> subprocess.CompletedProcess[str]:
    merged = os.environ.copy()
    merged.update(env)
    return subprocess.run(cmd, cwd=str(cwd), text=True, capture_output=True, env=merged, check=check)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _init_repo(tmp_path: Path, *, health_ok: bool = True, include_uploader: bool = True) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True, exist_ok=True)

    _write(
        repo / "scheduler.py",
        (
            "import sys\n"
            "if '--health-check' in sys.argv:\n"
            f"    sys.exit({0 if health_ok else 1})\n"
            "sys.exit(0)\n"
        ),
    )
    _write(repo / "src" / "__init__.py", "")
    if include_uploader:
        _write(repo / "src" / "youtube_uploader.py", "X = 1\n")
    _write(repo / "src" / "youtube_analytics_smoke.py", "Y = 1\n")
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
    deploy_state = base / "deploy_state"
    lock_dir = base / "deploy.lock"

    active_sha = "a" * 40
    active = releases / active_sha
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
        "deploy_state": deploy_state,
        "lock_dir": lock_dir,
        "active": active,
    }


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


def _base_env(layout: dict[str, Path], fakebin: Path | None = None) -> dict[str, str]:
    env = {
        "IMMUTABLE_V2_ALLOW_NON_OPT_ROOTS": "1",
        "IMMUTABLE_V2_RELEASES_ROOT": str(layout["releases"]),
        "IMMUTABLE_V2_CURRENT_LINK": str(layout["current"]),
        "IMMUTABLE_V2_DEPLOY_STATE_ROOT": str(layout["deploy_state"]),
        "IMMUTABLE_V2_SHARED_ROOT": str(layout["shared"]),
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
    release.mkdir(parents=True, exist_ok=True)
    _write(release / ".immutable_release_metadata.json", json.dumps({"release_sha": sha}, ensure_ascii=False))

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
    assert "mismatch" in (res.stderr + res.stdout)


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

    (layout["active"] / "channels" / "channel_registry.json").unlink()

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode != 0
    assert "Missing persistent asset source" in (res.stderr + res.stdout)


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


def test_service_restart_only_in_cutover_or_rollback(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    layout = _runtime_layout(tmp_path)
    fakebin, log = _fake_bin(tmp_path)
    env = _base_env(layout, fakebin)

    res = _invoke(repo, sha, "prepare", env)

    assert res.returncode == 0
    assert not log.exists() or "restart parapusulasi" not in log.read_text(encoding="utf-8")


def test_post_cutover_failure_triggers_rollback(tmp_path: Path) -> None:
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
    layout["lock_dir"].mkdir(parents=True, exist_ok=True)

    res = _invoke(repo, sha, "cutover", env)

    assert res.returncode != 0
    assert "lock exists" in (res.stderr + res.stdout)


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
