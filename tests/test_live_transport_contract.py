import pytest

from src.live_transport_contract import (
    LiveTransport,
    TransportError,
    TransportRequest,
    TransportResponse,
    FakeLiveTransport,
)


def test_transport_request_is_immutable() -> None:
    request = TransportRequest(
        request_identity="req-1",
        endpoint_id="youtube-analytics",
        query_parameters={"metrics": "views"},
        timeout_seconds=10,
        retry_metadata={"attempt": 1},
    )

    with pytest.raises(AttributeError):
        request.request_identity = "req-2"


def test_transport_response_is_immutable() -> None:
    response = TransportResponse(
        request_identity="req-1",
        endpoint_id="youtube-analytics",
        payload={"views": 10},
        timeout_seconds=10,
        retry_metadata={"attempt": 1},
    )

    with pytest.raises(AttributeError):
        response.payload = {"views": 20}


def test_fake_transport_is_deterministic() -> None:
    transport = FakeLiveTransport()
    request = TransportRequest(
        request_identity="req-1",
        endpoint_id="youtube-analytics",
        query_parameters={"channel_id": "channel_alpha"},
        timeout_seconds=10,
        retry_metadata={"attempt": 1},
    )

    first = transport.execute(request)
    second = transport.execute(request)

    assert first == second
    assert first.request_identity == "req-1"
    assert first.payload["channel_id"] == "channel_alpha"


def test_fake_transport_simulates_timeout() -> None:
    transport = FakeLiveTransport(failures={"timeout": "TIMEOUT"})
    request = TransportRequest(
        request_identity="req-timeout",
        endpoint_id="youtube-analytics",
        query_parameters={"channel_id": "channel_alpha"},
        timeout_seconds=5,
        retry_metadata={"attempt": 1},
    )

    with pytest.raises(TransportError) as exc_info:
        transport.execute(request)

    assert exc_info.value.category == "TIMEOUT"
    assert exc_info.value.retryable is True
    assert exc_info.value.safe_message == "request timed out"


def test_fake_transport_simulates_rate_limit() -> None:
    transport = FakeLiveTransport(failures={"rate-limit": "RATE_LIMIT"})
    request = TransportRequest(
        request_identity="req-rate",
        endpoint_id="youtube-analytics",
        query_parameters={"channel_id": "channel_alpha"},
        timeout_seconds=5,
        retry_metadata={"attempt": 1},
    )

    with pytest.raises(TransportError) as exc_info:
        transport.execute(request)

    assert exc_info.value.category == "RATE_LIMIT"
    assert exc_info.value.retryable is True
    assert exc_info.value.retry_after_seconds == 60


def test_retry_metadata_is_preserved() -> None:
    request = TransportRequest(
        request_identity="req-2",
        endpoint_id="youtube-analytics",
        query_parameters={"metrics": "views"},
        timeout_seconds=8,
        retry_metadata={"attempt": 2, "backoff_seconds": 2},
    )

    response = TransportResponse(
        request_identity="req-2",
        endpoint_id="youtube-analytics",
        payload={"metrics": "views"},
        timeout_seconds=8,
        retry_metadata={"attempt": 2, "backoff_seconds": 2},
    )

    assert request.retry_metadata["attempt"] == 2
    assert response.retry_metadata["attempt"] == 2


def test_request_identity_is_copied_to_response() -> None:
    request = TransportRequest(
        request_identity="req-3",
        endpoint_id="youtube-analytics",
        query_parameters={"metrics": "views"},
        timeout_seconds=4,
        retry_metadata={"attempt": 1},
    )
    response = TransportResponse.from_request(request, payload={"ok": True})

    assert response.request_identity == request.request_identity
    assert response.endpoint_id == request.endpoint_id
    assert response.timeout_seconds == request.timeout_seconds


def test_protocol_type_and_error_shape() -> None:
    transport = FakeLiveTransport()
    assert isinstance(transport, LiveTransport)
    assert hasattr(transport, "execute")

    request = TransportRequest(
        request_identity="req-4",
        endpoint_id="youtube-analytics",
        query_parameters={"channel_id": "channel_alpha"},
        timeout_seconds=3,
        retry_metadata={"attempt": 1},
    )
    response = transport.execute(request)
    assert response.payload["request_identity"] == request.request_identity


def test_no_network_is_required_for_fake_transport() -> None:
    transport = FakeLiveTransport()
    request = TransportRequest(
        request_identity="req-5",
        endpoint_id="youtube-analytics",
        query_parameters={"channel_id": "channel_alpha"},
        timeout_seconds=3,
        retry_metadata={"attempt": 1},
    )

    response = transport.execute(request)
    assert response.payload["transport_mode"] == "fake"
    assert response.payload["network"] is False
