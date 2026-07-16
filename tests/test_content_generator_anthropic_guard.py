from __future__ import annotations

import json
import threading
from types import SimpleNamespace

import httpx
import pytest
from anthropic._exceptions import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    OverloadedError,
    PermissionDeniedError,
    RateLimitError,
    ServiceUnavailableError,
)

import src.content_generator as content_generator
import src.scheduler_utils as scheduler_utils


def _payload_response(title: str = "Title"):
    payload = {
        "title": title,
        "description": "Description",
        "tags": ["a"],
        "script": "Script",
        "thumbnail_prompt": "Thumb",
        "category_id": "27",
        "hook": "Hook",
        "next_video_teaser": "Teaser",
        "pexels_search": "query",
        "chart_data": None,
    }
    return SimpleNamespace(content=[SimpleNamespace(text=json.dumps(payload, ensure_ascii=False))])


def _make_generator(messages) -> content_generator.ContentGenerator:
    generator = content_generator.ContentGenerator.__new__(content_generator.ContentGenerator)
    generator.client = SimpleNamespace(messages=messages)
    generator.niche = "saglik"
    generator.model = "fake-model"
    generator._persona = None
    generator._channel_name = "Test"
    generator._channel_topics = []
    generator._channel_dna_overrides = {}
    return generator


def _prepare_provider_state(monkeypatch, tmp_path):
    monkeypatch.setattr(content_generator, "_LAST_ANTHROPIC_CALL_AT", 0.0)
    monkeypatch.setattr(scheduler_utils, "PROVIDER_HEALTH_FILE", str(tmp_path / "provider_health.json"))
    monkeypatch.setenv("ANTHROPIC_RATE_GATE_LOCK_FILE", str(tmp_path / "anthropic_rate_gate.lock"))
    monkeypatch.setenv("ANTHROPIC_RATE_GATE_STATE_FILE", str(tmp_path / "anthropic_rate_gate.json"))
    monkeypatch.setenv("ANTHROPIC_MIN_REQUEST_INTERVAL_SECONDS", "0")
    monkeypatch.setenv("ANTHROPIC_MAX_RETRIES", "3")


def _status_error(error_cls, status_code: int, message: str, error_type: str | None = None):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    body = {"error": {"message": message}}
    if error_type:
        body = {"type": "error", "error": {"type": error_type, "message": message}}
    return error_cls(message, response=httpx.Response(status_code, request=request), body=body)


def _connection_error():
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return APIConnectionError(message="Connection error.", request=request)


def _timeout_error():
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return APITimeoutError(request)


class SequencedMessages:
    def __init__(self, events):
        self.events = list(events)
        self.calls = 0

    def create(self, **_kwargs):
        self.calls += 1
        event = self.events.pop(0)
        if isinstance(event, Exception):
            raise event
        return event


def test_generate_video_content_makes_exactly_one_messages_create(monkeypatch, tmp_path):
    _prepare_provider_state(monkeypatch, tmp_path)
    monkeypatch.setattr(content_generator, "build_prompt_metadata", lambda _prompt: {})
    monkeypatch.setattr(content_generator, "build_channel_dna_metadata", lambda **_kwargs: {})
    monkeypatch.setattr(content_generator, "build_quality_scores", lambda **_kwargs: {})
    monkeypatch.setattr(content_generator, "_content_has_niche_mismatch", lambda *_args, **_kwargs: False)

    captured = {}
    def _capture_prompt(topic, prev_title, next_topic_hint, content_type, additional_guidance=None, niche=None):
        captured.setdefault("next_topic_hint", next_topic_hint)
        return "PROMPT"

    monkeypatch.setattr(
        content_generator,
        "_build_content_prompt",
        _capture_prompt,
    )

    messages = SequencedMessages([_payload_response()])
    generator = _make_generator(messages)

    content = generator.generate_video_content("Saglikli uyku duzeni")

    assert content.title == "Title"
    assert messages.calls == 1
    assert captured["next_topic_hint"] == "Bir sonraki videoda yaygin bir hatayi adim adim duzeltecegiz"


