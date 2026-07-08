import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.collector_contract import is_valid_raw_observation
from src.hacker_news_collector import HackerNewsCollector


def test_collect_emits_contract_shape_and_persists_raw_events(tmp_path):
    def mock_fetcher(board, *, limit):
        assert board == "top"
        assert limit == 30
        return [
            {
                "id": 429001,
                "title": "Open-source browser engine updates",
                "url": "https://news.ycombinator.com/item?id=429001",
                "points": 321,
                "comments": 89,
                "language": "en",
            },
            {
                "id": 429002,
                "title": "Database indexing patterns in 2026",
                "url": "https://news.ycombinator.com/item?id=429002",
                "points": 188,
                "comments": 33,
                "language": "en",
            },
        ]

    collector = HackerNewsCollector(research_root=tmp_path, fetcher=mock_fetcher)
    emitted = collector.collect(["top"], observed_at_utc="2026-07-08T12:00:00+00:00")

    assert len(emitted) == 2
    assert all(is_valid_raw_observation(item) for item in emitted)
    assert emitted[0]["schema_version"] == 1
    assert emitted[0]["source"] == "hacker_news"
    assert emitted[0]["raw"]["topic"] == "Open-source browser engine updates"
    assert emitted[1]["raw"]["raw_context"]["collector"] == "hacker_news_v0"

    raw_files = sorted((tmp_path / "raw").glob("*.jsonl"))
    assert len(raw_files) == 1

    lines = [ln for ln in raw_files[0].read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 2

    first_event = json.loads(lines[0])
    assert first_event["event_type"] == "raw_observation"
    assert first_event["payload"]["schema_version"] == 1
    assert first_event["payload"]["source"] == "hacker_news"
    assert first_event["payload"]["raw"]["raw_context"]["board"] == "top"


def test_collect_fail_open_when_fetcher_raises(tmp_path):
    def broken_fetcher(board, *, limit):
        raise RuntimeError("temporary fetch error")

    collector = HackerNewsCollector(research_root=tmp_path, fetcher=broken_fetcher)
    emitted = collector.collect(["top"], observed_at_utc="2026-07-08T12:00:00+00:00")

    assert emitted == []
    raw_dir = tmp_path / "raw"
    assert not raw_dir.exists() or list(raw_dir.glob("*.jsonl")) == []
