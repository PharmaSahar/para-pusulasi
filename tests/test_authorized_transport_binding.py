from __future__ import annotations

import logging
from datetime import datetime, timezone

import pytest

from src.authorized_transport_binding import (
    AuthorizedTransportBindingError,
    AuthorizedTransportRequest,
    AuthorizedTransportRequestBinder,
    DeterministicAuthorizedTransportRequestBinder,
)
from src.credential_provider_contract import CredentialDescriptor, CredentialProviderRequest
from src.live_transport_contract import TransportRequest
from src.runtime_credential_contract import RuntimeCredentialLease


def _transport_request(*, endpoint_id: str = "youtube-analytics-endpoint") -> TransportRequest:
    return TransportRequest(
        request_identity="req-001",
        endpoint_id=endpoint_id,
        query_parameters={"channel_id": "channel_alpha", "metrics": "views"},
        timeout_seconds=10,
        retry_metadata={"attempt": 1},
    )


def _credential_request(*, credential_kind: str = "YOUTUBE_ANALYTICS") -> CredentialProviderRequest:
    return CredentialProviderRequest(
        provider_schema_version="credential-provider.v1",
        provider_name="runtime-provider-alpha",
        channel_id="channel_alpha",
        youtube_channel_id="UC-alpha",
        credential_kind=credential_kind,
        credential_identity="cred-alpha",
    )


def _descriptor(*, status: str = "ACTIVE", scopes: tuple[str, ...] = ("scope-a", "scope-b")) -> CredentialDescriptor:
    return CredentialDescriptor(
        provider_name="runtime-provider-alpha",
        credential_identity="cred-alpha",
        channel_id="channel_alpha",
        youtube_channel_id="UC-alpha",
        scope_names=scopes,
        expires_at=datetime(2026, 7, 24, 13, 0, tzinfo=timezone.utc),
        refresh_supported=True,
        status=status,
    )


def _lease(*, expires_at: datetime | None = None, scopes: tuple[str, ...] = ("scope-a", "scope-b")) -> RuntimeCredentialLease:
    return RuntimeCredentialLease(
        provider_name="runtime-provider-alpha",
        credential_identity="cred-alpha",
        channel_id="channel_alpha",
        youtube_channel_id="UC-alpha",
        scope_names=scopes,
        issued_at=datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc),
        expires_at=expires_at or datetime(2026, 7, 24, 13, 0, tzinfo=timezone.utc),
        refresh_supported=True,
        lease_identity="lease-001",
        secret_value="test-runtime-secret",
    )


def _binder(*, required_scopes: tuple[str, ...] = ()) -> DeterministicAuthorizedTransportRequestBinder:
    return DeterministicAuthorizedTransportRequestBinder(
        reference_time=datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc),
        required_scopes=required_scopes,
    )


def test_authorized_request_creation() -> None:
    authorized = _binder().bind(_transport_request(), _credential_request(), _descriptor(), _lease())
    assert isinstance(authorized, AuthorizedTransportRequest)
    assert authorized.request_identity == "req-001"


def test_authorized_request_is_immutable() -> None:
    authorized = _binder().bind(_transport_request(), _credential_request(), _descriptor(), _lease())
    with pytest.raises(AttributeError):
        authorized.channel_id = "other"


def test_existing_transport_request_is_reused() -> None:
    request = _transport_request()
    authorized = _binder().bind(request, _credential_request(), _descriptor(), _lease())
    assert authorized.request is request


def test_existing_lease_is_reused() -> None:
    lease = _lease()
    authorized = _binder().bind(_transport_request(), _credential_request(), _descriptor(), lease)
    result = authorized.with_authorization(lambda req, secret: (req.request_identity, secret))
    assert result == ("req-001", "test-runtime-secret")


def test_protocol_compatibility() -> None:
    binder = _binder()
    assert isinstance(binder, AuthorizedTransportRequestBinder)


def test_deterministic_binding_identity() -> None:
    binder = _binder()
    a = binder.bind(_transport_request(), _credential_request(), _descriptor(), _lease())
    b = binder.bind(_transport_request(), _credential_request(), _descriptor(), _lease())
    assert a.binding_identity == b.binding_identity


def test_repeated_binding_equality() -> None:
    binder = _binder()
    a = binder.bind(_transport_request(), _credential_request(), _descriptor(), _lease())
    b = binder.bind(_transport_request(), _credential_request(), _descriptor(), _lease())
    assert a == b


