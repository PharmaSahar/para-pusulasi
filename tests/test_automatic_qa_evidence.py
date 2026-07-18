from __future__ import annotations

import json

import pytest

from src.automatic_qa_evidence import (
    AUTOMATIC_QA_ALGORITHM_VERSION,
    AUTOMATIC_QA_EVIDENCE_SCHEMA_VERSION,
    AUTOMATIC_QA_TOKENIZER_VERSION,
    append_automatic_qa_evidence,
    build_automatic_qa_evidence,
    compute_evidence_hash,
    validate_automatic_qa_evidence,
)
from src.production_quality_platform import evaluate_automatic_qa


def _qa_payload(**overrides):
    payload = {
        "channel": "borsa_akademi",
        "niche": "borsa",
        "topic": "Borsa stratejisi",
        "title": "Borsa stratejisi 2026",
        "script": "Borsa stratejisi ve risk yonetimi",
        "description": "Borsa stratejisi aciklama",
        "tags": ["borsa", "strateji", "risk"],
        "thumbnail_prompt": "borsa stratejisi chart",
        "selected_visuals": ["a.jpg", "b.jpg"],
        "rejection_reasons": [],
        "script_similarity": 0.2,
        "shorts_enabled": True,
    }
    payload.update(overrides)
    return payload


def _evidence(**payload_overrides):
    qa_payload = _qa_payload(**payload_overrides)
    return build_automatic_qa_evidence(
        generation_id="content_test",
        run_id="run_test",
        qa_attempt=0,
        stage="media_fetch",
        git_sha_full="a" * 40,
        qa_payload=qa_payload,
        automatic_qa=evaluate_automatic_qa(qa_payload),
        timestamp="2026-07-18T00:00:00+00:00",
    )


def test_build_level1_evidence_validates_and_retains_final_thumbnail_prompt():
    evidence = _evidence(thumbnail_prompt="Borsa stratejisi final prompt")

    validate_automatic_qa_evidence(evidence)

    decision = evidence["decision_evidence"]
    assert decision["thumbnail_prompt"] == "Borsa stratejisi final prompt"
    assert decision["thumbnail_prompt_hash"]
    assert decision["thumbnail_relevance_threshold"] == 0.05
    assert evidence["qa_output"]["final_decision"] == "allow"
    assert evidence["tokenizer_version"] == AUTOMATIC_QA_TOKENIZER_VERSION


def test_missing_required_field_is_rejected():
    evidence = _evidence()
    del evidence["decision_evidence"]["thumbnail_prompt"]
    evidence["integrity"]["evidence_hash"] = compute_evidence_hash(evidence)

    with pytest.raises(ValueError, match="missing_decision_fields"):
        validate_automatic_qa_evidence(evidence)


def test_hash_mismatch_is_rejected():
    evidence = _evidence()
    evidence["decision_evidence"]["topic"] = "mutated after append"

    with pytest.raises(ValueError, match="evidence_hash_mismatch"):
        validate_automatic_qa_evidence(evidence)


def test_canonical_hash_is_stable_for_same_evidence():
    first = _evidence()
    second = _evidence()

    assert first["integrity"]["evidence_hash"] == second["integrity"]["evidence_hash"]
    assert compute_evidence_hash(first) == first["integrity"]["evidence_hash"]


def test_append_is_append_only_jsonl(tmp_path):
    path = tmp_path / "automatic_qa_evidence.jsonl"
    first = _evidence(thumbnail_prompt="Borsa stratejisi A")
    qa_payload = _qa_payload(thumbnail_prompt="Borsa stratejisi B")
    second = build_automatic_qa_evidence(
        generation_id="content_test",
        run_id="run_test",
        qa_attempt=1,
        stage="media_fetch",
        git_sha_full="a" * 40,
        qa_payload=qa_payload,
        automatic_qa=evaluate_automatic_qa(qa_payload),
        timestamp="2026-07-18T00:00:01+00:00",
    )

    append_automatic_qa_evidence(first, path=path)
    append_automatic_qa_evidence(second, path=path)

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [row["qa_attempt"] for row in rows] == [0, 1]
    assert rows[0]["decision_evidence"]["thumbnail_prompt"] == "Borsa stratejisi A"
    assert rows[1]["decision_evidence"]["thumbnail_prompt"] == "Borsa stratejisi B"


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda evidence: evidence.__setitem__("schema_version", "wrong"), "invalid_schema_version"),
        (lambda evidence: evidence.__setitem__("qa_algorithm_version", "wrong"), "invalid_qa_algorithm_version"),
        (lambda evidence: evidence.__setitem__("tokenizer_version", "wrong"), "invalid_tokenizer_version"),
        (lambda evidence: evidence["decision_evidence"].__setitem__("topic", 123), "invalid_topic"),
        (lambda evidence: evidence["decision_evidence"].__setitem__("thumbnail_prompt", 123), "invalid_thumbnail_prompt"),
        (lambda evidence: evidence["qa_output"].__setitem__("blocked_checks", [1]), "invalid_blocked_checks"),
        (lambda evidence: evidence["integrity"].__setitem__("evidence_hash", "bad"), "invalid_evidence_hash"),
    ],
)
def test_strict_schema_validation_rejects_invalid_values(mutate, message):
    evidence = _evidence()
    mutate(evidence)
    if message != "invalid_evidence_hash":
        evidence["integrity"]["evidence_hash"] = compute_evidence_hash(evidence)

    with pytest.raises(ValueError, match=message):
        validate_automatic_qa_evidence(evidence)


