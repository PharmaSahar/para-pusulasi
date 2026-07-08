import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.collector_contract import is_valid_raw_observation
from src.github_trends_collector import GitHubTrendsCollector


def test_collect_emits_contract_shape_and_persists_raw_events(tmp_path):
    def mock_fetcher(language, *, since):
        assert language == "python"
        assert since == "daily"
        return [
            {
                "name": "fastapi",
                "url": "https://github.com/tiangolo/fastapi",
                "description": "FastAPI framework",
                "language": "python",
                "stars": 100,
            },
            {
                "name": "pydantic",
                "url": "https://github.com/pydantic/pydantic",
                "description": "Data validation",
                "language": "python",
                "stars": 80,
            },
        ]

    collector = GitHubTrendsCollector(research_root=tmp_path, fetcher=mock_fetcher)
    emitted = collector.collect(["python"], observed_at_utc="2026-07-08T12:00:00+00:00")

    assert len(emitted) == 2
    assert all(is_valid_raw_observation(item) for item in emitted)
    assert emitted[0]["source"] == "github_trends"
    assert emitted[0]["raw"]["topic"] == "repo:fastapi"
    assert emitted[1]["raw"]["raw_context"]["collector"] == "github_trends_v0"

    raw_files = sorted((tmp_path / "raw").glob("*.jsonl"))
    assert len(raw_files) == 1
    lines = [ln for ln in raw_files[0].read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) == 2

    first_event = json.loads(lines[0])
    assert first_event["event_type"] == "raw_observation"
    assert first_event["payload"]["source"] == "github_trends"
    assert first_event["payload"]["raw"]["raw_context"]["repo_name"] == "fastapi"


def test_collect_fail_open_when_fetcher_raises(tmp_path):
    def broken_fetcher(language, *, since):
        raise RuntimeError("temporary fetch error")

    collector = GitHubTrendsCollector(research_root=tmp_path, fetcher=broken_fetcher)
    emitted = collector.collect(["python"], observed_at_utc="2026-07-08T12:00:00+00:00")

    assert emitted == []
    raw_dir = tmp_path / "raw"
    assert not raw_dir.exists() or list(raw_dir.glob("*.jsonl")) == []
