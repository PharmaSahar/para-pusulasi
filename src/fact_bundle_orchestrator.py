"""Thin orchestrator over the Fact Bundle service.

This module aggregates provider instances returned by the service into a
single in-memory result without wiring into the pipeline.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .fact_bundle_service import FactBundleService, build_fact_bundle_service


@dataclass(frozen=True, slots=True)
class FactBundleOrchestrationResult:
    """In-memory orchestration result for assembled fact providers."""

    providers: tuple[object, ...]
    provider_names: tuple[str, ...]

    @property
    def provider_count(self) -> int:
        return len(self.providers)


@dataclass(frozen=True, slots=True)
class FactBundleOrchestrator:
    """Aggregate provider outputs from the Fact Bundle service."""

    service: FactBundleService

    def orchestrate_all(self) -> FactBundleOrchestrationResult:
        providers = self.service.get_all_providers()
        return self._build_result(providers)

    def orchestrate_by_names(self, provider_names: Iterable[str]) -> FactBundleOrchestrationResult:
        providers = self.service.get_providers(provider_names)
        return self._build_result(providers)

    def orchestrate(self, provider_name: str) -> FactBundleOrchestrationResult:
        provider = self.service.get_provider(provider_name)
        return self._build_result((provider,))

    def _build_result(self, providers: tuple[object, ...]) -> FactBundleOrchestrationResult:
        provider_names = tuple(provider.__class__.__name__ for provider in providers)
        return FactBundleOrchestrationResult(providers=providers, provider_names=provider_names)


def build_fact_bundle_orchestrator() -> FactBundleOrchestrator:
    return FactBundleOrchestrator(service=build_fact_bundle_service())


__all__ = ["FactBundleOrchestrationResult", "FactBundleOrchestrator", "build_fact_bundle_orchestrator"]
