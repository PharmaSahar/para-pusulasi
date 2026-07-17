from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from src import canonical_runtime_analytics_shadow as shadow
from src.studio_analytics_learning_bridge import build_canonical_record_id


class _FakeContext:
    def __init__(self, token_path: Path):
        self.selected_token_path = token_path
        self.selected_token_source = "ANALYTICS_TOKEN_PRIMARY"


class _FakeCreds:
    valid = True
    expired = False


class _FakeQuery:
    def __init__(self, response: dict, error: Exception | None = None):
        self._response = response
        self._error = error

    def execute(self, num_retries=0):
        assert num_retries == 0
        if self._error is not None:
            raise self._error
        return self._response


class _FakeReports:
    def __init__(self, response: dict, error: Exception | None = None):
        self._response = response
        self._error = error

    def query(self, **kwargs):
        assert kwargs["ids"] == "channel==MINE"
        assert kwargs["dimensions"] == "video"
        return _FakeQuery(self._response, self._error)


class _FakeService:
    def __init__(self, response: dict, error: Exception | None = None):
        self._response = response
        self._error = error

    def reports(self):
        return _FakeReports(self._response, self._error)


def _mock_success_collection(monkeypatch, tmp_path: Path) -> None:
    token = tmp_path / "youtube_analytics_token.pickle"
    token.write_bytes(b"x")

    monkeypatch.setattr(shadow, "_resolve_gate_enabled", lambda: True)
    monkeypatch.setattr(shadow, "_resolve_channel_context", lambda channel_slug: _FakeContext(token))
    monkeypatch.setattr(shadow, "_load_credentials_read_only", lambda token_path: _FakeCreds())
    monkeypatch.setattr(shadow, "_credentials_scope_ok", lambda credentials: True)

    response = {
        "columnHeaders": [
            {"name": "video"},
            {"name": "views"},
            {"name": "estimatedMinutesWatched"},
            {"name": "averageViewDuration"},
            {"name": "averageViewPercentage"},
            {"name": "subscribersGained"},
            {"name": "subscribersLost"},
        ],
        "rows": [["vid_1", 1000, 600.0, 120.0, 62.5, 12, 2]],
    }
    monkeypatch.setattr(shadow, "_build_service", lambda credentials, timeout_seconds: _FakeService(response))


def test_collect_runtime_video_analytics_success(monkeypatch, tmp_path: Path):
    _mock_success_collection(monkeypatch, tmp_path)

    result = shadow.collect_runtime_video_analytics(
        channel_id="para_pusulasi",
        video_id="vid_1",
        start_date="2026-07-10",
        end_date="2026-07-16",
    )

    assert result.ok is True
    assert result.result_state == "SUCCESS"
    assert result.payload["api_call_succeeded"] is True
    assert result.payload["rows"][0]["video"] == "vid_1"


def test_collect_runtime_video_analytics_rejects_unsupported_metric(monkeypatch, tmp_path: Path):
    token = tmp_path / "youtube_analytics_token.pickle"
    token.write_bytes(b"x")

    monkeypatch.setattr(shadow, "_resolve_gate_enabled", lambda: True)
    monkeypatch.setattr(shadow, "_resolve_channel_context", lambda channel_slug: _FakeContext(token))
    monkeypatch.setattr(shadow, "_load_credentials_read_only", lambda token_path: _FakeCreds())
    monkeypatch.setattr(shadow, "_credentials_scope_ok", lambda credentials: True)

    response = {
        "columnHeaders": [{"name": "video"}, {"name": "likes"}],
        "rows": [["vid_1", 10]],
    }
    monkeypatch.setattr(shadow, "_build_service", lambda credentials, timeout_seconds: _FakeService(response))

    result = shadow.collect_runtime_video_analytics(
        channel_id="para_pusulasi",
        video_id="vid_1",
        start_date="2026-07-10",
        end_date="2026-07-16",
    )

    assert result.ok is False
    assert result.result_state == "UNSUPPORTED_METRIC"


