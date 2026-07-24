from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Protocol, runtime_checkable

from .credential_provider_contract import CredentialDescriptor, CredentialProviderRequest
from .live_transport_contract import TransportRequest
from .runtime_credential_contract import RuntimeCredentialLease

SUPPORTED_CREDENTIAL_KINDS = {"YOUTUBE_ANALYTICS", "YOUTUBE_DATA"}


class AuthorizedTransportBindingError(RuntimeError):
    """Safe binding error without exposing authorization material."""

    def __init__(
        self,
        safe_message: str,
        *,
        category: str,
        request_identity: str,
        binding_identity: str | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(safe_message)
        self.category = category
        self.retryable = retryable
        self.safe_message = safe_message
        self.request_identity = request_identity
        self.binding_identity = binding_identity

    def to_payload(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "retryable": self.retryable,
            "safe_message": self.safe_message,
            "request_identity": self.request_identity,
            "binding_identity": self.binding_identity,
        }


@dataclass(frozen=True, slots=True)
class AuthorizedTransportRequest:
    request: TransportRequest
    request_identity: str
    credential_identity: str
    lease_identity: str
    provider_name: str
    channel_id: str
    youtube_channel_id: str
    scope_names: tuple[str, ...]
    expires_at: datetime
    binding_identity: str
    _lease: RuntimeCredentialLease = field(repr=False, compare=False, hash=False)

    def __post_init__(self) -> None:
        if not isinstance(self.request, TransportRequest):
            raise ValueError("request must be a TransportRequest")
        if self.request_identity != self.request.request_identity:
            raise ValueError("request_identity mismatch")
        if not isinstance(self.expires_at, datetime) or self.expires_at.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware")

        normalized_scopes = tuple(sorted({str(scope).strip() for scope in self.scope_names}))
        if any(not scope for scope in normalized_scopes):
            raise ValueError("scope_names must not contain blank values")

        object.__setattr__(self, "scope_names", normalized_scopes)
        object.__setattr__(self, "expires_at", self.expires_at.astimezone(timezone.utc))

    def __repr__(self) -> str:
        return (
            "AuthorizedTransportRequest(request=TransportRequest(...), request_identity=..., "
            "credential_identity=..., lease_identity=..., provider_name=..., channel_id=..., "
            "youtube_channel_id=..., scope_names=..., expires_at=..., binding_identity=...)"
        )

    def __str__(self) -> str:
        return self.__repr__()

    def with_authorization(self, callback: Callable[[TransportRequest, str], Any]) -> Any:
        # Python cannot guarantee memory zeroization; this API only limits exposure scope.
        def _invoke(secret: str) -> Any:
            return callback(self.request, secret)

        return self._lease.with_secret(_invoke)

    def to_payload(self) -> dict[str, Any]:
        return {
            "request_identity": self.request_identity,
            "credential_identity": self.credential_identity,
            "lease_identity": self.lease_identity,
            "provider_name": self.provider_name,
            "channel_id": self.channel_id,
            "youtube_channel_id": self.youtube_channel_id,
            "scope_names": list(self.scope_names),
            "expires_at": self.expires_at.isoformat(),
            "binding_identity": self.binding_identity,
        }


@runtime_checkable
class AuthorizedTransportRequestBinder(Protocol):
    def bind(
        self,
        request: TransportRequest,
        credential_request: CredentialProviderRequest,
        descriptor: CredentialDescriptor,
        lease: RuntimeCredentialLease,
    ) -> AuthorizedTransportRequest:
        ...


class DeterministicAuthorizedTransportRequestBinder:
    """Deterministic, in-memory binder for safe authorized request composition."""

    def __init__(
        self,
        *,
        reference_time: datetime,
        required_scopes: tuple[str, ...] | None = None,
        failures: Mapping[str, str] | None = None,
    ) -> None:
        if not isinstance(reference_time, datetime) or reference_time.tzinfo is None:
            raise ValueError("reference_time must be timezone-aware")
        self._reference_time = reference_time.astimezone(timezone.utc)
        self._required_scopes = tuple(sorted({str(scope).strip() for scope in (required_scopes or ())}))
        self._failures = dict(failures or {})

    def bind(
        self,
        request: TransportRequest,
        credential_request: CredentialProviderRequest,
        descriptor: CredentialDescriptor,
        lease: RuntimeCredentialLease,
    ) -> AuthorizedTransportRequest:
        self._validate(request, credential_request, descriptor, lease)

        if self._failures.get("binding") == "internal":
            raise AuthorizedTransportBindingError(
                "internal error",
                category="INTERNAL_ERROR",
                request_identity=request.request_identity,
            )

        normalized_scopes = tuple(sorted(set(lease.scope_names)))
        binding_identity = self._build_binding_identity(
            request_identity=request.request_identity,
            provider_name=lease.provider_name,
            credential_identity=lease.credential_identity,
            lease_identity=lease.lease_identity,
            channel_id=lease.channel_id,
            youtube_channel_id=lease.youtube_channel_id,
            scope_names=normalized_scopes,
        )

        return AuthorizedTransportRequest(
            request=request,
            request_identity=request.request_identity,
            credential_identity=lease.credential_identity,
            lease_identity=lease.lease_identity,
            provider_name=lease.provider_name,
            channel_id=lease.channel_id,
            youtube_channel_id=lease.youtube_channel_id,
            scope_names=normalized_scopes,
            expires_at=lease.expires_at,
            binding_identity=binding_identity,
            _lease=lease,
        )

    def _validate(
        self,
        request: TransportRequest,
        credential_request: CredentialProviderRequest,
        descriptor: CredentialDescriptor,
        lease: RuntimeCredentialLease,
    ) -> None:
        if not str(request.request_identity or "").strip():
            raise AuthorizedTransportBindingError(
                "invalid request",
                category="INVALID_REQUEST",
                request_identity=request.request_identity,
            )

        if not str(credential_request.request_identity or "").strip():
            raise AuthorizedTransportBindingError(
                "invalid request",
                category="INVALID_REQUEST",
                request_identity=request.request_identity,
            )

        if credential_request.credential_kind not in SUPPORTED_CREDENTIAL_KINDS:
            raise AuthorizedTransportBindingError(
                "unsupported credential kind",
                category="INVALID_REQUEST",
                request_identity=request.request_identity,
            )

        if descriptor.status != "ACTIVE":
            raise AuthorizedTransportBindingError(
                "credential disabled",
                category="DISABLED",
                request_identity=request.request_identity,
            )

        if credential_request.provider_name != descriptor.provider_name or descriptor.provider_name != lease.provider_name:
            raise AuthorizedTransportBindingError(
                "provider mismatch",
                category="PROVIDER_MISMATCH",
                request_identity=request.request_identity,
            )

        if (
            credential_request.credential_identity != descriptor.credential_identity
            or credential_request.credential_identity != lease.credential_identity
        ):
            raise AuthorizedTransportBindingError(
                "credential mismatch",
                category="CREDENTIAL_MISMATCH",
                request_identity=request.request_identity,
            )

        if credential_request.channel_id != descriptor.channel_id or credential_request.channel_id != lease.channel_id:
            raise AuthorizedTransportBindingError(
                "channel mismatch",
                category="CHANNEL_MISMATCH",
                request_identity=request.request_identity,
            )

        if (
            credential_request.youtube_channel_id != descriptor.youtube_channel_id
            or credential_request.youtube_channel_id != lease.youtube_channel_id
        ):
            raise AuthorizedTransportBindingError(
                "youtube channel mismatch",
                category="YOUTUBE_CHANNEL_MISMATCH",
                request_identity=request.request_identity,
            )

        if lease.expires_at.tzinfo is None:
            raise ValueError("lease expiry must be timezone-aware")

        if lease.expires_at <= self._reference_time:
            raise AuthorizedTransportBindingError(
                "credential expired",
                category="EXPIRED",
                request_identity=request.request_identity,
                retryable=True,
            )

        lease_scopes = tuple(sorted(set(lease.scope_names)))
        descriptor_scopes = tuple(sorted(set(descriptor.scope_names)))
        if lease_scopes != descriptor_scopes:
            raise AuthorizedTransportBindingError(
                "scope mismatch",
                category="SCOPE_MISMATCH",
                request_identity=request.request_identity,
            )

        if any(scope not in lease_scopes for scope in self._required_scopes):
            raise AuthorizedTransportBindingError(
                "scope mismatch",
                category="SCOPE_MISMATCH",
                request_identity=request.request_identity,
            )

        if "secret" in str(request.endpoint_id).lower():
            raise AuthorizedTransportBindingError(
                "invalid request",
                category="INVALID_REQUEST",
                request_identity=request.request_identity,
            )

    def _build_binding_identity(
        self,
        *,
        request_identity: str,
        provider_name: str,
        credential_identity: str,
        lease_identity: str,
        channel_id: str,
        youtube_channel_id: str,
        scope_names: tuple[str, ...],
    ) -> str:
        payload = {
            "request_identity": request_identity,
            "provider_name": provider_name,
            "credential_identity": credential_identity,
            "lease_identity": lease_identity,
            "channel_id": channel_id,
            "youtube_channel_id": youtube_channel_id,
            "scope_names": list(scope_names),
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()


__all__ = [
    "AuthorizedTransportBindingError",
    "AuthorizedTransportRequest",
    "AuthorizedTransportRequestBinder",
    "DeterministicAuthorizedTransportRequestBinder",
]
