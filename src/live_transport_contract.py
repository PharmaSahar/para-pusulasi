from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable


class TransportError(RuntimeError):
    """Safe transport error without network or credential details."""

    def __init__(
        self,
        safe_message: str,
        *,
        category: str,
        request_identity: str,
        retryable: bool = False,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(safe_message)
        self.category = category
        self.retryable = retryable
        self.safe_message = safe_message
        self.request_identity = request_identity
        self.retry_after_seconds = retry_after_seconds

    def to_payload(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "retryable": self.retryable,
            "safe_message": self.safe_message,
            "request_identity": self.request_identity,
            "retry_after_seconds": self.retry_after_seconds,
        }


@dataclass(frozen=True, slots=True)
class TransportRequest:
    request_identity: str
    endpoint_id: str
    query_parameters: Mapping[str, Any]
    timeout_seconds: int
    retry_metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not str(self.request_identity or "").strip():
            raise ValueError("request_identity is required")
        if not str(self.endpoint_id or "").strip():
            raise ValueError("endpoint_id is required")
        if int(self.timeout_seconds) <= 0:
            raise ValueError("timeout_seconds must be positive")

        object.__setattr__(self, "query_parameters", dict(self.query_parameters))
        object.__setattr__(self, "retry_metadata", dict(self.retry_metadata))


@dataclass(frozen=True, slots=True)
class TransportResponse:
    request_identity: str
    endpoint_id: str
    payload: Mapping[str, Any]
    timeout_seconds: int
    retry_metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not str(self.request_identity or "").strip():
            raise ValueError("request_identity is required")
        if not str(self.endpoint_id or "").strip():
            raise ValueError("endpoint_id is required")
        if int(self.timeout_seconds) <= 0:
            raise ValueError("timeout_seconds must be positive")

        object.__setattr__(self, "payload", dict(self.payload))
        object.__setattr__(self, "retry_metadata", dict(self.retry_metadata))

    @classmethod
    def from_request(cls, request: TransportRequest, *, payload: Mapping[str, Any]) -> "TransportResponse":
        return cls(
            request_identity=request.request_identity,
            endpoint_id=request.endpoint_id,
            payload=dict(payload),
            timeout_seconds=request.timeout_seconds,
            retry_metadata=request.retry_metadata,
        )


@runtime_checkable
class LiveTransport(Protocol):
    def execute(self, request: TransportRequest) -> TransportResponse:
        ...


class FakeLiveTransport:
    """Deterministic fake transport with safe simulated failures."""

    def __init__(self, *, failures: Mapping[str, str] | None = None) -> None:
        self._failures = dict(failures or {})

    def execute(self, request: TransportRequest) -> TransportResponse:
        failure_key = next(iter(self._failures.keys()), None)
        if failure_key == "timeout":
            raise TransportError(
                "request timed out",
                category="TIMEOUT",
                request_identity=request.request_identity,
                retryable=True,
                retry_after_seconds=1,
            )
        if failure_key == "rate-limit":
            raise TransportError(
                "rate limited",
                category="RATE_LIMIT",
                request_identity=request.request_identity,
                retryable=True,
                retry_after_seconds=60,
            )
        if failure_key == "auth-required":
            raise TransportError(
                "authentication required",
                category="AUTH_REQUIRED",
                request_identity=request.request_identity,
                retryable=False,
            )
        if failure_key == "permission-denied":
            raise TransportError(
                "permission denied",
                category="PERMISSION_DENIED",
                request_identity=request.request_identity,
                retryable=False,
            )
        if failure_key == "service-unavailable":
            raise TransportError(
                "service unavailable",
                category="SERVICE_UNAVAILABLE",
                request_identity=request.request_identity,
                retryable=True,
                retry_after_seconds=5,
            )
        if failure_key == "invalid-request":
            raise TransportError(
                "invalid request",
                category="INVALID_REQUEST",
                request_identity=request.request_identity,
                retryable=False,
            )
        if failure_key == "internal-error":
            raise TransportError(
                "internal error",
                category="INTERNAL_ERROR",
                request_identity=request.request_identity,
                retryable=True,
                retry_after_seconds=2,
            )

        payload = {
            "request_identity": request.request_identity,
            "endpoint_id": request.endpoint_id,
            "channel_id": request.query_parameters.get("channel_id"),
            "transport_mode": "fake",
            "network": False,
            "timeout_seconds": request.timeout_seconds,
            "retry_metadata": request.retry_metadata,
        }
        return TransportResponse.from_request(request, payload=payload)


__all__ = [
    "FakeLiveTransport",
    "LiveTransport",
    "TransportError",
    "TransportRequest",
    "TransportResponse",
]
