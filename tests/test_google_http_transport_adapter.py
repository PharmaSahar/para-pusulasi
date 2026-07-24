from __future__ import annotations

from pathlib import Path

import pytest

from src.google_http_transport_adapter import (
    GoogleHttpTransportAdapter,
    HttpRequestModel,
    HttpResponseModel,
    HttpResponseParser,
)
from src.live_transport_contract import TransportError, TransportRequest, TransportResponse


class _FakeParser:
    def __init__(self) -> None:
        self.calls: list[tuple[TransportRequest, HttpResponseModel]] = []

    def parse(self, request: TransportRequest, response: HttpResponseModel) -> TransportResponse:
        self.calls.append((request, response))
        return TransportResponse.from_request(
            request,
            payload={
                "parsed": True,
                "status_code": response.status_code,
                "response_endpoint_id": response.endpoint_id,
            },
        )


def _request() -> TransportRequest:
    return TransportRequest(
        request_identity="req-100",
        endpoint_id="analytics-reports",
        query_parameters={"channel_id": "channel_alpha", "metrics": "views"},
        timeout_seconds=12,
        retry_metadata={"attempt": 1, "backoff_seconds": 0},
    )


def _adapter(parser: HttpResponseParser | None = None) -> GoogleHttpTransportAdapter:
    return GoogleHttpTransportAdapter(
        endpoint_mapping={"analytics-reports": "/youtube/analytics/v2/reports"},
        parser_registry={"analytics-reports": parser or _FakeParser()},
    )


def test_adapter_construction() -> None:
    adapter = _adapter()
    assert isinstance(adapter, GoogleHttpTransportAdapter)


def test_http_request_model_is_immutable() -> None:
    model = HttpRequestModel(
        request_identity="req-100",
        endpoint_id="analytics-reports",
        method="GET",
        url_path="/youtube/analytics/v2/reports",
        query_parameters={"metrics": "views"},
        timeout_seconds=10,
        retry_metadata={"attempt": 1},
    )
    with pytest.raises(AttributeError):
        model.method = "POST"


def test_http_response_model_is_immutable() -> None:
    model = HttpResponseModel(
        request_identity="req-100",
        endpoint_id="analytics-reports",
        status_code=200,
        payload_text='{"ok": true}',
    )
    with pytest.raises(AttributeError):
        model.status_code = 500


def test_deterministic_mapping() -> None:
    adapter = _adapter()
    request = _request()
    first = adapter.build_http_request(request)
    second = adapter.build_http_request(request)

    assert first == second
    assert first.request_identity == "req-100"
    assert first.url_path == "/youtube/analytics/v2/reports"


def test_mapping_preserves_timeout_and_retry_metadata() -> None:
    adapter = _adapter()
    request = _request()
    model = adapter.build_http_request(request)

    assert model.timeout_seconds == request.timeout_seconds
    assert model.retry_metadata == request.retry_metadata
    assert model.query_parameters == request.query_parameters


def test_unknown_endpoint_raises_invalid_request() -> None:
    adapter = GoogleHttpTransportAdapter(endpoint_mapping={}, parser_registry={})

    with pytest.raises(TransportError) as exc_info:
        adapter.build_http_request(_request())

    assert exc_info.value.category == "INVALID_REQUEST"


def test_parser_dispatch() -> None:
    parser = _FakeParser()
    adapter = _adapter(parser)
    request = _request()
    response = HttpResponseModel(
        request_identity="req-100",
        endpoint_id="analytics-reports",
        status_code=200,
        payload_text='{"rows": []}',
    )

    parsed = adapter.parse_http_response(request, response)

    assert parsed.payload["parsed"] is True
    assert len(parser.calls) == 1


def test_dependency_injection_custom_parser() -> None:
    class CustomParser:
        def parse(self, request: TransportRequest, response: HttpResponseModel) -> TransportResponse:
            return TransportResponse.from_request(request, payload={"custom": response.status_code})

    adapter = _adapter(CustomParser())
    parsed = adapter.parse_http_response(
        _request(),
        HttpResponseModel(
            request_identity="req-100",
            endpoint_id="analytics-reports",
            status_code=202,
            payload_text="ok",
        ),
    )
    assert parsed.payload == {"custom": 202}


def test_no_http_execution_surface() -> None:
    adapter = _adapter()
    assert not hasattr(adapter, "execute")


def test_parser_missing_raises_internal_error() -> None:
    adapter = GoogleHttpTransportAdapter(
        endpoint_mapping={"analytics-reports": "/youtube/analytics/v2/reports"},
        parser_registry={},
    )
    request = _request()
    response = HttpResponseModel(
        request_identity="req-100",
        endpoint_id="analytics-reports",
        status_code=200,
        payload_text='{"rows": []}',
    )

    with pytest.raises(TransportError) as exc_info:
        adapter.parse_http_response(request, response)

    assert exc_info.value.category == "INTERNAL_ERROR"


def test_response_identity_mismatch_raises_invalid_request() -> None:
    adapter = _adapter()
    request = _request()
    response = HttpResponseModel(
        request_identity="other",
        endpoint_id="analytics-reports",
        status_code=200,
        payload_text='{"rows": []}',
    )

    with pytest.raises(TransportError) as exc_info:
        adapter.parse_http_response(request, response)
    assert exc_info.value.category == "INVALID_REQUEST"


def test_no_forbidden_imports() -> None:
    source = Path("src/google_http_transport_adapter.py").read_text(encoding="utf-8").lower()
    forbidden = [
        "requests",
        "urllib",
        "aiohttp",
        "httpx",
        "httplib2",
        "socket",
        "googleapiclient",
        "google.auth",
    ]
    for token in forbidden:
        assert token not in source
