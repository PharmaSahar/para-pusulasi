import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import src.run_replay_once as replay_cli


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
        "{invalid-json-line}",
    ]
    fixture_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root


def test_run_replay_once_prints_json_summary(capsys, tmp_path):
    root = _write_fixture(tmp_path)

    code = replay_cli.main(["--research-root", str(root)])
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)

    assert code == 0
    assert payload["total_events_read"] == 2
    assert payload["total_events_emitted"] == 1
    assert payload["skipped_invalid"] == 1
    assert payload["by_source"] == {"google_trends": 1}


def test_run_replay_once_pretty_output_is_valid_json(capsys, tmp_path):
    root = _write_fixture(tmp_path)

    code = replay_cli.main(["--research-root", str(root), "--pretty"])
    out = capsys.readouterr().out
    payload = json.loads(out)

    assert code == 0
    assert payload["total_events_read"] == 2
    assert payload["total_events_emitted"] == 1
