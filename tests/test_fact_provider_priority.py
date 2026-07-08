from __future__ import annotations

from src.fact_provider_factory import FactProviderFactory
from src.fact_provider_registry import REGISTERED_FACT_PROVIDERS, list_registered_fact_provider_priorities


def test_registry_exposes_priority_metadata_for_all_registered_providers():
    expected_priorities = (100, 90, 80, 70, 60, 50, 40)

    assert list_registered_fact_provider_priorities() == expected_priorities
    assert tuple(entry.priority for entry in REGISTERED_FACT_PROVIDERS) == expected_priorities


def test_registry_priorities_are_unique_and_positive():
    priorities = [entry.priority for entry in REGISTERED_FACT_PROVIDERS]

    assert len(priorities) == len(set(priorities))
    assert all(priority > 0 for priority in priorities)


def test_provider_factory_remains_compatible_with_priority_metadata():
    factory = FactProviderFactory()

    assert factory.names() == tuple(entry.name for entry in REGISTERED_FACT_PROVIDERS)
    assert [provider.__class__ for provider in factory.create_all()] == [entry.provider.__class__ for entry in REGISTERED_FACT_PROVIDERS]
