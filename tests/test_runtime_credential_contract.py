from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pytest

from src.credential_provider_contract import CredentialDescriptor, CredentialProviderRequest
from src.runtime_credential_contract import (
    FakeRuntimeCredentialResolver,
    RuntimeCredentialLease,
    RuntimeCredentialResolver,
    RuntimeCredentialError,
)


def _descriptor(*, status: str = "ACTIVE", expires_at: datetime | None = None) -> CredentialDescriptor:
    return CredentialDescriptor(
        provider_name="youtube-analytics-runtime",
        credential_identity="cred-alpha",
        channel_id="channel_alpha",
        youtube_channel_id="UC-alpha",
        scope_names=("scope-a", "scope-b"),
        expires_at=expires_at,
        refresh_supported=True,
        status=status,
    )


def _request(*, credential_identity: str = "cred-alpha") -> CredentialProviderRequest:
    return CredentialProviderRequest(
        provider_schema_version="credential-provider.v1",
        provider_name="youtube-analytics-runtime",
        channel_id="channel_alpha",
        youtube_channel_id="UC-alpha",
        credential_kind="YOUTUBE_ANALYTICS",
        credential_identity=credential_identity,
    )


def test_lease_metadata_is_immutable() -> None:
    lease = RuntimeCredentialLease(
        provider_name="youtube-analytics-runtime",
        credential_identity="cred-alpha",
        channel_id="channel_alpha",
        youtube_channel_id="UC-alpha",
        scope_names=("scope-a", "scope-b"),
        issued_at=datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc),
        expires_at=datetime(2026, 7, 24, 13, 0, tzinfo=timezone.utc),
        refresh_supported=True,
        lease_identity="lease-001",
        secret_value="test-runtime-secret",
    )

    with pytest.raises(AttributeError):
        lease.provider_name = "changed"


def test_lease_identity_is_deterministic() -> None:
    lease_a = RuntimeCredentialLease(
        provider_name="youtube-analytics-runtime",
        credential_identity="cred-alpha",
        channel_id="channel_alpha",
        youtube_channel_id="UC-alpha",
        scope_names=("scope-a", "scope-b"),
        issued_at=datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc),
        expires_at=datetime(2026, 7, 24, 13, 0, tzinfo=timezone.utc),
        refresh_supported=True,
        lease_identity="lease-001",
        secret_value="test-runtime-secret",
    )
    lease_b = RuntimeCredentialLease(
        provider_name="youtube-analytics-runtime",
        credential_identity="cred-alpha",
        channel_id="channel_alpha",
        youtube_channel_id="UC-alpha",
        scope_names=("scope-a", "scope-b"),
        issued_at=datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc),
        expires_at=datetime(2026, 7, 24, 13, 0, tzinfo=timezone.utc),
        refresh_supported=True,
        lease_identity="lease-001",
        secret_value="different-secret",
    )

    assert lease_a.lease_identity == lease_b.lease_identity
    assert lease_a.to_payload() == lease_b.to_payload()


def test_secret_is_not_in_repr_or_str() -> None:
    lease = RuntimeCredentialLease(
        provider_name="youtube-analytics-runtime",
        credential_identity="cred-alpha",
        channel_id="channel_alpha",
        youtube_channel_id="UC-alpha",
        scope_names=("scope-a", "scope-b"),
        issued_at=datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc),
        expires_at=datetime(2026, 7, 24, 13, 0, tzinfo=timezone.utc),
        refresh_supported=True,
        lease_identity="lease-001",
        secret_value="test-runtime-secret",
    )

    text = repr(lease) + str(lease)
    assert "test-runtime-secret" not in text
    assert "secret_value" not in text


def test_secret_is_absent_from_safe_serialization() -> None:
    lease = RuntimeCredentialLease(
        provider_name="youtube-analytics-runtime",
        credential_identity="cred-alpha",
        channel_id="channel_alpha",
        youtube_channel_id="UC-alpha",
        scope_names=("scope-a", "scope-b"),
        issued_at=datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc),
        expires_at=datetime(2026, 7, 24, 13, 0, tzinfo=timezone.utc),
        refresh_supported=True,
        lease_identity="lease-001",
        secret_value="test-runtime-secret",
    )

    payload = lease.to_payload()
    assert "secret_value" not in payload
    assert payload["lease_identity"] == "lease-001"


