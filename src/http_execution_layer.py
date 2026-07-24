from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol, runtime_checkable

from .google_http_transport_adapter import HttpRequestModel, HttpResponseModel, HttpResponseParser
from .live_transport_contract import TransportResponse


class HttpExecutionError(RuntimeError):
    """Structured execution error for in-memory HTTP execution semantics."""

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
class ExecutionResult:
    request_identity: str
    endpoint_id: str
    status_code: int
    latency_ms: int
    timeout_seconds: int
    retry_metadata: Mapping[str, Any]
    parsed_response: TransportResponse

    def __post_init__(self) -> None:
        if not str(self.request_identity or "").strip():
            raise ValueError("request_identity is required")
        if not str(self.endpoint_id or "").strip():
            raise ValueError("endpoint_id is required")
        if int(self.status_code) <= 0:
            raise ValueError("status_code must be positive")
        if int(self.latency_ms) < 0:
            raise ValueError("latency_ms must be nonnegative")
        if int(self.timeout_seconds) <= 0:
            raise ValueError("timeout_seconds must be positive")
        object.__setattr__(self, "retry_metadata", dict(self.retry_metadata))


@runtime_checkable
class RetryDecisionPolicy(Protocol):
    def should_retry(self, error: HttpExecutionError, request: HttpRequestModel) -> bool:
        ...


@runtime_checkable
class HttpExecutor(Protocol):
    def execute(
        self,
        *,
        request: HttpRequestModel,
        parser: HttpResponseParser,
    ) -> ExecutionResult:
        ...


class FakeHttpExecutor:
    """Deterministic in-memory execution layer with fixture and failure injection."""

    def __init__(
        self,
        *,
        fixtures: Mapping[str, HttpResponseModel] | None = None,
        failures: Mapping[str, str] | None = None,
        latency_ms: Mapping[str, int] | None = None,
        retry_policy: RetryDecisionPolicy | None = None,
    ) -> None:
        self._fixtures = dict(fixtures or {})
        self._failures = {str(key): str(value).strip().lower() for key, value in dict(failures or {}).items()}
        self._latency_ms = {str(key): int(value) for key, value in dict(latency_ms or {}).items()}
        self._retry_policy = retry_policy

    def execute(
        self,
        *,
        request: HttpRequestModel,
        parser: HttpResponseParser,
    ) -> ExecutionResult:
        self._raise_simulated_failure(request)

        latency = int(self._latency_ms.get(request.endpoint_id, 0))
        if latency > int(request.timeout_seconds) * 1000:
            raise self._build_error(
                "request timed out",
                category="TIMEOUT",
                request=request,
                default_retryable=True,
            )

        fixture = self._fixtures.get(request.endpoint_id)
        response = self._normalized_response(request, fixture)

        try:
            parsed = parser.parse(request, response)
        except HttpExecutionError:
            raise
        except Exception as exc:
            raise self._build_error(
                "internal error",
                category="INTERNAL_ERROR",
                request=request,
                default_retryable=False,
            ) from exc

        return ExecutionResult(
            request_identity=request.request_identity,
            endpoint_id=request.endpoint_id,
            status_code=response.status_code,
            latency_ms=latency,
            timeout_seconds=request.timeout_seconds,
            retry_metadata=request.retry_metadata,
            parsed_response=parsed,
        )

    def _normalized_response(self, request: HttpRequestModel, fixture: HttpResponseModel | None) -> HttpResponseModel:
        if fixture is None:
            return HttpResponseModel(
                request_identity=request.request_identity,
                endpoint_id=request.endpoint_id,
                status_code=200,
                payload_text="{}",
                headers=(),
            )
        if fixture.request_identity != request.request_identity or fixture.endpoint_id != request.endpoint_id:
            raise self._build_error(
                "invalid request",
                category="INVALID_REQUEST",
                request=request,
                default_retryable=False,
            )
        return fixture

    def _raise_simulated_failure(self, request: HttpRequestModel) -> None:
        mode = self._failures.get(request.endpoint_id) or self._failures.get(request.request_identity)
        if mode is None:
            return
        if mode == "timeout":
            raise self._build_error("request timed out", category="TIMEOUT", request=request, default_retryable=True)
        if mode == "retryable":
            raise self._build_error("retryable failure", category="RETRYABLE", request=request, default_retryable=True)
        if mode == "permanent":
            raise self._build_error("permanent failure", category="PERMANENT", request=request, default_retryable=False)
        if mode == "invalid-request":
            raise self._build_error("invalid request", category="INVALID_REQUEST", request=request, default_retryable=False)
        if mode == "internal-error":
            raise self._build_error("internal error", category="INTERNAL_ERROR", request=request, default_retryable=False)
        raise self._build_error("internal error", category="INTERNAL_ERROR", request=request, default_retryable=False)

    def _build_error(
        self,
        safe_message: str,
        *,
        category: str,
        request: HttpRequestModel,
        default_retryable: bool,
    ) -> HttpExecutionError:
        provisional = HttpExecutionError(
            safe_message,
            category=category,
            request_identity=request.request_identity,
            retryable=default_retryable,
        )
        if self._retry_policy is None:
            return provisional
        retryable = bool(self._retry_policy.should_retry(provisional, request))
        return HttpExecutionError(
            safe_message,
            category=category,
            request_identity=request.request_identity,
            retryable=retryable,
        )


__all__ = [
    "ExecutionResult",
    "FakeHttpExecutor",
    "HttpExecutionError",
    "HttpExecutor",
    "RetryDecisionPolicy",
]
