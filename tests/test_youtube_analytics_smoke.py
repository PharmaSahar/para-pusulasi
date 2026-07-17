from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from googleapiclient.errors import HttpError

import src.youtube_analytics_smoke as smoke


class FakeCreds:
    def __init__(self, *, valid: bool = True, expired: bool = False, scopes: list[str] | None = None):
        self.valid = valid
        self.expired = expired
        self.scopes = scopes or [
            "https://www.googleapis.com/auth/yt-analytics.readonly",
            "https://www.googleapis.com/auth/youtube.readonly",
        ]

    def has_scopes(self, scopes):
        return set(scopes).issubset(set(self.scopes))


class FakeQuery:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.kwargs = None

    def execute(self, num_retries=0):
        assert num_retries == 0
        if self.error is not None:
            raise self.error
        return self.response


class FakeReports:
    def __init__(self, query: FakeQuery):
        self.query_obj = query

    def query(self, **kwargs):
        self.query_obj.kwargs = kwargs
        return self.query_obj


class FakeService:
    def __init__(self, query: FakeQuery):
        self._reports = FakeReports(query)

    def reports(self):
        return self._reports


def _channel_config(
    tmp_path: Path,
    *,
    analytics_token_exists: bool = True,
    uploader_token_exists: bool = False,
):
    analytics_token_path = tmp_path / "youtube_analytics_token.pickle"
    uploader_token_path = tmp_path / "youtube_token.pickle"
    if analytics_token_exists:
        analytics_token_path.write_bytes(b"analytics")
    if uploader_token_exists:
        uploader_token_path.write_bytes(b"uploader")
    return SimpleNamespace(
        channel_id="para_pusulasi",
        youtube_channel_id="UC6tU7UqYylfSA75pj3rEY_Q",
        youtube_analytics_token_path=str(analytics_token_path),
        token_path=str(uploader_token_path),
        client_secrets_path=str(tmp_path / "client_secrets.json"),
    )


def _patch_channel(monkeypatch, cfg):
    monkeypatch.setattr(smoke, "get_channel", lambda channel_slug: cfg)


def _http_error(status: int, message: str) -> HttpError:
    return HttpError(SimpleNamespace(status=status, reason=message), f'{{"error":{{"message":"{message}"}}}}'.encode("utf-8"))


def test_valid_one_channel_request(monkeypatch, tmp_path):
    cfg = _channel_config(tmp_path)
    _patch_channel(monkeypatch, cfg)
    monkeypatch.setenv("YOUTUBE_ANALYTICS_API_GO", "true")
    monkeypatch.setattr(smoke, "_load_credentials_read_only", lambda token_path: FakeCreds())
    query = FakeQuery(
        response={
            "columnHeaders": [
                {"name": "day"},
                {"name": "views"},
                {"name": "estimatedMinutesWatched"},
                {"name": "averageViewDuration"},
                {"name": "averageViewPercentage"},
                {"name": "impressions"},
                {"name": "impressionClickThroughRate"},
                {"name": "subscribersGained"},
                {"name": "subscribersLost"},
            ],
            "rows": [["2026-07-01", "120", "240.5", "45.0", "55.5", "900", "0.05", "3", "1"]],
        }
    )
    monkeypatch.setattr(smoke, "_build_service", lambda credentials, timeout_seconds: FakeService(query))

    report = smoke.run_read_only_smoke_and_write(
        channel_slugs=["para_pusulasi"],
        start_date="2026-07-01",
        end_date="2026-07-07",
        output_path=tmp_path / "smoke.json",
        timeout_seconds=7,
    )

    assert report["result_state"] == "SUCCESS"
    assert report["row_count"] == 1
    assert report["selected_token_source"] == "ANALYTICS_TOKEN_PRIMARY"
    assert report["normalized_rows"][0]["views"] == 120
    assert report["mutation_attempted"] is False
    assert json.loads((tmp_path / "smoke.json").read_text(encoding="utf-8"))["output_hash"] == report["output_hash"]


