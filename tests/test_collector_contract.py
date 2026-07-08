import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.collector_contract import is_valid_raw_observation, validate_raw_observation
from src.google_trends_collector import GoogleTrendsCollector


def test_validate_raw_observation_accepts_valid_shape():
    observation = {
        "source": "google_trends",
        "observed_at": "2026-07-08T12:00:00+00:00",
        "raw": {"topic": "bitcoin wallet"},
    }
    assert validate_raw_observation(observation) == []
    assert is_valid_raw_observation(observation) is True


def test_validate_raw_observation_rejects_invalid_fields():
    observation = {
        "source": "   ",
        "observed_at": "not-an-iso-date",
        "raw": "not-a-dict",
    }
    errors = validate_raw_observation(observation)
    assert "invalid_source" in errors
    assert "invalid_observed_at" in errors
    assert "invalid_raw" in errors


def test_google_trends_collector_emits_contract_shape(tmp_path):
    def mock_fetcher(query, *, geo, timeframe):
        return [{"topic": "bitcoin wallet", "search_volume": 87}]

    collector = GoogleTrendsCollector(research_root=tmp_path, fetcher=mock_fetcher)
    emitted = collector.collect(["bitcoin"], observed_at_utc="2026-07-08T12:00:00+00:00")

    assert len(emitted) == 1
    assert is_valid_raw_observation(emitted[0]) is True
    assert emitted[0]["source"] == "google_trends"
    assert emitted[0]["raw"]["topic"] == "bitcoin wallet"
