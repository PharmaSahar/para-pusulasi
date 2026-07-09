from __future__ import annotations

from src.fact_bundle_providers import FactDataProvider
from src.fact_provider_registry import REGISTERED_FACT_PROVIDERS, list_registered_fact_provider_names
from src.fact_sources import TrustedFactProvider


def test_registry_contains_all_implemented_fact_providers():
    assert list_registered_fact_provider_names() == (
        "FX",
        "market",
        "crypto",
        "commodity",
        "macro",
        "calendar",
        "news",
    )


def test_registry_provider_names_are_unique():
    names = list_registered_fact_provider_names()

    assert len(names) == len(set(names))


def test_registry_providers_implement_expected_interfaces():
    expected_interfaces = {
        "FX": TrustedFactProvider,
        "market": FactDataProvider,
        "crypto": FactDataProvider,
        "commodity": FactDataProvider,
        "macro": FactDataProvider,
        "calendar": FactDataProvider,
        "news": FactDataProvider,
    }

    assert [entry.name for entry in REGISTERED_FACT_PROVIDERS] == list(expected_interfaces.keys())

    for entry in REGISTERED_FACT_PROVIDERS:
        assert isinstance(entry.provider, expected_interfaces[entry.name])
