import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.collector_contract import is_valid_raw_observation
from src.product_hunt_collector import ProductHuntCollector


def test_collect_emits_contract_shape_and_persists_raw_events(tmp_path):
    def mock_fetcher(topic, *, limit):
        assert topic == "ai"
        assert limit == 20
        return [
            {
                "name": "Notion Mail",
                "url": "https://www.producthunt.com/posts/notion-mail",
                "tagline": "Inbox for teams",
                "votes": 340,
                "comments": 41,
                "language": "en",
            },
            {
                "name": "Linear AI",
                "url": "https://www.producthunt.com/posts/linear-ai",
                "tagline": "Issue workflows with AI",
                "votes": 210,
                "comments": 18,
                "language": "en",
            },
        ]

    collector = ProductHuntCollector(research_root=tmp_path, fetcher=mock_fetcher)
    emitted = collector.collect(["ai"], observed_at_utc="2026-07-08T12:00:00+00:00")

    assert len(emitted) == 2
    assert all(is_valid_raw_observation(item) for item in emitted)
    assert emitted[0]["schema_version"] == 1
    assert emitted[0]["source"] == "product_hunt"
    assert emitted[0]["raw"]["topic"] == "product:Notion Mail"
    assert emitted[1]["raw"]["raw_context"]["collector"] == "product_hunt_v0"

    raw_files = sorted((tmp_path / "raw").glob("*.jsonl"))
    assert len(raw_files) == 1

    lines = [ln for ln in raw_files[0].read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 2

    first_event = json.loads(lines[0])
    assert first_event["event_type"] == "raw_observation"
    assert first_event["payload"]["schema_version"] == 1
    assert first_event["payload"]["source"] == "product_hunt"
    assert first_event["payload"]["raw"]["raw_context"]["seed_topic"] == "ai"


def test_collect_fail_open_when_fetcher_raises(tmp_path):
    def broken_fetcher(topic, *, limit):
        raise RuntimeError("temporary fetch error")

    collector = ProductHuntCollector(research_root=tmp_path, fetcher=broken_fetcher)
    emitted = collector.collect(["ai"], observed_at_utc="2026-07-08T12:00:00+00:00")

    assert emitted == []
    raw_dir = tmp_path / "raw"
    assert not raw_dir.exists() or list(raw_dir.glob("*.jsonl")) == []
