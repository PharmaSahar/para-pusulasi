from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from googleapiclient.errors import HttpError
from httplib2 import ServerNotFoundError

import src.youtube_uploader as youtube_uploader
from src.content_generator import VideoContent
from src.production_safety_gate import (
    ProductionSafetyCheckResult,
    ProductionSafetyGateBlocked,
    ProductionSafetyGateResult,
)


class _FakeRequest:
    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.calls = 0

    def next_chunk(self):
        self.calls += 1
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _FakeVideos:
    def __init__(self, request):
        self._request = request

    def insert(self, **kwargs):
        return self._request


class _FakeService:
    def __init__(self, request):
        self._request = request

    def videos(self):
        return _FakeVideos(self._request)


def _make_video_file(tmp_path: Path) -> Path:
    video_path = tmp_path / "video.mp4"
    video_path.write_bytes(b"0" * 100_001)
    return video_path


def _make_content() -> VideoContent:
    return VideoContent(
        title="DNS test video",
        description="desc",
        tags=["test"],
        script="script",
        thumbnail_prompt="prompt",
        category_id="27",
        niche="teknoloji",
    )


def _make_http_error(status: int, payload: bytes) -> HttpError:
    return HttpError(SimpleNamespace(status=status, reason="test"), payload)


def test_upload_video_runs_dns_preflight(tmp_path: Path, monkeypatch):
    request = _FakeRequest([(None, {"id": "video123"})])
    uploader = youtube_uploader.YouTubeUploader()
    uploader._get_service = lambda: _FakeService(request)  # noqa: SLF001

    preflight_calls: list[str] = []
    monkeypatch.setattr(uploader, "_log_dns_resolution", lambda host: preflight_calls.append(f"log:{host}"))
    monkeypatch.setattr(uploader, "_ensure_dns_resolution", lambda host: preflight_calls.append(f"check:{host}"))

    video_path = _make_video_file(tmp_path)
    result = uploader.upload_video(str(video_path), _make_content())

    assert result == "video123"
    assert preflight_calls == ["log:youtube.googleapis.com", "check:youtube.googleapis.com"]
    assert request.calls == 1


def test_upload_video_blocks_when_production_safety_gate_fails(tmp_path: Path, monkeypatch):
    request = _FakeRequest([(None, {"id": "video123"})])
    uploader = youtube_uploader.YouTubeUploader()
    uploader._get_service = lambda: _FakeService(request)  # noqa: SLF001

    gate_result = ProductionSafetyGateResult(
        operation="upload",
        channel_id="default",
        job_id="",
        allowed=False,
        status="blocked",
        blocking_reason="active_deployment_lock",
        timestamp="2026-07-18T00:00:00+00:00",
        release_sha="a" * 40,
        checks=(
            ProductionSafetyCheckResult(
                check_name="active_deployment_lock",
                status="fail",
                severity="critical",
                reason_code="active_deployment_lock",
                message="An active deployment lock is present.",
                timestamp="2026-07-18T00:00:00+00:00",
                release_sha="a" * 40,
                channel_id="default",
                job_id="",
                evidence={"path": "/tmp/deploy.lock"},
            ),
        ),
        evidence={"critical_failures": 1, "warnings": 0, "check_count": 1},
    )

    def _block_upload(**_kwargs):
        raise ProductionSafetyGateBlocked(gate_result)

    monkeypatch.setattr(youtube_uploader, "ensure_production_safety_gate", _block_upload)

    with pytest.raises(ProductionSafetyGateBlocked) as exc:
        uploader.upload_video(str(_make_video_file(tmp_path)), _make_content())

    assert exc.value.gate_result.blocking_reason == "active_deployment_lock"
    assert request.calls == 0


