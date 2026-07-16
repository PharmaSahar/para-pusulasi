from __future__ import annotations

from src import trends_fetcher


def test_get_trending_topics_default_no_longer_assumes_finance() -> None:
    meta = trends_fetcher.get_trending_topics_with_metadata(count=5)

    assert meta["fallback_invoked"] is True
    assert meta["fallback_source"] == "static_niche:general"
    assert meta["topics"] == []


def test_get_trending_topics_explicit_finance_niche_preserves_finance_behavior() -> None:
    meta = trends_fetcher.get_trending_topics_with_metadata(niche="kisisel_finans", count=5)

    assert meta["fallback_invoked"] is True
    assert meta["fallback_source"] == "static_niche:kisisel_finans"
    assert len(meta["topics"]) > 0
    assert any(
        any(keyword in topic.lower() for keyword in ("dolar", "bist", "yatirim", "enflasyon"))
        for topic in meta["topics"]
    )


def test_get_trending_topics_wrapper_default_is_neutral() -> None:
    topics = trends_fetcher.get_trending_topics(count=5)

    assert topics == []
