import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.google_trends_collector import GoogleTrendsCollector


def test_collect_persists_raw_observations_with_mock_fetcher(tmp_path):
    def mock_fetcher(query, *, geo, timeframe):
        assert geo == "TR"
        assert timeframe == "now 7-d"
        if query == "bitcoin":
            return [
                {"topic": "bitcoin wallet", "search_volume": 87},
                {"topic": "bitcoin etf", "search_volume": 65, "language": "en", "country": "us"},
            ]
        return []

    collector = GoogleTrendsCollector(research_root=tmp_path, fetcher=mock_fetcher)
    emitted = collector.collect(["bitcoin"], observed_at_utc="2026-07-08T12:00:00+00:00")

    assert len(emitted) == 2
    assert emitted[0]["source"] == "google_trends"
    assert emitted[0]["observed_at"] == "2026-07-08T12:00:00+00:00"
    assert emitted[0]["raw"]["topic"] == "bitcoin wallet"
    assert emitted[1]["raw"]["country"] == "us"
    assert emitted[1]["raw"]["language"] == "en"

    raw_files = sorted((tmp_path / "raw").glob("*.jsonl"))
    assert len(raw_files) == 1

    lines = [ln for ln in raw_files[0].read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 2
    first_event = json.loads(lines[0])
    assert first_event["event_type"] == "raw_observation"
    assert first_event["payload"]["source"] == "google_trends"
    assert first_event["payload"]["raw"]["raw_context"]["collector"] == "google_trends_v0"


def test_collect_fail_open_when_fetcher_raises(tmp_path):
    def broken_fetcher(query, *, geo, timeframe):
        raise RuntimeError("temporary fetch error")

    collector = GoogleTrendsCollector(research_root=tmp_path, fetcher=broken_fetcher)
    emitted = collector.collect(["bitcoin"], observed_at_utc="2026-07-08T12:00:00+00:00")

    assert emitted == []
    raw_dir = tmp_path / "raw"
    assert not raw_dir.exists() or list(raw_dir.glob("*.jsonl")) == []
