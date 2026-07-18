from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .production_quality_platform import _similarity, _tokenize
from .runtime_storage import env_or_runtime_path, validate_runtime_write_path


AUTOMATIC_QA_EVIDENCE_SCHEMA_VERSION = "automatic_qa_evidence.v1"
AUTOMATIC_QA_ALGORITHM_VERSION = "automatic_qa.v1"
AUTOMATIC_QA_TOKENIZER_VERSION = "automatic_qa_tokenizer.v1"
AUTOMATIC_QA_EVIDENCE_EVENT_TYPE = "automatic_qa_evidence"
AUTOMATIC_QA_THUMBNAIL_RELEVANCE_THRESHOLD = 0.05
AUTOMATIC_QA_EVIDENCE_PATH = env_or_runtime_path(
    "AUTOMATIC_QA_EVIDENCE_PATH",
    "evidence/automatic_qa/automatic_qa_evidence.jsonl",
)

_REQUIRED_TOP_LEVEL_FIELDS = {
    "schema_version",
    "qa_algorithm_version",
    "tokenizer_version",
    "event_type",
    "generation_id",
    "run_id",
    "qa_attempt",
    "stage",
    "timestamp",
    "git_sha_full",
    "decision_evidence",
    "qa_output",
    "integrity",
}

_REQUIRED_DECISION_FIELDS = {
    "topic",
    "thumbnail_prompt",
    "thumbnail_prompt_hash",
    "normalized_topic",
    "normalized_thumbnail_prompt",
    "topic_tokens",
    "thumbnail_prompt_tokens",
    "thumbnail_token_intersection",
    "thumbnail_token_union",
    "thumbnail_similarity_score",
    "thumbnail_relevance_threshold",
    "niche_present",
    "topic_niche_similarity",
    "title_description_script_similarity",
    "tag_count",
    "has_title",
    "has_script",
    "has_description",
    "has_tags",
    "script_similarity",
    "selected_visual_count",
    "selected_visual_unique_count",
    "has_low_diversity_rejection",
}

