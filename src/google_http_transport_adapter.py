from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable

from .live_transport_contract import TransportError, TransportRequest, TransportResponse


@dataclass(frozen=True, slots=True)
class HttpRequestModel:
    request_identity: str
    endpoint_id: str
    method: str
    url_path: str
    query_parameters: Mapping[str, Any]
    timeout_seconds: int
    retry_metadata: Mapping[str, Any]
    headers: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not str(self.request_identity or "").strip():
            raise ValueError("request_identity is required")
        if not str(self.endpoint_id or "").strip():
            raise ValueError("endpoint_id is required")
        method = str(self.method or "").strip().upper()
        if method not in {"GET", "POST"}:
            raise ValueError("method must be GET or POST")
        if not str(self.url_path or "").strip():
            raise ValueError("url_path is required")
        if int(self.timeout_seconds) <= 0:
            raise ValueError("timeout_seconds must be positive")

        object.__setattr__(self, "method", method)
        object.__setattr__(self, "query_parameters", dict(self.query_parameters))
        object.__setattr__(self, "retry_metadata", dict(self.retry_metadata))


@dataclass(frozen=True, slots=True)
class HttpResponseModel:
    request_identity: str
    endpoint_id: str
    status_code: int
    payload_text: str
    headers: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        if not str(self.request_identity or "").strip():
            raise ValueError("request_identity is required")
        if not str(self.endpoint_id or "").strip():
            raise ValueError("endpoint_id is required")
        status_code = int(self.status_code)
        if status_code <= 0:
            raise ValueError("status_code must be positive")
        if not isinstance(self.payload_text, str):
            raise ValueError("payload_text must be a string")
        object.__setattr__(self, "status_code", status_code)


@runtime_checkable
class HttpResponseParser(Protocol):
    def parse(self, request: TransportRequest, response: HttpResponseModel) -> TransportResponse:
        ...


class GoogleHttpTransportAdapter:
    """Adapter skeleton that maps transport contracts to HTTP models without execution."""

    def __init__(
        self,
        *,
        endpoint_mapping: Mapping[str, str],
        parser_registry: Mapping[str, HttpResponseParser],
    ) -> None:
        self._endpoint_mapping = dict(endpoint_mapping)
        self._parser_registry = dict(parser_registry)

    def build_http_request(self, request: TransportRequest) -> HttpRequestModel:
        path = self._endpoint_mapping.get(request.endpoint_id)
        if not path:
            raise TransportError(
                "invalid request",
                category="INVALID_REQUEST",
                request_identity=request.request_identity,
            )

        return HttpRequestModel(
            request_identity=request.request_identity,
            endpoint_id=request.endpoint_id,
            method="GET",
            url_path=path,
            query_parameters=request.query_parameters,
            timeout_seconds=request.timeout_seconds,
            retry_metadata=request.retry_metadata,
            headers=(),
        )

    def parse_http_response(self, request: TransportRequest, response: HttpResponseModel) -> TransportResponse:
        if response.request_identity != request.request_identity:
            raise TransportError(
                "invalid request",
                category="INVALID_REQUEST",
                request_identity=request.request_identity,
            )
        if response.endpoint_id != request.endpoint_id:
            raise TransportError(
                "invalid request",
                category="INVALID_REQUEST",
                request_identity=request.request_identity,
            )

        parser = self._parser_registry.get(request.endpoint_id)
        if parser is None:
            raise TransportError(
                "internal error",
                category="INTERNAL_ERROR",
                request_identity=request.request_identity,
            )
        return parser.parse(request, response)


__all__ = [
    "GoogleHttpTransportAdapter",
    "HttpRequestModel",
    "HttpResponseModel",
    "HttpResponseParser",
]
