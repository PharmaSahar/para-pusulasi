from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from src.google_http_transport_adapter import HttpRequestModel, HttpResponseModel
from src.google_oauth_credentials import OAuthCredentialLease
from src.google_provider_integration import (
    GoogleEndpointDescriptor,
    GoogleEndpointRegistry,
    GoogleParserRegistry,
    GoogleResponseParser,
)
from src.http_execution_layer import ExecutionResult
from src.live_transport_contract import TransportResponse
from src.youtube_analytics_live_client import (
    AnalyticsLiveClient,
    AnalyticsRequestBuilder,
    AnalyticsResponseMapper,
    YouTubeAnalyticsLiveClientError,
)


class _TrackingParser:
    def __init__(self) -> None:
        self.calls: int = 0

    def parse_execution_result(self, result: ExecutionResult) -> TransportResponse:
        self.calls += 1
        return TransportResponse(
            request_identity=result.request_identity,
            endpoint_id=result.endpoint_id,
            payload={"result": "success", "body": {"rows": []}},
            timeout_seconds=result.timeout_seconds,
            retry_metadata=result.retry_metadata,
        )


class _RecordingExecutor:
    def __init__(self, *, payload_text: str = '{"rows": []}', status_code: int = 200) -> None:
        self.payload_text = payload_text
        self.status_code = status_code
        self.calls: list[HttpRequestModel] = []

    def execute(self, *, request: HttpRequestModel, parser) -> ExecutionResult:
        self.calls.append(request)
        response = HttpResponseModel(
            request_identity=request.request_identity,
            endpoint_id=request.endpoint_id,
            status_code=self.status_code,
            payload_text=self.payload_text,
            headers=(),
        )
        parsed = parser.parse(request, response)
        return ExecutionResult(
            request_identity=request.request_identity,
            endpoint_id=request.endpoint_id,
            status_code=response.status_code,
            latency_ms=4,
            timeout_seconds=request.timeout_seconds,
            retry_metadata=request.retry_metadata,
            parsed_response=parsed,
        )


def _lease() -> OAuthCredentialLease:
    return OAuthCredentialLease(
        provider_name="oauth-provider-alpha",
        credential_identity="cred-alpha",
        channel_id="channel_alpha",
        youtube_channel_id="UC-alpha",
        scope_names=("scope-a", "scope-b"),
        issued_at=datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc),
        expires_at=datetime(2026, 7, 24, 13, 0, tzinfo=timezone.utc),
        refresh_supported=True,
        lease_identity="lease-alpha",
        access_token_value="fake_access_token_value_alpha",
        refresh_token_value="fake_refresh_token_value_alpha",
    )


def _endpoint_descriptor() -> GoogleEndpointDescriptor:
    return GoogleEndpointDescriptor(
        endpoint_id="youtube-analytics-reports-query",
        method="GET",
        supported_query_parameters=(
            "ids",
            "startDate",
            "endDate",
            "metrics",
            "dimensions",
            "filters",
            "sort",
            "maxResults",
            "startIndex",
            "currency",
        ),
        parser_name="analytics_parser",
        default_timeout_seconds=30,
        retry_policy_metadata={"max_attempts": 3},
    )


def _build_client(*, execution_backend) -> AnalyticsLiveClient:
    endpoint_registry = GoogleEndpointRegistry(descriptors=[_endpoint_descriptor()])
    parser_registry = GoogleParserRegistry(parsers={"analytics_parser": GoogleResponseParser()})
    return AnalyticsLiveClient(
        endpoint_registry=endpoint_registry,
        parser_registry=parser_registry,
        execution_backend=execution_backend,
    )


def _run_dry(client: AnalyticsLiveClient) -> dict[str, Any]:
    return client.run_dry(
        oauth_lease=_lease(),
        channel_id="channel_alpha",
        youtube_channel_id="UC-alpha",
        start_date="2026-07-01",
        end_date="2026-07-07",
        metrics=("views", "likes"),
        dimensions=("day",),
        filters=("country==US",),
        sort=("-views",),
        max_results=200,
        start_index=1,
        currency="USD",
        timeout_seconds=11,
        retry_metadata={"attempt": 1},
    )


def test_reports_query_request_builder_construction() -> None:
    builder = AnalyticsRequestBuilder(
        endpoint_registry=GoogleEndpointRegistry(descriptors=[_endpoint_descriptor()]),
        endpoint_id="youtube-analytics-reports-query",
    )

    request = builder.build_reports_query_request(
        oauth_lease=_lease(),
        channel_id="channel_alpha",
        youtube_channel_id="UC-alpha",
        start_date="2026-07-01",
        end_date="2026-07-07",
        metrics=("views", "likes"),
        dimensions=("day",),
        filters=("country==US",),
        sort=("-views",),
        max_results=200,
        start_index=1,
        currency="USD",
        timeout_seconds=12,
        retry_metadata={"attempt": 1},
    )

    assert request.method == "GET"
    assert request.url_path == "/youtube/analytics/v2/reports"
    assert request.query_parameters["ids"] == "channel==UC-alpha"
    assert request.query_parameters["startDate"] == "2026-07-01"
    assert request.query_parameters["endDate"] == "2026-07-07"
    assert request.query_parameters["metrics"] == "likes,views"


