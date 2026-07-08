from __future__ import annotations

import pytest

from src.fact_provider_selector import FactProviderSelector


def test_select_all_preserves_priority_order():
    selector = FactProviderSelector()

    assert selector.select_names() == ("FX", "market", "crypto", "commodity", "macro", "calendar", "news")


def test_select_by_names_ignores_input_order_and_returns_priority_order():
    selector = FactProviderSelector()

    selected = selector.select_by_names(["news", "FX", "macro", "crypto"])

    assert [entry.name for entry in selected] == ["FX", "crypto", "macro", "news"]
    assert [entry.priority for entry in selected] == [100, 80, 60, 40]


def test_select_by_names_rejects_unknown_provider_names():
    selector = FactProviderSelector()

    with pytest.raises(KeyError, match="unknown provider names: missing"):
        selector.select_by_names(["market", "missing"])


def test_select_by_names_returns_empty_tuple_for_empty_input():
    selector = FactProviderSelector()

    assert selector.select_by_names([]) == ()
