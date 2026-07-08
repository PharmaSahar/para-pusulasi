import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.research_replay import replay_research_events_once


def _write_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "research"
    raw = root / "raw"
    raw.mkdir(parents=True, exist_ok=True)

    fixture_file = raw / "2026-07-08.jsonl"
    lines = [
        json.dumps(
            {
                "event_type": "raw_observation",
                "observed_at": "2026-07-08T12:00:00+00:00",
                "payload": {
                    "schema_version": 1,
                    "source": "google_trends",
                    "observed_at": "2026-07-08T12:00:00+00:00",
                    "raw": {"topic": "bitcoin wallet"},
                },
            },
            ensure_ascii=False,
        ),
        json.dumps(
            {
                "event_type": "raw_observation",
                "observed_at": "2026-07-09T12:00:00+00:00",
                "payload": {
                    "schema_version": 1,
                    "source": "github_trends",
                    "observed_at": "2026-07-09T12:00:00+00:00",
                    "raw": {"topic": "repo:fastapi"},
                },
            },
            ensure_ascii=False,
        ),
        json.dumps(
            {
                "event_type": "raw_observation",
                "observed_at": "2026-07-10T12:00:00+00:00",
                "payload": {
                    "schema_version": 2,
                    "source": "reddit_trends",
                    "observed_at": "2026-07-10T12:00:00+00:00",
                    "raw": {"topic": "startup ideas"},
                },
            },
            ensure_ascii=False,
        ),
        "{invalid-json-line}",
    ]
    fixture_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root


def test_replay_returns_summary_and_counts(tmp_path):
    root = _write_fixture(tmp_path)
    summary = replay_research_events_once(research_root=root)

    assert summary["total_events_read"] == 4
    assert summary["total_events_emitted"] == 3
    assert summary["skipped_invalid"] == 1
    assert summary["files_scanned"] == 1
    assert summary["files_with_events"] == 1
    assert summary["first_observed_at"] == "2026-07-08T12:00:00+00:00"
    assert summary["last_observed_at"] == "2026-07-10T12:00:00+00:00"
    assert summary["by_source"]["google_trends"] == 1
    assert summary["by_source"]["github_trends"] == 1
    assert summary["by_source"]["reddit_trends"] == 1


def test_replay_source_filter(tmp_path):
    root = _write_fixture(tmp_path)
    summary = replay_research_events_once(research_root=root, source="github_trends")

    assert summary["total_events_read"] == 4
    assert summary["total_events_emitted"] == 1
    assert summary["files_scanned"] == 1
    assert summary["files_with_events"] == 1
    assert summary["first_observed_at"] == "2026-07-09T12:00:00+00:00"
    assert summary["last_observed_at"] == "2026-07-09T12:00:00+00:00"
    assert summary["by_source"] == {"github_trends": 1}


def test_replay_schema_version_filter(tmp_path):
    root = _write_fixture(tmp_path)
    summary = replay_research_events_once(research_root=root, schema_version=1)

    assert summary["total_events_read"] == 4
    assert summary["total_events_emitted"] == 2
    assert summary["files_scanned"] == 1
    assert summary["files_with_events"] == 1
    assert summary["first_observed_at"] == "2026-07-08T12:00:00+00:00"
    assert summary["last_observed_at"] == "2026-07-09T12:00:00+00:00"
    assert summary["by_source"] == {"google_trends": 1, "github_trends": 1}


def test_replay_observed_at_range_filter(tmp_path):
    root = _write_fixture(tmp_path)
    summary = replay_research_events_once(
        research_root=root,
        observed_at_from="2026-07-09T00:00:00+00:00",
        observed_at_to="2026-07-09T23:59:59+00:00",
    )

    assert summary["total_events_read"] == 4
    assert summary["total_events_emitted"] == 1
    assert summary["files_scanned"] == 1
    assert summary["files_with_events"] == 1
    assert summary["first_observed_at"] == "2026-07-09T12:00:00+00:00"
    assert summary["last_observed_at"] == "2026-07-09T12:00:00+00:00"
    assert summary["by_source"] == {"github_trends": 1}
