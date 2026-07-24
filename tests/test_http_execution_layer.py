from __future__ import annotations

from pathlib import Path

import pytest

from src.google_http_transport_adapter import HttpRequestModel, HttpResponseModel
from src.http_execution_layer import (
    ExecutionResult,
    FakeHttpExecutor,
    HttpExecutionError,
    HttpExecutor,
    RetryDecisionPolicy,
)
from src.live_transport_contract import TransportResponse


class _Parser:
    def __init__(self) -> None:
        self.calls: list[tuple[HttpRequestModel, HttpResponseModel]] = []

    def parse(self, request: HttpRequestModel, response: HttpResponseModel) -> TransportResponse:
        self.calls.append((request, response))
        return TransportResponse(
            request_identity=request.request_identity,
            endpoint_id=request.endpoint_id,
            payload={"status_code": response.status_code, "payload_text": response.payload_text},
            timeout_seconds=request.timeout_seconds,
            retry_metadata=request.retry_metadata,
        )


class _RetryPolicy:
    def should_retry(self, error: HttpExecutionError, request: HttpRequestModel) -> bool:
        return error.category in {"TIMEOUT", "RETRYABLE"}


def _request() -> HttpRequestModel:
    return HttpRequestModel(
        request_identity="req-exec-001",
        endpoint_id="analytics-reports",
        method="GET",
        url_path="/runtime/reports",
        query_parameters={"channel_id": "channel_alpha", "metrics": "views"},
        timeout_seconds=2,
        retry_metadata={"attempt": 1},
    )


def test_executor_protocol() -> None:
    executor = FakeHttpExecutor()
    assert isinstance(executor, HttpExecutor)


def test_deterministic_execution() -> None:
    parser = _Parser()
    fixture = HttpResponseModel(
        request_identity="req-exec-001",
        endpoint_id="analytics-reports",
        status_code=200,
        payload_text='{"rows": []}',
    )
    executor = FakeHttpExecutor(fixtures={"analytics-reports": fixture})

    first = executor.execute(request=_request(), parser=parser)
    second = executor.execute(request=_request(), parser=parser)

    assert first == second
    assert first.parsed_response.payload["status_code"] == 200


def test_parser_integration() -> None:
    parser = _Parser()
    fixture = HttpResponseModel(
        request_identity="req-exec-001",
        endpoint_id="analytics-reports",
        status_code=202,
        payload_text="ok",
    )
    executor = FakeHttpExecutor(fixtures={"analytics-reports": fixture})

    result = executor.execute(request=_request(), parser=parser)

    assert len(parser.calls) == 1
    assert result.status_code == 202


def test_timeout_simulation() -> None:
    parser = _Parser()
    executor = FakeHttpExecutor(latency_ms={"analytics-reports": 3000})

    with pytest.raises(HttpExecutionError) as exc_info:
        executor.execute(request=_request(), parser=parser)

    assert exc_info.value.category == "TIMEOUT"
    assert exc_info.value.retryable is True


def test_retry_decision_for_retryable_failure() -> None:
    parser = _Parser()
    executor = FakeHttpExecutor(
        failures={"analytics-reports": "retryable"},
        retry_policy=_RetryPolicy(),
    )

    with pytest.raises(HttpExecutionError) as exc_info:
        executor.execute(request=_request(), parser=parser)

    assert exc_info.value.category == "RETRYABLE"
    assert exc_info.value.retryable is True


def test_permanent_failure() -> None:
    parser = _Parser()
    executor = FakeHttpExecutor(
        failures={"analytics-reports": "permanent"},
        retry_policy=_RetryPolicy(),
    )

    with pytest.raises(HttpExecutionError) as exc_info:
        executor.execute(request=_request(), parser=parser)

    assert exc_info.value.category == "PERMANENT"
    assert exc_info.value.retryable is False


def test_injected_fixture_execution() -> None:
    parser = _Parser()
    fixture = HttpResponseModel(
        request_identity="req-exec-001",
        endpoint_id="analytics-reports",
        status_code=206,
        payload_text='{"partial": true}',
    )
    executor = FakeHttpExecutor(fixtures={"analytics-reports": fixture})

    result = executor.execute(request=_request(), parser=parser)

    assert result.status_code == 206
    assert result.parsed_response.payload["payload_text"] == '{"partial": true}'


def test_execution_result_is_immutable() -> None:
    parser = _Parser()
    executor = FakeHttpExecutor()
    result = executor.execute(request=_request(), parser=parser)

    with pytest.raises(AttributeError):
        result.status_code = 500


def test_fixture_identity_mismatch_is_invalid_request() -> None:
    parser = _Parser()
    fixture = HttpResponseModel(
        request_identity="other",
        endpoint_id="analytics-reports",
        status_code=200,
        payload_text="{}",
    )
    executor = FakeHttpExecutor(fixtures={"analytics-reports": fixture})

    with pytest.raises(HttpExecutionError) as exc_info:
        executor.execute(request=_request(), parser=parser)

    assert exc_info.value.category == "INVALID_REQUEST"


def test_no_forbidden_imports_or_http_stack() -> None:
    source = Path("src/http_execution_layer.py").read_text(encoding="utf-8").lower()
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
