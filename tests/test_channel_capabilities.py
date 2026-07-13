from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.youtube_uploader as youtube_uploader
from src.channel_capabilities import (
    CachedCapabilityProvider,
    CapabilityState,
    ChannelCapabilityProfile,
    ChannelCapabilityResolver,
    StaticRegistryCapabilityProvider,
    capability_gating_enabled,
)
from src.content_generator import VideoContent


def test_manual_display_name_mapping_targets_existing_canonical_ids() -> None:
    payload = json.loads(Path("channels/channel_registry.json").read_text(encoding="utf-8"))
    channels = dict(payload.get("channels") or {})

    expected_ids = {
        "para_pusulasi",
        "kariyer_pusulasi",
        "girisim_okulu",
        "borsa_akademi",
        "kripto_rehber",
    }

    assert expected_ids.issubset(set(channels.keys()))


def test_static_registry_contains_expected_initial_capabilities() -> None:
    provider = StaticRegistryCapabilityProvider(Path("config/channel_capability_registry.json"))

    full = provider.get_channel_capabilities("para_pusulasi")
    assert full is not None
    assert full.standard_features is CapabilityState.ENABLED
    assert full.intermediate_features is CapabilityState.ENABLED
    assert full.advanced_features is CapabilityState.ENABLED

    partial = provider.get_channel_capabilities("borsa_akademi")
    assert partial is not None
    assert partial.standard_features is CapabilityState.ENABLED
    assert partial.intermediate_features is CapabilityState.ENABLED
    assert partial.advanced_features is CapabilityState.PENDING


def test_missing_known_channel_uses_safe_standard_only_default() -> None:
    provider = StaticRegistryCapabilityProvider(Path("config/channel_capability_registry.json"))
    profile = provider.get_channel_capabilities("saglik_pusulasi")

    assert profile is not None
    assert profile.standard_features is CapabilityState.ENABLED
    assert profile.intermediate_features is CapabilityState.DISABLED
    assert profile.advanced_features is CapabilityState.DISABLED


def test_unknown_channel_resolves_fail_safe() -> None:
    resolver = ChannelCapabilityResolver(
        live_provider=StaticRegistryCapabilityProvider(Path("/tmp/does-not-exist-live.json")),
        cache_provider=CachedCapabilityProvider(Path("/tmp/does-not-exist-cache.json")),
        static_provider=StaticRegistryCapabilityProvider(Path("/tmp/does-not-exist-static.json")),
    )

    resolution = resolver.resolve("unknown_channel_xyz")

    assert resolution.profile.standard_features is CapabilityState.UNKNOWN
    assert resolution.profile.intermediate_features is CapabilityState.DISABLED
    assert resolution.profile.advanced_features is CapabilityState.DISABLED
    assert resolution.source == "safe_default:unknown_channel"


