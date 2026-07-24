from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.credential_provider_contract import CredentialDescriptor, CredentialProviderRequest
from src.google_oauth_credentials import (
    CredentialRedactor,
    FakeOAuthProvider,
    InMemoryCredentialPersistence,
    OAuthCredentialError,
    OAuthCredentialLease,
    OAuthCredentialProvider,
    OAuthRefreshPolicy,
)


def _request() -> CredentialProviderRequest:
    return CredentialProviderRequest(
        provider_schema_version="credential-provider.v1",
        provider_name="oauth-provider-alpha",
        channel_id="channel_alpha",
        youtube_channel_id="UC-alpha",
        credential_kind="YOUTUBE_ANALYTICS",
        credential_identity="cred-alpha",
    )


def _descriptor(status: str = "ACTIVE") -> CredentialDescriptor:
    return CredentialDescriptor(
        provider_name="oauth-provider-alpha",
        credential_identity="cred-alpha",
        channel_id="channel_alpha",
        youtube_channel_id="UC-alpha",
        scope_names=("scope-a", "scope-b"),
        expires_at=datetime(2026, 7, 24, 13, 0, tzinfo=timezone.utc),
        refresh_supported=True,
        status=status,
    )


def test_credential_acquisition() -> None:
    provider = FakeOAuthProvider(reference_time=datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc))
    lease = provider.acquire(_request(), _descriptor())
    assert isinstance(lease, OAuthCredentialLease)
    assert lease.provider_name == "oauth-provider-alpha"


def test_refresh_policy() -> None:
    lease = OAuthCredentialLease(
        provider_name="oauth-provider-alpha",
        credential_identity="cred-alpha",
        channel_id="channel_alpha",
        youtube_channel_id="UC-alpha",
        scope_names=("scope-a", "scope-b"),
        issued_at=datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc),
        expires_at=datetime(2026, 7, 24, 12, 10, tzinfo=timezone.utc),
        refresh_supported=True,
        lease_identity="lease-1",
        access_token_value="fake_access_value",
        refresh_token_value="fake_refresh_value",
    )
    policy = OAuthRefreshPolicy(refresh_window_seconds=120)

    assert policy.should_refresh(lease, reference_time=datetime(2026, 7, 24, 12, 8, tzinfo=timezone.utc)) is True
    assert policy.should_refresh(lease, reference_time=datetime(2026, 7, 24, 12, 7, tzinfo=timezone.utc)) is False


def test_expiration_handling() -> None:
    provider = FakeOAuthProvider(reference_time=datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc), token_ttl_seconds=60)
    lease = provider.acquire(_request(), _descriptor())
    assert lease.expires_at == datetime(2026, 7, 24, 12, 1, tzinfo=timezone.utc)


def test_redaction() -> None:
    payload = {"access_token": "fake_access_abcdefgh", "refresh_token": "fake_refresh_abcdefgh", "status": "ok"}
    redacted = CredentialRedactor.redact_mapping(payload)
    assert redacted["status"] == "ok"
    assert "fake_access_abcdefgh" not in str(redacted)
    assert "fake_refresh_abcdefgh" not in str(redacted)


def test_immutable_credentials() -> None:
    lease = OAuthCredentialLease(
        provider_name="oauth-provider-alpha",
        credential_identity="cred-alpha",
        channel_id="channel_alpha",
        youtube_channel_id="UC-alpha",
        scope_names=("scope-a", "scope-b"),
        issued_at=datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc),
        expires_at=datetime(2026, 7, 24, 12, 10, tzinfo=timezone.utc),
        refresh_supported=True,
        lease_identity="lease-1",
        access_token_value="fake_access_value",
        refresh_token_value="fake_refresh_value",
    )
    with pytest.raises(AttributeError):
        lease.provider_name = "changed"


def test_fake_provider_is_protocol_compatible() -> None:
    provider = FakeOAuthProvider(reference_time=datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc))
    assert isinstance(provider, OAuthCredentialProvider)


def test_dependency_injection_with_persistence() -> None:
    store = InMemoryCredentialPersistence()
    provider = FakeOAuthProvider(
        reference_time=datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc),
        persistence=store,
    )
    lease = provider.acquire(_request(), _descriptor())
    assert store.get(lease.lease_identity) == lease


def test_deterministic_refresh_behavior() -> None:
    provider = FakeOAuthProvider(reference_time=datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc))
    lease = provider.acquire(_request(), _descriptor())
    refreshed = provider.refresh(lease)
    refreshed_again = provider.refresh(lease)

    assert refreshed == refreshed_again
    assert refreshed.issued_at == datetime(2026, 7, 24, 12, 0, 1, tzinfo=timezone.utc)


def test_secret_absent_from_repr_and_payload() -> None:
    provider = FakeOAuthProvider(reference_time=datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc))
    lease = provider.acquire(_request(), _descriptor())

    text = repr(lease) + str(lease)
    payload = lease.to_payload()
    assert "fake_access_" not in text
    assert "fake_refresh_" not in text
    assert "access_token" not in payload
    assert "refresh_token" not in payload


def test_refresh_unsupported_raises() -> None:
    lease = OAuthCredentialLease(
        provider_name="oauth-provider-alpha",
        credential_identity="cred-alpha",
        channel_id="channel_alpha",
        youtube_channel_id="UC-alpha",
        scope_names=("scope-a", "scope-b"),
        issued_at=datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc),
        expires_at=datetime(2026, 7, 24, 12, 10, tzinfo=timezone.utc),
        refresh_supported=False,
        lease_identity="lease-1",
        access_token_value="fake_access_value",
        refresh_token_value="fake_refresh_value",
    )
    provider = FakeOAuthProvider(reference_time=datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc))

    with pytest.raises(OAuthCredentialError) as exc_info:
        provider.refresh(lease)
    assert exc_info.value.category == "PERMANENT"


def test_no_youtube_api_execution_tokens_in_source() -> None:
    source = Path("src/google_oauth_credentials.py").read_text(encoding="utf-8").lower()
    forbidden = ["youtubeanalytics", "youtube data", "reports.query", "analytics download"]
    for token in forbidden:
        assert token not in source
