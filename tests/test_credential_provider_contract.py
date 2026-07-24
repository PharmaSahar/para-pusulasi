from __future__ import annotations

import json
import os
import socket
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from src.credential_provider_contract import (
    CredentialDescriptor,
    CredentialProviderError,
    CredentialProviderRequest,
    InMemoryCredentialProvider,
)


def _build_request(**overrides):
    payload = {
        "provider_schema_version": "credential-provider.v1",
        "provider_name": "fake",
        "channel_id": "channel_alpha",
        "youtube_channel_id": "UC-alpha",
        "credential_kind": "YOUTUBE_ANALYTICS",
        "credential_identity": "cred-alpha",
    }
    payload.update(overrides)
    return CredentialProviderRequest(**payload)


def _build_descriptor(**overrides):
    payload = {
        "provider_name": "fake",
        "credential_identity": "cred-alpha",
        "channel_id": "channel_alpha",
        "youtube_channel_id": "UC-alpha",
        "scope_names": ("youtube.readonly",),
        "expires_at": datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc),
        "refresh_supported": True,
        "status": "ACTIVE",
    }
    payload.update(overrides)
    return CredentialDescriptor(**payload)


def test_request_identity_is_deterministic_for_equivalent_requests():
    first = _build_request()
    second = _build_request()
    assert first.request_identity == second.request_identity


def test_request_model_is_immutable():
    request = _build_request()
    with pytest.raises(FrozenInstanceError):
        request.channel_id = "changed"


def test_descriptor_model_is_immutable():
    descriptor = _build_descriptor()
    with pytest.raises(FrozenInstanceError):
        descriptor.status = "DISABLED"


def test_descriptor_contains_no_sensitive_values():
    descriptor = _build_descriptor()
    payload = descriptor.to_payload()
    for forbidden in ("access_token", "refresh_token", "client_secret", "client_id", "authorization_code", "token_value", "private_key"):
        assert forbidden not in payload


def test_fake_provider_returns_configured_descriptor():
    provider = InMemoryCredentialProvider(
        provider_name="fake",
        descriptors=[_build_descriptor()],
    )
    resolved = provider.resolve(_build_request())
    assert resolved.credential_identity == "cred-alpha"
    assert resolved.status == "ACTIVE"


def test_fake_provider_missing_descriptor_raises_not_found():
    provider = InMemoryCredentialProvider(provider_name="fake")
    with pytest.raises(CredentialProviderError) as exc_info:
        provider.resolve(_build_request())
    assert exc_info.value.category == "NOT_FOUND"


def test_channel_mismatch_raises_channel_mismatch():
    provider = InMemoryCredentialProvider(
        provider_name="fake",
        descriptors=[_build_descriptor(channel_id="channel_beta")],
    )
    with pytest.raises(CredentialProviderError) as exc_info:
        provider.resolve(_build_request())
    assert exc_info.value.category == "CHANNEL_MISMATCH"


def test_unsupported_provider_raises_error():
    provider = InMemoryCredentialProvider(provider_name="fake")
    with pytest.raises(CredentialProviderError) as exc_info:
        provider.resolve(_build_request(provider_name="other"))
    assert exc_info.value.category == "UNSUPPORTED_PROVIDER"


def test_unsupported_kind_raises_error():
    provider = InMemoryCredentialProvider(provider_name="fake")
    with pytest.raises(CredentialProviderError) as exc_info:
        provider.resolve(_build_request(credential_kind="YOUTUBE_LIVE"))
    assert exc_info.value.category == "UNSUPPORTED_KIND"


def test_expired_descriptor_is_retryable():
    provider = InMemoryCredentialProvider(
        provider_name="fake",
        descriptors=[_build_descriptor(status="EXPIRED")],
    )
    with pytest.raises(CredentialProviderError) as exc_info:
        provider.resolve(_build_request())
    assert exc_info.value.category == "EXPIRED"
    assert exc_info.value.retryable is True


def test_safe_serialization_omits_traceback_details():
    error = CredentialProviderError(
        "credential missing",
        category="NOT_FOUND",
        request_identity="req-1",
    )
    payload = error.to_payload()
    assert payload["category"] == "NOT_FOUND"
    assert "traceback" not in payload
    assert payload["request_identity"] == "req-1"


def test_provider_does_not_use_environment_values(monkeypatch):
    monkeypatch.setenv("SOME_SECRET_VALUE", "should-not-be-used")
    provider = InMemoryCredentialProvider(
        provider_name="fake",
        descriptors=[_build_descriptor()],
    )
    descriptor = provider.resolve(_build_request())
    assert descriptor.credential_identity == "cred-alpha"


def test_provider_does_not_use_network(monkeypatch):
    def _fail(*args, **kwargs):
        raise AssertionError("network access should not occur")

    monkeypatch.setattr(socket, "create_connection", _fail)
    provider = InMemoryCredentialProvider(
        provider_name="fake",
        descriptors=[_build_descriptor()],
    )
    descriptor = provider.resolve(_build_request())
    assert descriptor.credential_identity == "cred-alpha"


def test_payload_is_json_serializable():
    descriptor = _build_descriptor()
    payload = descriptor.to_payload()
    json.dumps(payload)
