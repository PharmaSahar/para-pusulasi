from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

SUPPORTED_PROVIDER_SCHEMA_VERSIONS = {"credential-provider.v1"}
SUPPORTED_CREDENTIAL_KINDS = {"YOUTUBE_ANALYTICS", "YOUTUBE_DATA"}


class CredentialProviderError(RuntimeError):
    """Structured credential error without transport details."""

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
class CredentialProviderRequest:
    provider_schema_version: str
    provider_name: str
    channel_id: str
    youtube_channel_id: str
    credential_kind: str
    credential_identity: str
    request_identity: str | None = None

    def __post_init__(self) -> None:
        schema_version = str(self.provider_schema_version or "").strip()
        if not schema_version:
            raise ValueError("provider_schema_version is required")
        if schema_version not in SUPPORTED_PROVIDER_SCHEMA_VERSIONS:
            raise ValueError("unsupported provider schema version")

        provider_name = str(self.provider_name or "").strip()
        if not provider_name:
            raise ValueError("provider_name is required")

        channel_id = str(self.channel_id or "").strip()
        if not channel_id:
            raise ValueError("channel_id is required")

        youtube_channel_id = str(self.youtube_channel_id or "").strip()
        if not youtube_channel_id:
            raise ValueError("youtube_channel_id is required")

        credential_kind = str(self.credential_kind or "").strip().upper()
        if not credential_kind:
            raise ValueError("credential_kind is required")

        credential_identity = str(self.credential_identity or "").strip()
        if not credential_identity:
            raise ValueError("credential_identity is required")

        payload = {
            "provider_schema_version": schema_version,
            "provider_name": provider_name,
            "channel_id": channel_id,
            "youtube_channel_id": youtube_channel_id,
            "credential_kind": credential_kind,
            "credential_identity": credential_identity,
        }
        request_identity = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        object.__setattr__(self, "provider_name", provider_name)
        object.__setattr__(self, "channel_id", channel_id)
        object.__setattr__(self, "youtube_channel_id", youtube_channel_id)
        object.__setattr__(self, "credential_kind", credential_kind)
        object.__setattr__(self, "credential_identity", credential_identity)
        object.__setattr__(self, "request_identity", request_identity)


@dataclass(frozen=True, slots=True)
class CredentialDescriptor:
    provider_name: str
    credential_identity: str
    channel_id: str
    youtube_channel_id: str
    scope_names: tuple[str, ...]
    expires_at: datetime | None
    refresh_supported: bool
    status: str

    def __post_init__(self) -> None:
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
            if self.expires_at.tzinfo is None:
                raise ValueError("expires_at must be timezone-aware")
            object.__setattr__(self, "expires_at", self.expires_at.astimezone(timezone.utc))

        status = str(self.status or "").strip().upper()
        if not status:
            raise ValueError("status is required")
        object.__setattr__(self, "status", status)

    def to_payload(self) -> dict[str, Any]:
        return {
            "provider_name": self.provider_name,
            "credential_identity": self.credential_identity,
            "channel_id": self.channel_id,
            "youtube_channel_id": self.youtube_channel_id,
            "scope_names": list(self.scope_names),
            "expires_at": self.expires_at.isoformat() if self.expires_at is not None else None,
            "refresh_supported": self.refresh_supported,
            "status": self.status,
        }


class CredentialProvider(Protocol):
    provider_name: str

    def resolve(self, request: CredentialProviderRequest) -> CredentialDescriptor:
        ...


class InMemoryCredentialProvider:
    def __init__(
        self,
        *,
        provider_name: str,
        descriptors: list[CredentialDescriptor] | None = None,
    ) -> None:
        self.provider_name = provider_name
        self._descriptors = list(descriptors or [])

    def resolve(self, request: CredentialProviderRequest) -> CredentialDescriptor:
        if str(request.provider_name or "").strip() != self.provider_name:
            raise CredentialProviderError(
                "unsupported provider",
                category="UNSUPPORTED_PROVIDER",
                request_identity=request.request_identity,
            )

        if str(request.credential_kind or "").strip().upper() not in SUPPORTED_CREDENTIAL_KINDS:
            raise CredentialProviderError(
                "unsupported credential kind",
                category="UNSUPPORTED_KIND",
                request_identity=request.request_identity,
            )

        for descriptor in self._descriptors:
            if descriptor.credential_identity != request.credential_identity:
                continue
            if descriptor.channel_id != request.channel_id:
                raise CredentialProviderError(
                    "channel mismatch",
                    category="CHANNEL_MISMATCH",
                    request_identity=request.request_identity,
                )
            if descriptor.youtube_channel_id != request.youtube_channel_id:
                raise CredentialProviderError(
                    "channel mismatch",
                    category="CHANNEL_MISMATCH",
                    request_identity=request.request_identity,
                )
            if descriptor.status == "EXPIRED":
                raise CredentialProviderError(
                    "credential expired",
                    category="EXPIRED",
                    request_identity=request.request_identity,
                    retryable=True,
                )
            if descriptor.status == "DISABLED":
                raise CredentialProviderError(
                    "credential disabled",
                    category="DISABLED",
                    request_identity=request.request_identity,
                )
            return descriptor

        raise CredentialProviderError(
            "credential not found",
            category="NOT_FOUND",
            request_identity=request.request_identity,
        )


__all__ = [
    "CredentialDescriptor",
    "CredentialProvider",
    "CredentialProviderError",
    "CredentialProviderRequest",
    "InMemoryCredentialProvider",
]
