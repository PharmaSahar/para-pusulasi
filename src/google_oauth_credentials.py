from __future__ import annotations

import hashlib
import json
from dataclasses import InitVar, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Protocol, runtime_checkable

from .credential_provider_contract import CredentialDescriptor, CredentialProviderRequest


class OAuthCredentialError(RuntimeError):
    """Safe OAuth credential error with structured metadata."""

    def __init__(
        self,
        safe_message: str,
        *,
        category: str,
        request_identity: str | None = None,
        retryable: bool = False,
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
class OAuthCredentialLease:
    provider_name: str
    credential_identity: str
    channel_id: str
    youtube_channel_id: str
    scope_names: tuple[str, ...]
    issued_at: datetime
    expires_at: datetime
    refresh_supported: bool
    lease_identity: str
    token_type: str = "Bearer"
    access_token_value: InitVar[str | None] = None
    refresh_token_value: InitVar[str | None] = None
    _access_token_value: str | None = field(default=None, init=False, repr=False, compare=False, hash=False)
    _refresh_token_value: str | None = field(default=None, init=False, repr=False, compare=False, hash=False)

    def __post_init__(self, access_token_value: str | None, refresh_token_value: str | None) -> None:
        if not str(self.provider_name or "").strip():
            raise ValueError("provider_name is required")
        if not str(self.credential_identity or "").strip():
            raise ValueError("credential_identity is required")
        if not str(self.channel_id or "").strip():
            raise ValueError("channel_id is required")
        if not str(self.youtube_channel_id or "").strip():
            raise ValueError("youtube_channel_id is required")
        if not str(self.lease_identity or "").strip():
            raise ValueError("lease_identity is required")
        if not isinstance(self.issued_at, datetime) or self.issued_at.tzinfo is None:
            raise ValueError("issued_at must be timezone-aware")
        if not isinstance(self.expires_at, datetime) or self.expires_at.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware")

        issued_at_utc = self.issued_at.astimezone(timezone.utc)
        expires_at_utc = self.expires_at.astimezone(timezone.utc)
        if issued_at_utc > expires_at_utc:
            raise ValueError("issued_at must be on or before expires_at")

        scopes = tuple(sorted({str(scope).strip() for scope in self.scope_names}))
        if any(not scope for scope in scopes):
            raise ValueError("scope_names must not contain blank values")

        token_type = str(self.token_type or "").strip() or "Bearer"

        object.__setattr__(self, "issued_at", issued_at_utc)
        object.__setattr__(self, "expires_at", expires_at_utc)
        object.__setattr__(self, "scope_names", scopes)
        object.__setattr__(self, "token_type", token_type)
        object.__setattr__(self, "_access_token_value", access_token_value)
        object.__setattr__(self, "_refresh_token_value", refresh_token_value)

    def __repr__(self) -> str:
        return (
            "OAuthCredentialLease(provider_name=..., credential_identity=..., channel_id=..., "
            "youtube_channel_id=..., scope_names=..., issued_at=..., expires_at=..., "
            "refresh_supported=..., lease_identity=..., token_type=...)"
        )

    def __str__(self) -> str:
        return self.__repr__()

    def with_access_token(self, callback: Callable[[str], Any]) -> Any:
        if self._access_token_value is None:
            raise OAuthCredentialError("access token unavailable", category="INTERNAL_ERROR")
        return callback(self._access_token_value)

    def with_refresh_token(self, callback: Callable[[str], Any]) -> Any:
        if self._refresh_token_value is None:
            raise OAuthCredentialError("refresh token unavailable", category="INTERNAL_ERROR")
        return callback(self._refresh_token_value)

    def to_payload(self) -> dict[str, Any]:
        return {
            "provider_name": self.provider_name,
            "credential_identity": self.credential_identity,
            "channel_id": self.channel_id,
            "youtube_channel_id": self.youtube_channel_id,
            "scope_names": list(self.scope_names),
            "issued_at": self.issued_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "refresh_supported": self.refresh_supported,
            "lease_identity": self.lease_identity,
            "token_type": self.token_type,
        }


@dataclass(frozen=True, slots=True)
class OAuthRefreshPolicy:
    refresh_window_seconds: int

    def __post_init__(self) -> None:
        if int(self.refresh_window_seconds) < 0:
            raise ValueError("refresh_window_seconds must be nonnegative")

    def should_refresh(self, lease: OAuthCredentialLease, *, reference_time: datetime) -> bool:
        if not isinstance(reference_time, datetime) or reference_time.tzinfo is None:
            raise ValueError("reference_time must be timezone-aware")
        reference_utc = reference_time.astimezone(timezone.utc)
        refresh_at = lease.expires_at - timedelta(seconds=int(self.refresh_window_seconds))
        return reference_utc >= refresh_at


class CredentialRedactor:
    @staticmethod
    def redact_token(value: str | None) -> str:
        if value is None:
            return "<redacted:none>"
        token = str(value)
        if len(token) <= 6:
            return "<redacted:short>"
        return f"<redacted:{token[:2]}...{token[-2:]}>"

    @staticmethod
    def redact_mapping(payload: Mapping[str, Any]) -> dict[str, Any]:
        redacted: dict[str, Any] = {}
        for key, value in payload.items():
            normalized_key = str(key).lower()
            if "token" in normalized_key or "secret" in normalized_key:
                redacted[str(key)] = CredentialRedactor.redact_token(None if value is None else str(value))
            else:
                redacted[str(key)] = value
        return redacted


class CredentialPersistence(Protocol):
    def save(self, lease: OAuthCredentialLease) -> None:
        ...


@runtime_checkable
class OAuthCredentialProvider(Protocol):
    def acquire(self, request: CredentialProviderRequest, descriptor: CredentialDescriptor) -> OAuthCredentialLease:
        ...

    def refresh(self, lease: OAuthCredentialLease) -> OAuthCredentialLease:
        ...


class InMemoryCredentialPersistence:
    def __init__(self) -> None:
        self._leases: dict[str, OAuthCredentialLease] = {}

    def save(self, lease: OAuthCredentialLease) -> None:
        self._leases[lease.lease_identity] = lease

    def get(self, lease_identity: str) -> OAuthCredentialLease | None:
        return self._leases.get(lease_identity)


class FakeOAuthProvider:
    """Deterministic offline OAuth provider for contract testing only."""

    def __init__(
        self,
        *,
        reference_time: datetime,
        token_ttl_seconds: int = 3600,
        persistence: CredentialPersistence | None = None,
    ) -> None:
        if reference_time.tzinfo is None:
            raise ValueError("reference_time must be timezone-aware")
        if int(token_ttl_seconds) <= 0:
            raise ValueError("token_ttl_seconds must be positive")
        self._reference_time = reference_time.astimezone(timezone.utc)
        self._token_ttl_seconds = int(token_ttl_seconds)
        self._persistence = persistence

    def acquire(self, request: CredentialProviderRequest, descriptor: CredentialDescriptor) -> OAuthCredentialLease:
        self._validate_request_descriptor(request, descriptor)
        lease = self._build_lease(
            request=request,
            issued_at=self._reference_time,
        )
        if self._persistence is not None:
            self._persistence.save(lease)
        return lease

    def refresh(self, lease: OAuthCredentialLease) -> OAuthCredentialLease:
        if not lease.refresh_supported:
            raise OAuthCredentialError("refresh unsupported", category="PERMANENT", retryable=False)

        request = CredentialProviderRequest(
            provider_schema_version="credential-provider.v1",
            provider_name=lease.provider_name,
            channel_id=lease.channel_id,
            youtube_channel_id=lease.youtube_channel_id,
            credential_kind="YOUTUBE_ANALYTICS",
            credential_identity=lease.credential_identity,
        )

        refreshed = self._build_lease(
            request=request,
            issued_at=self._reference_time + timedelta(seconds=1),
        )
        if self._persistence is not None:
            self._persistence.save(refreshed)
        return refreshed

    def _build_lease(self, *, request: CredentialProviderRequest, issued_at: datetime) -> OAuthCredentialLease:
        expires_at = issued_at + timedelta(seconds=self._token_ttl_seconds)
        scope_names = ("scope-a", "scope-b")

        access_token_value = self._derive_secret("access", request.request_identity, issued_at)
        refresh_token_value = self._derive_secret("refresh", request.request_identity, issued_at)

        lease_identity = hashlib.sha256(
            json.dumps(
                {
                    "provider_name": request.provider_name,
                    "credential_identity": request.credential_identity,
                    "channel_id": request.channel_id,
                    "youtube_channel_id": request.youtube_channel_id,
                    "scope_names": list(scope_names),
                    "issued_at": issued_at.isoformat(),
                    "expires_at": expires_at.isoformat(),
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()

        return OAuthCredentialLease(
            provider_name=request.provider_name,
            credential_identity=request.credential_identity,
            channel_id=request.channel_id,
            youtube_channel_id=request.youtube_channel_id,
            scope_names=scope_names,
            issued_at=issued_at,
            expires_at=expires_at,
            refresh_supported=True,
            lease_identity=lease_identity,
            token_type="Bearer",
            access_token_value=access_token_value,
            refresh_token_value=refresh_token_value,
        )

    def _validate_request_descriptor(self, request: CredentialProviderRequest, descriptor: CredentialDescriptor) -> None:
        if request.provider_name != descriptor.provider_name:
            raise OAuthCredentialError(
                "provider mismatch",
                category="INVALID_REQUEST",
                request_identity=request.request_identity,
            )
        if request.credential_identity != descriptor.credential_identity:
            raise OAuthCredentialError(
                "credential mismatch",
                category="INVALID_REQUEST",
                request_identity=request.request_identity,
            )
        if request.channel_id != descriptor.channel_id:
            raise OAuthCredentialError(
                "channel mismatch",
                category="INVALID_REQUEST",
                request_identity=request.request_identity,
            )
        if request.youtube_channel_id != descriptor.youtube_channel_id:
            raise OAuthCredentialError(
                "channel mismatch",
                category="INVALID_REQUEST",
                request_identity=request.request_identity,
            )
        if descriptor.status != "ACTIVE":
            raise OAuthCredentialError(
                "credential disabled",
                category="PERMANENT",
                request_identity=request.request_identity,
                retryable=False,
            )

    def _derive_secret(self, prefix: str, request_identity: str | None, issued_at: datetime) -> str:
        digest = hashlib.sha256(f"{prefix}:{request_identity}:{issued_at.isoformat()}".encode("utf-8")).hexdigest()
        return f"fake_{prefix}_{digest[:20]}"


__all__ = [
    "CredentialPersistence",
    "CredentialRedactor",
    "FakeOAuthProvider",
    "InMemoryCredentialPersistence",
    "OAuthCredentialError",
    "OAuthCredentialLease",
    "OAuthCredentialProvider",
    "OAuthRefreshPolicy",
]
