"""Prompt Registry v1: deterministic prompt metadata helpers."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_prompt(prompt_text: str) -> str:
    return (prompt_text or "").strip()


def build_prompt_metadata(prompt_text: str) -> dict:
    normalized = _normalize_prompt(prompt_text)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    prompt_hash = digest
    prompt_id = f"pr_{digest[:16]}"
    prompt_version = f"v1-{digest[:8]}"
    return {
        "prompt_hash": prompt_hash,
        "prompt_id": prompt_id,
        "prompt_version": prompt_version,
        "created_at": _utc_now_iso(),
    }
