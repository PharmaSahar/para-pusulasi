from __future__ import annotations

import pytest

from src.fact_provider_composition import FactProviderComposition, build_fact_provider_composition
from src.fact_provider_registry import REGISTERED_FACT_PROVIDERS


def test_composition_returns_instantiated_providers_in_priority_order():
    composition = build_fact_provider_composition()

    providers = composition.compose_all()

    assert [provider.__class__ for provider in providers] == [entry.provider.__class__ for entry in REGISTERED_FACT_PROVIDERS]
    assert providers[0] is not REGISTERED_FACT_PROVIDERS[0].provider


def test_composition_preserves_selector_priority_for_filtered_names():
    composition = FactProviderComposition(
        selector=build_fact_provider_composition().selector,
        factory=build_fact_provider_composition().factory,
    )

    providers = composition.compose_by_names(["news", "FX", "macro", "crypto"])

    assert [provider.__class__.__name__ for provider in providers] == ["LiveFXProvider", "LiveCryptoFactProvider", "LiveMacroFactProvider", "LiveNewsFactProvider"]


def test_composition_rejects_unknown_provider_names():
    composition = build_fact_provider_composition()

    with pytest.raises(KeyError, match="unknown provider names: missing"):
        composition.compose_by_names(["missing"])


def test_composition_exposes_selector_order_without_mutating_registry():
    composition = build_fact_provider_composition()

    selected = composition.select_all()

    assert [entry.name for entry in selected] == ["FX", "market", "crypto", "commodity", "macro", "calendar", "news"]
    assert [entry.priority for entry in selected] == [100, 90, 80, 70, 60, 50, 40]