def test_missing_primary_token_does_not_use_uploader_fallback(monkeypatch, tmp_path):
    cfg = _channel_config(tmp_path, analytics_token_exists=False, uploader_token_exists=True)
    _patch_channel(monkeypatch, cfg)
    monkeypatch.setenv("YOUTUBE_ANALYTICS_API_GO", "true")

    loaded_paths: list[str] = []

    def _load(token_path):
        loaded_paths.append(str(token_path))
        return FakeCreds()

    monkeypatch.setattr(smoke, "_load_credentials_read_only", _load)
    query = FakeQuery(response={"columnHeaders": [{"name": "day"}, {"name": "views"}], "rows": [["2026-07-01", "1"]]})
    monkeypatch.setattr(smoke, "_build_service", lambda credentials, timeout_seconds: FakeService(query))

    report = smoke.run_read_only_smoke(
        channel_slugs=["para_pusulasi"],
        start_date="2026-07-01",
        end_date="2026-07-07",
        output_path=tmp_path / "smoke.json",
    )

    assert report["result_state"] == "TOKEN_MISSING"
    assert report["selected_token_source"] == "NONE"
    assert loaded_paths == []


def test_primary_token_selected_when_present(monkeypatch, tmp_path):
    cfg = _channel_config(tmp_path, analytics_token_exists=True, uploader_token_exists=True)
    _patch_channel(monkeypatch, cfg)
    monkeypatch.setenv("YOUTUBE_ANALYTICS_API_GO", "true")

    loaded_paths: list[str] = []

    def _load(token_path):
        loaded_paths.append(str(token_path))
        return FakeCreds()

    monkeypatch.setattr(smoke, "_load_credentials_read_only", _load)
    query = FakeQuery(response={"columnHeaders": [{"name": "day"}, {"name": "views"}], "rows": [["2026-07-01", "1"]]})
    monkeypatch.setattr(smoke, "_build_service", lambda credentials, timeout_seconds: FakeService(query))

    report = smoke.run_read_only_smoke(
        channel_slugs=["para_pusulasi"],
        start_date="2026-07-01",
        end_date="2026-07-07",
        output_path=tmp_path / "smoke.json",
    )

    assert report["result_state"] == "SUCCESS"
    assert report["selected_token_source"] == "ANALYTICS_TOKEN_PRIMARY"
    assert loaded_paths == [cfg.youtube_analytics_token_path]


def test_both_token_paths_missing_returns_token_missing(monkeypatch, tmp_path):
    cfg = _channel_config(tmp_path, analytics_token_exists=False, uploader_token_exists=False)
    _patch_channel(monkeypatch, cfg)
    monkeypatch.setenv("YOUTUBE_ANALYTICS_API_GO", "true")

    report = smoke.run_read_only_smoke(
        channel_slugs=["para_pusulasi"],
        start_date="2026-07-01",
        end_date="2026-07-07",
        output_path=tmp_path / "smoke.json",
    )

    assert report["result_state"] == "TOKEN_MISSING"
    assert report["selected_token_source"] == "NONE"


def test_missing_primary_token_reports_missing_even_if_uploader_scope_is_valid(monkeypatch, tmp_path):
    cfg = _channel_config(tmp_path, analytics_token_exists=False, uploader_token_exists=True)
    _patch_channel(monkeypatch, cfg)
    monkeypatch.setenv("YOUTUBE_ANALYTICS_API_GO", "true")
    monkeypatch.setattr(
        smoke,
        "_load_credentials_read_only",
        lambda token_path: FakeCreds(scopes=["https://www.googleapis.com/auth/youtube.upload"]),
    )

    report = smoke.run_read_only_smoke(
        channel_slugs=["para_pusulasi"],
        start_date="2026-07-01",
        end_date="2026-07-07",
        output_path=tmp_path / "smoke.json",
    )

    assert report["selected_token_source"] == "NONE"
    assert report["result_state"] == "TOKEN_MISSING"


def test_maximum_seven_day_window(monkeypatch, tmp_path):
    assert smoke._validate_date_window("2026-07-01", "2026-07-07") == ("2026-07-01", "2026-07-07")
    with pytest.raises(ValueError, match="window_exceeds_seven_days"):
        smoke._validate_date_window("2026-07-01", "2026-07-08")


@pytest.mark.parametrize(
    "start_date,end_date",
    [
        ("2026-07-08", "2026-07-01"),
        ("2026-07-01", "2026-07-08"),
    ],
)
def test_invalid_date_window(start_date, end_date, tmp_path):
    report = smoke.run_read_only_smoke(
        channel_slugs=["para_pusulasi"],
        start_date=start_date,
        end_date=end_date,
        output_path=tmp_path / "smoke.json",
    )

    assert report["result_state"] == "INVALID_DATE_WINDOW"


def test_missing_channel(tmp_path):
    report = smoke.run_read_only_smoke(
        channel_slugs=[],
        start_date="2026-07-01",
        end_date="2026-07-07",
        output_path=tmp_path / "smoke.json",
    )

    assert report["result_state"] == "CHANNEL_MAPPING_ERROR"