def test_provider_priority_live_then_cache_then_static(tmp_path: Path) -> None:
    live_path = tmp_path / "live.json"
    cache_path = tmp_path / "cache.json"
    static_path = tmp_path / "static.json"

    live_path.write_text(
        json.dumps(
            {
                "channels": {
                    "para_pusulasi": {
                        "standard_features": "ENABLED",
                        "intermediate_features": "ENABLED",
                        "advanced_features": "ENABLED",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    cache_path.write_text(
        json.dumps(
            {
                "channels": {
                    "para_pusulasi": {
                        "standard_features": "ENABLED",
                        "intermediate_features": "DISABLED",
                        "advanced_features": "DISABLED",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    static_path.write_text(
        json.dumps(
            {
                "channels": {
                    "para_pusulasi": {
                        "standard_features": "ENABLED",
                        "intermediate_features": "DISABLED",
                        "advanced_features": "PENDING",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    resolver = ChannelCapabilityResolver(
        live_provider=StaticRegistryCapabilityProvider(live_path),
        cache_provider=CachedCapabilityProvider(cache_path),
        static_provider=StaticRegistryCapabilityProvider(static_path),
    )

    resolution = resolver.resolve("para_pusulasi")

    assert resolution.source == "static_registry"
    assert resolution.profile.advanced_features is CapabilityState.ENABLED


def test_feature_helpers_map_to_expected_tiers() -> None:
    intermediate_only = ChannelCapabilityProfile(
        channel_id="test",
        standard_features=CapabilityState.ENABLED,
        intermediate_features=CapabilityState.ENABLED,
        advanced_features=CapabilityState.DISABLED,
        source="test",
    )
    assert intermediate_only.supports_custom_thumbnails() is True
    assert intermediate_only.supports_long_form_over_15_minutes() is True
    assert intermediate_only.supports_live_streaming() is True
    assert intermediate_only.supports_external_links() is False
    assert intermediate_only.supports_increased_upload_limits() is False
    assert intermediate_only.supports_feature("not_a_real_feature") is False


class _BrokenProvider:
    provider_name = "broken"

    def get_channel_capabilities(self, channel_id: str):
        _ = channel_id
        raise RuntimeError("provider unavailable")


class _CaptureVideos:
    def __init__(self):
        self.last_insert_kwargs = None

    def insert(self, **kwargs):
        self.last_insert_kwargs = kwargs
        return object()


class _CaptureService:
    def __init__(self):
        self._videos = _CaptureVideos()

    def videos(self):
        return self._videos


def _make_video_file(tmp_path: Path, name: str = "video.mp4") -> Path:
    video_path = tmp_path / name
    video_path.write_bytes(b"0" * 100_001)
    return video_path


def _make_content() -> VideoContent:
    return VideoContent(
        title="Capability test",
        description="desc",
        tags=["test"],
        script="script",
        thumbnail_prompt="prompt",
        category_id="27",
        niche="teknoloji",
    )


def test_provider_failure_falls_back_to_next_provider(tmp_path: Path) -> None:
    static_path = tmp_path / "static.json"
    static_path.write_text(
        json.dumps(
            {
                "channels": {
                    "para_pusulasi": {
                        "standard_features": "ENABLED",
                        "intermediate_features": "ENABLED",
                        "advanced_features": "PENDING",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    resolver = ChannelCapabilityResolver(
        live_provider=_BrokenProvider(),
        cache_provider=_BrokenProvider(),
        static_provider=StaticRegistryCapabilityProvider(static_path),
    )

    resolution = resolver.resolve("para_pusulasi")
    assert resolution.source == "static_registry"
    assert resolution.profile.advanced_features is CapabilityState.PENDING


def test_invalid_registry_values_fail_closed(tmp_path: Path) -> None:
    registry_path = tmp_path / "invalid_states.json"
    registry_path.write_text(
        json.dumps(
            {
                "channels": {
                    "para_pusulasi": {
                        "standard_features": "maybe",
                        "intermediate_features": "ENABLED",
                        "advanced_features": "ENABLED",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    profile = StaticRegistryCapabilityProvider(registry_path).get_channel_capabilities("para_pusulasi")

    assert profile is not None
    assert profile.standard_features is CapabilityState.UNKNOWN
    assert profile.intermediate_features is CapabilityState.DISABLED
    assert profile.advanced_features is CapabilityState.DISABLED
    assert profile.supports_custom_thumbnails() is False
    assert profile.supports_external_links() is False


def test_advanced_enabled_with_intermediate_disabled_is_normalized_fail_closed(tmp_path: Path) -> None:
    registry_path = tmp_path / "inconsistent.json"
    registry_path.write_text(
        json.dumps(
            {
                "channels": {
                    "borsa_akademi": {
                        "standard_features": "ENABLED",
                        "intermediate_features": "DISABLED",
                        "advanced_features": "ENABLED",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    profile = StaticRegistryCapabilityProvider(registry_path).get_channel_capabilities("borsa_akademi")
    assert profile is not None
    assert profile.intermediate_features is CapabilityState.DISABLED
    assert profile.advanced_features is CapabilityState.DISABLED


def test_capability_gating_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CHANNEL_CAPABILITY_GATING_ENABLED", raising=False)
    assert capability_gating_enabled() is False


def test_uploader_behavior_unchanged_when_gating_flag_absent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CHANNEL_CAPABILITY_GATING_ENABLED", raising=False)
    uploader = youtube_uploader.YouTubeUploader(channel_cfg=SimpleNamespace(channel_id="para_pusulasi"))
    capture_service = _CaptureService()

    monkeypatch.setattr(uploader, "_log_dns_resolution", lambda _host: None)
    monkeypatch.setattr(uploader, "_ensure_dns_resolution", lambda _host: None)
    monkeypatch.setattr(uploader, "_get_service", lambda: capture_service)
    monkeypatch.setattr(uploader, "_resumable_upload", lambda _request: "video123")
    monkeypatch.setattr(
        uploader,
        "_get_video_duration_seconds",
        lambda _path: (_ for _ in ()).throw(AssertionError("duration check must not run when gating disabled")),
    )
    monkeypatch.setattr(
        uploader,
        "_strip_external_links",
        lambda _text: (_ for _ in ()).throw(AssertionError("link stripping must not run when gating disabled")),
    )
    monkeypatch.setattr(uploader, "_build_upload_description", lambda **_kwargs: "Visit https://example.com now")

    thumb = tmp_path / "thumb.jpg"
    thumb.write_bytes(b"thumb")
    uploaded_thumbs = []
    monkeypatch.setattr(uploader, "_upload_thumbnail", lambda _video_id, _path: uploaded_thumbs.append(True))
    uploader._can_add_comment = False

    result = uploader.upload_video(str(_make_video_file(tmp_path)), _make_content(), thumbnail_path=str(thumb))

    assert result == "video123"
    assert uploaded_thumbs == [True]
    assert "https://example.com" in capture_service._videos.last_insert_kwargs["body"]["snippet"]["description"]


def test_long_video_is_blocked_only_when_gating_enabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHANNEL_CAPABILITY_GATING_ENABLED", "true")
    uploader = youtube_uploader.YouTubeUploader(channel_cfg=SimpleNamespace(channel_id="borsa_akademi"))
    monkeypatch.setattr(uploader, "_log_dns_resolution", lambda _host: None)
    monkeypatch.setattr(uploader, "_ensure_dns_resolution", lambda _host: None)
    monkeypatch.setattr(uploader, "_get_video_duration_seconds", lambda _path: 16 * 60)
    uploader._capability_profile = ChannelCapabilityProfile(
        channel_id="borsa_akademi",
        standard_features=CapabilityState.ENABLED,
        intermediate_features=CapabilityState.DISABLED,
        advanced_features=CapabilityState.DISABLED,
        source="test",
    )

    with pytest.raises(RuntimeError, match="capability_guard_long_form_over_15m_not_allowed"):
        uploader.upload_video(str(_make_video_file(tmp_path)), _make_content())


def test_custom_thumbnail_is_gated_when_explicitly_enabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHANNEL_CAPABILITY_GATING_ENABLED", "true")
    uploader = youtube_uploader.YouTubeUploader(channel_cfg=SimpleNamespace(channel_id="borsa_akademi"))
    capture_service = _CaptureService()

    monkeypatch.setattr(uploader, "_log_dns_resolution", lambda _host: None)
    monkeypatch.setattr(uploader, "_ensure_dns_resolution", lambda _host: None)
    monkeypatch.setattr(uploader, "_get_service", lambda: capture_service)
    monkeypatch.setattr(uploader, "_resumable_upload", lambda _request: "video123")
    monkeypatch.setattr(uploader, "_get_video_duration_seconds", lambda _path: 120)
    monkeypatch.setattr(uploader, "_build_upload_description", lambda **_kwargs: "description")
    uploader._capability_profile = ChannelCapabilityProfile(
        channel_id="borsa_akademi",
        standard_features=CapabilityState.ENABLED,
        intermediate_features=CapabilityState.DISABLED,
        advanced_features=CapabilityState.DISABLED,
        source="test",
    )

    thumb = tmp_path / "thumb.jpg"
    thumb.write_bytes(b"thumb")
    uploaded_thumbs = []
    monkeypatch.setattr(uploader, "_upload_thumbnail", lambda _video_id, _path: uploaded_thumbs.append(True))
    uploader._can_add_comment = False

    result = uploader.upload_video(str(_make_video_file(tmp_path)), _make_content(), thumbnail_path=str(thumb))

    assert result == "video123"
    assert uploaded_thumbs == []


def test_external_link_stripping_applies_only_when_gating_enabled_and_advanced_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CHANNEL_CAPABILITY_GATING_ENABLED", "true")
    uploader = youtube_uploader.YouTubeUploader(channel_cfg=SimpleNamespace(channel_id="borsa_akademi"))
    capture_service = _CaptureService()

    monkeypatch.setattr(uploader, "_log_dns_resolution", lambda _host: None)
    monkeypatch.setattr(uploader, "_ensure_dns_resolution", lambda _host: None)
    monkeypatch.setattr(uploader, "_get_service", lambda: capture_service)
    monkeypatch.setattr(uploader, "_resumable_upload", lambda _request: "video123")
    monkeypatch.setattr(uploader, "_get_video_duration_seconds", lambda _path: 120)
    monkeypatch.setattr(uploader, "_build_upload_description", lambda **_kwargs: "Use https://example.com and https://example.org")
    uploader._can_add_comment = False

    uploader._capability_profile = ChannelCapabilityProfile(
        channel_id="borsa_akademi",
        standard_features=CapabilityState.ENABLED,
        intermediate_features=CapabilityState.ENABLED,
        advanced_features=CapabilityState.DISABLED,
        source="test",
    )
    uploader.upload_video(str(_make_video_file(tmp_path, "a.mp4")), _make_content())
    blocked_description = capture_service._videos.last_insert_kwargs["body"]["snippet"]["description"]
    assert "http://" not in blocked_description
    assert "https://" not in blocked_description

    uploader._capability_profile = ChannelCapabilityProfile(
        channel_id="para_pusulasi",
        standard_features=CapabilityState.ENABLED,
        intermediate_features=CapabilityState.ENABLED,
        advanced_features=CapabilityState.ENABLED,
        source="test",
    )
    uploader.upload_video(str(_make_video_file(tmp_path, "b.mp4")), _make_content())
    allowed_description = capture_service._videos.last_insert_kwargs["body"]["snippet"]["description"]
    assert "https://example.com" in allowed_description
