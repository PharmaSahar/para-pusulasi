"""Priority-based provider selection for the Fact Bundle provider catalog."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterable

from .fact_provider_registry import REGISTERED_FACT_PROVIDERS, RegisteredFactProvider, get_registered_fact_provider


@dataclass(frozen=True, slots=True)
class FactProviderSelector:
    """Select providers from the existing registry in priority order."""

    def select_all(self) -> tuple[RegisteredFactProvider, ...]:
        return self._sort_entries(REGISTERED_FACT_PROVIDERS)

    def select_by_names(self, provider_names: Iterable[str]) -> tuple[RegisteredFactProvider, ...]:
        normalized_names = {name.strip().lower() for name in provider_names}
        if not normalized_names:
            return ()

        entries_by_name = {entry.name.lower(): entry for entry in REGISTERED_FACT_PROVIDERS}
        missing_names = sorted(name for name in normalized_names if name not in entries_by_name)
        if missing_names:
            raise KeyError(f"unknown provider names: {', '.join(missing_names)}")

        selected = (entries_by_name[name] for name in normalized_names)
        return self._sort_entries(selected)

    def select_names(self) -> tuple[str, ...]:
        return tuple(entry.name for entry in self.select_all())

    def select(self, provider_name: str) -> RegisteredFactProvider:
        return get_registered_fact_provider(provider_name)

    def _sort_entries(self, entries: Iterable[RegisteredFactProvider]) -> tuple[RegisteredFactProvider, ...]:
        return tuple(sorted(entries, key=lambda entry: (-entry.priority, entry.name.lower())))


def build_fact_provider_selector() -> FactProviderSelector:
    return FactProviderSelector()


__all__ = ["FactProviderSelector", "build_fact_provider_selector"]
