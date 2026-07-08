from __future__ import annotations

import pytest

from src.fact_bundle_orchestrator import FactBundleOrchestrator, build_fact_bundle_orchestrator
from src.fact_bundle_service import build_fact_bundle_service
from src.fact_provider_registry import REGISTERED_FACT_PROVIDERS


def test_orchestrator_aggregates_all_service_providers():
    orchestrator = build_fact_bundle_orchestrator()

    result = orchestrator.orchestrate_all()

    assert result.provider_count == len(REGISTERED_FACT_PROVIDERS)
    assert [provider.__class__ for provider in result.providers] == [entry.provider.__class__ for entry in REGISTERED_FACT_PROVIDERS]
    assert result.provider_names == tuple(provider.__class__.__name__ for provider in result.providers)


def test_orchestrator_preserves_priority_order_for_filtered_names():
    orchestrator = FactBundleOrchestrator(service=build_fact_bundle_service())

    result = orchestrator.orchestrate_by_names(["news", "FX", "macro", "crypto"])

    assert [provider.__class__.__name__ for provider in result.providers] == ["LiveFXProvider", "LiveCryptoFactProvider", "LiveMacroFactProvider", "LiveNewsFactProvider"]
    assert result.provider_count == 4


def test_orchestrator_returns_single_provider_result():
    orchestrator = build_fact_bundle_orchestrator()

    result = orchestrator.orchestrate("market")

    assert result.provider_count == 1
    assert result.provider_names == ("LiveMarketFactProvider",)


def test_orchestrator_propagates_unknown_provider_names():
    orchestrator = build_fact_bundle_orchestrator()

    with pytest.raises(KeyError, match="unknown provider names: missing"):
        orchestrator.orchestrate_by_names(["missing"])