def test_collect_runtime_video_analytics_valid_partial_window(monkeypatch, tmp_path: Path):
    _mock_success_collection(monkeypatch, tmp_path)

    result = shadow.collect_runtime_video_analytics(
        channel_id="para_pusulasi",
        video_id="vid_1",
        start_date="2026-07-16",
        end_date="2026-07-16",
    )

    assert result.ok is True
    assert result.result_state == "VALID_PARTIAL_WINDOW"
    assert result.payload["day_count"] == 1


def test_collect_runtime_video_analytics_true_empty_response(monkeypatch, tmp_path: Path):
    token = tmp_path / "youtube_analytics_token.pickle"
    token.write_bytes(b"x")

    monkeypatch.setattr(shadow, "_resolve_gate_enabled", lambda: True)
    monkeypatch.setattr(shadow, "_resolve_channel_context", lambda channel_slug: _FakeContext(token))
    monkeypatch.setattr(shadow, "_load_credentials_read_only", lambda token_path: _FakeCreds())
    monkeypatch.setattr(shadow, "_credentials_scope_ok", lambda credentials: True)
    monkeypatch.setattr(
        shadow,
        "_build_service",
        lambda credentials, timeout_seconds: _FakeService(
            {
                "columnHeaders": [
                    {"name": "video"},
                    {"name": "views"},
                    {"name": "estimatedMinutesWatched"},
                    {"name": "averageViewDuration"},
                    {"name": "averageViewPercentage"},
                    {"name": "subscribersGained"},
                    {"name": "subscribersLost"},
                ],
                "rows": [],
            }
        ),
    )

    result = shadow.collect_runtime_video_analytics(
        channel_id="para_pusulasi",
        video_id="vid_1",
        start_date="2026-07-10",
        end_date="2026-07-16",
    )

    assert result.ok is False
    assert result.result_state == "TRUE_EMPTY_RESPONSE"


def test_deterministic_record_id(monkeypatch, tmp_path: Path):
    _mock_success_collection(monkeypatch, tmp_path)

    collection = shadow.collect_runtime_video_analytics(
        channel_id="para_pusulasi",
        video_id="vid_1",
        start_date="2026-07-10",
        end_date="2026-07-16",
    )

    first = shadow.build_runtime_canonical_record(
        collection=collection,
        channel_id="para_pusulasi",
        content_id="content_1",
        run_id="run_1",
        video_id="vid_1",
    )
    second = shadow.build_runtime_canonical_record(
        collection=collection,
        channel_id="para_pusulasi",
        content_id="content_1",
        run_id="run_1",
        video_id="vid_1",
    )

    assert first["analytics_record_id"] == second["analytics_record_id"]


