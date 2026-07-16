from __future__ import annotations

from pathlib import Path

import src.premium_services as premium_services
import src.scheduler_utils as scheduler_utils


class _FakeResponse:
    def __init__(self, payload=None, content=b"", headers=None, status_code=200):
        self._payload = payload or {}
        self.content = content
        self.headers = headers or {}
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http_{self.status_code}")

    def json(self):
        return self._payload

    def iter_content(self, chunk_size=65536):
        _ = chunk_size
        if self.content:
            yield self.content


def test_scheduler_startup_banner_is_neutral_and_call_shape_unchanged(monkeypatch):
    captured = []

    monkeypatch.setattr(scheduler_utils, "send_telegram", lambda message: captured.append(message))
    monkeypatch.setattr(scheduler_utils, "get_free_disk_gb", lambda: 42.3)

    scheduler_utils.notify_startup(5)

    assert len(captured) == 1
    msg = captured[0]
    assert "Parapusulasi Scheduler Basladi" in msg
    assert "5 aktif kanal" in msg
    lowered = msg.lower()
    for token in ("para pusulasi", "finance", "finans", "investment", "borsa", "crypto", "kripto"):
        assert token not in lowered


def test_generate_dalle_thumbnail_generic_prompt_is_neutral_and_backward_compatible(monkeypatch, tmp_path: Path):
    calls = {"post": [], "get": []}

    def fake_env(key: str) -> str:
        values = {
            "OPENAI_API_KEY": "key",
            "OPENAI_IMAGE_ENABLED": "true",
        }
        return values.get(key, "")

    def fake_post(url, headers=None, json=None, timeout=None):
        calls["post"].append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return _FakeResponse(payload={"data": [{"url": "https://example.com/image.jpg"}]})

    def fake_get(url, timeout=None, stream=False):
        calls["get"].append({"url": url, "timeout": timeout, "stream": stream})
        return _FakeResponse(content=b"image-bytes", headers={"Content-Type": "image/jpeg"})

    monkeypatch.setattr(premium_services, "_get_env", fake_env)
    monkeypatch.setattr(premium_services.requests, "post", fake_post)
    monkeypatch.setattr(premium_services.requests, "get", fake_get)

    out = tmp_path / "thumb.jpg"
    result = premium_services.generate_dalle_thumbnail("healthy routine", str(out))

    assert result == str(out)
    assert out.exists()
    assert len(calls["post"]) == 1
    prompt = calls["post"][0]["json"]["prompt"]
    assert "educational channel" in prompt
    assert "Turkish educational YouTube aesthetic" in prompt
    assert "finance channel" not in prompt


def test_generate_dalle_thumbnail_finance_context_preserves_finance_style(monkeypatch, tmp_path: Path):
    captured = {}

    def fake_env(key: str) -> str:
        values = {
            "OPENAI_API_KEY": "key",
            "OPENAI_IMAGE_ENABLED": "true",
        }
        return values.get(key, "")

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["prompt"] = json["prompt"]
        return _FakeResponse(payload={"data": [{"url": "https://example.com/image.jpg"}]})

    def fake_get(url, timeout=None, stream=False):
        return _FakeResponse(content=b"image-bytes", headers={"Content-Type": "image/jpeg"})

    monkeypatch.setattr(premium_services, "_get_env", fake_env)
    monkeypatch.setattr(premium_services.requests, "post", fake_post)
    monkeypatch.setattr(premium_services.requests, "get", fake_get)

    out = tmp_path / "thumb_finance.jpg"
    premium_services.generate_dalle_thumbnail("market trend", str(out), niche="kisisel_finans")

    assert "finance channel" in captured["prompt"]
    assert "Turkish finance YouTube aesthetic" in captured["prompt"]


