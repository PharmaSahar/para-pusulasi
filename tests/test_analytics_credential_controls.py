from __future__ import annotations

import hashlib
import json
import os
import pickle
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

import ops.analytics_credential_preflight as preflight
import ops.detect_legacy_analytics_tokens as legacy
import ops.migrate_analytics_token_to_shared as migrate
import src.analytics_token_policy as policy


class _FakeCreds:
    def __init__(self, scopes: list[str] | None = None, refresh_token: str = "refresh"):
        self._scopes = scopes or [
            "https://www.googleapis.com/auth/yt-analytics.readonly",
            "https://www.googleapis.com/auth/youtube.readonly",
        ]
        self.refresh_token = refresh_token

    def has_scopes(self, scopes):
        return set(scopes).issubset(set(self._scopes))


class _FakeStatResult:
    def __init__(self, *, mode: int, uid: int = 0, gid: int = 0, dev: int = 1, ino: int = 1):
        self.st_mode = mode
        self.st_uid = uid
        self.st_gid = gid
        self.st_dev = dev
        self.st_ino = ino



def _fake_stat_for(path_map: dict[str, _FakeStatResult]):
    def _stat(path: str):
        text = str(path)
        for key, value in path_map.items():
            if text == key or text.endswith(key):
                return value
        raise FileNotFoundError(text)

    return _stat



def test_analytics_preflight_pass_and_failures(tmp_path, monkeypatch):
    channel_slug = "teknoloji_pusulasi"
    canonical_root = tmp_path / "shared" / "tokens" / "channels"
    monkeypatch.setattr(policy, "CANONICAL_ANALYTICS_TOKEN_ROOT", canonical_root)
    monkeypatch.setattr(preflight, "CANONICAL_ANALYTICS_TOKEN_ROOT", canonical_root)

    token_path = canonical_root / channel_slug / "youtube_analytics_token.pickle"
    uploader_path = canonical_root / channel_slug / "youtube_token.pickle"
    token_path.parent.mkdir(parents=True, exist_ok=True)
    uploader_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_bytes(pickle.dumps(_FakeCreds()))
    uploader_path.write_bytes(b"uploader")

    cfg = SimpleNamespace(
        channel_id=channel_slug,
        youtube_channel_id="UC123",
        youtube_analytics_token_path=str(token_path),
        token_path=str(uploader_path),
    )

    fake_stat = _fake_stat_for({
        str(token_path): _FakeStatResult(mode=0o100600),
        str(uploader_path): _FakeStatResult(mode=0o100600, ino=2),
    })

    pass_result = preflight.inspect_channel(
        channel_slug,
        stat_fn=fake_stat,
        load_credentials_fn=pickle.load,
        open_fn=open,
        channel_resolver=lambda _slug: cfg,
    )
    assert pass_result.status == preflight.RESULT_PASS

    bad_mode_stat = _fake_stat_for({
        str(token_path): _FakeStatResult(mode=0o100644),
        str(uploader_path): _FakeStatResult(mode=0o100600, ino=2),
    })
    bad_mode = preflight.inspect_channel(
        channel_slug,
        stat_fn=bad_mode_stat,
        load_credentials_fn=pickle.load,
        open_fn=open,
        channel_resolver=lambda _slug: cfg,
    )
    assert bad_mode.status == preflight.RESULT_INVALID_PERMISSIONS

    symlink_root = tmp_path / "symlink-case"
    symlink_root.mkdir(parents=True, exist_ok=True)
    symlink_target = symlink_root / "real.pickle"
    symlink_target.write_bytes(pickle.dumps(_FakeCreds()))
    symlink_path = symlink_root / "youtube_analytics_token.pickle"
    symlink_path.symlink_to(symlink_target)
    symlink_cfg = SimpleNamespace(
        channel_id=channel_slug,
        youtube_channel_id="UC123",
        youtube_analytics_token_path=str(symlink_path),
        token_path=str(uploader_path),
    )
    symlink_result = preflight.inspect_channel(
        channel_slug,
        stat_fn=fake_stat,
        load_credentials_fn=pickle.load,
        open_fn=open,
        channel_resolver=lambda _slug: symlink_cfg,
    )
    assert symlink_result.status == preflight.RESULT_SYMLINK_FORBIDDEN



