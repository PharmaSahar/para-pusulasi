import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.collector_contract import is_valid_raw_observation
from src.reddit_trends_collector import RedditTrendsCollector


def test_collect_emits_contract_shape_and_persists_raw_events(tmp_path):
    def mock_fetcher(subreddit, *, limit):
        assert subreddit == "Entrepreneur"
        assert limit == 25
        return [
            {
                "id": "abc123",
                "title": "How to validate startup ideas quickly",
                "url": "https://reddit.com/r/Entrepreneur/abc123",
                "language": "en",
                "score": 250,
                "num_comments": 42,
            },
            {
                "id": "def456",
                "title": "Best niches for faceless channels",
                "url": "https://reddit.com/r/Entrepreneur/def456",
                "language": "en",
                "score": 180,
                "num_comments": 27,
            },
        ]

    collector = RedditTrendsCollector(research_root=tmp_path, fetcher=mock_fetcher)
    emitted = collector.collect(["Entrepreneur"], observed_at_utc="2026-07-08T12:00:00+00:00")

    assert len(emitted) == 2
    assert all(is_valid_raw_observation(item) for item in emitted)
    assert emitted[0]["source"] == "reddit_trends"
    assert emitted[0]["raw"]["topic"] == "How to validate startup ideas quickly"
    assert emitted[1]["raw"]["raw_context"]["collector"] == "reddit_trends_v0"

    raw_files = sorted((tmp_path / "raw").glob("*.jsonl"))
    assert len(raw_files) == 1

    lines = [ln for ln in raw_files[0].read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 2

    first_event = json.loads(lines[0])
    assert first_event["event_type"] == "raw_observation"
    assert first_event["payload"]["source"] == "reddit_trends"
    assert first_event["payload"]["raw"]["raw_context"]["subreddit"] == "Entrepreneur"


def test_collect_fail_open_when_fetcher_raises(tmp_path):
    def broken_fetcher(subreddit, *, limit):
        raise RuntimeError("temporary fetch error")

    collector = RedditTrendsCollector(research_root=tmp_path, fetcher=broken_fetcher)
    emitted = collector.collect(["Entrepreneur"], observed_at_utc="2026-07-08T12:00:00+00:00")

    assert emitted == []
    raw_dir = tmp_path / "raw"
    assert not raw_dir.exists() or list(raw_dir.glob("*.jsonl")) == []
