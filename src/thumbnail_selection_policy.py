"""Deterministic thumbnail candidate selection policies (T2.5 foundation)."""

from __future__ import annotations

import hashlib
from typing import Sequence, TypeVar


CandidateT = TypeVar("CandidateT")

POLICY_ROUND_ROBIN = "round_robin"
POLICY_FIRST = "first"
POLICY_DETERMINISTIC_HASH = "deterministic_hash"
SUPPORTED_SELECTION_POLICIES = (
    POLICY_ROUND_ROBIN,
    POLICY_FIRST,
    POLICY_DETERMINISTIC_HASH,
)


def _required_non_empty(field_name: str, value: str | None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"missing_required_field:{field_name}")
    return value.strip()


def _normalize_policy_name(policy: str) -> str:
    value = _required_non_empty("policy", policy).lower()
    if value not in SUPPORTED_SELECTION_POLICIES:
        raise ValueError("unknown_selection_policy")
    return value


def _validate_candidates(candidates: Sequence[CandidateT]) -> None:
    if not isinstance(candidates, Sequence) or len(candidates) == 0:
        raise ValueError("empty_candidates")


def _coerce_non_negative_int(field_name: str, value: int | None) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or value < 0:
        raise ValueError(f"invalid_{field_name}")
    return value


def _stable_hash_index(key: str, modulo: int) -> int:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return int(digest[:16], 16) % modulo


def select_thumbnail_candidate_index(
    *,
    candidates: Sequence[CandidateT],
    policy: str,
    index: int | None = None,
    run_number: int | None = None,
    content_id: str | None = None,
    video_id: str | None = None,
) -> int:
    """Select candidate index deterministically for supported policies."""
    _validate_candidates(candidates)
    resolved_policy = _normalize_policy_name(policy)
    resolved_index = _coerce_non_negative_int("index", index)
    resolved_run_number = _coerce_non_negative_int("run_number", run_number)

    if resolved_policy == POLICY_FIRST:
        return 0

    if resolved_policy == POLICY_ROUND_ROBIN:
        if resolved_index is not None:
            return resolved_index % len(candidates)
        if resolved_run_number is not None:
            return resolved_run_number % len(candidates)
        return 0

    # deterministic_hash
    key = (str(content_id).strip() if isinstance(content_id, str) and content_id.strip() else "") or (
        str(video_id).strip() if isinstance(video_id, str) and video_id.strip() else ""
    )
    if not key:
        raise ValueError("missing_required_field:content_id_or_video_id")
    return _stable_hash_index(key, len(candidates))


def select_thumbnail_candidate(
    *,
    candidates: Sequence[CandidateT],
    policy: str,
    index: int | None = None,
    run_number: int | None = None,
    content_id: str | None = None,
    video_id: str | None = None,
) -> CandidateT:
    """Return selected candidate by applying the configured policy."""
    selected_index = select_thumbnail_candidate_index(
        candidates=candidates,
        policy=policy,
        index=index,
        run_number=run_number,
        content_id=content_id,
        video_id=video_id,
    )
    if selected_index < 0 or selected_index >= len(candidates):
        raise ValueError("selected_candidate_out_of_bounds")
    return candidates[selected_index]