def test_oauth_lease_injection_redacts_token() -> None:
    builder = AnalyticsRequestBuilder(
        endpoint_registry=GoogleEndpointRegistry(descriptors=[_endpoint_descriptor()]),
        endpoint_id="youtube-analytics-reports-query",
    )

    request = builder.build_reports_query_request(
        oauth_lease=_lease(),
        channel_id="channel_alpha",
        youtube_channel_id="UC-alpha",
        start_date="2026-07-01",
        end_date="2026-07-07",
        metrics=("views",),
        timeout_seconds=9,
    )

    assert request.retry_metadata["oauth_lease_identity"] == "lease-alpha"
    assert str(request.retry_metadata["oauth_token_marker"]).startswith("<redacted:")
    assert "fake_access_token_value_alpha" not in str(request.retry_metadata)


def test_timeout_propagation_to_execution_backend() -> None:
    recorder = _RecordingExecutor(payload_text='{"rows": []}', status_code=200)
    client = _build_client(execution_backend=recorder)

    _run_dry(client)

    assert len(recorder.calls) == 1
    assert recorder.calls[0].timeout_seconds == 11


def test_parser_dispatch_is_used() -> None:
    tracker = _TrackingParser()
    endpoint_registry = GoogleEndpointRegistry(descriptors=[_endpoint_descriptor()])
    parser_registry = GoogleParserRegistry(parsers={"analytics_parser": tracker})
    client = AnalyticsLiveClient(
        endpoint_registry=endpoint_registry,
        parser_registry=parser_registry,
        execution_backend=_RecordingExecutor(payload_text='{"rows": []}'),
    )

    output = _run_dry(client)

    assert output["status"] == "success"
    assert tracker.calls == 1


def test_deterministic_dry_run_execution() -> None:
    client = _build_client(
        execution_backend=_RecordingExecutor(
            payload_text='{"rows": [{"day": "2026-07-01", "views": 10}]}'
        )
    )

    first = _run_dry(client)
    second = _run_dry(client)

    assert first == second
    assert first["row_count"] == 1


def test_response_mapping_empty_response() -> None:
    mapper = AnalyticsResponseMapper()
    mapped = mapper.map(
        TransportResponse(
            request_identity="req-1",
            endpoint_id="youtube-analytics-reports-query",
            payload={"result": "success", "body": {}},
            timeout_seconds=7,
            retry_metadata={"attempt": 1},
        )
    )
    assert mapped["row_count"] == 0
    assert mapped["rows"] == ()


def test_retryable_error_is_exposed() -> None:
    recorder = _RecordingExecutor(payload_text='{"error": "rate"}', status_code=429)
    client = _build_client(execution_backend=recorder)

    with pytest.raises(YouTubeAnalyticsLiveClientError) as exc_info:
        _run_dry(client)

    assert exc_info.value.category == "RETRYABLE_ERROR"
    assert exc_info.value.retryable is True


def test_permanent_error_is_exposed() -> None:
    recorder = _RecordingExecutor(payload_text='{"error": "forbidden"}', status_code=403)
    client = _build_client(execution_backend=recorder)

    with pytest.raises(YouTubeAnalyticsLiveClientError) as exc_info:
        _run_dry(client)

    assert exc_info.value.category == "PERMANENT_ERROR"
    assert exc_info.value.retryable is False


def test_malformed_payload_is_exposed() -> None:
    recorder = _RecordingExecutor(payload_text="not-json", status_code=200)
    client = _build_client(execution_backend=recorder)

    with pytest.raises(YouTubeAnalyticsLiveClientError) as exc_info:
        _run_dry(client)

    assert exc_info.value.category == "MALFORMED_PAYLOAD"


def test_channel_mismatch_rejected() -> None:
    builder = AnalyticsRequestBuilder(
        endpoint_registry=GoogleEndpointRegistry(descriptors=[_endpoint_descriptor()]),
        endpoint_id="youtube-analytics-reports-query",
    )

    with pytest.raises(ValueError):
        builder.build_reports_query_request(
            oauth_lease=_lease(),
            channel_id="channel_other",
            youtube_channel_id="UC-alpha",
            start_date="2026-07-01",
            end_date="2026-07-07",
            metrics=("views",),
            timeout_seconds=10,
        )


def test_no_write_or_scheduler_behaviors_in_source() -> None:
    source = Path("src/youtube_analytics_live_client.py").read_text(encoding="utf-8").lower()
    forbidden = [
        "scheduler",
        "upload",
        "snapshot",
        "dashboard",
        "deploy",
        "write_text(",
        ".write(",
        "open(",
    ]
    for token in forbidden:
        assert token not in source
