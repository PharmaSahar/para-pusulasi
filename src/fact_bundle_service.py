"""High-level service entry point for assembling fact providers.

This service is a thin wrapper over the composition layer and does not wire
into the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterable

from .fact_provider_composition import FactProviderComposition, build_fact_provider_composition


@dataclass(frozen=True, slots=True)
class FactBundleService:
    """Expose a single entry point over the provider composition layer."""

    composition: FactProviderComposition

    def get_all_providers(self) -> tuple[object, ...]:
        return self.composition.compose_all()

    def get_providers(self, provider_names: Iterable[str]) -> tuple[object, ...]:
        return self.composition.compose_by_names(provider_names)

    def get_provider(self, provider_name: str) -> object:
        return self.composition.compose(provider_name)


def build_fact_bundle_service() -> FactBundleService:
    return FactBundleService(composition=build_fact_provider_composition())


__all__ = ["FactBundleService", "build_fact_bundle_service"]