_REQUIRED_OUTPUT_FIELDS = {"checks", "blocked_checks", "final_decision"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _is_sha256_hex(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    return all(ch in "0123456789abcdef" for ch in value)


def _is_number(value: object) -> bool:
    return (not isinstance(value, bool)) and isinstance(value, (int, float))


def _is_non_negative_int(value: object) -> bool:
    return (not isinstance(value, bool)) and isinstance(value, int) and value >= 0


def _is_string_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _text_hash(value: object) -> str | None:
    text = str(value or "")
    return _sha256_text(text)


def _sorted_tokens(value: object) -> list[str]:
    return sorted(_tokenize(str(value or "")))


def _without_evidence_hash(evidence: dict[str, Any]) -> dict[str, Any]:
    clone = json.loads(json.dumps(evidence, ensure_ascii=False))
    integrity = clone.get("integrity")
    if isinstance(integrity, dict):
        integrity.pop("evidence_hash", None)
    return clone


def compute_evidence_hash(evidence: dict[str, Any]) -> str:
    return _sha256_text(_canonical_json(_without_evidence_hash(evidence)))


def build_automatic_qa_evidence(
    *,
    generation_id: str,
    run_id: str,
    qa_attempt: int,
    stage: str,
    git_sha_full: str,
    qa_payload: dict[str, Any],
    automatic_qa: dict[str, Any],
    timestamp: str | None = None,
) -> dict[str, Any]:
    topic = str(qa_payload.get("topic") or qa_payload.get("title") or "")
    title = str(qa_payload.get("title") or "")
    script = str(qa_payload.get("script") or "")
    description = str(qa_payload.get("description") or "")
    tags = [str(item).strip() for item in (qa_payload.get("tags") or []) if str(item).strip()]
    niche = str(qa_payload.get("niche") or "")
    thumbnail_prompt = str(qa_payload.get("thumbnail_prompt") or "")
    selected_visuals = [str(item) for item in (qa_payload.get("selected_visuals") or []) if str(item).strip()]
    rejection_reasons = [str(item) for item in (qa_payload.get("rejection_reasons") or []) if str(item).strip()]
    topic_tokens = _sorted_tokens(topic)
    thumbnail_tokens = _sorted_tokens(thumbnail_prompt)
    token_intersection = sorted(set(topic_tokens) & set(thumbnail_tokens))
    token_union = sorted(set(topic_tokens) | set(thumbnail_tokens))

    evidence = {
        "schema_version": AUTOMATIC_QA_EVIDENCE_SCHEMA_VERSION,
        "qa_algorithm_version": AUTOMATIC_QA_ALGORITHM_VERSION,
        "tokenizer_version": AUTOMATIC_QA_TOKENIZER_VERSION,
        "event_type": AUTOMATIC_QA_EVIDENCE_EVENT_TYPE,
        "generation_id": str(generation_id or ""),
        "run_id": str(run_id or ""),
        "qa_attempt": int(qa_attempt),
        "stage": str(stage or ""),
        "timestamp": timestamp or _now_iso(),
        "git_sha_full": str(git_sha_full or "unknown"),
        "decision_evidence": {
            "topic": topic,
            "thumbnail_prompt": thumbnail_prompt,
            "thumbnail_prompt_hash": _text_hash(thumbnail_prompt),
            "normalized_topic": " ".join(topic_tokens),
            "normalized_thumbnail_prompt": " ".join(thumbnail_tokens),
            "topic_tokens": topic_tokens,
            "thumbnail_prompt_tokens": thumbnail_tokens,
            "thumbnail_token_intersection": token_intersection,
            "thumbnail_token_union": token_union,
            "thumbnail_similarity_score": _similarity(topic, thumbnail_prompt),
            "thumbnail_relevance_threshold": AUTOMATIC_QA_THUMBNAIL_RELEVANCE_THRESHOLD,
            "niche_present": bool(niche),
            "topic_niche_similarity": _similarity(topic, niche),
            "title_description_script_similarity": _similarity(title + " " + description, script),
            "tag_count": len(tags),
            "has_title": bool(title),
            "has_script": bool(script),
            "has_description": bool(description),
            "has_tags": bool(tags),
            "script_similarity": float(qa_payload.get("script_similarity", 0.0) or 0.0),
            "selected_visual_count": len(selected_visuals),
            "selected_visual_unique_count": len(set(selected_visuals)),
            "has_low_diversity_rejection": "DUPLICATE_OR_LOW_DIVERSITY" in rejection_reasons,
        },
        "qa_output": {
            "checks": dict(automatic_qa.get("checks") or {}),
            "blocked_checks": list(automatic_qa.get("blocked_checks") or []),
            "final_decision": str(automatic_qa.get("decision") or ""),
        },
        "integrity": {},
    }
    evidence["integrity"]["evidence_hash"] = compute_evidence_hash(evidence)
    validate_automatic_qa_evidence(evidence)
    return evidence


def validate_automatic_qa_evidence(evidence: dict[str, Any]) -> None:
    missing = sorted(field for field in _REQUIRED_TOP_LEVEL_FIELDS if field not in evidence)
    if missing:
        raise ValueError(f"automatic_qa_evidence_invalid: missing_top_level={missing}")

    if evidence.get("schema_version") != AUTOMATIC_QA_EVIDENCE_SCHEMA_VERSION:
        raise ValueError("automatic_qa_evidence_invalid: invalid_schema_version")
    if evidence.get("qa_algorithm_version") != AUTOMATIC_QA_ALGORITHM_VERSION:
        raise ValueError("automatic_qa_evidence_invalid: invalid_qa_algorithm_version")
    if evidence.get("tokenizer_version") != AUTOMATIC_QA_TOKENIZER_VERSION:
        raise ValueError("automatic_qa_evidence_invalid: invalid_tokenizer_version")
    if evidence.get("event_type") != AUTOMATIC_QA_EVIDENCE_EVENT_TYPE:
        raise ValueError("automatic_qa_evidence_invalid: invalid_event_type")
    if evidence.get("stage") != "media_fetch":
        raise ValueError("automatic_qa_evidence_invalid: invalid_stage")
    for field in ("generation_id", "run_id", "timestamp", "git_sha_full"):
        if not isinstance(evidence.get(field), str) or not evidence.get(field).strip():
            raise ValueError(f"automatic_qa_evidence_invalid: invalid_{field}")
    if not _is_non_negative_int(evidence.get("qa_attempt")):
        raise ValueError("automatic_qa_evidence_invalid: invalid_qa_attempt")

    decision_evidence = evidence.get("decision_evidence")
    if not isinstance(decision_evidence, dict):
        raise ValueError("automatic_qa_evidence_invalid: decision_evidence_not_object")
    missing_decision = sorted(field for field in _REQUIRED_DECISION_FIELDS if field not in decision_evidence)
    if missing_decision:
        raise ValueError(f"automatic_qa_evidence_invalid: missing_decision_fields={missing_decision}")

    for field in ("topic", "thumbnail_prompt", "normalized_topic", "normalized_thumbnail_prompt"):
        if not isinstance(decision_evidence.get(field), str):
            raise ValueError(f"automatic_qa_evidence_invalid: invalid_{field}")
    if not _is_sha256_hex(decision_evidence.get("thumbnail_prompt_hash")):
        raise ValueError("automatic_qa_evidence_invalid: invalid_thumbnail_prompt_hash")
    for field in (
        "topic_tokens",
        "thumbnail_prompt_tokens",
        "thumbnail_token_intersection",
        "thumbnail_token_union",
    ):
        if not _is_string_list(decision_evidence.get(field)):
            raise ValueError(f"automatic_qa_evidence_invalid: invalid_{field}")
    for field in (
        "thumbnail_similarity_score",
        "thumbnail_relevance_threshold",
        "topic_niche_similarity",
        "title_description_script_similarity",
        "script_similarity",
    ):
        if not _is_number(decision_evidence.get(field)):
            raise ValueError(f"automatic_qa_evidence_invalid: invalid_{field}")
    for field in ("tag_count", "selected_visual_count", "selected_visual_unique_count"):
        if not _is_non_negative_int(decision_evidence.get(field)):
            raise ValueError(f"automatic_qa_evidence_invalid: invalid_{field}")
    for field in (
        "niche_present",
        "has_title",
        "has_script",
        "has_description",
        "has_tags",
        "has_low_diversity_rejection",
    ):
        if not isinstance(decision_evidence.get(field), bool):
            raise ValueError(f"automatic_qa_evidence_invalid: invalid_{field}")

    qa_output = evidence.get("qa_output")
    if not isinstance(qa_output, dict):
        raise ValueError("automatic_qa_evidence_invalid: qa_output_not_object")
    missing_output = sorted(field for field in _REQUIRED_OUTPUT_FIELDS if field not in qa_output)
    if missing_output:
        raise ValueError(f"automatic_qa_evidence_invalid: missing_output_fields={missing_output}")
    if not isinstance(qa_output.get("checks"), dict):
        raise ValueError("automatic_qa_evidence_invalid: invalid_checks")
    if not _is_string_list(qa_output.get("blocked_checks")):
        raise ValueError("automatic_qa_evidence_invalid: invalid_blocked_checks")
    if qa_output.get("final_decision") not in {"allow", "block"}:
        raise ValueError("automatic_qa_evidence_invalid: invalid_final_decision")

    integrity = evidence.get("integrity")
    if not isinstance(integrity, dict):
        raise ValueError("automatic_qa_evidence_invalid: integrity_not_object")
    expected = compute_evidence_hash(evidence)
    actual = integrity.get("evidence_hash")
    if not _is_sha256_hex(actual):
        raise ValueError("automatic_qa_evidence_invalid: invalid_evidence_hash")
    if actual != expected:
        raise ValueError("automatic_qa_evidence_invalid: evidence_hash_mismatch")


def append_automatic_qa_evidence(evidence: dict[str, Any], path: Path | None = None) -> Path:
    validate_automatic_qa_evidence(evidence)
    target = path or AUTOMATIC_QA_EVIDENCE_PATH
    if not validate_runtime_write_path(target, purpose="automatic_qa_evidence_append"):
        raise RuntimeError(f"automatic_qa_evidence_write_blocked: target={target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    with target.open("a", encoding="utf-8") as handle:
        handle.write(encoded)
    return target


def record_automatic_qa_evidence(*, path: Path | None = None, **kwargs: Any) -> dict[str, Any]:
    evidence = build_automatic_qa_evidence(**kwargs)
    append_automatic_qa_evidence(evidence, path=path)
    return evidence