from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


POLICY_VERSION = "visual_safety.v1"
MODERATION_VERSION = "metadata_rules.v1"

_UNSAFE_TERMS = {
    "bikini",
    "swimsuit",
    "swimwear",
    "beachwear",
    "lingerie",
    "underwear",
    "bra",
    "cleavage",
    "sexy",
    "sensual",
    "glamour",
    "pin-up",
    "topless",
    "nude",
    "nudity",
    "naked",
    "erotic",
    "pornographic",
}

_CHANNEL_UNSUITABLE_TERMS = {
    "fashion model",
    "glamour model",
    "model on beach",
    "woman on beach",
    "attractive woman",
    "sexy woman",
    "body transformation",
    "beach woman",
    "fitness woman",
    "curves",
    "provocative",
    "scantily clad",
}

_NON_FASHION_NICHES = {
    "borsa",
    "egitim",
    "finance",
    "finans",
    "gayrimenkul",
    "girisim",
    "girisimcilik",
    "health",
    "history",
    "kariyer",
    "kisisel_finans",
    "kripto",
    "news",
    "productivity",
    "saglik",
    "teknoloji",
}

_SAFE_QUERY_BY_NICHE = {
    "kisisel_finans": "personal finance budget spreadsheet calculator desk",
    "borsa": "stock market chart analysis monitor desk",
    "kripto": "cryptocurrency blockchain chart digital screen",
    "kariyer": "professional office laptop planning documents",
    "girisim": "startup office workspace team planning",
    "girisimcilik": "startup office workspace team planning",
    "teknoloji": "technology software digital workspace screens",
    "egitim": "education learning study books classroom",
    "gayrimenkul": "real estate house property architecture exterior",
    "saglik": "health medical clinic equipment nutrition",
}

