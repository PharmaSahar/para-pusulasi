from __future__ import annotations

import pytest

from src.fact_provider_factory import FactProviderFactory, build_fact_provider_factory
from src.fact_provider_registry import REGISTERED_FACT_PROVIDERS


def test_factory_lists_registered_provider_names():
    factory = build_fact_provider_factory()

    assert factory.names() == tuple(entry.name for entry in REGISTERED_FACT_PROVIDERS)


def test_factory_creates_fresh_instances_from_registry():
    factory = FactProviderFactory()

    for entry in REGISTERED_FACT_PROVIDERS:
        created = factory.create(entry.name)

        assert created is not entry.provider
        assert created.__class__ is entry.provider.__class__


def test_factory_creates_all_registered_providers_in_order():
    factory = FactProviderFactory()

    created = factory.create_all()

    assert len(created) == len(REGISTERED_FACT_PROVIDERS)
    assert [provider.__class__ for provider in created] == [entry.provider.__class__ for entry in REGISTERED_FACT_PROVIDERS]
    assert created[0].__class__.__name__ == REGISTERED_FACT_PROVIDERS[0].provider.__class__.__name__


def test_factory_rejects_unknown_provider_name():
    factory = FactProviderFactory()

    with pytest.raises(KeyError):
        factory.create("missing")
