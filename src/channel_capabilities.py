from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)

CHANNEL_REGISTRY_PATH = Path("channels/channel_registry.json")
DEFAULT_CAPABILITY_REGISTRY_PATH = Path("config/channel_capability_registry.json")
DEFAULT_CAPABILITY_CACHE_PATH = Path("output/state/channel_capability_cache.json")


class CapabilityState(str, Enum):
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"
    PENDING = "PENDING"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def from_raw(cls, value: object) -> "CapabilityState":
        if isinstance(value, cls):
            return value
        text = str(value or "").strip().upper()
        if text in cls._value2member_map_:
            return cls(text)
        return cls.UNKNOWN


class ChannelFeature(str, Enum):
    CUSTOM_THUMBNAILS = "custom_thumbnails"
    LONG_FORM_OVER_15_MINUTES = "long_form_over_15_minutes"
    LIVE_STREAMING = "live_streaming"
    EXTERNAL_LINKS = "external_links"
    INCREASED_UPLOAD_LIMITS = "increased_upload_limits"


FEATURE_CAPABILITY_REQUIREMENTS: dict[ChannelFeature, str] = {
    ChannelFeature.CUSTOM_THUMBNAILS: "intermediate_features",
    ChannelFeature.LONG_FORM_OVER_15_MINUTES: "intermediate_features",
    ChannelFeature.LIVE_STREAMING: "intermediate_features",
    ChannelFeature.EXTERNAL_LINKS: "advanced_features",
    ChannelFeature.INCREASED_UPLOAD_LIMITS: "advanced_features",
}


@dataclass(frozen=True)
class ChannelCapabilityProfile:
    channel_id: str
    standard_features: CapabilityState
    intermediate_features: CapabilityState
    advanced_features: CapabilityState
    source: str = "unknown"

    def supports_standard_features(self) -> bool:
        return self.standard_features is CapabilityState.ENABLED

    def supports_intermediate_features(self) -> bool:
        return self.intermediate_features is CapabilityState.ENABLED

    def supports_advanced_features(self) -> bool:
        return self.advanced_features is CapabilityState.ENABLED

    def supports_feature(self, feature: ChannelFeature | str) -> bool:
        try:
            key = feature if isinstance(feature, ChannelFeature) else ChannelFeature(str(feature))
        except Exception:
            return False
        required_capability = FEATURE_CAPABILITY_REQUIREMENTS.get(key)
        if required_capability == "standard_features":
            return self.supports_standard_features()
        if required_capability == "intermediate_features":
            return self.supports_intermediate_features()
        if required_capability == "advanced_features":
            return self.supports_advanced_features()
        return False

    def supports_custom_thumbnails(self) -> bool:
        return self.supports_feature(ChannelFeature.CUSTOM_THUMBNAILS)

    def supports_long_form_over_15_minutes(self) -> bool:
        return self.supports_feature(ChannelFeature.LONG_FORM_OVER_15_MINUTES)

    def supports_live_streaming(self) -> bool:
        return self.supports_feature(ChannelFeature.LIVE_STREAMING)

    def supports_external_links(self) -> bool:
        return self.supports_feature(ChannelFeature.EXTERNAL_LINKS)

    def supports_increased_upload_limits(self) -> bool:
        return self.supports_feature(ChannelFeature.INCREASED_UPLOAD_LIMITS)


@dataclass(frozen=True)
class CapabilityResolution:
    profile: ChannelCapabilityProfile
    source: str


class ChannelCapabilityProvider(Protocol):
    provider_name: str

    def get_channel_capabilities(self, channel_id: str) -> ChannelCapabilityProfile | None:
        ...


def _load_json(path: Path) -> dict:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _build_profile(channel_id: str, payload: dict, *, source: str) -> ChannelCapabilityProfile:
    standard = CapabilityState.from_raw(payload.get("standard_features"))
    intermediate = CapabilityState.from_raw(payload.get("intermediate_features"))
    advanced = CapabilityState.from_raw(payload.get("advanced_features"))

    # Fail closed on tier inconsistencies. Higher tiers cannot be enabled when lower tiers are disabled/unknown/pending.
    if standard is not CapabilityState.ENABLED:
        intermediate = CapabilityState.DISABLED
        advanced = CapabilityState.DISABLED
    elif intermediate is not CapabilityState.ENABLED and advanced is CapabilityState.ENABLED:
        advanced = CapabilityState.DISABLED

    return ChannelCapabilityProfile(
        channel_id=str(channel_id or "").strip(),
        standard_features=standard,
        intermediate_features=intermediate,
        advanced_features=advanced,
        source=source,
    )


def _normalize_profile(profile: ChannelCapabilityProfile, *, fallback_channel_id: str = "") -> ChannelCapabilityProfile:
    channel_id = str(getattr(profile, "channel_id", "") or "").strip() or str(fallback_channel_id or "").strip()
    payload = {
        "standard_features": getattr(profile, "standard_features", CapabilityState.UNKNOWN),
        "intermediate_features": getattr(profile, "intermediate_features", CapabilityState.UNKNOWN),
        "advanced_features": getattr(profile, "advanced_features", CapabilityState.UNKNOWN),
    }
    source = str(getattr(profile, "source", "") or "normalized")
    return _build_profile(channel_id, payload, source=source)


