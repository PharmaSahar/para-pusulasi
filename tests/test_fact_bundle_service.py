from __future__ import annotations

import pytest

from src.fact_bundle_service import FactBundleService, build_fact_bundle_service
from src.fact_provider_composition import build_fact_provider_composition
from src.fact_provider_registry import REGISTERED_FACT_PROVIDERS


def test_service_returns_all_providers_in_priority_order():
    service = build_fact_bundle_service()

    providers = service.get_all_providers()

    assert [provider.__class__ for provider in providers] == [entry.provider.__class__ for entry in REGISTERED_FACT_PROVIDERS]


def test_service_filters_providers_by_name_and_keeps_priority_order():
    service = FactBundleService(composition=build_fact_provider_composition())

    providers = service.get_providers(["news", "FX", "macro", "crypto"])

    assert [provider.__class__.__name__ for provider in providers] == ["LiveFXProvider", "LiveCryptoFactProvider", "LiveMacroFactProvider", "LiveNewsFactProvider"]


def test_service_raises_for_unknown_provider_names():
    service = build_fact_bundle_service()

    with pytest.raises(KeyError, match="unknown provider names: missing"):
        service.get_providers(["missing"])


def test_service_returns_single_provider():
    service = build_fact_bundle_service()

    provider = service.get_provider("market")

    assert provider.__class__.__name__ == "LiveMarketFactProvider"