def test_unknown_channel(monkeypatch, tmp_path):
    monkeypatch.setattr(smoke, "get_channel", lambda channel_slug: (_ for _ in ()).throw(ValueError("missing")))
    report = smoke.run_read_only_smoke(
        channel_slugs=["unknown"],
        start_date="2026-07-01",
        end_date="2026-07-07",
        output_path=tmp_path / "smoke.json",
    )

    assert report["result_state"] == "CHANNEL_MAPPING_ERROR"


def test_missing_credentials(monkeypatch, tmp_path):
    cfg = _channel_config(tmp_path, analytics_token_exists=False, uploader_token_exists=False)
    _patch_channel(monkeypatch, cfg)
    monkeypatch.setenv("YOUTUBE_ANALYTICS_API_GO", "true")
    monkeypatch.setattr(smoke, "_load_credentials_read_only", lambda token_path: None)

    report = smoke.run_read_only_smoke(
        channel_slugs=["para_pusulasi"],
        start_date="2026-07-01",
        end_date="2026-07-07",
        output_path=tmp_path / "smoke.json",
    )

    assert report["result_state"] == "TOKEN_MISSING"
    assert report["selected_token_source"] == "NONE"


def test_missing_token(monkeypatch, tmp_path):
    cfg = _channel_config(tmp_path, analytics_token_exists=False, uploader_token_exists=False)
    _patch_channel(monkeypatch, cfg)
    monkeypatch.setenv("YOUTUBE_ANALYTICS_API_GO", "true")

    report = smoke.run_read_only_smoke(
        channel_slugs=["para_pusulasi"],
        start_date="2026-07-01",
        end_date="2026-07-07",
        output_path=tmp_path / "smoke.json",
    )

    assert report["result_state"] == "TOKEN_MISSING"
    assert report["selected_token_source"] == "NONE"


def test_api_disabled_response(monkeypatch, tmp_path):
    cfg = _channel_config(tmp_path)
    _patch_channel(monkeypatch, cfg)
    monkeypatch.setenv("YOUTUBE_ANALYTICS_API_GO", "true")
    monkeypatch.setattr(smoke, "_load_credentials_read_only", lambda token_path: FakeCreds())

    error = _http_error(403, "API not enabled")
    query = FakeQuery(error=error)
    monkeypatch.setattr(smoke, "_build_service", lambda credentials, timeout_seconds: FakeService(query))

    report = smoke.run_read_only_smoke(
        channel_slugs=["para_pusulasi"],
        start_date="2026-07-01",
        end_date="2026-07-07",
        output_path=tmp_path / "smoke.json",
    )

    assert report["result_state"] == "API_NOT_ENABLED"


@pytest.mark.parametrize(
    "status,message,expected",
    [
        (401, "Unauthorized", "AUTHENTICATION_BLOCKED"),
        (403, "quotaExceeded", "QUOTA_BLOCKED"),
        (403, "insufficient permissions", "API_SCOPE_INSUFFICIENT"),
        (429, "rate limit", "QUOTA_BLOCKED"),
    ],
)
def test_http_error_classification(monkeypatch, tmp_path, status, message, expected):
    cfg = _channel_config(tmp_path)
    _patch_channel(monkeypatch, cfg)
    monkeypatch.setenv("YOUTUBE_ANALYTICS_API_GO", "true")
    monkeypatch.setattr(smoke, "_load_credentials_read_only", lambda token_path: FakeCreds())
    error = _http_error(status, message)
    query = FakeQuery(error=error)
    monkeypatch.setattr(smoke, "_build_service", lambda credentials, timeout_seconds: FakeService(query))

    report = smoke.run_read_only_smoke(
        channel_slugs=["para_pusulasi"],
        start_date="2026-07-01",
        end_date="2026-07-07",
        output_path=tmp_path / "smoke.json",
    )

    assert report["result_state"] == expected


def test_empty_response(monkeypatch, tmp_path):
    cfg = _channel_config(tmp_path)
    _patch_channel(monkeypatch, cfg)
    monkeypatch.setenv("YOUTUBE_ANALYTICS_API_GO", "true")
    monkeypatch.setattr(smoke, "_load_credentials_read_only", lambda token_path: FakeCreds())
    query = FakeQuery(response={"columnHeaders": [{"name": "day"}, {"name": "views"}], "rows": []})
    monkeypatch.setattr(smoke, "_build_service", lambda credentials, timeout_seconds: FakeService(query))

    report = smoke.run_read_only_smoke(
        channel_slugs=["para_pusulasi"],
        start_date="2026-07-01",
        end_date="2026-07-07",
        output_path=tmp_path / "smoke.json",
    )

    assert report["result_state"] == "EMPTY_RESPONSE"