def test_provider_mismatch() -> None:
    request = _credential_request()
    descriptor = _descriptor()
    lease = RuntimeCredentialLease(
        provider_name="other-provider",
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
    with pytest.raises(AuthorizedTransportBindingError) as exc_info:
        _binder().bind(_transport_request(), request, descriptor, lease)
    assert exc_info.value.category == "PROVIDER_MISMATCH"


def test_credential_identity_mismatch() -> None:
    request = CredentialProviderRequest(
        provider_schema_version="credential-provider.v1",
        provider_name="runtime-provider-alpha",
        channel_id="channel_alpha",
        youtube_channel_id="UC-alpha",
        credential_kind="YOUTUBE_ANALYTICS",
        credential_identity="other",
    )
    with pytest.raises(AuthorizedTransportBindingError) as exc_info:
        _binder().bind(_transport_request(), request, _descriptor(), _lease())
    assert exc_info.value.category == "CREDENTIAL_MISMATCH"


def test_channel_mismatch() -> None:
    request = CredentialProviderRequest(
        provider_schema_version="credential-provider.v1",
        provider_name="runtime-provider-alpha",
        channel_id="other-channel",
        youtube_channel_id="UC-alpha",
        credential_kind="YOUTUBE_ANALYTICS",
        credential_identity="cred-alpha",
    )
    with pytest.raises(AuthorizedTransportBindingError) as exc_info:
        _binder().bind(_transport_request(), request, _descriptor(), _lease())
    assert exc_info.value.category == "CHANNEL_MISMATCH"


def test_youtube_channel_mismatch() -> None:
    request = CredentialProviderRequest(
        provider_schema_version="credential-provider.v1",
        provider_name="runtime-provider-alpha",
        channel_id="channel_alpha",
        youtube_channel_id="UC-other",
        credential_kind="YOUTUBE_ANALYTICS",
        credential_identity="cred-alpha",
    )
    with pytest.raises(AuthorizedTransportBindingError) as exc_info:
        _binder().bind(_transport_request(), request, _descriptor(), _lease())
    assert exc_info.value.category == "YOUTUBE_CHANNEL_MISMATCH"


def test_disabled_descriptor() -> None:
    with pytest.raises(AuthorizedTransportBindingError) as exc_info:
        _binder().bind(_transport_request(), _credential_request(), _descriptor(status="DISABLED"), _lease())
    assert exc_info.value.category == "DISABLED"


def test_unsupported_credential_kind() -> None:
    request = _credential_request(credential_kind="OTHER")
    with pytest.raises(AuthorizedTransportBindingError) as exc_info:
        _binder().bind(_transport_request(), request, _descriptor(), _lease())
    assert exc_info.value.category == "INVALID_REQUEST"


def test_missing_required_scope() -> None:
    binder = _binder(required_scopes=("scope-c",))
    with pytest.raises(AuthorizedTransportBindingError) as exc_info:
        binder.bind(_transport_request(), _credential_request(), _descriptor(), _lease())
    assert exc_info.value.category == "SCOPE_MISMATCH"


def test_expired_lease() -> None:
    expired_lease = _lease(expires_at=datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc))
    with pytest.raises(AuthorizedTransportBindingError) as exc_info:
        _binder().bind(_transport_request(), _credential_request(), _descriptor(), expired_lease)
    assert exc_info.value.category == "EXPIRED"


def test_exact_expiry_boundary_is_expired() -> None:
    lease = _lease(expires_at=datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc))
    with pytest.raises(AuthorizedTransportBindingError):
        _binder().bind(_transport_request(), _credential_request(), _descriptor(), lease)


def test_valid_future_expiry() -> None:
    lease = _lease(expires_at=datetime(2026, 7, 24, 12, 1, tzinfo=timezone.utc))
    authorized = _binder().bind(_transport_request(), _credential_request(), _descriptor(), lease)
    assert authorized.expires_at > datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc)


def test_naive_reference_time_rejected() -> None:
    with pytest.raises(ValueError):
        DeterministicAuthorizedTransportRequestBinder(reference_time=datetime(2026, 7, 24, 12, 0))


def test_explicit_authorization_callback() -> None:
    authorized = _binder().bind(_transport_request(), _credential_request(), _descriptor(), _lease())
    out = authorized.with_authorization(lambda req, secret: f"{req.request_identity}:{secret}")
    assert out == "req-001:test-runtime-secret"


