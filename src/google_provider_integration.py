from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence

from .authorized_transport_binding import AuthorizedTransportRequest
from .google_http_transport_adapter import HttpRequestModel
from .http_execution_layer import ExecutionResult
from .live_transport_contract import TransportRequest, TransportResponse


class GoogleProviderIntegrationError(RuntimeError):
    """Safe structured error for offline Google provider integration."""

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
class GoogleEndpointDescriptor:
    endpoint_id: str
    method: str
    supported_query_parameters: tuple[str, ...]
    parser_name: str
    default_timeout_seconds: int
    retry_policy_metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        endpoint_id = str(self.endpoint_id or "").strip()
        if not endpoint_id:
            raise ValueError("endpoint_id is required")
        method = str(self.method or "").strip().upper()
        if method not in {"GET", "POST"}:
            raise ValueError("method must be GET or POST")
        parser_name = str(self.parser_name or "").strip()
        if not parser_name:
            raise ValueError("parser_name is required")
        timeout = int(self.default_timeout_seconds)
        if timeout <= 0:
            raise ValueError("default_timeout_seconds must be positive")

        params = tuple(sorted({str(value).strip() for value in self.supported_query_parameters}))
        if any(not value for value in params):
            raise ValueError("supported_query_parameters must not contain blanks")

        object.__setattr__(self, "endpoint_id", endpoint_id)
        object.__setattr__(self, "method", method)
        object.__setattr__(self, "parser_name", parser_name)
        object.__setattr__(self, "default_timeout_seconds", timeout)
        object.__setattr__(self, "supported_query_parameters", params)
        object.__setattr__(self, "retry_policy_metadata", dict(self.retry_policy_metadata))


class GoogleEndpointRegistry:
    def __init__(self, *, descriptors: Sequence[GoogleEndpointDescriptor]) -> None:
        self._descriptors = {descriptor.endpoint_id: descriptor for descriptor in descriptors}

    def get(self, endpoint_id: str) -> GoogleEndpointDescriptor:
        selected = self._descriptors.get(str(endpoint_id or "").strip())
        if selected is None:
            raise GoogleProviderIntegrationError(
                "invalid request",
                category="INVALID_REQUEST",
                request_identity="unknown",
                retryable=False,
            )
        return selected


@dataclass(frozen=True, slots=True)
class ExecutionRequest:
    transport_request: TransportRequest
    http_request: HttpRequestModel
    parser_name: str


class GoogleRequestBuilder:
    def __init__(self, *, endpoint_registry: GoogleEndpointRegistry) -> None:
        self._endpoint_registry = endpoint_registry

    def build(self, authorized_request: AuthorizedTransportRequest) -> ExecutionRequest:
        transport_request = authorized_request.request
        descriptor = self._endpoint_registry.get(transport_request.endpoint_id)

        filtered_query = {
            key: value
            for key, value in transport_request.query_parameters.items()
            if str(key) in descriptor.supported_query_parameters
        }

        http_request = HttpRequestModel(
            request_identity=transport_request.request_identity,
            endpoint_id=transport_request.endpoint_id,
            method=descriptor.method,
            url_path=f"/offline/google/{descriptor.endpoint_id}",
            query_parameters=filtered_query,
            timeout_seconds=transport_request.timeout_seconds,
            retry_metadata=transport_request.retry_metadata,
            headers=(),
        )

        return ExecutionRequest(
            transport_request=transport_request,
            http_request=http_request,
            parser_name=descriptor.parser_name,
        )


class GoogleResponseParser:
    def parse_execution_result(self, result: ExecutionResult) -> TransportResponse:
        status_code = int(result.status_code)
        if status_code in {429, 500, 502, 503, 504}:
            raise GoogleProviderIntegrationError(
                "retryable error",
                category="RETRYABLE_ERROR",
                request_identity=result.request_identity,
                retryable=True,
            )
        if status_code >= 400:
            raise GoogleProviderIntegrationError(
                "permanent error",
                category="PERMANENT_ERROR",
                request_identity=result.request_identity,
                retryable=False,
            )

        payload_text = result.parsed_response.payload.get("payload_text")
        if not isinstance(payload_text, str):
            raise GoogleProviderIntegrationError(
                "malformed payload",
                category="MALFORMED_PAYLOAD",
                request_identity=result.request_identity,
                retryable=False,
            )

        try:
            body = json.loads(payload_text)
        except json.JSONDecodeError as exc:
            raise GoogleProviderIntegrationError(
                "malformed payload",
                category="MALFORMED_PAYLOAD",
                request_identity=result.request_identity,
                retryable=False,
            ) from exc

        if not isinstance(body, dict):
            raise GoogleProviderIntegrationError(
                "malformed payload",
                category="MALFORMED_PAYLOAD",
                request_identity=result.request_identity,
                retryable=False,
            )

        return TransportResponse(
            request_identity=result.request_identity,
            endpoint_id=result.endpoint_id,
            payload={
                "result": "success",
                "status_code": status_code,
                "latency_ms": result.latency_ms,
                "body": body,
            },
            timeout_seconds=result.timeout_seconds,
            retry_metadata=result.retry_metadata,
        )


class ExecutionResultParser(Protocol):
    def parse_execution_result(self, result: ExecutionResult) -> TransportResponse:
        ...


class GoogleParserRegistry:
    def __init__(self, *, parsers: Mapping[str, ExecutionResultParser]) -> None:
        self._parsers = dict(parsers)

    def dispatch(self, *, parser_name: str, result: ExecutionResult) -> TransportResponse:
        parser = self._parsers.get(str(parser_name or "").strip())
        if parser is None:
            raise GoogleProviderIntegrationError(
                "invalid request",
                category="INVALID_REQUEST",
                request_identity=result.request_identity,
                retryable=False,
            )
        return parser.parse_execution_result(result)


__all__ = [
    "ExecutionRequest",
    "ExecutionResultParser",
    "GoogleEndpointDescriptor",
    "GoogleEndpointRegistry",
    "GoogleParserRegistry",
    "GoogleProviderIntegrationError",
    "GoogleRequestBuilder",
    "GoogleResponseParser",
]