def test_deterministic_normalization_and_hash(monkeypatch, tmp_path):
    cfg = _channel_config(tmp_path)
    _patch_channel(monkeypatch, cfg)
    monkeypatch.setenv("YOUTUBE_ANALYTICS_API_GO", "true")
    monkeypatch.setattr(smoke, "_load_credentials_read_only", lambda token_path: FakeCreds())
    fixed = {
        "columnHeaders": [{"name": "day"}, {"name": "views"}],
        "rows": [["2026-07-01", "3"]],
    }
    query = FakeQuery(response=fixed)
    monkeypatch.setattr(smoke, "_build_service", lambda credentials, timeout_seconds: FakeService(query))
    monkeypatch.setattr(smoke, "_now_iso", lambda: "2026-07-15T12:00:00+00:00")

    first = smoke.run_read_only_smoke_and_write(
        channel_slugs=["para_pusulasi"],
        start_date="2026-07-01",
        end_date="2026-07-07",
        output_path=tmp_path / "first.json",
    )
    second = smoke.run_read_only_smoke_and_write(
        channel_slugs=["para_pusulasi"],
        start_date="2026-07-01",
        end_date="2026-07-07",
        output_path=tmp_path / "second.json",
    )

    assert first["normalized_rows"] == second["normalized_rows"]
    assert first["output_hash"] == second["output_hash"]


def test_secret_redaction(tmp_path):
    message = "access_token=ya29.secret refresh_token=abc client_secret=def /private/path"
    redacted = smoke._redact_error(message)
    assert "ya29.secret" not in redacted
    assert "refresh_token" in redacted
    assert "[REDACTED]" in redacted


def test_no_uploader_or_scheduler_mutation_text():
    source = Path("src/youtube_analytics_smoke.py").read_text(encoding="utf-8")
    forbidden = [
        "youtube_uploader",
        "youtube_auth",
        "update_production_dashboard",
        "write_production_evidence",
        "append_performance_snapshot",
        "scheduler.py",
        "InstalledAppFlow",
        "run_local_server",
        "pickle.dump",
        "credentials.refresh",
        "thumbnails.set",
        "videos.insert",
        "videos.update",
        "videos.delete",
        "playlistItems.insert",
        "playlistItems.delete",
        "channels.update",
        "captions.insert",
        "comments.insert",
        "liveBroadcasts.insert",
    ]
    for needle in forbidden:
        assert needle not in source


def test_cli_exit_codes(monkeypatch, tmp_path):
    cfg = _channel_config(tmp_path)
    _patch_channel(monkeypatch, cfg)
    monkeypatch.setenv("YOUTUBE_ANALYTICS_API_GO", "true")
    monkeypatch.setattr(smoke, "_load_credentials_read_only", lambda token_path: FakeCreds())
    query = FakeQuery(response={"columnHeaders": [{"name": "day"}, {"name": "views"}], "rows": [["2026-07-01", "1"]]})
    monkeypatch.setattr(smoke, "_build_service", lambda credentials, timeout_seconds: FakeService(query))

    ok = smoke.main([
        "--channel",
        "para_pusulasi",
        "--start-date",
        "2026-07-01",
        "--end-date",
        "2026-07-07",
        "--output",
        str(tmp_path / "smoke.json"),
        "--timeout-seconds",
        "7",
    ])
    bad = smoke.main([
        "--channel",
        "para_pusulasi",
        "--channel",
        "borsa_akademi",
        "--start-date",
        "2026-07-01",
        "--end-date",
        "2026-07-07",
        "--output",
        str(tmp_path / "bad.json"),
    ])

    assert ok == 0
    assert bad != 0


def test_selected_token_source_is_redacted_alias(monkeypatch, tmp_path):
    cfg = _channel_config(tmp_path, analytics_token_exists=False, uploader_token_exists=True)
    _patch_channel(monkeypatch, cfg)
    monkeypatch.setenv("YOUTUBE_ANALYTICS_API_GO", "true")
    monkeypatch.setattr(smoke, "_load_credentials_read_only", lambda token_path: None)

    report = smoke.run_read_only_smoke(
        channel_slugs=["para_pusulasi"],
        start_date="2026-07-01",
        end_date="2026-07-07",
        output_path=tmp_path / "smoke.json",
    )

    assert report["selected_token_source"] in {
        "ANALYTICS_TOKEN_PRIMARY",
        "NONE",
    }
    assert str(tmp_path) not in report["selected_token_source"]
