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
                    "schema_version": 1,
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


def test_replay_summary_is_identical_across_repeated_runs(tmp_path):
    root = _write_fixture(tmp_path)

    first = replay_research_events_once(research_root=root)
    second = replay_research_events_once(research_root=root)

    assert first == second


def test_filtered_replay_summary_is_identical_across_repeated_runs(tmp_path):
    root = _write_fixture(tmp_path)

    first = replay_research_events_once(
        research_root=root,
        source="github_trends",
        schema_version=1,
        observed_at_from="2026-07-09T00:00:00+00:00",
        observed_at_to="2026-07-09T23:59:59+00:00",
    )
    second = replay_research_events_once(
        research_root=root,
        source="github_trends",
        schema_version=1,
        observed_at_from="2026-07-09T00:00:00+00:00",
        observed_at_to="2026-07-09T23:59:59+00:00",
    )

    assert first == second


def test_by_source_json_serialization_is_deterministic(tmp_path):
    root = _write_fixture(tmp_path)

    first = replay_research_events_once(research_root=root)
    second = replay_research_events_once(research_root=root)

    first_json = json.dumps(first["by_source"], ensure_ascii=False)
    second_json = json.dumps(second["by_source"], ensure_ascii=False)
    assert first_json == second_json

    # Also assert deterministic canonical serialization.
    first_canonical = json.dumps(first["by_source"], ensure_ascii=False, sort_keys=True)
    second_canonical = json.dumps(second["by_source"], ensure_ascii=False, sort_keys=True)
    assert first_canonical == second_canonical