def test_legacy_detector_allowlist_and_expiry(tmp_path, monkeypatch):
    canonical_root = tmp_path / "shared" / "tokens" / "channels"
    operator_root = tmp_path / "operator"
    current_root = tmp_path / "current"
    allowlist_path = tmp_path / "allowlist.json"
    monkeypatch.setattr(policy, "CANONICAL_ANALYTICS_TOKEN_ROOT", canonical_root)
    monkeypatch.setattr(legacy, "CANONICAL_ANALYTICS_TOKEN_ROOT", canonical_root)
    monkeypatch.setattr(legacy, "SCAN_ROOTS", (operator_root, current_root))
    monkeypatch.setattr(legacy, "LEGACY_ALLOWLIST_PATH", allowlist_path)

    channel_slug = "teknoloji_pusulasi"
    legacy_path = operator_root / "channels" / channel_slug / "youtube_analytics_token.pickle"
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_bytes(b"legacy-token")
    sha256 = hashlib.sha256(b"legacy-token").hexdigest()

    allowlist_path.write_text(
        json.dumps(
            [
                {
                    "channel_slug": channel_slug,
                    "legacy_path": str(legacy_path.resolve()),
                    "sha256": sha256,
                    "reason": "rollback_copy",
                    "expires_at": "2999-01-01T00:00:00Z",
                }
            ]
        ),
        encoding="utf-8",
    )

    report = legacy.inspect_legacy_tokens()
    assert report["overall_status"] == legacy.RESULT_PASS
    assert report["findings"][0]["status"] == legacy.RESULT_ALLOWLISTED

    allowlist_path.write_text(
        json.dumps(
            [
                {
                    "channel_slug": channel_slug,
                    "legacy_path": str(legacy_path.resolve()),
                    "sha256": sha256,
                    "reason": "rollback_copy",
                    "expires_at": "2000-01-01T00:00:00Z",
                }
            ]
        ),
        encoding="utf-8",
    )
    expired = legacy.inspect_legacy_tokens()
    assert expired["overall_status"] == "FAIL"
    assert expired["findings"][0]["status"] == legacy.RESULT_DETECTED
    assert expired["findings"][0]["reason"] == "allowlist_expired"



def test_migration_dry_run_apply_and_conflict(tmp_path, monkeypatch):
    source_path = tmp_path / "source.pickle"
    source_bytes = b"analytics-token-data"
    source_path.write_bytes(source_bytes)
    expected_sha256 = hashlib.sha256(source_bytes).hexdigest()

    destination_path = tmp_path / "shared" / "tokens" / "channels" / "teknoloji_pusulasi" / "youtube_analytics_token.pickle"
    monkeypatch.setattr(migrate, "canonical_analytics_token_path", lambda slug: destination_path)

    dry_run = migrate.migrate_analytics_token_to_shared(
        channel_slug="teknoloji_pusulasi",
        source=str(source_path),
        expected_sha256=expected_sha256,
        dry_run=True,
        apply=False,
    )
    assert dry_run.status == migrate.RESULT_DRY_RUN
    assert not destination_path.exists()

    fake_stat = lambda _path: _FakeStatResult(mode=0o100600, uid=0, gid=0, dev=1, ino=2)  # noqa: E731
    applied = migrate.migrate_analytics_token_to_shared(
        channel_slug="teknoloji_pusulasi",
        source=str(source_path),
        expected_sha256=expected_sha256,
        dry_run=False,
        apply=True,
        stat_fn=fake_stat,
        chown_fn=lambda *_args, **_kwargs: None,
    )
    assert applied.status == migrate.RESULT_PASS
    assert applied.applied is True
    assert destination_path.read_bytes() == source_bytes
    assert source_path.exists()

    second = migrate.migrate_analytics_token_to_shared(
        channel_slug="teknoloji_pusulasi",
        source=str(source_path),
        expected_sha256=expected_sha256,
        dry_run=False,
        apply=True,
        stat_fn=fake_stat,
        chown_fn=lambda *_args, **_kwargs: None,
    )
    assert second.status == migrate.RESULT_PASS
    assert second.applied is False

    destination_path.write_bytes(b"different")
    conflict = migrate.migrate_analytics_token_to_shared(
        channel_slug="teknoloji_pusulasi",
        source=str(source_path),
        expected_sha256=expected_sha256,
        dry_run=False,
        apply=True,
        stat_fn=fake_stat,
        chown_fn=lambda *_args, **_kwargs: None,
    )
    assert conflict.status == migrate.RESULT_DESTINATION_CONFLICT
    assert destination_path.read_bytes() == b"different"