def test_secret_is_only_accessible_via_explicit_callback() -> None:
    lease = RuntimeCredentialLease(
        provider_name="youtube-analytics-runtime",
        credential_identity="cred-alpha",
        channel_id="channel_alpha",
        youtube_channel_id="UC-alpha",
        scope_names=("scope-a", "scope-b"),
        issued_at=datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc),
        expires_at=datetime(2026, 7, 24, 13, 0, tzinfo=timezone.utc),
        refresh_supported=True,
        lease_identity="lease-001",
        secret_value="test-runtime-secret",
    )

    result = lease.with_secret(lambda secret: secret.upper())
    assert result == "TEST-RUNTIME-SECRET"


def test_resolver_protocol_is_compatible() -> None:
    resolver = FakeRuntimeCredentialResolver()
    assert isinstance(resolver, RuntimeCredentialResolver)


def test_fake_resolver_returns_deterministic_lease() -> None:
    resolver = FakeRuntimeCredentialResolver()
    request = _request()
    descriptor = _descriptor()

    lease_a = resolver.resolve(request, descriptor)
    lease_b = resolver.resolve(request, descriptor)

    assert lease_a.lease_identity == lease_b.lease_identity
    assert lease_a.to_payload() == lease_b.to_payload()


def test_provider_mismatch_raises_safe_error() -> None:
    resolver = FakeRuntimeCredentialResolver()
    request = _request()
    descriptor = _descriptor()
    request = CredentialProviderRequest(
        provider_schema_version="credential-provider.v1",
        provider_name="other-provider",
        channel_id="channel_alpha",
        youtube_channel_id="UC-alpha",
        credential_kind="YOUTUBE_ANALYTICS",
        credential_identity="cred-alpha",
    )

    with pytest.raises(RuntimeCredentialError) as exc_info:
        resolver.resolve(request, descriptor)

    assert exc_info.value.category == "UNSUPPORTED_PROVIDER"
    assert exc_info.value.safe_message == "unsupported provider"
    assert exc_info.value.request_identity == request.request_identity


def test_credential_identity_mismatch_raises_safe_error() -> None:
    resolver = FakeRuntimeCredentialResolver()
    request = _request(credential_identity="other")
    descriptor = _descriptor()

    with pytest.raises(RuntimeCredentialError) as exc_info:
        resolver.resolve(request, descriptor)

    assert exc_info.value.category == "NOT_FOUND"
    assert exc_info.value.safe_message == "credential not found"


def test_channel_mismatch_raises_safe_error() -> None:
    resolver = FakeRuntimeCredentialResolver()
    request = CredentialProviderRequest(
        provider_schema_version="credential-provider.v1",
        provider_name="youtube-analytics-runtime",
        channel_id="other-channel",
        youtube_channel_id="UC-alpha",
        credential_kind="YOUTUBE_ANALYTICS",
        credential_identity="cred-alpha",
    )
    descriptor = _descriptor()

    with pytest.raises(RuntimeCredentialError) as exc_info:
        resolver.resolve(request, descriptor)

    assert exc_info.value.category == "CHANNEL_MISMATCH"


def test_youtube_channel_mismatch_raises_safe_error() -> None:
    resolver = FakeRuntimeCredentialResolver()
    request = CredentialProviderRequest(
        provider_schema_version="credential-provider.v1",
        provider_name="youtube-analytics-runtime",
        channel_id="channel_alpha",
        youtube_channel_id="UC-other",
        credential_kind="YOUTUBE_ANALYTICS",
        credential_identity="cred-alpha",
    )
    descriptor = _descriptor()

    with pytest.raises(RuntimeCredentialError) as exc_info:
        resolver.resolve(request, descriptor)

    assert exc_info.value.category == "CHANNEL_MISMATCH"


def test_unsupported_credential_kind_raises_safe_error() -> None:
    resolver = FakeRuntimeCredentialResolver()
    request = CredentialProviderRequest(
        provider_schema_version="credential-provider.v1",
        provider_name="youtube-analytics-runtime",
        channel_id="channel_alpha",
        youtube_channel_id="UC-alpha",
        credential_kind="OTHER",
        credential_identity="cred-alpha",
    )
    descriptor = _descriptor()

    with pytest.raises(RuntimeCredentialError) as exc_info:
        resolver.resolve(request, descriptor)

    assert exc_info.value.category == "UNSUPPORTED_KIND"


def test_disabled_descriptor_raises_safe_error() -> None:
    resolver = FakeRuntimeCredentialResolver()
    request = _request()
    descriptor = _descriptor(status="DISABLED")

    with pytest.raises(RuntimeCredentialError) as exc_info:
        resolver.resolve(request, descriptor)

    assert exc_info.value.category == "DISABLED"


