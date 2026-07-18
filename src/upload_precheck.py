from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .content_quality_guard import check_channel_topic_fit
from .production_observation import production_observation_mode_enabled
from .visual_safety_policy import build_upload_quarantine_result, validate_visual_manifest


DEFAULT_POLICY_PATH = Path("config/content_domain_policy.json")
OWNERSHIP_DIR = Path("output/state/content_ownership")


@dataclass
class PrecheckResult:
    status: str
    quarantine_reason: str
    guard_reason_codes: list[str]
    recoverable: bool
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "quarantine_reason": self.quarantine_reason,
            "guard_reason_codes": list(self.guard_reason_codes),
            "recoverable": bool(self.recoverable),
            "details": dict(self.details),
        }


def _is_enabled(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _sha256_file(path: str | Path) -> str:
    p = Path(path)
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_policy(path: Path = DEFAULT_POLICY_PATH) -> dict[str, Any]:
    if not path.exists():
        return {"niches": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"niches": {}}


def _forbidden_keyword_matches(text: str, niche: str, policy: dict[str, Any]) -> list[str]:
    niches = dict(policy.get("niches") or {})
    niche_cfg = dict(niches.get(str(niche or "").strip().lower()) or {})
    forbidden = [str(x).strip().lower() for x in list(niche_cfg.get("forbidden_keywords") or []) if str(x).strip()]
    combined = str(text or "").lower()
    return [kw for kw in forbidden if kw in combined]


def _is_channel_scoped_path(channel_id: str, path: str | Path) -> bool:
    rel = str(Path(path).as_posix())
    marker = f"channels/{channel_id}/"
    return marker in rel


def _artifact_record(path: str | Path | None) -> dict[str, Any]:
    path_value = str(path or "").strip()
    record: dict[str, Any] = {
        "path": path_value,
        "available": False,
        "status": "missing",
        "sha256": None,
        "size": None,
    }
    if not path_value:
        return record

    p = Path(path_value)
    if not p.exists():
        return record
    if not p.is_file():
        record["status"] = "unreadable"
        record["error_type"] = "NotAFile"
        return record

    try:
        record["sha256"] = _sha256_file(p)
        record["size"] = int(p.stat().st_size)
        record["available"] = True
        record["status"] = "present"
    except Exception as exc:
        record["status"] = "unreadable"
        record["error_type"] = exc.__class__.__name__
    return record


def persist_ownership_manifest(
    *,
    channel_id: str,
    content_id: str,
    run_id: str,
    niche: str,
    title: str,
    topic: str,
    script: str,
    script_path: str,
    video_path: str,
    thumbnail_path: str | None = None,
    visual_manifest_path: str | None = None,
) -> Path:
    OWNERSHIP_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "channel_id": str(channel_id or "").strip(),
        "content_id": str(content_id or "").strip(),
        "run_id": str(run_id or "").strip(),
        "niche": str(niche or "").strip(),
        "title": str(title or ""),
        "topic": str(topic or ""),
        "script_preview": str(script or "")[:400],
        "artifacts": {
            "script": _artifact_record(script_path),
            "video": _artifact_record(video_path),
            "thumbnail": _artifact_record(thumbnail_path) if thumbnail_path is not None else {
                "path": "",
                "available": False,
                "status": "missing",
                "sha256": None,
                "size": None,
            },
        },
        "visual_manifest_path": str(visual_manifest_path or ""),
    }

    target = OWNERSHIP_DIR / f"{payload['content_id']}_{payload['run_id']}.json"
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)
    return target