def test_generate_dalle_thumbnail_preserves_custom_style_context(monkeypatch, tmp_path: Path):
    captured = {}

    def fake_env(key: str) -> str:
        values = {
            "OPENAI_API_KEY": "key",
            "OPENAI_IMAGE_ENABLED": "true",
        }
        return values.get(key, "")

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["prompt"] = json["prompt"]
        return _FakeResponse(payload={"data": [{"url": "https://example.com/image.jpg"}]})

    def fake_get(url, timeout=None, stream=False):
        return _FakeResponse(content=b"image-bytes", headers={"Content-Type": "image/jpeg"})

    monkeypatch.setattr(premium_services, "_get_env", fake_env)
    monkeypatch.setattr(premium_services.requests, "post", fake_post)
    monkeypatch.setattr(premium_services.requests, "get", fake_get)

    out = tmp_path / "thumb_style.jpg"
    premium_services.generate_dalle_thumbnail(
        "minimal concept",
        str(out),
        style_context="cyber neon studio",
    )

    assert "Style context: cyber neon studio." in captured["prompt"]


def test_generate_dalle_thumbnail_error_behavior_unchanged_returns_none(monkeypatch, tmp_path: Path):
    def fake_env(key: str) -> str:
        values = {
            "OPENAI_API_KEY": "key",
            "OPENAI_IMAGE_ENABLED": "true",
        }
        return values.get(key, "")

    class _FailResponse(_FakeResponse):
        def raise_for_status(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(premium_services, "_get_env", fake_env)
    monkeypatch.setattr(premium_services.requests, "post", lambda *args, **kwargs: _FailResponse())

    out = tmp_path / "thumb_fail.jpg"
    result = premium_services.generate_dalle_thumbnail("topic", str(out))

    assert result is None


def test_generate_heygen_video_generic_title_fallback_is_neutral(monkeypatch, tmp_path: Path):
    post_calls = []

    def fake_env(key: str) -> str:
        values = {
            "HEYGEN_API_KEY": "key",
            "HEYGEN_AVATAR_ID": "avatar_1",
        }
        return values.get(key, "")

    def fake_post(url, headers=None, json=None, timeout=None):
        post_calls.append({"url": url, "json": json})
        return _FakeResponse(payload={"data": {"video_id": "vid_123"}})

    def fake_get(url, headers=None, timeout=None, stream=False):
        if "video_status.get" in url:
            return _FakeResponse(payload={"data": {"status": "completed", "video_url": "https://example.com/video.mp4"}})
        return _FakeResponse(content=b"video-bytes", headers={"Content-Type": "video/mp4"})

    monkeypatch.setattr(premium_services, "_get_env", fake_env)
    monkeypatch.setattr(premium_services.requests, "post", fake_post)
    monkeypatch.setattr(premium_services.requests, "get", fake_get)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    out = tmp_path / "heygen.mp4"
    result = premium_services.generate_heygen_video("script", "", "", str(out))

    assert result == str(out)
    assert out.exists()
    assert post_calls[0]["json"]["title"] == "Parapusulasi Video"


def test_generate_heygen_video_preserves_explicit_custom_title(monkeypatch, tmp_path: Path):
    post_calls = []

    def fake_env(key: str) -> str:
        values = {
            "HEYGEN_API_KEY": "key",
            "HEYGEN_AVATAR_ID": "avatar_1",
        }
        return values.get(key, "")

    def fake_post(url, headers=None, json=None, timeout=None):
        post_calls.append({"url": url, "json": json})
        return _FakeResponse(payload={"data": {"video_id": "vid_123"}})

    def fake_get(url, headers=None, timeout=None, stream=False):
        if "video_status.get" in url:
            return _FakeResponse(payload={"data": {"status": "completed", "video_url": "https://example.com/video.mp4"}})
        return _FakeResponse(content=b"video-bytes", headers={"Content-Type": "video/mp4"})

    monkeypatch.setattr(premium_services, "_get_env", fake_env)
    monkeypatch.setattr(premium_services.requests, "post", fake_post)
    monkeypatch.setattr(premium_services.requests, "get", fake_get)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    out = tmp_path / "heygen_custom.mp4"
    premium_services.generate_heygen_video(
        "script",
        "",
        "",
        str(out),
        title="Finance Capsule 2026",
    )

    assert post_calls[0]["json"]["title"] == "Finance Capsule 2026"