def test_resumable_upload_retries_server_not_found(monkeypatch):
    request = _FakeRequest([
        ServerNotFoundError("Unable to find the server at youtube.googleapis.com"),
        (None, {"id": "retry123"}),
    ])
    uploader = youtube_uploader.YouTubeUploader()
    sleeps: list[int] = []
    dns_logs: list[str] = []
    monkeypatch.setattr(youtube_uploader.time, "sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(uploader, "_log_dns_resolution", lambda host: dns_logs.append(host))

    result = uploader._resumable_upload(request)  # noqa: SLF001

    assert result == "retry123"
    assert request.calls == 2
    assert sleeps == [2]
    assert dns_logs == ["youtube.googleapis.com"]


def test_resumable_upload_does_not_retry_credential_or_quota_4xx(monkeypatch):
    request = _FakeRequest([
        _make_http_error(403, b'{"error":{"errors":[{"reason":"quotaExceeded"}]}}'),
    ])
    uploader = youtube_uploader.YouTubeUploader()
    sleeps: list[int] = []
    monkeypatch.setattr(youtube_uploader.time, "sleep", lambda seconds: sleeps.append(seconds))

    with pytest.raises(HttpError):
        uploader._resumable_upload(request)  # noqa: SLF001

    assert request.calls == 1
    assert sleeps == []


def test_resumable_upload_retries_transient_5xx_http_error(monkeypatch):
    request = _FakeRequest([
        _make_http_error(503, b"service unavailable"),
        (None, {"id": "ok-after-retry"}),
    ])
    uploader = youtube_uploader.YouTubeUploader()
    sleeps: list[int] = []
    monkeypatch.setattr(youtube_uploader.time, "sleep", lambda seconds: sleeps.append(seconds))

    result = uploader._resumable_upload(request)  # noqa: SLF001

    assert result == "ok-after-retry"
    assert request.calls == 2
    assert sleeps == [2]


def test_resumable_upload_retries_408_request_timeout(monkeypatch):
    request = _FakeRequest([
        _make_http_error(408, b"request timeout"),
        (None, {"id": "ok-408-retry"}),
    ])
    uploader = youtube_uploader.YouTubeUploader()
    sleeps: list[int] = []
    monkeypatch.setattr(youtube_uploader.time, "sleep", lambda seconds: sleeps.append(seconds))

    result = uploader._resumable_upload(request)  # noqa: SLF001

    assert result == "ok-408-retry"
    assert request.calls == 2
    assert sleeps == [2]


def test_resumable_upload_retries_409_resumable_conflict(monkeypatch):
    request = _FakeRequest([
        _make_http_error(409, b'{"error":{"message":"resumable upload session conflict"}}'),
        (None, {"id": "ok-409-retry"}),
    ])
    uploader = youtube_uploader.YouTubeUploader()
    sleeps: list[int] = []
    monkeypatch.setattr(youtube_uploader.time, "sleep", lambda seconds: sleeps.append(seconds))

    result = uploader._resumable_upload(request)  # noqa: SLF001

    assert result == "ok-409-retry"
    assert request.calls == 2
    assert sleeps == [2]


def test_resumable_upload_retries_429_rate_limited(monkeypatch):
    request = _FakeRequest([
        _make_http_error(429, b'{"error":{"errors":[{"reason":"rateLimitExceeded"}]}}'),
        (None, {"id": "ok-429-retry"}),
    ])
    uploader = youtube_uploader.YouTubeUploader()
    sleeps: list[int] = []
    monkeypatch.setattr(youtube_uploader.time, "sleep", lambda seconds: sleeps.append(seconds))

    result = uploader._resumable_upload(request)  # noqa: SLF001

    assert result == "ok-429-retry"
    assert request.calls == 2
    assert sleeps == [2]


def test_resumable_upload_retries_timeout(monkeypatch):
    request = _FakeRequest([
        TimeoutError("timeout"),
        (None, {"id": "ok-timeout-retry"}),
    ])
    uploader = youtube_uploader.YouTubeUploader()
    sleeps: list[int] = []
    monkeypatch.setattr(youtube_uploader.time, "sleep", lambda seconds: sleeps.append(seconds))

    result = uploader._resumable_upload(request)  # noqa: SLF001

    assert result == "ok-timeout-retry"
    assert request.calls == 2
    assert sleeps == [2]


def test_resumable_upload_fails_when_response_has_no_video_id(monkeypatch):
    request = _FakeRequest([(None, {"kind": "youtube#video"})])
    uploader = youtube_uploader.YouTubeUploader()
    monkeypatch.setattr(youtube_uploader.time, "sleep", lambda _seconds: None)

    with pytest.raises(RuntimeError, match="upload_response_missing_id"):
        uploader._resumable_upload(request)  # noqa: SLF001

    assert request.calls == 1


def test_resumable_upload_transient_errors_retry_with_bounded_limit(monkeypatch):
    request = _FakeRequest([
        _make_http_error(503, b"service unavailable"),
        _make_http_error(503, b"service unavailable"),
        _make_http_error(503, b"service unavailable"),
        _make_http_error(503, b"service unavailable"),
    ])
    uploader = youtube_uploader.YouTubeUploader()
    sleeps: list[int] = []
    monkeypatch.setattr(youtube_uploader.time, "sleep", lambda seconds: sleeps.append(seconds))

    with pytest.raises(HttpError):
        uploader._resumable_upload(request)  # noqa: SLF001

    assert request.calls == 4
    assert sleeps == [2, 4, 8]


def test_default_language_uses_channel_config_first(monkeypatch):
    uploader = youtube_uploader.YouTubeUploader(channel_cfg=SimpleNamespace(language="en-US"))
    monkeypatch.setattr(youtube_uploader.config, "channel_language", "tr")

    assert uploader._resolve_default_language() == "en-US"  # noqa: SLF001


def test_default_language_falls_back_to_safe_default_when_invalid(monkeypatch):
    uploader = youtube_uploader.YouTubeUploader(channel_cfg=SimpleNamespace(language="***"))
    monkeypatch.setattr(youtube_uploader.config, "channel_language", "")

    assert uploader._resolve_default_language() == "en"  # noqa: SLF001


def test_ensure_dns_resolution_converts_gaierror_to_server_not_found(monkeypatch):
    uploader = youtube_uploader.YouTubeUploader()

    def fake_getaddrinfo(*args, **kwargs):
        raise youtube_uploader.socket.gaierror(8, "nodename nor servname provided, or not known")

    monkeypatch.setattr(youtube_uploader.socket, "getaddrinfo", fake_getaddrinfo)

    with pytest.raises(ServerNotFoundError):
        uploader._ensure_dns_resolution("youtube.googleapis.com")  # noqa: SLF001


def test_build_upload_description_uses_shared_validator_shorts_bypass(monkeypatch, tmp_path: Path):
    uploader = youtube_uploader.YouTubeUploader()
    content = _make_content()
    content.description = "Aciklama\n\nBOLUMLER:\n00:00 Giris\n00:10 Ornek"
    monkeypatch.setattr(uploader, "_get_video_duration_seconds", lambda _path: 30)

    description = uploader._build_upload_description(content, str(_make_video_file(tmp_path)))  # noqa: SLF001

    assert "BOLUMLER" not in description


def test_build_upload_description_reports_preflight_revalidate(monkeypatch, tmp_path: Path):
    uploader = youtube_uploader.YouTubeUploader()
    content = _make_content()
    content.description = "Aciklama\n\nBOLUMLER:\n00:00 Giris\n00:05 Hizli\n00:08 Son"

    events: list[dict] = []
    artifacts: list[dict] = []
    monkeypatch.setattr(youtube_uploader, "append_chapter_validation_event", lambda payload: events.append(payload))
    monkeypatch.setattr(
        youtube_uploader,
        "write_latest_chapter_validator_artifact",
        lambda **kwargs: artifacts.append(kwargs),
    )
    monkeypatch.setattr(uploader, "_get_video_duration_seconds", lambda _path: 130)
    monkeypatch.setattr(
        uploader,
        "_build_chapters_for_duration",
        lambda _duration: "\n".join(
            [
                "⏱️ BOLUMLER:",
                "00:00 Giris",
                "00:06 Hizli Gecis",
                "00:20 Temel Kavramlar",
                "01:05 Ornekler",
                "01:55 Abone Ol",
            ]
        ),
    )

    video_path = _make_video_file(tmp_path)
    description = uploader._build_upload_description(content, str(video_path))  # noqa: SLF001

    assert description
    assert events
    latest = events[-1]
    assert "revalidate" in latest
    assert "min_gap_ok" in latest["revalidate"]
    assert "ending_guard_pass" in latest["revalidate"]
    assert "cta_removed_count" in latest["revalidate"]
    assert artifacts
    latest_artifact = artifacts[-1]
    chapter_result = latest_artifact["chapter_result"]
    assert chapter_result["schema_version"] == "2.0"
    assert chapter_result["validator_version"] == "1.1.0"
    assert "fix_counts" in chapter_result


def test_build_upload_description_validator_exception_fail_open(monkeypatch, tmp_path: Path):
    uploader = youtube_uploader.YouTubeUploader()
    content = _make_content()
    content.description = "Aciklama"

    events: list[dict] = []
    artifacts: list[dict] = []
    monkeypatch.setattr(youtube_uploader, "append_chapter_validation_event", lambda payload: events.append(payload))
    monkeypatch.setattr(
        youtube_uploader,
        "write_latest_chapter_validator_artifact",
        lambda **kwargs: artifacts.append(kwargs),
    )
    monkeypatch.setattr(uploader, "_get_video_duration_seconds", lambda _path: 130)
    monkeypatch.setattr(
        youtube_uploader,
        "validate_and_fix_chapters",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("validator boom")),
    )

    description = uploader._build_upload_description(content, str(_make_video_file(tmp_path)))  # noqa: SLF001

    assert description
    assert events
    assert artifacts
    latest_event = events[-1]
    assert latest_event["revalidate"]["chapter_contract_pass"] is False
    assert latest_event["revalidate"]["bypass_reason"] == "validator_error"
    artifact_result = artifacts[-1]["chapter_result"]
    assert artifact_result["auto_fix_actions"] == ["validator_fail_open"]


