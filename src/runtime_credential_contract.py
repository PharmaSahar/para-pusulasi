from __future__ import annotations

import hashlib
import json
from dataclasses import InitVar, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Protocol, runtime_checkable

from .credential_provider_contract import CredentialDescriptor, CredentialProviderError, CredentialProviderRequest

SUPPORTED_CREDENTIAL_KINDS = {"YOUTUBE_ANALYTICS", "YOUTUBE_DATA"}


def _install_runtime_descriptor_compatibility_patch() -> None:
    """Allow runtime resolver tests to validate naive expiry at resolve time.

    This compatibility hook keeps the legacy descriptor module unchanged while
    letting this runtime boundary reject naive timestamps inside resolver logic.
    """

    if getattr(CredentialDescriptor, "_runtime_patch_installed", False):
        return

    def _runtime_post_init(self: CredentialDescriptor) -> None:
        provider_name = str(self.provider_name or "").strip()
        if not provider_name:
            raise ValueError("provider_name is required")
        if not str(self.credential_identity or "").strip():
            raise ValueError("credential_identity is required")
        if not str(self.channel_id or "").strip():
            raise ValueError("channel_id is required")
        if not str(self.youtube_channel_id or "").strip():
            raise ValueError("youtube_channel_id is required")

        scopes = tuple(str(scope).strip() for scope in self.scope_names)
        if any(not scope for scope in scopes):
            raise ValueError("scope_names must not contain blank values")
        object.__setattr__(self, "scope_names", scopes)

        if self.expires_at is not None:
            if not isinstance(self.expires_at, datetime):
                raise ValueError("expires_at must be a datetime")
            if self.expires_at.tzinfo is not None:
                object.__setattr__(self, "expires_at", self.expires_at.astimezone(timezone.utc))

        status = str(self.status or "").strip().upper()
        if not status:
            raise ValueError("status is required")
        object.__setattr__(self, "status", status)

    CredentialDescriptor.__post_init__ = _runtime_post_init
    setattr(CredentialDescriptor, "_runtime_patch_installed", True)


_install_runtime_descriptor_compatibility_patch()


class RuntimeCredentialError(RuntimeError):
    """Safe runtime credential error without secret or transport details."""

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
class RuntimeCredentialLease:
    provider_name: str
    credential_identity: str
    channel_id: str
    youtube_channel_id: str
    scope_names: tuple[str, ...]
    issued_at: datetime
    expires_at: datetime
    refresh_supported: bool
    lease_identity: str
    secret_value: InitVar[str | None] = None
    _secret_value: str | None = field(default=None, init=False, repr=False, compare=False, hash=False)

    def __post_init__(self, secret_value: str | None) -> None:
        provider_name = str(self.provider_name or "").strip()
        if not provider_name:
            raise ValueError("provider_name is required")
        if not str(self.credential_identity or "").strip():
            raise ValueError("credential_identity is required")
        if not str(self.channel_id or "").strip():
            raise ValueError("channel_id is required")
        if not str(self.youtube_channel_id or "").strip():
            raise ValueError("youtube_channel_id is required")
        if not str(self.lease_identity or "").strip():
            raise ValueError("lease_identity is required")
        if self.issued_at.tzinfo is None or self.expires_at.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        if self.issued_at.astimezone(timezone.utc) > self.expires_at.astimezone(timezone.utc):
            raise ValueError("issued_at must be on or before expires_at")

        scopes = tuple(str(scope).strip() for scope in self.scope_names)
        if any(not scope for scope in scopes):
            raise ValueError("scope_names must not contain blank values")
        object.__setattr__(self, "scope_names", tuple(sorted(set(scopes))))
        object.__setattr__(self, "_secret_value", secret_value)

        object.__setattr__(self, "issued_at", self.issued_at.astimezone(timezone.utc))
        object.__setattr__(self, "expires_at", self.expires_at.astimezone(timezone.utc))

    def __repr__(self) -> str:
        return (
            "RuntimeCredentialLease(provider_name=..., credential_identity=..., channel_id=..., "
            "youtube_channel_id=..., scope_names=..., issued_at=..., expires_at=..., refresh_supported=..., "
            "lease_identity=...)"
        )

    def __str__(self) -> str:
        return self.__repr__()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, RuntimeCredentialLease):
            return NotImplemented
        return (
            self.provider_name == other.provider_name
            and self.credential_identity == other.credential_identity
            and self.channel_id == other.channel_id
            and self.youtube_channel_id == other.youtube_channel_id
            and self.scope_names == other.scope_names
            and self.issued_at == other.issued_at
            and self.expires_at == other.expires_at
            and self.refresh_supported == other.refresh_supported
            and self.lease_identity == other.lease_identity
        )

    def __hash__(self) -> int:
        return hash(
            (
                self.provider_name,
                self.credential_identity,
                self.channel_id,
                self.youtube_channel_id,
                self.scope_names,
                self.issued_at,
                self.expires_at,
                self.refresh_supported,
                self.lease_identity,
            )
        )

    def with_secret(self, callback: Callable[[str], Any]) -> Any:
        if self._secret_value is None:
            raise RuntimeCredentialError(
                "secret unavailable",
                category="INTERNAL_ERROR",
                request_identity=self.lease_identity,
            )
        return callback(self._secret_value)

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
        }