def _known_channel_ids(path: Path = CHANNEL_REGISTRY_PATH) -> set[str]:
    payload = _load_json(path)
    channels = payload.get("channels") if isinstance(payload, dict) else None
    if not isinstance(channels, dict):
        return set()
    return {str(key).strip() for key in channels.keys() if str(key).strip()}


class StaticRegistryCapabilityProvider:
    provider_name = "static_registry"

    def __init__(self, registry_path: Path = DEFAULT_CAPABILITY_REGISTRY_PATH):
        self.registry_path = Path(registry_path)

    def get_channel_capabilities(self, channel_id: str) -> ChannelCapabilityProfile | None:
        payload = _load_json(self.registry_path)
        channels = payload.get("channels") if isinstance(payload, dict) else None
        if not isinstance(channels, dict):
            return None

        raw = channels.get(channel_id)
        if isinstance(raw, dict):
            return _build_profile(channel_id, raw, source=self.provider_name)

        defaults = payload.get("defaults_for_known_channels") if isinstance(payload, dict) else None
        known_default = defaults if isinstance(defaults, dict) else {}
        if channel_id in _known_channel_ids() and known_default:
            return _build_profile(channel_id, known_default, source=f"{self.provider_name}:defaults")

        return None


class CachedCapabilityProvider:
    provider_name = "cached_last_known"

    def __init__(self, cache_path: Path = DEFAULT_CAPABILITY_CACHE_PATH):
        self.cache_path = Path(cache_path)

    def get_channel_capabilities(self, channel_id: str) -> ChannelCapabilityProfile | None:
        payload = _load_json(self.cache_path)
        channels = payload.get("channels") if isinstance(payload, dict) else None
        if not isinstance(channels, dict):
            return None
        raw = channels.get(channel_id)
        if not isinstance(raw, dict):
            return None
        return _build_profile(channel_id, raw, source=self.provider_name)


class NullLiveCapabilityProvider:
    provider_name = "live_provider_unavailable"

    def get_channel_capabilities(self, channel_id: str) -> ChannelCapabilityProfile | None:
        _ = channel_id
        return None


class ChannelCapabilityResolver:
    """Resolve channel capabilities with deterministic, fail-safe priority.

    Priority:
    1) Live provider (verified runtime provider)
    2) Cached last known profile
    3) Static registry
    4) Safe defaults
    """

    def __init__(
        self,
        *,
        live_provider: ChannelCapabilityProvider | None = None,
        cache_provider: ChannelCapabilityProvider | None = None,
        static_provider: ChannelCapabilityProvider | None = None,
    ):
        self.live_provider = live_provider or NullLiveCapabilityProvider()
        self.cache_provider = cache_provider or CachedCapabilityProvider()
        self.static_provider = static_provider or StaticRegistryCapabilityProvider()

    def resolve(self, channel_id: str) -> CapabilityResolution:
        cid = str(channel_id or "").strip()

        for provider in (self.live_provider, self.cache_provider, self.static_provider):
            try:
                profile = provider.get_channel_capabilities(cid)
            except Exception as exc:
                logger.warning("Capability provider failed: provider=%s error=%s", getattr(provider, "provider_name", "unknown"), exc)
                continue
            if isinstance(profile, ChannelCapabilityProfile):
                normalized = _normalize_profile(profile, fallback_channel_id=cid)
                return CapabilityResolution(profile=normalized, source=normalized.source)

        fallback = self._safe_default_profile(cid)
        return CapabilityResolution(profile=fallback, source=fallback.source)

    def _safe_default_profile(self, channel_id: str) -> ChannelCapabilityProfile:
        known = channel_id in _known_channel_ids()
        if known:
            # Preserve baseline publish capability for configured channels.
            return ChannelCapabilityProfile(
                channel_id=channel_id,
                standard_features=CapabilityState.ENABLED,
                intermediate_features=CapabilityState.DISABLED,
                advanced_features=CapabilityState.DISABLED,
                source="safe_default:known_channel",
            )
        return ChannelCapabilityProfile(
            channel_id=channel_id,
            standard_features=CapabilityState.UNKNOWN,
            intermediate_features=CapabilityState.DISABLED,
            advanced_features=CapabilityState.DISABLED,
            source="safe_default:unknown_channel",
        )


def _is_enabled(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def capability_gating_enabled() -> bool:
    """Phase 1 remains opt-in to avoid changing production behavior by default."""
    return _is_enabled(os.getenv("CHANNEL_CAPABILITY_GATING_ENABLED", "false"))


_DEFAULT_RESOLVER: ChannelCapabilityResolver | None = None


def get_default_channel_capability_resolver() -> ChannelCapabilityResolver:
    global _DEFAULT_RESOLVER
    if _DEFAULT_RESOLVER is None:
        _DEFAULT_RESOLVER = ChannelCapabilityResolver()
    return _DEFAULT_RESOLVER