@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("generation_id", "invalid_generation_id"),
        ("run_id", "invalid_run_id"),
        ("timestamp", "invalid_timestamp"),
        ("git_sha_full", "invalid_git_sha_full"),
    ],
)
def test_empty_identity_fields_are_rejected_independently(field, message):
    evidence = _evidence()
    evidence[field] = ""
    evidence["integrity"]["evidence_hash"] = compute_evidence_hash(evidence)

    with pytest.raises(ValueError, match=message):
        validate_automatic_qa_evidence(evidence)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("qa_attempt", True, "invalid_qa_attempt"),
        ("qa_attempt", "0", "invalid_qa_attempt"),
    ],
)
def test_invalid_qa_attempt_types_are_rejected(field, value, message):
    evidence = _evidence()
    evidence[field] = value
    evidence["integrity"]["evidence_hash"] = compute_evidence_hash(evidence)

    with pytest.raises(ValueError, match=message):
        validate_automatic_qa_evidence(evidence)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("thumbnail_similarity_score", True, "invalid_thumbnail_similarity_score"),
        ("thumbnail_similarity_score", "0.5", "invalid_thumbnail_similarity_score"),
        ("topic_niche_similarity", True, "invalid_topic_niche_similarity"),
        ("topic_niche_similarity", "0.5", "invalid_topic_niche_similarity"),
        ("title_description_script_similarity", True, "invalid_title_description_script_similarity"),
        ("title_description_script_similarity", "0.5", "invalid_title_description_script_similarity"),
        ("script_similarity", True, "invalid_script_similarity"),
        ("script_similarity", "0.5", "invalid_script_similarity"),
        ("thumbnail_relevance_threshold", True, "invalid_thumbnail_relevance_threshold"),
        ("thumbnail_relevance_threshold", "0.05", "invalid_thumbnail_relevance_threshold"),
    ],
)
def test_invalid_similarity_and_threshold_types_are_rejected(field, value, message):
    evidence = _evidence()
    evidence["decision_evidence"][field] = value
    evidence["integrity"]["evidence_hash"] = compute_evidence_hash(evidence)

    with pytest.raises(ValueError, match=message):
        validate_automatic_qa_evidence(evidence)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("topic_tokens", "borsa", "invalid_topic_tokens"),
        ("topic_tokens", ["borsa", 1], "invalid_topic_tokens"),
        ("thumbnail_prompt_tokens", "borsa", "invalid_thumbnail_prompt_tokens"),
        ("thumbnail_prompt_tokens", ["borsa", 1], "invalid_thumbnail_prompt_tokens"),
        ("thumbnail_token_intersection", "borsa", "invalid_thumbnail_token_intersection"),
        ("thumbnail_token_intersection", ["borsa", 1], "invalid_thumbnail_token_intersection"),
        ("thumbnail_token_union", "borsa", "invalid_thumbnail_token_union"),
        ("thumbnail_token_union", ["borsa", 1], "invalid_thumbnail_token_union"),
    ],
)
def test_invalid_token_list_types_are_rejected(field, value, message):
    evidence = _evidence()
    evidence["decision_evidence"][field] = value
    evidence["integrity"]["evidence_hash"] = compute_evidence_hash(evidence)

    with pytest.raises(ValueError, match=message):
        validate_automatic_qa_evidence(evidence)


def test_empty_thumbnail_prompt_is_retained_and_hashes_as_string():
    evidence = _evidence(thumbnail_prompt="")

    validate_automatic_qa_evidence(evidence)

    assert evidence["schema_version"] == AUTOMATIC_QA_EVIDENCE_SCHEMA_VERSION
    assert evidence["qa_algorithm_version"] == AUTOMATIC_QA_ALGORITHM_VERSION
    assert evidence["decision_evidence"]["thumbnail_prompt"] == ""
    assert len(evidence["decision_evidence"]["thumbnail_prompt_hash"]) == 64