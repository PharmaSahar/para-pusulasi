from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from httplib2 import ServerNotFoundError

import src.youtube_uploader as youtube_uploader
from src.content_generator import VideoContent


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


def test_ensure_dns_resolution_converts_gaierror_to_server_not_found(monkeypatch):
    uploader = youtube_uploader.YouTubeUploader()

    def fake_getaddrinfo(*args, **kwargs):
        raise youtube_uploader.socket.gaierror(8, "nodename nor servname provided, or not known")

    monkeypatch.setattr(youtube_uploader.socket, "getaddrinfo", fake_getaddrinfo)

    with pytest.raises(ServerNotFoundError):
        uploader._ensure_dns_resolution("youtube.googleapis.com")  # noqa: SLF001
