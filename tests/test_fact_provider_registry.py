from __future__ import annotations

from src.fact_provider_registry import (
    REGISTERED_FACT_PROVIDERS,
    build_fact_data_provider_registry,
    get_registered_fact_provider,
    list_registered_fact_provider_names,
)
from src.fact_sources import LiveFXProvider
from src.fact_bundle_providers import FactDataProvider


def test_registry_lists_all_current_fact_providers():
    assert list_registered_fact_provider_names() == (
        "FX",
        "market",
        "crypto",
        "commodity",
        "macro",
        "calendar",
        "news",
    )


def test_registry_catalog_exposes_expected_interfaces():
    fx_entry = get_registered_fact_provider("FX")
    assert isinstance(fx_entry.provider, LiveFXProvider)
    assert fx_entry.interface == "TrustedFactProvider"

    data_entry_names = [entry.name for entry in REGISTERED_FACT_PROVIDERS if isinstance(entry.provider, FactDataProvider)]
    assert data_entry_names == ["market", "crypto", "commodity", "macro", "calendar", "news"]


def test_fact_data_provider_registry_registers_shared_interface_providers():
    registry = build_fact_data_provider_registry()

    assert registry.names() == (
        "live_market",
        "live_crypto",
        "live_commodity",
        "live_macro",
        "live_calendar",
        "live_news",
    )