def evaluate_upload_precheck(
    *,
    channel_id: str,
    content_id: str,
    run_id: str,
    niche: str,
    title: str,
    topic: str,
    script: str,
    description: str | None = None,
    tags: list[str] | None = None,
    script_path: str,
    video_path: str,
    thumbnail_path: str | None,
    manifest_path: str | Path,
    visual_manifest_path: str | Path | None = None,
    final_visual_assets: list[str] | None = None,
    duplicate_upload_detected: bool = False,
    quarantine_state: str = "",
    dry_run: bool = False,
    enabled: bool | None = None,
) -> dict[str, Any]:
    gate_enabled = _is_enabled(os.getenv("UPLOAD_PRECHECK_ENABLED", "true")) if enabled is None else bool(enabled)
    if not gate_enabled:
        return PrecheckResult(
            status="allow",
            quarantine_reason="",
            guard_reason_codes=[],
            recoverable=True,
            details={"gate_enabled": False},
        ).to_dict()

    try:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    except Exception as exc:
        return PrecheckResult(
            status="blocked",
            quarantine_reason="precheck_manifest_unreadable",
            guard_reason_codes=["upload_precheck_manifest_unreadable"],
            recoverable=False,
            details={"error": exc.__class__.__name__},
        ).to_dict()

    reason_codes: list[str] = []
    details: dict[str, Any] = {
        "manifest_path": str(manifest_path),
        "gate_enabled": True,
    }

    # Immutable ownership tuple must match current upload context.
    tuple_mismatches: list[str] = []
    for key, expected in {
        "channel_id": channel_id,
        "content_id": content_id,
        "run_id": run_id,
    }.items():
        actual = str(manifest.get(key) or "").strip()
        exp = str(expected or "").strip()
        if actual != exp:
            tuple_mismatches.append(f"{key}:{actual}!={exp}")
    if tuple_mismatches:
        reason_codes.append("upload_precheck_tuple_mismatch")
        details["tuple_mismatches"] = tuple_mismatches

    if dry_run:
        details["dry_run"] = True

    if duplicate_upload_detected:
        reason_codes.append("upload_precheck_duplicate_upload_prevented")

    if quarantine_state and quarantine_state not in {"", "allow", "clear"}:
        reason_codes.append("upload_precheck_quarantine_state_blocked")
        details["quarantine_state"] = quarantine_state

    if not _is_channel_scoped_path(channel_id=channel_id, path=video_path):
        reason_codes.append("upload_precheck_video_path_channel_scope_violation")
    if thumbnail_path and Path(thumbnail_path).exists() and not _is_channel_scoped_path(channel_id=channel_id, path=thumbnail_path):
        reason_codes.append("upload_precheck_thumbnail_path_channel_scope_violation")

    manifest_artifacts = dict(manifest.get("artifacts") or {})
    resolved_visual_manifest_path = str(visual_manifest_path or manifest.get("visual_manifest_path") or "").strip()
    visual_manifest = None
    if resolved_visual_manifest_path:
        try:
            visual_manifest = json.loads(Path(resolved_visual_manifest_path).read_text(encoding="utf-8"))
        except Exception as exc:
            reason_codes.append("visual_manifest_unreadable")
            details["visual_manifest_error"] = exc.__class__.__name__
    visual_decision = validate_visual_manifest(
        manifest=visual_manifest,
        channel_id=channel_id,
        content_id=content_id,
        run_id=run_id,
        final_assets=final_visual_assets,
    )
    details["visual_safety"] = visual_decision.to_dict()
    if not visual_decision.allowed:
        reason_codes.extend(visual_decision.failed_rules)
        details["visual_quarantine"] = build_upload_quarantine_result(
            channel_id=channel_id,
            content_id=content_id,
            run_id=run_id,
            failed_rules=visual_decision.failed_rules,
            evidence_paths=[resolved_visual_manifest_path] if resolved_visual_manifest_path else [],
            unsafe_assets=list(visual_decision.evidence.get("unsafe_assets") or []),
        )

    def _validate_artifact(label: str, path_value: str | None, *, required: bool = True):
        artifact_path = str(path_value or "").strip()
        manifest_artifact = dict(manifest_artifacts.get(label) or {})
        if not artifact_path:
            if required:
                reason_codes.append(f"upload_precheck_{label}_missing")
            return

        path_obj = Path(artifact_path)
        if not path_obj.exists():
            if required:
                reason_codes.append(f"upload_precheck_{label}_missing")
            return
        if not path_obj.is_file():
            reason_codes.append(f"upload_precheck_{label}_unreadable")
            return

        if not manifest_artifact or not str(manifest_artifact.get("path") or "").strip():
            reason_codes.append(f"upload_precheck_{label}_ownership_metadata_missing")

        try:
            actual_hash = _sha256_file(path_obj)
        except Exception as exc:
            reason_codes.append(f"upload_precheck_{label}_hash_unavailable")
            details[f"{label}_hash_error"] = exc.__class__.__name__
            return

        manifest_hash = str(manifest_artifact.get("sha256") or "").strip()
        if not manifest_hash:
            reason_codes.append(f"upload_precheck_{label}_ownership_metadata_missing")
        elif manifest_hash != actual_hash:
            reason_codes.append(f"upload_precheck_{label}_hash_mismatch")

        manifest_path = str(manifest_artifact.get("path") or "").strip()
        if manifest_path and manifest_path != artifact_path:
            reason_codes.append(f"upload_precheck_{label}_ownership_metadata_mismatch")

    observation_mode = production_observation_mode_enabled()
    details["production_observation_mode"] = bool(observation_mode)
    _validate_artifact("script", script_path, required=True)
    _validate_artifact("video", video_path, required=not observation_mode)
    _validate_artifact("thumbnail", thumbnail_path, required=True)

    try:
        video_size = Path(video_path).stat().st_size
    except Exception:
        video_size = 0
    if video_size <= 0 and not observation_mode:
        reason_codes.append("upload_precheck_video_empty")
        details["video_size"] = video_size

    if not str(title or "").strip():
        reason_codes.append("upload_precheck_title_missing")
    if description is not None and not str(description or "").strip():
        reason_codes.append("upload_precheck_description_missing")
    if tags is not None and not list(tags or []):
        reason_codes.append("upload_precheck_tags_missing")

    tag_tokens = [
        str(tag).strip().lower().replace("#", "")
        for tag in list(tags or [])
        if str(tag).strip() and len(str(tag).strip().replace("#", "")) >= 3
    ]
    combined_text = " ".join([str(title or ""), str(topic or ""), str(script or ""), str(description or "")]).lower()
    if tag_tokens and not any(token and token in combined_text for token in tag_tokens[:5]):
        reason_codes.append("upload_precheck_metadata_consistency_failed")

    fit, fit_reasons = check_channel_topic_fit(
        topic=str(topic or ""),
        script=str(script or ""),
        title=str(title or ""),
        niche=str(niche or ""),
        channel_topics=None,
    )
    if fit == "fail":
        reason_codes.append("channel_dna_mismatch")
        details["channel_fit_reasons"] = fit_reasons

    policy = _load_policy()
    forbidden_hits = _forbidden_keyword_matches(
        text=f"{title} {topic} {script} {description} {' '.join(list(tags or []))}",
        niche=str(niche or ""),
        policy=policy,
    )
    if forbidden_hits:
        reason_codes.append("domain_policy_forbidden_keyword")
        details["forbidden_keyword_hits"] = forbidden_hits[:12]

    if reason_codes:
        return PrecheckResult(
            status="blocked",
            quarantine_reason="channel_dna_mismatch" if "channel_dna_mismatch" in reason_codes else "upload_precheck_blocked",
            guard_reason_codes=sorted(set(reason_codes + ["upload_precheck_final_guard"])),
            recoverable=True,
            details=details,
        ).to_dict()

    return PrecheckResult(
        status="allow",
        quarantine_reason="",
        guard_reason_codes=[],
        recoverable=True,
        details=details,
    ).to_dict()
