"""Provider factory for currently implemented fact providers.

This module instantiates provider objects from the existing provider catalog
without wiring them into the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass

from .fact_bundle_providers import FactDataProvider
from .fact_provider_registry import REGISTERED_FACT_PROVIDERS, RegisteredFactProvider, get_registered_fact_provider
from .fact_sources import TrustedFactProvider


@dataclass(frozen=True, slots=True)
class FactProviderFactory:
    """Create fresh provider instances from the provider catalog."""

    def create(self, provider_name: str):
        entry = get_registered_fact_provider(provider_name)
        return self._instantiate(entry)

    def create_all(self) -> tuple[object, ...]:
        return tuple(self._instantiate(entry) for entry in REGISTERED_FACT_PROVIDERS)

    def names(self) -> tuple[str, ...]:
        return tuple(entry.name for entry in REGISTERED_FACT_PROVIDERS)

    def _instantiate(self, entry: RegisteredFactProvider):
        provider = entry.provider
        if isinstance(provider, (FactDataProvider, TrustedFactProvider)):
            return provider.__class__()
        raise TypeError(f"unsupported provider interface: {entry.name}")


def build_fact_provider_factory() -> FactProviderFactory:
    return FactProviderFactory()


__all__ = ["FactProviderFactory", "build_fact_provider_factory"]
