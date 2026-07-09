from __future__ import annotations

from src.fact_provider_factory import FactProviderFactory
from src.fact_provider_registry import REGISTERED_FACT_PROVIDERS
from src.fact_provider_selector import FactProviderSelector, build_fact_provider_selector


def test_selector_returns_providers_ordered_by_priority():
    selector = build_fact_provider_selector()

    assert selector.select_names() == ("FX", "market", "crypto", "commodity", "macro", "calendar", "news")
    assert [entry.priority for entry in selector.select_all()] == [100, 90, 80, 70, 60, 50, 40]


def test_selector_preserves_registry_entries_and_instability_tie_breaking():
    selector = FactProviderSelector()

    selected = selector.select_all()

    assert selected == tuple(sorted(REGISTERED_FACT_PROVIDERS, key=lambda entry: (-entry.priority, entry.name.lower())))


def test_selector_returns_registry_entry_by_name():
    selector = FactProviderSelector()

    entry = selector.select("market")

    assert entry.name == "market"
    assert entry.priority == 90


def test_selector_keeps_factory_compatible():
    selector = FactProviderSelector()
    factory = FactProviderFactory()

    assert selector.select_names() == factory.names()
    assert [entry.provider.__class__ for entry in selector.select_all()] == [entry.provider.__class__ for entry in REGISTERED_FACT_PROVIDERS]