def test_append_only_idempotency_and_duplicate_prevention(monkeypatch, tmp_path: Path):
    _mock_success_collection(monkeypatch, tmp_path)
    out = tmp_path / "canonical.jsonl"

    collection = shadow.collect_runtime_video_analytics(
        channel_id="para_pusulasi",
        video_id="vid_1",
        start_date="2026-07-10",
        end_date="2026-07-16",
    )
    record = shadow.build_runtime_canonical_record(
        collection=collection,
        channel_id="para_pusulasi",
        content_id="content_1",
        run_id="run_1",
        video_id="vid_1",
    )

    first = shadow.append_runtime_canonical_records(rows=[record], output_path=out)
    second = shadow.append_runtime_canonical_records(rows=[record], output_path=out)

    assert first["appended"] == 1
    assert second["duplicates"] == 1

    lines = [line for line in out.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 1


def test_validator_rejects_malformed_payload(tmp_path: Path):
    out = tmp_path / "canonical.jsonl"
    malformed = {
        "schema_version": "v1",
        "analytics_record_id": "car_bad",
        "provider": "FutureOfficialYouTubeProvider",
        "source_row_number": 1,
        "content_type": "UNKNOWN",
        "imported_at": datetime.now(timezone.utc).isoformat(),
        "metrics_version": "v1",
        "provenance": {},
        "advisory_only": False,
        "pipeline_output_changed": False,
        "metrics": {},
    }

    report = shadow.append_runtime_canonical_records(rows=[malformed], output_path=out)
    assert report["invalid_rows"] == 1
    assert not out.exists()


def test_deterministic_serialization_and_replay(monkeypatch, tmp_path: Path):
    _mock_success_collection(monkeypatch, tmp_path)
    out = tmp_path / "canonical.jsonl"

    collection = shadow.collect_runtime_video_analytics(
        channel_id="para_pusulasi",
        video_id="vid_1",
        start_date="2026-07-10",
        end_date="2026-07-16",
    )
    record = shadow.build_runtime_canonical_record(
        collection=collection,
        channel_id="para_pusulasi",
        content_id="content_1",
        run_id="run_1",
        video_id="vid_1",
    )

    shadow.append_runtime_canonical_records(rows=[record], output_path=out)
    decoded = json.loads(out.read_text(encoding="utf-8").strip())
    assert list(decoded.keys()) == sorted(decoded.keys())

    first_replay = shadow.replay_runtime_canonical_rows(output_path=out)
    second_replay = shadow.replay_runtime_canonical_rows(output_path=out)
    assert first_replay["digest"] == second_replay["digest"]


def test_shadow_execution_disabled(monkeypatch):
    monkeypatch.delenv(shadow.RUNTIME_SHADOW_FLAG, raising=False)
    report = shadow.run_pipeline_runtime_canonical_shadow(
        channel_id="para_pusulasi",
        content_id="content_1",
        run_id="run_1",
        video_id="vid_1",
    )
    assert report["status"] == "shadow_disabled"


def test_shadow_execution_runtime_compatibility(monkeypatch, tmp_path: Path):
    monkeypatch.setenv(shadow.RUNTIME_SHADOW_FLAG, "true")
    monkeypatch.setattr(
        shadow,
        "collect_runtime_video_analytics",
        lambda **kwargs: shadow.RuntimeCollectorResult(
            ok=False,
            result_state="API_NOT_ENABLED",
            error_class="API_NOT_ENABLED",
            redacted_error=None,
            payload={},
        ),
    )

    report = shadow.run_pipeline_runtime_canonical_shadow(
        channel_id="para_pusulasi",
        content_id="content_1",
        run_id="run_1",
        video_id="vid_1",
        output_path=tmp_path / "canonical.jsonl",
    )

    assert report["status"] == "shadow_collect_failed"
    assert report["result_state"] == "API_NOT_ENABLED"


def test_resolve_effective_window_uses_available_days(monkeypatch):
    now = datetime.fromisoformat("2026-07-17T12:00:00+00:00")

    start, end, day_count = shadow._resolve_effective_window(
        now_date=now.date(),
        requested_days=7,
        earliest_valid_date="2026-07-16",
    )

    assert start == "2026-07-16"
    assert end == "2026-07-17"
    assert day_count == 2


def test_bridge_public_record_id_seam_is_deterministic() -> None:
    first = build_canonical_record_id(
        provider="FutureOfficialYouTubeProvider",
        source_file_hash="hash_1",
        source_row_number=1,
        youtube_video_id="vid_1",
        snapshot_start="2026-07-10",
        snapshot_end="2026-07-16",
        metrics_version="v1",
    )
    second = build_canonical_record_id(
        provider="FutureOfficialYouTubeProvider",
        source_file_hash="hash_1",
        source_row_number=1,
        youtube_video_id="vid_1",
        snapshot_start="2026-07-10",
        snapshot_end="2026-07-16",
        metrics_version="v1",
    )
    assert first == second
    assert first.startswith("car_")