def test_expired_credential_raises_safe_error() -> None:
    resolver = FakeRuntimeCredentialResolver()
    request = _request()
    descriptor = _descriptor(expires_at=datetime(2026, 7, 24, 11, 0, tzinfo=timezone.utc))

    with pytest.raises(RuntimeCredentialError) as exc_info:
        resolver.resolve(request, descriptor)

    assert exc_info.value.category == "EXPIRED"
    assert exc_info.value.retryable is True


def test_exact_expiry_boundary_is_treated_as_expired() -> None:
    resolver = FakeRuntimeCredentialResolver(reference_time=datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc))
    request = _request()
    descriptor = _descriptor(expires_at=datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc))

    with pytest.raises(RuntimeCredentialError) as exc_info:
        resolver.resolve(request, descriptor)

    assert exc_info.value.category == "EXPIRED"


def test_naive_datetime_is_rejected() -> None:
    resolver = FakeRuntimeCredentialResolver()
    request = _request()
    descriptor = _descriptor(expires_at=datetime(2026, 7, 24, 12, 0))

    with pytest.raises(ValueError):
        resolver.resolve(request, descriptor)


def test_scope_normalization_and_exact_validation() -> None:
    resolver = FakeRuntimeCredentialResolver()
    request = _request()
    descriptor = _descriptor()
    descriptor = CredentialDescriptor(
        provider_name="youtube-analytics-runtime",
        credential_identity="cred-alpha",
        channel_id="channel_alpha",
        youtube_channel_id="UC-alpha",
        scope_names=("scope-b", "scope-a", "scope-a"),
        expires_at=datetime(2026, 7, 24, 13, 0, tzinfo=timezone.utc),
        refresh_supported=True,
        status="ACTIVE",
    )

    lease = resolver.resolve(request, descriptor)
    assert lease.scope_names == ("scope-a", "scope-b")


def test_missing_required_scope_raises_safe_error() -> None:
    resolver = FakeRuntimeCredentialResolver(required_scopes=("scope-c",))
    request = _request()
    descriptor = _descriptor()

    with pytest.raises(RuntimeCredentialError) as exc_info:
        resolver.resolve(request, descriptor)

    assert exc_info.value.category == "SCOPE_MISMATCH"


def test_fake_resolver_is_deterministic_across_repeated_calls() -> None:
    resolver = FakeRuntimeCredentialResolver(reference_time=datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc))
    request = _request()
    descriptor = _descriptor(expires_at=datetime(2026, 7, 24, 13, 0, tzinfo=timezone.utc))

    leases = [resolver.resolve(request, descriptor) for _ in range(2)]
    assert all(lease.lease_identity == leases[0].lease_identity for lease in leases)


def test_no_environment_or_filesystem_access_in_fake_resolver() -> None:
    resolver = FakeRuntimeCredentialResolver()
    request = _request()
    descriptor = _descriptor()
    lease = resolver.resolve(request, descriptor)

    assert lease.to_payload()["provider_name"] == "youtube-analytics-runtime"
    assert "secret" not in repr(lease)


def test_no_network_dependency_and_no_google_imports() -> None:
    from pathlib import Path

    source = Path("src/runtime_credential_contract.py").read_text(encoding="utf-8")
    forbidden_tokens = ["requests", "googleapiclient", "google.auth", "httpx", "aiohttp", "urllib", "socket"]
    for token in forbidden_tokens:
        assert token not in source.lower()


def test_safe_error_has_no_secret_and_safe_metadata() -> None:
    resolver = FakeRuntimeCredentialResolver()
    request = _request()
    descriptor = _descriptor(status="DISABLED")

    with pytest.raises(RuntimeCredentialError) as exc_info:
        resolver.resolve(request, descriptor)

    payload = exc_info.value.to_payload()
    assert payload["category"] == "DISABLED"
    assert payload["request_identity"] == request.request_identity
    assert "secret" not in payload["safe_message"].lower()


def test_secret_not_present_in_logs(caplog) -> None:
    lease = RuntimeCredentialLease(
        provider_name="youtube-analytics-runtime",
        credential_identity="cred-alpha",
        channel_id="channel_alpha",
        youtube_channel_id="UC-alpha",
        scope_names=("scope-a", "scope-b"),
        issued_at=datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc),
        expires_at=datetime(2026, 7, 24, 13, 0, tzinfo=timezone.utc),
        refresh_supported=True,
        lease_identity="lease-001",
        secret_value="test-runtime-secret",
    )

    with caplog.at_level(logging.INFO):
        logging.getLogger("test").info("lease %s", lease)

    assert "test-runtime-secret" not in caplog.text


def test_descriptor_remains_metadata_only() -> None:
    descriptor = _descriptor()
    payload = descriptor.to_payload()
    assert payload["provider_name"] == "youtube-analytics-runtime"
    assert payload["status"] == "ACTIVE"
