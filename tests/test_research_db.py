import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.opportunity_normalizer import normalize_observation
from src.research_db import (
    append_or_update_opportunity,
    append_raw_observation,
    load_latest_opportunities,
    normalized_path,
    raw_day_path,
    schema_path,
)


def test_append_raw_observation_creates_daily_event_file(tmp_path):
    observed = "2026-07-08T10:00:00+00:00"
    ok = append_raw_observation({"topic": "dolar tahmini", "source": "manual"}, root=tmp_path, observed_at_utc=observed)
    assert ok is True

    path = raw_day_path(root=tmp_path, now_utc=datetime(2026, 7, 8, tzinfo=timezone.utc))
    assert path.exists()
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["event_type"] == "raw_observation"
    assert event["observed_at"] == observed


def test_append_or_update_preserves_first_seen_and_updates_last_seen(tmp_path):
    base = {
        "topic": "dolar tahmini",
        "category": "finans",
        "country": "TR",
        "language": "TR",
        "source": "manual",
    }
    first = normalize_observation(base, observed_at_utc="2026-07-08T10:00:00+00:00")
    second = normalize_observation(base, observed_at_utc="2026-07-09T10:00:00+00:00")

    merged_first = append_or_update_opportunity(first, root=tmp_path, observed_at_utc="2026-07-08T10:00:00+00:00")
    merged_second = append_or_update_opportunity(second, root=tmp_path, observed_at_utc="2026-07-09T10:00:00+00:00")

    assert merged_first["first_seen"] == "2026-07-08T10:00:00+00:00"
    assert merged_first["last_seen"] == "2026-07-08T10:00:00+00:00"
    assert merged_second["first_seen"] == "2026-07-08T10:00:00+00:00"
    assert merged_second["last_seen"] == "2026-07-09T10:00:00+00:00"

    opportunities_file = normalized_path(root=tmp_path)
    lines = opportunities_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2

    latest = load_latest_opportunities(root=tmp_path)
    opp_id = merged_second["opportunity_id"]
    assert latest[opp_id]["first_seen"] == "2026-07-08T10:00:00+00:00"
    assert latest[opp_id]["last_seen"] == "2026-07-09T10:00:00+00:00"


def test_schema_file_bootstraps_on_first_write(tmp_path):
    append_raw_observation({"topic": "ai tools", "source": "manual"}, root=tmp_path)
    spath = schema_path(root=tmp_path)
    assert spath.exists()
    schema = json.loads(spath.read_text(encoding="utf-8"))
    assert schema["schema_version"] == "opportunity_v1"
    assert "required" in schema