def test_callback_receives_original_request() -> None:
    request = _transport_request()
    authorized = _binder().bind(request, _credential_request(), _descriptor(), _lease())
    out = authorized.with_authorization(lambda req, secret: req is request)
    assert out is True


def test_callback_not_called_on_failed_validation() -> None:
    called = {"value": False}

    def _callback(req: TransportRequest, secret: str) -> str:
        called["value"] = True
        return "ok"

    with pytest.raises(AuthorizedTransportBindingError):
        _binder(required_scopes=("scope-c",)).bind(_transport_request(), _credential_request(), _descriptor(), _lease())
    assert called["value"] is False


def test_secret_absent_from_repr_and_str() -> None:
    authorized = _binder().bind(_transport_request(), _credential_request(), _descriptor(), _lease())
    text = repr(authorized) + str(authorized)
    assert "test-runtime-secret" not in text
    assert "secret_value" not in text


def test_secret_absent_from_safe_serialization() -> None:
    authorized = _binder().bind(_transport_request(), _credential_request(), _descriptor(), _lease())
    payload = authorized.to_payload()
    assert "secret" not in json_compatible_text(payload)


def test_secret_absent_from_identity_fields() -> None:
    authorized = _binder().bind(_transport_request(), _credential_request(), _descriptor(), _lease())
    assert "test-runtime-secret" not in authorized.request_identity
    assert "test-runtime-secret" not in authorized.binding_identity


def test_secret_absent_from_exceptions() -> None:
    lease = RuntimeCredentialLease(
        provider_name="runtime-provider-alpha",
        credential_identity="cred-alpha",
        channel_id="channel_alpha",
        youtube_channel_id="UC-alpha",
        scope_names=("scope-a", "scope-b"),
        issued_at=datetime(2026, 7, 24, 12, 0, tzinfo=timezone.utc),
        expires_at=datetime(2026, 7, 24, 13, 0, tzinfo=timezone.utc),
        refresh_supported=True,
        lease_identity="lease-001",
        secret_value=None,
    )
    authorized = _binder().bind(_transport_request(), _credential_request(), _descriptor(), lease)
    with pytest.raises(Exception) as exc_info:
        authorized.with_authorization(lambda req, secret: secret)
    assert "test-runtime-secret" not in str(exc_info.value)


def test_secret_absent_from_captured_logs(caplog) -> None:
    authorized = _binder().bind(_transport_request(), _credential_request(), _descriptor(), _lease())
    with caplog.at_level(logging.INFO):
        logging.getLogger("test").info("authorized=%s", authorized)
    assert "test-runtime-secret" not in caplog.text


def test_no_secret_copied_into_query_parameters_or_endpoint() -> None:
    request = _transport_request()
    authorized = _binder().bind(request, _credential_request(), _descriptor(), _lease())
    assert "test-runtime-secret" not in str(authorized.request.query_parameters)
    assert "test-runtime-secret" not in authorized.request.endpoint_id


def test_no_network_environment_or_filesystem_dependency() -> None:
    from pathlib import Path

    source = Path("src/authorized_transport_binding.py").read_text(encoding="utf-8").lower()
    forbidden_tokens = [
        "requests",
        "urllib",
        "aiohttp",
        "httpx",
        "httplib2",
        "socket",
        "os.environ",
        "getenv",
        "open(",
        "path.read",
        "path.write",
        "google",
        "googleapiclient",
    ]
    for token in forbidden_tokens:
        assert token not in source


def test_safe_structured_errors() -> None:
    with pytest.raises(AuthorizedTransportBindingError) as exc_info:
        _binder(required_scopes=("scope-c",)).bind(_transport_request(), _credential_request(), _descriptor(), _lease())
    payload = exc_info.value.to_payload()
    assert sorted(payload.keys()) == [
        "binding_identity",
        "category",
        "request_identity",
        "retryable",
        "safe_message",
    ]


def test_deterministic_execution() -> None:
    binder = _binder()
    request = _transport_request()
    cred_request = _credential_request()
    descriptor = _descriptor()
    lease = _lease()

    outputs = [binder.bind(request, cred_request, descriptor, lease).binding_identity for _ in range(3)]
    assert outputs[0] == outputs[1] == outputs[2]


def json_compatible_text(payload: dict[str, object]) -> str:
    parts: list[str] = []
    for key, value in payload.items():
        parts.append(f"{key}={value}")
    return "|".join(parts).lower()
