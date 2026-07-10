from __future__ import annotations

import json
from pathlib import Path

from ops import queue_quarantine_admin as admin


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_list_returns_only_quarantined_entries(tmp_path):
    queue_path = tmp_path / "channel_queue.json"
    report_path = tmp_path / "report.json"

    _write_json(
        queue_path,
        {
            "ch1": [
                {"queue_entry_id": "qe1", "status": "active", "title": "A"},
                {"queue_entry_id": "qe2", "status": "quarantined", "title": "B"},
            ],
            "ch2": [
                {"queue_entry_id": "qe3", "status": "quarantined", "title": "C"},
            ],
        },
    )

    code = admin.main(["--queue", str(queue_path), "--report", str(report_path), "list"])

    assert code == 0
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["detail"]["quarantined_count"] == 2
    ids = {item["queue_entry_id"] for item in payload["detail"]["items"]}
    assert ids == {"qe2", "qe3"}


def test_restore_dry_run_checks_eligibility_without_mutation(tmp_path):
    queue_path = tmp_path / "channel_queue.json"
    report_path = tmp_path / "report.json"

    before = {
        "ch1": [
            {
                "queue_entry_id": "qe2",
                "status": "quarantined",
                "title": "B",
                "quarantine_reason": "channel_dna_mismatch",
            }
        ]
    }
    _write_json(queue_path, before)

    code = admin.main(
        [
            "--queue",
            str(queue_path),
            "--report",
            str(report_path),
            "restore",
            "--channel",
            "ch1",
            "--queue-entry-id",
            "qe2",
            "--reviewer",
            "qa",
            "--dry-run",
        ]
    )

    assert code == 0
    after = json.loads(queue_path.read_text(encoding="utf-8"))
    assert after == before
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["action"] == "restore_dry_run"
    assert payload["detail"]["eligible"] is True
    assert payload["detail"]["applied"] is False


def test_restore_applies_and_writes_review_fields(tmp_path, monkeypatch):
    queue_path = tmp_path / "channel_queue.json"
    report_path = tmp_path / "report.json"
    trail_path = tmp_path / "trail.jsonl"

    import src.scheduler_utils as scheduler_utils

    monkeypatch.setattr(scheduler_utils, "QUARANTINE_TRAIL_PATH", trail_path)

    _write_json(
        queue_path,
        {
            "ch1": [
                {
                    "queue_entry_id": "qe2",
                    "status": "quarantined",
                    "title": "B",
                    "quarantine_reason": "channel_dna_mismatch",
                }
            ]
        },
    )

    code = admin.main(
        [
            "--queue",
            str(queue_path),
            "--report",
            str(report_path),
            "restore",
            "--channel",
            "ch1",
            "--queue-entry-id",
            "qe2",
            "--reviewer",
            "qa",
            "--note",
            "approved",
        ]
    )

    assert code == 0
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    entry = queue["ch1"][0]
    assert entry["status"] == "restored"
    assert entry["review_status"] == "approved"
    assert entry["reviewed_by"] == "qa"

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["ok"] is True
    assert payload["detail"]["applied"] is True

    lines = [line for line in trail_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 1
    assert json.loads(lines[0])["event"] == "queue_entry_restored"
