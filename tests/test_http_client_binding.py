from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.error import URLError

import pytest

from src.google_http_transport_adapter import HttpRequestModel, HttpResponseModel
from src.http_client_binding import (
    HttpClient,
    HttpClientBinding,
    HttpClientBindingError,
    HttpClientResponse,
    StdlibHttpClient,
)
from src.http_execution_layer import ExecutionResult
from src.live_transport_contract import TransportResponse


class _Parser:
    def parse(self, request: HttpRequestModel, response: HttpResponseModel) -> TransportResponse:
        return TransportResponse(
            request_identity=request.request_identity,
            endpoint_id=request.endpoint_id,
            payload={"payload_text": response.payload_text, "status_code": response.status_code},
            timeout_seconds=request.timeout_seconds,
            retry_metadata=request.retry_metadata,
        )


class _FakeClient:
    def __init__(self, response: HttpClientResponse | None = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def send(
        self,
        *,
        method: str,
        url: str,
        headers: tuple[tuple[str, str], ...],
        body: bytes | None,
        timeout_seconds: int,
    ) -> HttpClientResponse:
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "body": body,
                "timeout_seconds": timeout_seconds,
            }
        )
        if self.error is not None:
            raise self.error
        assert self.response is not None
        return self.response


def _request(method: str = "GET", headers: tuple[tuple[str, str], ...] = ()) -> HttpRequestModel:
    return HttpRequestModel(
        request_identity="req-client-001",
        endpoint_id="endpoint-alpha",
        method=method,
        url_path="/v1/resource",
        query_parameters={"b": "2", "a": "1"},
        timeout_seconds=7,
        retry_metadata={"attempt": 1},
        headers=headers,
    )


def test_client_protocol() -> None:
    assert isinstance(_FakeClient(response=HttpClientResponse(200, "{}", (), 3)), HttpClient)


def test_request_serialization_get() -> None:
    fake = _FakeClient(response=HttpClientResponse(200, "{}", (), 4))
    binding = HttpClientBinding(client=fake, base_url="https://offline.local")
    binding.execute(request=_request("GET"), parser=_Parser())

    call = fake.calls[0]
    assert call["url"].startswith("https://offline.local/v1/resource?")
    assert "a=1" in call["url"]
    assert "b=2" in call["url"]
    assert call["body"] is None


def test_request_serialization_post() -> None:
    fake = _FakeClient(response=HttpClientResponse(201, '{"ok":true}', (), 5))
    binding = HttpClientBinding(client=fake, base_url="https://offline.local")
    binding.execute(request=_request("POST"), parser=_Parser())

    call = fake.calls[0]
    assert call["method"] == "POST"
    assert call["body"] == b'{"a":"1","b":"2"}'
    header_map = {k.lower(): v for k, v in call["headers"]}
    assert header_map["content-type"] == "application/json"


def test_response_mapping_to_execution_result() -> None:
    fake = _FakeClient(response=HttpClientResponse(200, '{"rows":[]}', (("X-Test", "ok"),), 9))
    binding = HttpClientBinding(client=fake, base_url="https://offline.local")

    result = binding.execute(request=_request(), parser=_Parser())

    assert isinstance(result, ExecutionResult)
    assert result.status_code == 200
    assert result.latency_ms == 9
    assert result.parsed_response.payload["payload_text"] == '{"rows":[]}'


def test_timeout_propagation() -> None:
    fake = _FakeClient(
        error=HttpClientBindingError(
            "request timed out",
            category="TIMEOUT",
            request_identity="unknown",
            retryable=True,
        )
    )
    binding = HttpClientBinding(client=fake, base_url="https://offline.local")

    with pytest.raises(HttpClientBindingError) as exc_info:
        binding.execute(request=_request(), parser=_Parser())

    assert exc_info.value.category == "TIMEOUT"
    assert exc_info.value.request_identity == "req-client-001"


def test_injected_fake_client_deterministic_execution() -> None:
    fake = _FakeClient(response=HttpClientResponse(200, "{}", (), 1))
    binding = HttpClientBinding(client=fake, base_url="https://offline.local")
    first = binding.execute(request=_request(), parser=_Parser())
    second = binding.execute(request=_request(), parser=_Parser())

    assert first == second


def test_immutable_model() -> None:
    response = HttpClientResponse(status_code=200, payload_text="{}", headers=(), latency_ms=1)
    with pytest.raises(AttributeError):
        response.status_code = 500


def test_no_oauth_or_authorization_header_injection() -> None:
    fake = _FakeClient(response=HttpClientResponse(200, "{}", (), 1))
    binding = HttpClientBinding(client=fake, base_url="https://offline.local")

    with pytest.raises(HttpClientBindingError) as exc_info:
        binding.execute(request=_request(headers=(("Authorization", "Bearer x"),)), parser=_Parser())

    assert exc_info.value.category == "INVALID_REQUEST"


def test_no_google_specific_behavior() -> None:
    source = Path("src/http_client_binding.py").read_text(encoding="utf-8").lower()
    forbidden = ["googleapiclient", "google.auth", "oauth", "authorization", "access_token", "refresh_token"]
    for token in forbidden:
        assert token not in source


def test_stdlib_http_client_uses_injected_urlopen(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Response:
        def __init__(self) -> None:
            self.headers = {"Content-Type": "application/json"}

        def getcode(self) -> int:
            return 200

        def read(self) -> bytes:
            return b"{}"

        def __enter__(self) -> "_Response":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    captured: dict[str, Any] = {}

    def _fake_urlopen(request, timeout):
        captured["full_url"] = request.full_url
        captured["method"] = request.get_method()
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)

    client = StdlibHttpClient()
    out = client.send(
        method="GET",
        url="https://offline.local/v1/resource?a=1",
        headers=(),
        body=None,
        timeout_seconds=11,
    )

    assert out.status_code == 200
    assert captured["method"] == "GET"
    assert captured["timeout"] == 11


def test_stdlib_http_client_maps_urlerror_to_permanent(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_urlopen(request, timeout):
        raise URLError("offline")

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    client = StdlibHttpClient()

    with pytest.raises(HttpClientBindingError) as exc_info:
        client.send(method="GET", url="https://offline.local/v1", headers=(), body=None, timeout_seconds=3)

    assert exc_info.value.category == "PERMANENT"
