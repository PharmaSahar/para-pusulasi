import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.opportunity_normalizer import build_opportunity_id, normalize_observation


def test_build_opportunity_id_is_stable_for_canonical_equivalents():
    first = build_opportunity_id(
        country="TR",
        language="TR",
        topic=" Dolar  Tahmini ",
        source="Google Trends",
    )
    second = build_opportunity_id(
        country="tr",
        language="tr",
        topic="dolar tahmini",
        source="google   trends",
    )

    assert first == second
    assert first.startswith("opp_")
    assert len(first) == 68


def test_normalize_observation_builds_required_fields():
    raw = {
        "topic": "BIST 100 teknik analiz",
        "category": "Borsa",
        "country": "TR",
        "language": "TR",
        "source": "reddit",
        "search_volume": 420,
        "competition": 0.4,
        "confidence": 0.7,
    }

    normalized = normalize_observation(raw, observed_at_utc="2026-07-08T10:00:00+00:00")

    assert normalized["opportunity_id"].startswith("opp_")
    assert normalized["topic"] == "bist 100 teknik analiz"
    assert normalized["category"] == "borsa"
    assert normalized["country"] == "tr"
    assert normalized["language"] == "tr"
    assert normalized["source"] == "reddit"
    assert normalized["first_seen"] == "2026-07-08T10:00:00+00:00"
    assert normalized["last_seen"] == "2026-07-08T10:00:00+00:00"
    assert normalized["search_volume"] == 420
    assert normalized["competition"] == 0.4
    assert normalized["confidence"] == 0.7