_TERM_RE = re.compile(
    r"\b(" + "|".join(re.escape(term) for term in sorted(_UNSAFE_TERMS | _CHANNEL_UNSUITABLE_TERMS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class VisualSafetyDecision:
    allowed: bool
    failed_rules: list[str]
    reason: str
    policy_version: str = POLICY_VERSION
    rewritten_query: str = ""
    moderation_version: str = MODERATION_VERSION
    confidence: str = "high"
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "failed_rules": list(self.failed_rules),
            "reason": self.reason,
            "policy_version": self.policy_version,
            "rewritten_query": self.rewritten_query,
            "moderation_version": self.moderation_version,
            "confidence": self.confidence,
            "evidence": dict(self.evidence),
        }


def _normalise_niche(niche: str | None) -> str:
    return str(niche or "").strip().lower().replace("ı", "i")


def _safe_fallback_query(niche: str | None, topic: str | None = None) -> str:
    niche_norm = _normalise_niche(niche)
    return _SAFE_QUERY_BY_NICHE.get(niche_norm, "professional office desk planning documents")


def _combined_text(*parts: Any) -> str:
    return " ".join(str(part or "") for part in parts if str(part or "").strip())


def _matched_terms(text: str) -> list[str]:
    return sorted({match.group(1).lower() for match in _TERM_RE.finditer(str(text or ""))})


def _has_unsafe_term(terms: list[str]) -> bool:
    return any(
        unsafe_term == term or re.search(r"\b" + re.escape(unsafe_term) + r"\b", term)
        for term in terms
        for unsafe_term in _UNSAFE_TERMS
    )


def evaluate_visual_query(*, query: str | None, channel_id: str, niche: str | None, topic: str | None = None) -> VisualSafetyDecision:
    raw = str(query or "").strip()
    if not raw:
        return VisualSafetyDecision(
            allowed=False,
            failed_rules=["visual_query_missing"],
            reason="missing_visual_query",
            rewritten_query=_safe_fallback_query(niche, topic),
            evidence={"channel_id": channel_id, "topic": topic or "", "original_query": raw},
        )

    terms = _matched_terms(raw)
    niche_norm = _normalise_niche(niche)
    failed: list[str] = []
    if terms:
        failed.append("visual_query_unsafe_terms")
    if niche_norm in _NON_FASHION_NICHES and any(term in _CHANNEL_UNSUITABLE_TERMS for term in terms):
        failed.append("visual_query_channel_unsuitable")

    if failed:
        return VisualSafetyDecision(
            allowed=False,
            failed_rules=sorted(set(failed)),
            reason="unsafe_or_unsuitable_visual_query",
            rewritten_query=_safe_fallback_query(niche, topic),
            evidence={"channel_id": channel_id, "topic": topic or "", "original_query": raw, "matched_terms": terms},
        )

    return VisualSafetyDecision(
        allowed=True,
        failed_rules=[],
        reason="query_allowed",
        rewritten_query=raw,
        evidence={"channel_id": channel_id, "topic": topic or "", "original_query": raw},
    )


def evaluate_visual_candidate(
    *,
    candidate: dict[str, Any] | None,
    media_type: str,
    channel_id: str,
    niche: str | None,
    topic: str | None,
    query: str | None = None,
    source: str = "provider",
) -> VisualSafetyDecision:
    if not isinstance(candidate, dict):
        return VisualSafetyDecision(
            allowed=False,
            failed_rules=["visual_candidate_missing"],
            reason="missing_visual_candidate",
            evidence={"channel_id": channel_id, "source": source, "media_type": media_type},
        )

    text_parts = [query or "", candidate.get("alt"), candidate.get("url"), candidate.get("photographer")]
    text_parts.extend(candidate.get("tags") or [])
    user = candidate.get("user") or {}
    if isinstance(user, dict):
        text_parts.append(user.get("name"))
    text = _combined_text(*text_parts)
    if not text.strip():
        return VisualSafetyDecision(
            allowed=False,
            failed_rules=["visual_candidate_metadata_missing"],
            reason="missing_visual_candidate_metadata",
            evidence={"channel_id": channel_id, "source": source, "media_type": media_type},
        )

    terms = _matched_terms(text)
    niche_norm = _normalise_niche(niche)
    failed: list[str] = []
    if _has_unsafe_term(terms):
        failed.append("visual_candidate_unsafe_terms")
    if niche_norm in _NON_FASHION_NICHES and any(term in _CHANNEL_UNSUITABLE_TERMS for term in terms):
        failed.append("visual_candidate_channel_unsuitable")

    if failed:
        return VisualSafetyDecision(
            allowed=False,
            failed_rules=sorted(set(failed)),
            reason="unsafe_or_unsuitable_visual_candidate",
            evidence={"channel_id": channel_id, "source": source, "media_type": media_type, "matched_terms": terms},
        )

    return VisualSafetyDecision(
        allowed=True,
        failed_rules=[],
        reason="candidate_allowed",
        evidence={"channel_id": channel_id, "source": source, "media_type": media_type},
    )


def evaluate_external_moderation(
    *,
    classifier: Any,
    asset: Any,
    channel_id: str,
    source: str,
) -> VisualSafetyDecision:
    if not callable(classifier):
        return VisualSafetyDecision(
            allowed=False,
            failed_rules=["visual_classifier_missing"],
            reason="missing_visual_classifier",
            evidence={"channel_id": channel_id, "source": source},
        )

    try:
        result = classifier(asset)
    except TimeoutError:
        return VisualSafetyDecision(
            allowed=False,
            failed_rules=["visual_classifier_timeout"],
            reason="visual_classifier_timeout",
            evidence={"channel_id": channel_id, "source": source},
        )
    except Exception as exc:
        return VisualSafetyDecision(
            allowed=False,
            failed_rules=["visual_classifier_exception"],
            reason="visual_classifier_exception",
            evidence={"channel_id": channel_id, "source": source, "error_type": exc.__class__.__name__},
        )

    if not isinstance(result, dict):
        return VisualSafetyDecision(
            allowed=False,
            failed_rules=["visual_moderation_missing"],
            reason="missing_visual_moderation_result",
            evidence={"channel_id": channel_id, "source": source},
        )

    status = str(result.get("status") or result.get("result") or "").strip().lower()
    confidence = str(result.get("confidence") or "").strip().lower()
    if status != "safe":
        return VisualSafetyDecision(
            allowed=False,
            failed_rules=["visual_moderation_unsafe"],
            reason="unsafe_visual_moderation_result",
            evidence={"channel_id": channel_id, "source": source, "moderation": dict(result)},
        )
    if confidence in {"", "low", "borderline", "unknown"}:
        return VisualSafetyDecision(
            allowed=False,
            failed_rules=["visual_moderation_low_confidence"],
            reason="low_confidence_visual_moderation_result",
            evidence={"channel_id": channel_id, "source": source, "moderation": dict(result)},
        )

    return VisualSafetyDecision(
        allowed=True,
        failed_rules=[],
        reason="visual_moderation_allowed",
        evidence={"channel_id": channel_id, "source": source, "moderation_version": MODERATION_VERSION},
    )


def fingerprint_asset(path_or_url: str) -> str:
    raw = str(path_or_url or "").strip()
    p = Path(raw)
    if raw and p.exists() and p.is_file():
        digest = hashlib.sha256()
        with p.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_visual_manifest(
    *,
    channel_id: str,
    content_id: str,
    run_id: str,
    niche: str,
    topic: str,
    assets: list[str],
    output_path: str | Path,
) -> Path:
    records = []
    for asset in assets:
        asset_text = str(asset or "").strip()
        if not asset_text:
            continue
        records.append(
            {
                "asset": asset_text,
                "asset_fingerprint": fingerprint_asset(asset_text),
                "source": "final_render_manifest",
                "approved": True,
                "moderation_result": "safe",
                "moderation_version": MODERATION_VERSION,
                "policy_version": POLICY_VERSION,
                "channel_id": channel_id,
                "niche": niche,
                "topic": topic,
            }
        )
    payload = {
        "schema_version": "visual_manifest.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "policy_version": POLICY_VERSION,
        "channel_id": channel_id,
        "content_id": content_id,
        "run_id": run_id,
        "niche": niche,
        "topic": topic,
        "assets": records,
    }
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(target)
    return target


def validate_visual_manifest(
    *,
    manifest: dict[str, Any] | None,
    channel_id: str,
    content_id: str,
    run_id: str,
    final_assets: list[str] | None = None,
) -> VisualSafetyDecision:
    if not isinstance(manifest, dict):
        return VisualSafetyDecision(False, ["visual_manifest_missing"], "missing_visual_manifest")

    failed: list[str] = []
    evidence: dict[str, Any] = {}
    if str(manifest.get("policy_version") or "") != POLICY_VERSION:
        failed.append("visual_policy_version_stale")
    for key, expected in {"channel_id": channel_id, "content_id": content_id, "run_id": run_id}.items():
        if str(manifest.get(key) or "") != str(expected or ""):
            failed.append(f"visual_manifest_{key}_mismatch")

    assets = list(manifest.get("assets") or [])
    if not assets:
        failed.append("visual_manifest_assets_missing")
    unsafe_assets: list[dict[str, Any]] = []
    manifest_asset_values = {str(item.get("asset") or "") for item in assets if isinstance(item, dict)}
    for item in assets:
        if not isinstance(item, dict):
            failed.append("visual_manifest_asset_malformed")
            continue
        asset_failed: list[str] = []
        if str(item.get("channel_id") or "") != str(channel_id or ""):
            asset_failed.append("visual_asset_channel_mismatch")
        if str(item.get("policy_version") or "") != POLICY_VERSION:
            asset_failed.append("visual_asset_policy_version_stale")
        if not item.get("asset_fingerprint"):
            asset_failed.append("visual_asset_fingerprint_missing")
        if not item.get("moderation_result") or str(item.get("moderation_version") or "") != MODERATION_VERSION:
            asset_failed.append("visual_asset_moderation_missing")
        if item.get("approved") is not True or str(item.get("moderation_result") or "") != "safe":
            asset_failed.append("visual_asset_not_approved")
        if asset_failed:
            unsafe_assets.append({"asset": item.get("asset"), "failed_rules": asset_failed})
            failed.extend(asset_failed)

    if final_assets is not None:
        final_set = {str(item or "") for item in final_assets if str(item or "").strip()}
        if final_set != manifest_asset_values:
            failed.append("visual_final_asset_manifest_mismatch")
            evidence["final_assets"] = sorted(final_set)
            evidence["manifest_assets"] = sorted(manifest_asset_values)

    if failed:
        evidence["unsafe_assets"] = unsafe_assets
        return VisualSafetyDecision(False, sorted(set(failed)), "visual_manifest_blocked", evidence=evidence)
    return VisualSafetyDecision(True, [], "visual_manifest_allowed", evidence={"asset_count": len(assets)})


def validate_cache_provenance(*, entry: dict[str, Any], channel_id: str, niche: str, topic_domain: str, provider: str) -> VisualSafetyDecision:
    failed: list[str] = []
    if str(entry.get("channel_id") or "") != str(channel_id or ""):
        failed.append("visual_cache_channel_mismatch")
    if str(entry.get("policy_version") or "") != POLICY_VERSION:
        failed.append("visual_cache_policy_version_missing")
    if str(entry.get("moderation_version") or "") != MODERATION_VERSION or str(entry.get("moderation_result") or "") != "safe":
        failed.append("visual_cache_moderation_missing")
    if str(entry.get("provider") or "") != str(provider or ""):
        failed.append("visual_cache_provider_mismatch")
    if str(entry.get("topic_domain") or "") != str(topic_domain or ""):
        failed.append("visual_cache_topic_domain_mismatch")
    if not entry.get("asset_fingerprint"):
        failed.append("visual_cache_asset_fingerprint_missing")
    if failed:
        return VisualSafetyDecision(False, sorted(set(failed)), "visual_cache_provenance_blocked")
    return VisualSafetyDecision(True, [], "visual_cache_provenance_allowed")


def build_upload_quarantine_result(
    *,
    channel_id: str,
    content_id: str,
    run_id: str,
    failed_rules: list[str],
    evidence_paths: list[str] | None = None,
    unsafe_assets: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "prevent_upload": True,
        "quarantine_reason": "visual_safety_policy_blocked",
        "channel_id": channel_id,
        "content_id": content_id,
        "run_id": run_id,
        "unsafe_assets": list(unsafe_assets or []),
        "failed_rules": sorted(set(failed_rules)),
        "policy_version": POLICY_VERSION,
        "evidence_paths": list(evidence_paths or []),
        "operator_action": "review_visual_assets_and_regenerate_after_policy_fix",
    }