"""Provider catalog for currently implemented fact providers.

This module only lists available providers. It does not wire them into the
pipeline or perform any live fetches.
"""

from __future__ import annotations

from dataclasses import dataclass

from .calendar_fact_provider import LiveCalendarFactProvider
from .commodity_fact_provider import LiveCommodityFactProvider
from .crypto_fact_provider import LiveCryptoFactProvider
from .fact_bundle_providers import FactDataProvider, ProviderRegistry
from .fact_sources import LiveFXProvider, TrustedFactProvider
from .macro_fact_provider import LiveMacroFactProvider
from .market_fact_provider import LiveMarketFactProvider
from .news_fact_provider import LiveNewsFactProvider


@dataclass(frozen=True, slots=True)
class RegisteredFactProvider:
    """A catalog entry for a currently implemented fact provider."""

    name: str
    provider: object
    interface: str
    priority: int


REGISTERED_FACT_PROVIDERS: tuple[RegisteredFactProvider, ...] = (
    RegisteredFactProvider(name="FX", provider=LiveFXProvider(), interface="TrustedFactProvider", priority=100),
    RegisteredFactProvider(name="market", provider=LiveMarketFactProvider(), interface="FactDataProvider", priority=90),
    RegisteredFactProvider(name="crypto", provider=LiveCryptoFactProvider(), interface="FactDataProvider", priority=80),
    RegisteredFactProvider(name="commodity", provider=LiveCommodityFactProvider(), interface="FactDataProvider", priority=70),
    RegisteredFactProvider(name="macro", provider=LiveMacroFactProvider(), interface="FactDataProvider", priority=60),
    RegisteredFactProvider(name="calendar", provider=LiveCalendarFactProvider(), interface="FactDataProvider", priority=50),
    RegisteredFactProvider(name="news", provider=LiveNewsFactProvider(), interface="FactDataProvider", priority=40),
)


def list_registered_fact_provider_names() -> tuple[str, ...]:
    return tuple(entry.name for entry in REGISTERED_FACT_PROVIDERS)


def list_registered_fact_provider_priorities() -> tuple[int, ...]:
    return tuple(entry.priority for entry in REGISTERED_FACT_PROVIDERS)


def build_fact_data_provider_registry() -> ProviderRegistry:
    """Build a ProviderRegistry for providers that implement the shared provider interface."""

    registry = ProviderRegistry()
    for entry in REGISTERED_FACT_PROVIDERS:
        provider = entry.provider
        if isinstance(provider, FactDataProvider):
            registry.register(provider)
    return registry


def get_registered_fact_provider(name: str) -> RegisteredFactProvider:
    normalized = name.strip().lower()
    for entry in REGISTERED_FACT_PROVIDERS:
        if entry.name.lower() == normalized:
            return entry
    raise KeyError(name)


__all__ = [
    "REGISTERED_FACT_PROVIDERS",
    "RegisteredFactProvider",
    "build_fact_data_provider_registry",
    "get_registered_fact_provider",
    "list_registered_fact_provider_names",
    "list_registered_fact_provider_priorities",
]