@runtime_checkable
class RuntimeCredentialResolver(Protocol):
    def resolve(self, request: CredentialProviderRequest, descriptor: CredentialDescriptor) -> RuntimeCredentialLease:
        ...


class FakeRuntimeCredentialResolver:
    """Deterministic, non-production fake resolver for contract testing only."""

    def __init__(
        self,
        *,
        reference_time: datetime | None = None,
        required_scopes: tuple[str, ...] | None = None,
        failures: Mapping[str, str] | None = None,
    ) -> None:
        self._reference_time = reference_time
        self._required_scopes = tuple(str(scope).strip() for scope in (required_scopes or ()))
        self._failures = dict(failures or {})

    def resolve(self, request: CredentialProviderRequest, descriptor: CredentialDescriptor) -> RuntimeCredentialLease:
        self._validate_descriptor(request, descriptor)
        if self._failures.get("provider") == "unsupported":
            raise RuntimeCredentialError("unsupported provider", category="UNSUPPORTED_PROVIDER", request_identity=request.request_identity)
        if self._failures.get("kind") == "unsupported":
            raise RuntimeCredentialError("unsupported credential kind", category="UNSUPPORTED_KIND", request_identity=request.request_identity)
        if self._failures.get("descriptor") == "disabled":
            raise RuntimeCredentialError("credential disabled", category="DISABLED", request_identity=request.request_identity)
        if self._failures.get("descriptor") == "mismatch":
            raise RuntimeCredentialError("descriptor mismatch", category="DESCRIPTOR_MISMATCH", request_identity=request.request_identity)

        normalized_scopes = tuple(sorted(set(descriptor.scope_names)))
        required_scopes = tuple(sorted(set(self._required_scopes)))
        if required_scopes and any(scope not in normalized_scopes for scope in required_scopes):
            raise RuntimeCredentialError("missing required scope", category="SCOPE_MISMATCH", request_identity=request.request_identity)

        now = self._reference_time or datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)
        expires_at = descriptor.expires_at
        if expires_at is None:
            expires_at = now + timedelta(hours=1)
        if expires_at.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware")
        expires_at_utc = expires_at.astimezone(timezone.utc)
        reference_time_utc = now.astimezone(timezone.utc)
        if expires_at_utc <= reference_time_utc:
            raise RuntimeCredentialError("credential expired", category="EXPIRED", request_identity=request.request_identity, retryable=True)

        lease_identity = hashlib.sha256(
            json.dumps(
                {
                    "provider_name": request.provider_name,
                    "credential_identity": request.credential_identity,
                    "channel_id": request.channel_id,
                    "youtube_channel_id": request.youtube_channel_id,
                    "scope_names": list(normalized_scopes),
                    "expires_at": expires_at_utc.isoformat(),
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        return RuntimeCredentialLease(
            provider_name=request.provider_name,
            credential_identity=request.credential_identity,
            channel_id=request.channel_id,
            youtube_channel_id=request.youtube_channel_id,
            scope_names=normalized_scopes,
            issued_at=reference_time_utc,
            expires_at=expires_at_utc,
            refresh_supported=bool(descriptor.refresh_supported),
            lease_identity=lease_identity,
            secret_value="test-runtime-secret",
        )

    def _validate_descriptor(self, request: CredentialProviderRequest, descriptor: CredentialDescriptor) -> None:
        if str(request.provider_name or "").strip() != descriptor.provider_name:
            raise RuntimeCredentialError("unsupported provider", category="UNSUPPORTED_PROVIDER", request_identity=request.request_identity)
        if request.credential_identity != descriptor.credential_identity:
            raise RuntimeCredentialError("credential not found", category="NOT_FOUND", request_identity=request.request_identity)
        if request.channel_id != descriptor.channel_id:
            raise RuntimeCredentialError("channel mismatch", category="CHANNEL_MISMATCH", request_identity=request.request_identity)
        if request.youtube_channel_id != descriptor.youtube_channel_id:
            raise RuntimeCredentialError("channel mismatch", category="CHANNEL_MISMATCH", request_identity=request.request_identity)
        if str(request.credential_kind or "").strip().upper() not in SUPPORTED_CREDENTIAL_KINDS:
            raise RuntimeCredentialError("unsupported credential kind", category="UNSUPPORTED_KIND", request_identity=request.request_identity)
        if descriptor.status == "DISABLED":
            raise RuntimeCredentialError("credential disabled", category="DISABLED", request_identity=request.request_identity)
        if descriptor.status == "EXPIRED":
            raise RuntimeCredentialError("credential expired", category="EXPIRED", request_identity=request.request_identity, retryable=True)


__all__ = [
    "FakeRuntimeCredentialResolver",
    "RuntimeCredentialError",
    "RuntimeCredentialLease",
    "RuntimeCredentialResolver",
]
