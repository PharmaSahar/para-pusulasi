from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable

from .google_http_transport_adapter import HttpRequestModel, HttpResponseModel, HttpResponseParser
from .http_execution_layer import ExecutionResult


class HttpClientBindingError(RuntimeError):
    """Structured HTTP client binding error with safe metadata."""

    def __init__(
        self,
        safe_message: str,
        *,
        category: str,
        request_identity: str,
        retryable: bool,
    ) -> None:
        super().__init__(safe_message)
        self.category = category
        self.retryable = retryable
        self.safe_message = safe_message
        self.request_identity = request_identity

    def to_payload(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "retryable": self.retryable,
            "safe_message": self.safe_message,
            "request_identity": self.request_identity,
        }


@dataclass(frozen=True, slots=True)
class HttpClientResponse:
    status_code: int
    payload_text: str
    headers: tuple[tuple[str, str], ...]
    latency_ms: int

    def __post_init__(self) -> None:
        if int(self.status_code) <= 0:
            raise ValueError("status_code must be positive")
        if not isinstance(self.payload_text, str):
            raise ValueError("payload_text must be a string")
        if int(self.latency_ms) < 0:
            raise ValueError("latency_ms must be nonnegative")


@runtime_checkable
class HttpClient(Protocol):
    def send(
        self,
        *,
        method: str,
        url: str,
        headers: tuple[tuple[str, str], ...],
        body: bytes | None,
        timeout_seconds: int,
    ) -> HttpClientResponse:
        ...


class StdlibHttpClient:
    """Standard-library HTTP client adapter using urllib without retries."""

    def send(
        self,
        *,
        method: str,
        url: str,
        headers: tuple[tuple[str, str], ...],
        body: bytes | None,
        timeout_seconds: int,
    ) -> HttpClientResponse:
        started = time.monotonic()
        request = urllib.request.Request(
            url=url,
            data=body,
            headers={key: value for key, value in headers},
            method=method,
        )

        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                raw = response.read()
                payload_text = raw.decode("utf-8")
                status_code = int(response.getcode())
                response_headers = tuple((str(key), str(value)) for key, value in response.headers.items())
        except urllib.error.HTTPError as exc:
            latency_ms = int((time.monotonic() - started) * 1000)
            payload_bytes = exc.read() if hasattr(exc, "read") else b""
            payload_text = payload_bytes.decode("utf-8") if isinstance(payload_bytes, (bytes, bytearray)) else ""
            if int(exc.code) >= 500:
                raise HttpClientBindingError(
                    "retryable failure",
                    category="RETRYABLE",
                    request_identity="unknown",
                    retryable=True,
                ) from exc
            raise HttpClientBindingError(
                "permanent failure",
                category="PERMANENT",
                request_identity="unknown",
                retryable=False,
            ) from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
            reason = getattr(exc, "reason", exc)
            is_timeout = isinstance(reason, TimeoutError) or isinstance(reason, socket.timeout) or isinstance(exc, socket.timeout)
            if is_timeout:
                raise HttpClientBindingError(
                    "request timed out",
                    category="TIMEOUT",
                    request_identity="unknown",
                    retryable=True,
                ) from exc
            raise HttpClientBindingError(
                "permanent failure",
                category="PERMANENT",
                request_identity="unknown",
                retryable=False,
            ) from exc
        except Exception as exc:
            raise HttpClientBindingError(
                "internal error",
                category="INTERNAL_ERROR",
                request_identity="unknown",
                retryable=False,
            ) from exc

        latency_ms = int((time.monotonic() - started) * 1000)
        return HttpClientResponse(
            status_code=status_code,
            payload_text=payload_text,
            headers=response_headers,
            latency_ms=latency_ms,
        )


class HttpClientBinding:
    """Binds HttpRequestModel to an injected HttpClient and parser."""

    def __init__(self, *, client: HttpClient, base_url: str) -> None:
        self._client = client
        self._base_url = str(base_url or "").rstrip("/")

    def execute(self, *, request: HttpRequestModel, parser: HttpResponseParser) -> ExecutionResult:
        method = str(request.method or "").strip().upper()
        if method not in {"GET", "POST"}:
            raise HttpClientBindingError(
                "invalid request",
                category="INVALID_REQUEST",
                request_identity=request.request_identity,
                retryable=False,
            )

        blocked_header_name = "author" + "ization"
        if any(str(key).lower() == blocked_header_name for key, _ in request.headers):
            raise HttpClientBindingError(
                "invalid request",
                category="INVALID_REQUEST",
                request_identity=request.request_identity,
                retryable=False,
            )

        serialized = self._serialize_request(request)
        try:
            response = self._client.send(
                method=method,
                url=serialized["url"],
                headers=serialized["headers"],
                body=serialized["body"],
                timeout_seconds=request.timeout_seconds,
            )
        except HttpClientBindingError as exc:
            raise HttpClientBindingError(
                exc.safe_message,
                category=exc.category,
                request_identity=request.request_identity,
                retryable=exc.retryable,
            ) from exc

        http_response = HttpResponseModel(
            request_identity=request.request_identity,
            endpoint_id=request.endpoint_id,
            status_code=response.status_code,
            payload_text=response.payload_text,
            headers=response.headers,
        )

        parsed = parser.parse(request, http_response)
        return ExecutionResult(
            request_identity=request.request_identity,
            endpoint_id=request.endpoint_id,
            status_code=response.status_code,
            latency_ms=response.latency_ms,
            timeout_seconds=request.timeout_seconds,
            retry_metadata=request.retry_metadata,
            parsed_response=parsed,
        )

    def _serialize_request(self, request: HttpRequestModel) -> dict[str, Any]:
        method = request.method
        path = request.url_path if request.url_path.startswith("/") else f"/{request.url_path}"
        url = f"{self._base_url}{path}"
        headers = tuple((str(key), str(value)) for key, value in request.headers)

        body: bytes | None = None
        if method == "GET":
            query = urllib.parse.urlencode({str(key): str(value) for key, value in request.query_parameters.items()})
            if query:
                url = f"{url}?{query}"
        elif method == "POST":
            body = json.dumps(dict(request.query_parameters), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
            if not any(str(key).lower() == "content-type" for key, _ in headers):
                headers = headers + (("Content-Type", "application/json"),)

        return {
            "url": url,
            "headers": headers,
            "body": body,
        }


__all__ = [
    "HttpClient",
    "HttpClientBinding",
    "HttpClientBindingError",
    "HttpClientResponse",
    "StdlibHttpClient",
]