def test_uploader_generic_fallback_tags_are_neutral():
    uploader = youtube_uploader.YouTubeUploader()
    content = VideoContent(
        title="Veri odakli karar alma",
        description="desc",
        tags=[],
        script="script",
        thumbnail_prompt="prompt",
        category_id="27",
        niche="",
    )

    tags = uploader._fallback_tags_from_content(content)  # noqa: SLF001
    lowered = [t.lower() for t in tags]
    assert "finans" not in lowered
    assert "yatirim" not in lowered


def test_uploader_finance_tags_preserve_explicit_finance_niche():
    uploader = youtube_uploader.YouTubeUploader()
    content = VideoContent(
        title="Piyasa yorumu",
        description="desc",
        tags=[],
        script="script",
        thumbnail_prompt="prompt",
        category_id="27",
        niche="finans",
    )

    tags = uploader._fallback_tags_from_content(content)  # noqa: SLF001
    lowered = [t.lower() for t in tags]
    assert "finans" in lowered


def test_upload_no_network_smoke_captures_preflight_description(monkeypatch, tmp_path: Path):
    request = _FakeRequest([(None, {"id": "video123"})])
    uploader = youtube_uploader.YouTubeUploader()
    captured_bodies: list[dict] = []

    class _CaptureVideos:
        def insert(self, **kwargs):
            captured_bodies.append(kwargs.get("body") or {})
            return request

    class _CaptureService:
        def videos(self):
            return _CaptureVideos()

    uploader._get_service = lambda: _CaptureService()  # noqa: SLF001
    uploader._resumable_upload = lambda _req: "video123"  # noqa: SLF001
    uploader._can_add_comment = False

    monkeypatch.setattr(uploader, "_log_dns_resolution", lambda _host: None)
    monkeypatch.setattr(uploader, "_ensure_dns_resolution", lambda _host: None)
    monkeypatch.setattr(uploader, "_get_video_duration_seconds", lambda _path: 130)
    monkeypatch.setattr(
        uploader,
        "_build_chapters_for_duration",
        lambda _duration: "\n".join(
            [
                "⏱️ BOLUMLER:",
                "00:00 Giris",
                "00:06 Hizli Gecis",
                "00:20 Temel Kavramlar",
                "01:05 Ornekler",
                "01:55 Abone Ol",
            ]
        ),
    )

    content = _make_content()
    content.description = "Aciklama\n\nBOLUMLER:\n00:00 Giris\n00:03 Kisa\n00:09 Outro"

    video_path = _make_video_file(tmp_path)
    video_id = uploader.upload_video(str(video_path), content)

    assert video_id == "video123"
    assert request.calls == 0
    assert len(captured_bodies) == 1
    sent_description = captured_bodies[0]["snippet"]["description"]
    assert "Abone Ol" not in sent_description
    assert "Outro" not in sent_description

    from src.chapter_validator import chapter_entries_from_description

    secs = [item["seconds"] for item in chapter_entries_from_description(sent_description)]
    assert secs == sorted(secs)
    assert all((secs[i + 1] - secs[i]) >= 10 for i in range(len(secs) - 1))
    assert secs and secs[0] == 0
