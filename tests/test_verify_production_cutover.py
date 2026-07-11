from __future__ import annotations

import json

import ops.verify_production_cutover as cutover


def _configure_common_mocks(monkeypatch):
    monkeypatch.setattr(cutover, "_discover_scheduler_pids", lambda: [4242])
    monkeypatch.setattr(cutover, "_read_pid", lambda: 4242)
    monkeypatch.setattr(cutover, "_process_info", lambda _pid: {
        "command": "python scheduler.py",
        "elapsed": "00:10:00",
        "cwd": str(cutover.ROOT),
    })


def test_cutover_returns_nonzero_when_build_sha_mismatch(monkeypatch, capsys):
    _configure_common_mocks(monkeypatch)
    monkeypatch.setattr(cutover, "_head_sha", lambda: "fb518e9")
    monkeypatch.setattr(cutover, "_last_build_info", lambda: {
        "line": "BUILD_INFO scheduler git_sha=bc9e1c2",
        "sha": "bc9e1c2",
    })

    rc = cutover.main()
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["checks"]["build_sha_matches_head"] is False
    assert payload["ok"] is False


def test_cutover_returns_zero_when_required_checks_pass(monkeypatch, capsys):
    _configure_common_mocks(monkeypatch)
    monkeypatch.setattr(cutover, "_head_sha", lambda: "fb518e9")
    monkeypatch.setattr(cutover, "_last_build_info", lambda: {
        "line": "BUILD_INFO scheduler git_sha=fb518e9",
        "sha": "fb518e9",
    })

    rc = cutover.main()
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["checks"]["build_sha_matches_head"] is True
    assert payload["ok"] is True
