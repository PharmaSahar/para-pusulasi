from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from .google_http_transport_adapter import HttpRequestModel, HttpResponseModel, HttpResponseParser
from .google_oauth_credentials import CredentialRedactor, OAuthCredentialLease
from .google_provider_integration import (
    GoogleEndpointDescriptor,
    GoogleEndpointRegistry,
    GoogleParserRegistry,
    GoogleProviderIntegrationError,
)
from .http_execution_layer import ExecutionResult
from .live_transport_contract import TransportResponse


class YouTubeAnalyticsLiveClientError(RuntimeError):
    """Safe live client error for read-only analytics retrieval."""

    def __init__(
        self,
        safe_message: str,
        *,
        category: str,
        request_identity: str,
        retryable: bool,
    ) -> None:
        super().__init__(safe_message)
        self.safe_message = safe_message
        self.category = category
        self.request_identity = request_identity
        self.retryable = retryable

    def to_payload(self) -> dict[str, Any]:
        return {
            "safe_message": self.safe_message,
            "category": self.category,
            "request_identity": self.request_identity,
            "retryable": self.retryable,
        }


class _PayloadTextParser:
    """Parser used by execution backends to expose payload_text for provider parsing."""

    def parse(self, request: HttpRequestModel, response: HttpResponseModel) -> TransportResponse:
        return TransportResponse(
            request_identity=request.request_identity,
            endpoint_id=request.endpoint_id,
            payload={
                "payload_text": response.payload_text,
                "status_code": response.status_code,
            },
            timeout_seconds=request.timeout_seconds,
            retry_metadata=request.retry_metadata,
        )


class ExecutionBackend(Protocol):
    def execute(self, *, request: HttpRequestModel, parser: HttpResponseParser) -> ExecutionResult:
        ...