def test_generate_and_save_makes_exactly_two_messages_create_and_reuses_second_topic_hint(monkeypatch, tmp_path):
    _prepare_provider_state(monkeypatch, tmp_path)
    monkeypatch.setattr(content_generator, "build_prompt_metadata", lambda _prompt: {})
    monkeypatch.setattr(content_generator, "build_channel_dna_metadata", lambda **_kwargs: {})
    monkeypatch.setattr(content_generator, "build_quality_scores", lambda **_kwargs: {})
    monkeypatch.setattr(content_generator, "_content_has_niche_mismatch", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(content_generator, "_load_used_titles", lambda: [])
    monkeypatch.setattr("src.trends_fetcher.get_trending_topics", lambda niche, count=4: [], raising=False)
    monkeypatch.setattr("src.trends_fetcher.get_seasonal_boost_topics", lambda niche: [], raising=False)
    monkeypatch.setattr(content_generator.VideoContent, "save", lambda self, path=None: str(tmp_path / "content.json"))
    monkeypatch.setattr("src.content_pyramid.get_content_type_for_next_video", lambda *_args, **_kwargs: "semi_evergreen")

    captured = {}
    def _capture_prompt(topic, prev_title, next_topic_hint, content_type, additional_guidance=None, niche=None):
        captured.setdefault("next_topic_hint", next_topic_hint)
        return "PROMPT"

    monkeypatch.setattr(
        content_generator,
        "_build_content_prompt",
        _capture_prompt,
    )

    topic_text = "1. Ilk konu\n2. Ikinci konu\n3. Ucuncu konu"
    messages = SequencedMessages([SimpleNamespace(content=[SimpleNamespace(text=topic_text)]), _payload_response()])
    generator = _make_generator(messages)
    generator.niche = "kisisel_finans"

    content = generator.generate_and_save()

    assert content.title == "Title"
    assert messages.calls == 2
    assert captured["next_topic_hint"] == "Ikinci konu"


@pytest.mark.parametrize(
    ("error_factory", "expected_calls"),
    [
        (lambda: _status_error(RateLimitError, 429, "too many", "rate_limit_error"), 2),
        (lambda: _status_error(OverloadedError, 529, "Overloaded", "overloaded_error"), 2),
        (lambda: _status_error(InternalServerError, 500, "InternalServerError"), 2),
        (lambda: _status_error(ServiceUnavailableError, 503, "ServiceUnavailableError"), 2),
        (_connection_error, 2),
        (_timeout_error, 2),
    ],
)
def test_retryable_anthropic_exceptions_retry_once_and_then_succeed(monkeypatch, tmp_path, error_factory, expected_calls):
    _prepare_provider_state(monkeypatch, tmp_path)
    monkeypatch.setenv("ANTHROPIC_MAX_RETRIES", "2")

    messages = SequencedMessages([error_factory(), _payload_response()])
    generator = _make_generator(messages)

    response = generator._anthropic_create(model="fake", messages=[{"role": "user", "content": "x"}])
    provider_state = scheduler_utils._load_provider_health_state()["providers"]["anthropic"]

    assert response.content[0].text
    assert messages.calls == expected_calls
    assert provider_state["consecutive_failures"] == 0
    assert provider_state["open_until"] == ""
    assert provider_state["last_success_note"] == "messages_create_ok_attempt_2"


@pytest.mark.parametrize(
    "error_factory",
    [
        lambda: _status_error(BadRequestError, 400, "BadRequestError"),
        lambda: _status_error(AuthenticationError, 401, "AuthenticationError"),
        lambda: _status_error(PermissionDeniedError, 403, "PermissionDeniedError"),
    ],
)
def test_non_retryable_anthropic_exceptions_do_not_retry(monkeypatch, tmp_path, error_factory):
    _prepare_provider_state(monkeypatch, tmp_path)
    monkeypatch.setenv("ANTHROPIC_MAX_RETRIES", "3")

    messages = SequencedMessages([error_factory()])
    generator = _make_generator(messages)

    with pytest.raises(Exception):
        generator._anthropic_create(model="fake", messages=[{"role": "user", "content": "x"}])

    provider_state = scheduler_utils._load_provider_health_state()["providers"]["anthropic"]
    assert messages.calls == 1
    assert provider_state["consecutive_failures"] == 1


def test_generate_video_content_uses_local_fail_open_on_credit_exhaustion(monkeypatch, tmp_path):
    _prepare_provider_state(monkeypatch, tmp_path)
    monkeypatch.setenv("ANTHROPIC_FAIL_OPEN_LOCAL_CONTENT", "1")
    monkeypatch.setattr(content_generator, "build_prompt_metadata", lambda _prompt: {})
    monkeypatch.setattr(content_generator, "build_channel_dna_metadata", lambda **_kwargs: {})
    monkeypatch.setattr(content_generator, "build_quality_scores", lambda **_kwargs: {})

    messages = SequencedMessages([
        _status_error(
            BadRequestError,
            400,
            "Your credit balance is too low to access the Anthropic API.",
            "invalid_request_error",
        )
    ])
    generator = _make_generator(messages)

    content = generator.generate_video_content("Yatirim disiplini nasil kurulur")

    assert messages.calls == 1
    assert "Pratik Rehber" in content.title
    assert "uygulanabilir" in content.description.lower()
    assert len(content.script) > 200


def test_generate_video_content_uses_local_fail_open_on_circuit_open_runtime_error(monkeypatch, tmp_path):
    _prepare_provider_state(monkeypatch, tmp_path)
    monkeypatch.setenv("ANTHROPIC_FAIL_OPEN_LOCAL_CONTENT", "1")
    monkeypatch.setattr(content_generator, "build_prompt_metadata", lambda _prompt: {})
    monkeypatch.setattr(content_generator, "build_channel_dna_metadata", lambda **_kwargs: {})
    monkeypatch.setattr(content_generator, "build_quality_scores", lambda **_kwargs: {})

    messages = SequencedMessages([RuntimeError("Anthropic circuit open; retry after 300s")])
    generator = _make_generator(messages)

    content = generator.generate_video_content("BIST icin temel risk yonetimi")

    assert messages.calls == 1
    assert "Pratik Rehber" in content.title
    assert len(content.script) > 200


def test_retry_exhaustion_counts_as_single_logical_failure(monkeypatch, tmp_path):
    _prepare_provider_state(monkeypatch, tmp_path)
    overloaded = _status_error(OverloadedError, 529, "Overloaded", "overloaded_error")
    messages = SequencedMessages([overloaded, _status_error(OverloadedError, 529, "Overloaded", "overloaded_error"), _status_error(OverloadedError, 529, "Overloaded", "overloaded_error")])
    generator = _make_generator(messages)

    with pytest.raises(OverloadedError) as exc_info:
        generator._anthropic_create(model="fake", messages=[{"role": "user", "content": "x"}])

    provider_state = scheduler_utils._load_provider_health_state()["providers"]["anthropic"]
    circuit = scheduler_utils.get_provider_circuit_status("anthropic")

    assert messages.calls == 3
    assert provider_state["consecutive_failures"] == 1
    assert bool(provider_state["open_until"])
    assert circuit["is_open"] is True
    assert getattr(exc_info.value, "_provider_failure_recorded", False) is True
    assert getattr(exc_info.value, "_skip_scheduler_pipeline_retry", False) is True


def test_successful_retry_clears_provider_circuit(monkeypatch, tmp_path):
    _prepare_provider_state(monkeypatch, tmp_path)
    scheduler_utils.record_provider_failure("anthropic", "HTTP 529 - Overloaded")

    provider_health = tmp_path / "provider_health.json"
    provider_health.write_text(json.dumps({"providers": {"anthropic": {"provider": "anthropic", "consecutive_failures": 0, "open_until": "", "last_error_type": "overload"}}}), encoding="utf-8")

    messages = SequencedMessages([_status_error(OverloadedError, 529, "Overloaded", "overloaded_error"), _payload_response()])
    generator = _make_generator(messages)

    response = generator._anthropic_create(model="fake", messages=[{"role": "user", "content": "x"}])
    provider_state = scheduler_utils._load_provider_health_state()["providers"]["anthropic"]

    assert response.content[0].text
    assert messages.calls == 2
    assert provider_state["consecutive_failures"] == 0
    assert provider_state["open_until"] == ""


def test_concurrent_threads_enter_messages_create_one_at_a_time(monkeypatch, tmp_path):
    _prepare_provider_state(monkeypatch, tmp_path)

    release_event = threading.Event()
    entered_event = threading.Event()

    class ConcurrentMessages:
        def __init__(self):
            self.calls = 0
            self.active = 0
            self.max_active = 0
            self.lock = threading.Lock()

        def create(self, **_kwargs):
            with self.lock:
                self.calls += 1
                self.active += 1
                self.max_active = max(self.max_active, self.active)
            entered_event.set()
            release_event.wait(timeout=0.5)
            with self.lock:
                self.active -= 1
            return _payload_response(title=f"Title {self.calls}")

    messages = ConcurrentMessages()
    generator = _make_generator(messages)
    barrier = threading.Barrier(3)
    results = []

    def worker():
        barrier.wait(timeout=1)
        resp = generator._anthropic_create(model="fake", messages=[{"role": "user", "content": "x"}])
        results.append(resp.content[0].text)

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for thread in threads:
        thread.start()
    entered_event.wait(timeout=1)
    release_event.set()
    for thread in threads:
        thread.join(timeout=1)

    assert len(results) == 3
    assert messages.calls == 3
    assert messages.max_active == 1


def test_min_interval_uses_monkeypatched_clock_without_real_sleep(monkeypatch, tmp_path):
    _prepare_provider_state(monkeypatch, tmp_path)
    monkeypatch.setenv("ANTHROPIC_MIN_REQUEST_INTERVAL_SECONDS", "10")

    class FakeClock:
        def __init__(self):
            self.now = 100.0
            self.sleep_calls = []

        def monotonic(self):
            return self.now

        def time(self):
            return self.now

        def sleep(self, seconds):
            self.sleep_calls.append(seconds)
            self.now += seconds

    clock = FakeClock()
    monkeypatch.setattr(content_generator.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(content_generator.time, "time", clock.time)
    monkeypatch.setattr(content_generator.time, "sleep", clock.sleep)

    messages = SequencedMessages([_payload_response("A"), _payload_response("B")])
    generator = _make_generator(messages)

    generator._anthropic_create(model="fake", messages=[{"role": "user", "content": "x"}])
    generator._anthropic_create(model="fake", messages=[{"role": "user", "content": "x"}])

    assert messages.calls == 2
    assert clock.sleep_calls == [10.0]