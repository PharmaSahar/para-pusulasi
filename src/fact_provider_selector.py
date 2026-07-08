"""Priority-based provider selection for the Fact Bundle provider catalog."""

from __future__ import annotations

from dataclasses import dataclass

from .fact_provider_registry import REGISTERED_FACT_PROVIDERS, RegisteredFactProvider, get_registered_fact_provider


@dataclass(frozen=True, slots=True)
class FactProviderSelector:
    """Select providers from the existing registry in priority order."""

    def select_all(self) -> tuple[RegisteredFactProvider, ...]:
        return tuple(sorted(REGISTERED_FACT_PROVIDERS, key=lambda entry: (-entry.priority, entry.name.lower())))

    def select_names(self) -> tuple[str, ...]:
        return tuple(entry.name for entry in self.select_all())

    def select(self, provider_name: str) -> RegisteredFactProvider:
        return get_registered_fact_provider(provider_name)


def build_fact_provider_selector() -> FactProviderSelector:
    return FactProviderSelector()


__all__ = ["FactProviderSelector", "build_fact_provider_selector"]
