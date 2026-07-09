"""Composition layer for fact provider selection and instantiation.

This module wires the registry-backed selector and factory together without
connecting them to the pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterable

from .fact_provider_factory import FactProviderFactory, build_fact_provider_factory
from .fact_provider_registry import RegisteredFactProvider
from .fact_provider_selector import FactProviderSelector, build_fact_provider_selector


@dataclass(frozen=True, slots=True)
class FactProviderComposition:
    """Compose instantiated providers in selector priority order."""

    selector: FactProviderSelector
    factory: FactProviderFactory

    def compose_all(self) -> tuple[object, ...]:
        return tuple(self.factory.create(entry.name) for entry in self.selector.select_all())

    def compose_by_names(self, provider_names: Iterable[str]) -> tuple[object, ...]:
        selected = self.selector.select_by_names(provider_names)
        return tuple(self.factory.create(entry.name) for entry in selected)

    def compose(self, provider_name: str) -> object:
        return self.factory.create(provider_name)

    def select_all(self) -> tuple[RegisteredFactProvider, ...]:
        return self.selector.select_all()


def build_fact_provider_composition() -> FactProviderComposition:
    return FactProviderComposition(
        selector=build_fact_provider_selector(),
        factory=build_fact_provider_factory(),
    )


__all__ = ["FactProviderComposition", "build_fact_provider_composition"]
