import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.google_trends_collector import GoogleTrendsCollector
from src.research_scheduler import run_research_collectors_once


def test_passive_research_pipeline_smoke_with_static_input(tmp_path):
    def mock_fetcher(query, *, geo, timeframe):
        assert query == "bitcoin"
        return [
            {"topic": "bitcoin wallet", "search_volume": 87},
        ]

    collector = GoogleTrendsCollector(research_root=tmp_path, fetcher=mock_fetcher)

    summary = run_research_collectors_once(
        collectors={"google_trends": collector},
        collector_inputs={"google_trends": {"queries": ["bitcoin"]}},
        observed_at_utc="2026-07-08T12:00:00+00:00",
    )

    summary_json = json.loads(json.dumps(summary))
    assert isinstance(summary_json, dict)
    assert any(row.get("collector") == "google_trends" for row in summary_json.get("results", []))
    assert summary_json.get("observations_written", 0) > 0

    raw_files = sorted((tmp_path / "raw").glob("*.jsonl"))
    assert len(raw_files) == 1

    lines = [ln for ln in raw_files[0].read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) >= 1

    first_event = json.loads(lines[0])
    assert first_event["event_type"] == "raw_observation"
    assert isinstance(first_event["payload"], dict)
    assert isinstance(first_event["payload"].get("raw"), dict)
    assert first_event["payload"]["raw"]["topic"] == "bitcoin wallet"
