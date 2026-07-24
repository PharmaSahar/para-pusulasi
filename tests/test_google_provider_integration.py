from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.authorized_transport_binding import AuthorizedTransportRequest
from src.google_provider_integration import (
    GoogleEndpointDescriptor,
    GoogleEndpointRegistry,
    GoogleParserRegistry,
    GoogleProviderIntegrationError,
    GoogleRequestBuilder,
    GoogleResponseParser,
)
from src.http_execution_layer import ExecutionResult
from src.live_transport_contract import TransportRequest, TransportResponse
from src.runtime_credential_contract import RuntimeCredentialLease


def _transport_request() -> TransportRequest:
    return TransportRequest(
        request_identity="req-g-001",
        endpoint_id="google-analytics-reports",
        query_parameters={"metrics": "views", "channel_id": "channel_alpha", "drop_me": "x"},
        timeout_seconds=15,
        retry_metadata={"attempt": 1},
    )


def _authorized_request() -> AuthorizedTransportRequest:
    request = _transport_request()
    lease = RuntimeCredentialLease(
        provider_name="google-provider-offline",
        credential_identity="cred-alpha",
        channel_id="channel_alpha",
        youtube_channel_id="UC-alpha",
        scope_names=("scope-a", "scope-b"),
        issued_at=datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc),
        expires_at=datetime(2026, 7, 24, 13, 0, tzinfo=timezone.utc),
        refresh_supported=True,
        lease_identity="lease-g-001",
        secret_value="test-runtime-secret",
    )
    return AuthorizedTransportRequest(
        request=request,
        request_identity=request.request_identity,
        credential_identity="cred-alpha",
        lease_identity="lease-g-001",
        provider_name="google-provider-offline",
        channel_id="channel_alpha",
        youtube_channel_id="UC-alpha",
        scope_names=("scope-a", "scope-b"),
        expires_at=datetime(2026, 7, 24, 13, 0, tzinfo=timezone.utc),
        binding_identity="binding-g-001",
        _lease=lease,
    )


def _descriptor() -> GoogleEndpointDescriptor:
    return GoogleEndpointDescriptor(
        endpoint_id="google-analytics-reports",
        method="GET",
        supported_query_parameters=("channel_id", "metrics"),
        parser_name="analytics_parser",
        default_timeout_seconds=20,
        retry_policy_metadata={"max_attempts": 3},
    )


def _execution_result(status_code: int, payload_text: str) -> ExecutionResult:
    request = _transport_request()
    parsed_response = TransportResponse(
        request_identity=request.request_identity,
        endpoint_id=request.endpoint_id,
        payload={"payload_text": payload_text},
        timeout_seconds=request.timeout_seconds,
        retry_metadata=request.retry_metadata,
    )
    return ExecutionResult(
        request_identity=request.request_identity,
        endpoint_id=request.endpoint_id,
        status_code=status_code,
        latency_ms=5,
        timeout_seconds=request.timeout_seconds,
        retry_metadata=request.retry_metadata,
        parsed_response=parsed_response,
    )


def test_endpoint_registry_and_lookup() -> None:
    registry = GoogleEndpointRegistry(descriptors=[_descriptor()])
    selected = registry.get("google-analytics-reports")
    assert selected.endpoint_id == "google-analytics-reports"


def test_unknown_endpoint_lookup_fails() -> None:
    registry = GoogleEndpointRegistry(descriptors=[_descriptor()])
    with pytest.raises(GoogleProviderIntegrationError) as exc_info:
        registry.get("unknown")
    assert exc_info.value.category == "INVALID_REQUEST"


def test_request_builder_and_determinism() -> None:
    registry = GoogleEndpointRegistry(descriptors=[_descriptor()])
    builder = GoogleRequestBuilder(endpoint_registry=registry)
    authorized = _authorized_request()

    first = builder.build(authorized)
    second = builder.build(authorized)

    assert first == second
    assert first.http_request.url_path == "/offline/google/google-analytics-reports"
    assert first.http_request.query_parameters == {"channel_id": "channel_alpha", "metrics": "views"}


def test_request_builder_has_no_secret_or_auth_header() -> None:
    registry = GoogleEndpointRegistry(descriptors=[_descriptor()])
    builder = GoogleRequestBuilder(endpoint_registry=registry)
    execution_request = builder.build(_authorized_request())

    assert execution_request.http_request.headers == ()
    assert "authorization" not in str(execution_request.http_request.headers).lower()
    assert "test-runtime-secret" not in str(execution_request.http_request.query_parameters)


def test_immutable_models() -> None:
    descriptor = _descriptor()
    with pytest.raises(AttributeError):
        descriptor.method = "POST"

    registry = GoogleEndpointRegistry(descriptors=[_descriptor()])
    request = GoogleRequestBuilder(endpoint_registry=registry).build(_authorized_request())
    with pytest.raises(AttributeError):
        request.parser_name = "changed"


def test_parser_dispatch_success() -> None:
    parser = GoogleResponseParser()
    registry = GoogleParserRegistry(parsers={"analytics_parser": parser})
    result = _execution_result(200, '{"rows": []}')

    parsed = registry.dispatch(parser_name="analytics_parser", result=result)
    assert parsed.payload["result"] == "success"


def test_success_parsing() -> None:
    parser = GoogleResponseParser()
    parsed = parser.parse_execution_result(_execution_result(200, '{"views": 10}'))
    assert parsed.payload["body"]["views"] == 10


def test_retryable_error_parsing() -> None:
    parser = GoogleResponseParser()
    with pytest.raises(GoogleProviderIntegrationError) as exc_info:
        parser.parse_execution_result(_execution_result(429, '{"error": "rate"}'))
    assert exc_info.value.category == "RETRYABLE_ERROR"


def test_permanent_error_parsing() -> None:
    parser = GoogleResponseParser()
    with pytest.raises(GoogleProviderIntegrationError) as exc_info:
        parser.parse_execution_result(_execution_result(403, '{"error": "forbidden"}'))
    assert exc_info.value.category == "PERMANENT_ERROR"


def test_malformed_payload_parsing() -> None:
    parser = GoogleResponseParser()
    with pytest.raises(GoogleProviderIntegrationError) as exc_info:
        parser.parse_execution_result(_execution_result(200, "not-json"))
    assert exc_info.value.category == "MALFORMED_PAYLOAD"


def test_parser_registry_unknown_parser() -> None:
    registry = GoogleParserRegistry(parsers={})
    with pytest.raises(GoogleProviderIntegrationError) as exc_info:
        registry.dispatch(parser_name="missing", result=_execution_result(200, "{}"))
    assert exc_info.value.category == "INVALID_REQUEST"


def test_no_http_socket_or_google_network_imports() -> None:
    source = Path("src/google_provider_integration.py").read_text(encoding="utf-8").lower()
    forbidden = ["requests", "urllib", "aiohttp", "httpx", "httplib2", "socket", "googleapiclient", "google.auth"]
    for token in forbidden:
        assert token not in source