@dataclass(frozen=True, slots=True)
class AnalyticsRequestBuilder:
    endpoint_registry: GoogleEndpointRegistry
    endpoint_id: str

    def build_reports_query_request(
        self,
        *,
        oauth_lease: OAuthCredentialLease,
        channel_id: str,
        youtube_channel_id: str,
        start_date: str,
        end_date: str,
        metrics: tuple[str, ...],
        dimensions: tuple[str, ...] = (),
        filters: tuple[str, ...] = (),
        sort: tuple[str, ...] = (),
        max_results: int | None = None,
        start_index: int | None = None,
        currency: str | None = None,
        timeout_seconds: int,
        retry_metadata: Mapping[str, Any] | None = None,
    ) -> HttpRequestModel:
        descriptor = self.endpoint_registry.get(self.endpoint_id)
        self._validate_channel_binding(
            oauth_lease=oauth_lease,
            channel_id=channel_id,
            youtube_channel_id=youtube_channel_id,
        )

        normalized_metrics = tuple(sorted({str(value).strip() for value in metrics}))
        if not normalized_metrics or any(not value for value in normalized_metrics):
            raise ValueError("metrics must contain at least one non-blank value")

        query: dict[str, Any] = {
            "ids": f"channel=={youtube_channel_id}",
            "startDate": str(start_date).strip(),
            "endDate": str(end_date).strip(),
            "metrics": ",".join(normalized_metrics),
        }

        normalized_dimensions = tuple(sorted({str(value).strip() for value in dimensions}))
        if normalized_dimensions:
            query["dimensions"] = ",".join(normalized_dimensions)

        normalized_filters = tuple(sorted({str(value).strip() for value in filters}))
        if normalized_filters:
            query["filters"] = ";".join(normalized_filters)

        normalized_sort = tuple(sorted({str(value).strip() for value in sort}))
        if normalized_sort:
            query["sort"] = ",".join(normalized_sort)

        if max_results is not None:
            query["maxResults"] = int(max_results)
        if start_index is not None:
            query["startIndex"] = int(start_index)
        if currency is not None:
            query["currency"] = str(currency).strip()

        if not query["startDate"] or not query["endDate"]:
            raise ValueError("start_date and end_date are required")

        redacted_token = oauth_lease.with_access_token(CredentialRedactor.redact_token)

        merged_retry_metadata = dict(retry_metadata or {})
        merged_retry_metadata["oauth_lease_identity"] = oauth_lease.lease_identity
        merged_retry_metadata["oauth_token_marker"] = redacted_token
        merged_retry_metadata["credential_identity"] = oauth_lease.credential_identity

        filtered_query = self._filter_query(query, descriptor)
        request_identity = self._build_request_identity(
            endpoint_id=descriptor.endpoint_id,
            channel_id=channel_id,
            youtube_channel_id=youtube_channel_id,
            query_parameters=filtered_query,
            timeout_seconds=timeout_seconds,
        )

        return HttpRequestModel(
            request_identity=request_identity,
            endpoint_id=descriptor.endpoint_id,
            method=descriptor.method,
            url_path="/youtube/analytics/v2/reports",
            query_parameters=filtered_query,
            timeout_seconds=int(timeout_seconds),
            retry_metadata=merged_retry_metadata,
            headers=(),
        )

    def _filter_query(
        self,
        query: Mapping[str, Any],
        descriptor: GoogleEndpointDescriptor,
    ) -> dict[str, Any]:
        allowed = set(descriptor.supported_query_parameters)
        return {key: value for key, value in query.items() if key in allowed}

    def _validate_channel_binding(
        self,
        *,
        oauth_lease: OAuthCredentialLease,
        channel_id: str,
        youtube_channel_id: str,
    ) -> None:
        normalized_channel_id = str(channel_id or "").strip()
        normalized_youtube_channel_id = str(youtube_channel_id or "").strip()
        if not normalized_channel_id:
            raise ValueError("channel_id is required")
        if not normalized_youtube_channel_id:
            raise ValueError("youtube_channel_id is required")
        if oauth_lease.channel_id != normalized_channel_id:
            raise ValueError("channel_id mismatch")
        if oauth_lease.youtube_channel_id != normalized_youtube_channel_id:
            raise ValueError("youtube_channel_id mismatch")

    def _build_request_identity(
        self,
        *,
        endpoint_id: str,
        channel_id: str,
        youtube_channel_id: str,
        query_parameters: Mapping[str, Any],
        timeout_seconds: int,
    ) -> str:
        payload = {
            "endpoint_id": endpoint_id,
            "channel_id": channel_id,
            "youtube_channel_id": youtube_channel_id,
            "query_parameters": dict(query_parameters),
            "timeout_seconds": int(timeout_seconds),
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()


@dataclass(frozen=True, slots=True)
class AnalyticsResponseMapper:
    def map(self, response: TransportResponse) -> dict[str, Any]:
        payload = dict(response.payload)
        if payload.get("result") != "success":
            raise YouTubeAnalyticsLiveClientError(
                "malformed payload",
                category="MALFORMED_PAYLOAD",
                request_identity=response.request_identity,
                retryable=False,
            )

        body = payload.get("body")
        if not isinstance(body, dict):
            raise YouTubeAnalyticsLiveClientError(
                "malformed payload",
                category="MALFORMED_PAYLOAD",
                request_identity=response.request_identity,
                retryable=False,
            )

        rows = body.get("rows")
        if rows is None:
            normalized_rows: tuple[Any, ...] = ()
        elif isinstance(rows, list):
            normalized_rows = tuple(rows)
        else:
            raise YouTubeAnalyticsLiveClientError(
                "malformed payload",
                category="MALFORMED_PAYLOAD",
                request_identity=response.request_identity,
                retryable=False,
            )

        return {
            "request_identity": response.request_identity,
            "endpoint_id": response.endpoint_id,
            "status": "success",
            "row_count": len(normalized_rows),
            "rows": normalized_rows,
            "body": body,
            "timeout_seconds": response.timeout_seconds,
            "retry_metadata": dict(response.retry_metadata),
        }


class AnalyticsLiveClient:
    """Read-only analytics client that executes reports.query through injected contracts."""

    def __init__(
        self,
        *,
        endpoint_registry: GoogleEndpointRegistry,
        parser_registry: GoogleParserRegistry,
        execution_backend: ExecutionBackend,
        endpoint_id: str = "youtube-analytics-reports-query",
        request_builder: AnalyticsRequestBuilder | None = None,
        response_mapper: AnalyticsResponseMapper | None = None,
    ) -> None:
        self._endpoint_registry = endpoint_registry
        self._parser_registry = parser_registry
        self._execution_backend = execution_backend
        self._endpoint_id = str(endpoint_id or "").strip()
        if not self._endpoint_id:
            raise ValueError("endpoint_id is required")
        self._request_builder = request_builder or AnalyticsRequestBuilder(
            endpoint_registry=endpoint_registry,
            endpoint_id=self._endpoint_id,
        )
        self._response_mapper = response_mapper or AnalyticsResponseMapper()

    def run_dry(
        self,
        *,
        oauth_lease: OAuthCredentialLease,
        channel_id: str,
        youtube_channel_id: str,
        start_date: str,
        end_date: str,
        metrics: tuple[str, ...],
        dimensions: tuple[str, ...] = (),
        filters: tuple[str, ...] = (),
        sort: tuple[str, ...] = (),
        max_results: int | None = None,
        start_index: int | None = None,
        currency: str | None = None,
        timeout_seconds: int,
        retry_metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        descriptor = self._endpoint_registry.get(self._endpoint_id)
        request = self._request_builder.build_reports_query_request(
            oauth_lease=oauth_lease,
            channel_id=channel_id,
            youtube_channel_id=youtube_channel_id,
            start_date=start_date,
            end_date=end_date,
            metrics=metrics,
            dimensions=dimensions,
            filters=filters,
            sort=sort,
            max_results=max_results,
            start_index=start_index,
            currency=currency,
            timeout_seconds=timeout_seconds,
            retry_metadata=retry_metadata,
        )

        try:
            execution_result = self._execution_backend.execute(request=request, parser=_PayloadTextParser())
            provider_response = self._parser_registry.dispatch(
                parser_name=descriptor.parser_name,
                result=execution_result,
            )
            return self._response_mapper.map(provider_response)
        except GoogleProviderIntegrationError as exc:
            raise YouTubeAnalyticsLiveClientError(
                exc.safe_message,
                category=exc.category,
                request_identity=exc.request_identity,
                retryable=exc.retryable,
            ) from exc


__all__ = [
    "AnalyticsLiveClient",
    "AnalyticsRequestBuilder",
    "AnalyticsResponseMapper",
    "ExecutionBackend",
    "YouTubeAnalyticsLiveClientError",
]
