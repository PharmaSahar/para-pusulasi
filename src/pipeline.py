"""
Tam Otomasyon Pipeline - Tek ve Cok Kanalli Mod
"""
import logging
import os
import re
import json
import subprocess
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .config import config as _default_config
from .content_generator import ContentGenerator, TopicDomainBlockedError, VideoContent
from .editor_review import build_editor_review_metadata
from .fact_sources import build_default_fact_provider
from .factual_freshness import FactCheckFailed, validate_script_factual_freshness
from .image_fetcher import ImageFetcher
from .analytics_join import build_analytics_join_metadata
from .audio_metadata_contract import AUDIO_METADATA_SCHEMA_VERSION
from .audio_metadata_validator import validate_audio_metadata_contract
from .channel_performance import append_performance_snapshot, build_performance_snapshot
from .performance_optimizer import build_optimization_guidance, load_channel_optimization_state
from .render_metrics import build_render_metrics
from .experiment_registry import build_experiment_id, DEFAULT_SCHEMA_VERSION
from .telemetry import (
    build_event_envelope,
    emit_event,
    generate_content_id,
    generate_run_id,
)
from .thumbnail_intelligence_validator import (
    normalize_rejection_reasons,
    validate_thumbnail_metadata_contract,
)
from .thumbnail_metadata_contract import THUMBNAIL_METADATA_SCHEMA_VERSION
from .thumbnail_candidate_generator import generate_thumbnail_candidates
from .thumbnail_experiment_registry_binding import register_thumbnail_variant_bindings
from .thumbnail_selection_policy import select_thumbnail_candidate
from .tts_engine import TTSEngine
from .video_creator_pro import VideoCreator
from .upload_precheck import evaluate_upload_precheck, persist_ownership_manifest
from .youtube_uploader import YouTubeUploader
from .production_quality_platform import (
    build_idempotency_key,
    evaluate_automatic_qa,
    evaluate_thumbnail_intelligence,
    get_registered_upload,
    record_production_event,
    register_upload,
    run_stage_with_recovery,
    score_script_quality,
    update_production_dashboard,
    update_production_observability_latest,
    write_production_evidence,
)

logger = logging.getLogger(__name__)
_PIPELINE_PROCESS_STARTED_AT_UTC = datetime.now(timezone.utc).isoformat()

_FACT_CHECK_RETRY_GUIDANCE = (
    "FACT-CHECK SAFE MODE: Yalnizca dogrulanabilir, kaynaklanabilir ve tarihsel baglami net olan veriler kullan. "
    "Baslikta, hook'ta, scriptte, thumbnail_prompt'ta ve aciklamada kesin fiyat hedefi, anlik kur seviyesi, endeks seviyesi, "
    "yuzde oran, son tarih, onay tarihi veya spekulatif piyasa tahmini kullanma. "
    "Volatil piyasa konularini yalnizca risk yonetimi, temel prensipler, tarihsel dersler ve senaryo okuma cercevesinde anlat. "
    "Canli veri izlenimi veren iddialari cikar; gerekli tum sayisal ornekleri acikca varsayimsal egitim ornegi olarak etiketle."
)

_RETRY_TOPIC_BY_CLAIM_TYPE = {
    "crypto": "Kripto piyasasinda fiyat hedefi vermeden risk yonetimi ve volatiliteyi anlama rehberi",
    "stock": "Borsa piyasasinda fiyat ve endeks seviyesi vermeden risk yonetimi rehberi",
    "commodity": "Emtia oynakligini kesin seviye vermeden yorumlama rehberi",
    "fx_usd_try": "Dolar/TL oynakliginda kesin kur seviyesi vermeden portfoy koruma rehberi",
    "inflation": "Enflasyon ortami icin kesin oran vermeden butce ve portfoy dayanıkliligi rehberi",
    "interest": "Faiz ortami icin kesin oran vermeden nakit ve portfoy planlama rehberi",
    "date_deadline": "Tarih ve son tarih iddialari olmadan surec ve kontrol listesi rehberi",
}


_REQUIRED_SNAPSHOT_FIELDS = (
    "performance_schema_version",
    "day",
    "created_at",
    "channel_id",
    "content_id",
    "run_id",
    "title",
)


def _is_enabled(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _is_fact_bundle_pipeline_adapter_enabled(cfg) -> bool:
    cfg_value = getattr(cfg, "fact_bundle_pipeline_adapter_enabled", None)
    if cfg_value is not None:
        return _is_enabled(cfg_value)
    return _is_enabled(os.getenv("FACT_BUNDLE_PIPELINE_ADAPTER_ENABLED", "false"))


def _invoke_fact_bundle_pipeline_adapter(cfg, result: dict) -> None:
    """Invoke Fact Bundle adapter only when explicitly enabled.

    This integration is fail-open to avoid changing production behavior.
    """
    if not _is_fact_bundle_pipeline_adapter_enabled(cfg):
        logger.info("Fact Bundle pipeline adapter skipped: feature flag disabled")
        return

    try:
        from .fact_bundle_pipeline_adapter import build_fact_bundle_pipeline_adapter

        logger.info("Fact Bundle pipeline adapter invoked: feature flag enabled")
        adapter = build_fact_bundle_pipeline_adapter(enabled=True)
        adapter_result = adapter.run()
        orchestration_result = adapter_result.orchestration_result
        result["fact_bundle_pipeline_adapter"] = {
            "enabled": bool(adapter_result.enabled),
            "applied": bool(adapter_result.applied),
            "reason": str(adapter_result.reason),
            "provider_count": int(orchestration_result.provider_count) if orchestration_result else 0,
            "provider_names": list(orchestration_result.provider_names) if orchestration_result else [],
        }
        logger.info(
            "Fact Bundle pipeline adapter success: applied=%s provider_count=%s",
            bool(adapter_result.applied),
            int(orchestration_result.provider_count) if orchestration_result else 0,
        )
    except Exception as e:
        logger.warning(
            "Fact Bundle pipeline adapter failed: error_type=%s",
            e.__class__.__name__,
        )


def _is_unverifiable_claim_failure(reason: str) -> bool:
    return "unverifiable_volatile_claim" in reason


def _extract_unverifiable_claim_type(reason: str) -> str | None:
    match = re.search(r"\(([^()]+)\)\s*$", reason)
    if not match:
        return None
    return match.group(1).strip().lower()


def _build_retry_guidance(reason: str) -> str:
    claim_type = _extract_unverifiable_claim_type(reason)
    claim_specific_rules = {
        "crypto": "Kripto fiyat hedefi, ETF tarih iddiasi, yil sonu hedefi veya belirli seviye yazma.",
        "stock": "Endeks seviyesi, hisse hedef fiyati, kisa vadeli piyasa seviyesi veya sayisal tahmin yazma.",
        "commodity": "Altin, gumus, petrol gibi varliklar icin kesin seviye ve hedef yazma.",
        "fx_usd_try": "Dolar/TL icin kesin kur, bant veya hedef seviye yazma.",
        "inflation": "Kesin enflasyon yuzdesi veya resmi veri gibi sunulan oran yazma.",
        "interest": "Kesin faiz oranlari veya toplantı sonucu tahmini yazma.",
        "date_deadline": "Son tarih, takvim, onay tarihi veya kesin zaman iddiasi yazma.",
    }
    extra_rule = claim_specific_rules.get(claim_type)
    if not extra_rule:
        return _FACT_CHECK_RETRY_GUIDANCE
    return f"{_FACT_CHECK_RETRY_GUIDANCE} {extra_rule}"


def _build_retry_topic(original_topic: str | None, generated_title: str, reason: str) -> str:
    claim_type = _extract_unverifiable_claim_type(reason)
    if claim_type in _RETRY_TOPIC_BY_CLAIM_TYPE:
        return _RETRY_TOPIC_BY_CLAIM_TYPE[claim_type]

    base = (original_topic or generated_title or "Volatil piyasalarda risk yonetimi").strip()
    sanitized = re.sub(r"\b20\d{2}\b", "", base)
    sanitized = re.sub(r"\d+[\d.,]*\s*(TL|\$|USD|TRY|BTC|ETH|%)?", "", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"\s+", " ", sanitized).strip(" -:,.?")
    if not sanitized:
        sanitized = "Volatil piyasalarda risk yonetimi"
    return f"{sanitized} icin fiyat hedefi vermeden risk yonetimi rehberi"


def _resolve_posting_slot(publish_at: str | None) -> str:
    """Infer morning/evening slot from scheduled publish time."""
    if publish_at:
        try:
            dt = datetime.fromisoformat(str(publish_at).replace("Z", "+00:00"))
            return "morning" if dt.hour < 15 else "evening"
        except Exception:
            pass
    now_local = datetime.now()
    return "morning" if now_local.hour < 15 else "evening"


def _resolve_git_head_short() -> str:
    try:
        output = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return output or "unknown"
    except Exception:
        return "unknown"


def _resolve_git_head_full() -> str:
    try:
        output = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return output or "unknown"
    except Exception:
        return "unknown"


def _build_runtime_build_identity() -> dict:
    full_sha = _resolve_git_head_full()
    short_sha = _resolve_git_head_short()
    return {
        "git_sha_full": full_sha,
        "git_sha_short": short_sha,
        "process_pid": os.getpid(),
        "process_started_at_utc": _PIPELINE_PROCESS_STARTED_AT_UTC,
        "python_executable": os.path.realpath(str(os.sys.executable)),
        "working_directory": os.getcwd(),
    }


def _classify_upload_failure(error_text: str) -> str:
    text = str(error_text or "").lower()
    if any(token in text for token in ("quota", "ratelimit", "rate limit", "rate_limited")):
        return "auth_or_quota"
    if any(token in text for token in ("credential", "permission", "http 401", "http 403")):
        return "auth_or_quota"
    if any(token in text for token in ("validation", "invalid", "metadata", "http 400")):
        return "metadata_rejection"
    if any(token in text for token in ("conflict", "idempot", "duplicate", "http 409")):
        return "duplicate_or_idempotency"
    if any(token in text for token in ("timeout", "server_error", "service unavailable", "http 5", "network", "dns")):
        return "api_error"
    if "missing_id" in text:
        return "missing_response_id"
    return "unknown"


def _resolve_analytics_live_runtime(cfg) -> tuple[bool, str]:
    """Resolve analytics-live runtime mode with strict production no-go guard.

    Live collector remains disabled until API-go decision is explicitly enabled.
    """
    cfg_flag = getattr(cfg, "live_collector_enabled", None)
    if cfg_flag is None:
        cfg_flag = os.getenv("LIVE_COLLECTOR_ENABLED", "false")
    requested = _is_enabled(cfg_flag)
    api_go = _is_enabled(os.getenv("YOUTUBE_ANALYTICS_API_GO", "false"))

    if not api_go:
        return False, "no_go_api_not_enabled"
    if not requested:
        return False, "disabled_by_flag"
    # Keep disabled by policy even if requested, until explicit rollout approval.
    return False, "disabled_by_policy"


def _production_quality_platform_enabled() -> bool:
    explicit_enable = _is_enabled(os.getenv("PRODUCTION_QUALITY_PLATFORM_ENABLED", "false"))
    current_test = str(os.getenv("PYTEST_CURRENT_TEST") or "")
    pytest_gate_allowlist = (
        "test_pipeline_quality_integration.py" in current_test
        or "test_production_quality_platform.py" in current_test
    )
    runtime_override = _is_enabled(os.getenv("PIPELINE_RUNTIME_GATES_IN_TESTS", "false"))
    if (
        current_test
        and not runtime_override
        and not pytest_gate_allowlist
    ):
        return False
    return explicit_enable


def _content_quality_gate_enabled() -> bool:
    explicit_enable = _is_enabled(os.getenv("CONTENT_QUALITY_GATE_ENABLED", "false"))
    current_test = str(os.getenv("PYTEST_CURRENT_TEST") or "")
    pytest_gate_allowlist = (
        "test_pipeline_quality_integration.py" in current_test
        or "test_production_quality_platform.py" in current_test
    )
    runtime_override = _is_enabled(os.getenv("PIPELINE_RUNTIME_GATES_IN_TESTS", "false"))
    if (
        current_test
        and not runtime_override
        and not pytest_gate_allowlist
    ):
        return False
    return explicit_enable


def _content_quality_shadow_mode_enabled() -> bool:
    try:
        from .shadow_content_quality import content_quality_shadow_mode_enabled

        return bool(content_quality_shadow_mode_enabled())
    except Exception:
        return False


def _attach_audio_mix_metadata(result: dict, creator: object) -> None:
    mix = getattr(creator, "last_audio_mix_metadata", None)
    if isinstance(mix, dict) and mix:
        result["audio_mix"] = mix


def _resolve_experiment_id(*, explicit_experiment_id: str | None, cfg: object) -> str:
    if explicit_experiment_id and str(explicit_experiment_id).strip():
        return str(explicit_experiment_id).strip()

    cfg_value = getattr(cfg, "experiment_id", None)
    if cfg_value and str(cfg_value).strip():
        return str(cfg_value).strip()

    env_value = os.getenv("EXPERIMENT_ID")
    if env_value and str(env_value).strip():
        return str(env_value).strip()

    return build_experiment_id()


def _append_pipeline_run_registry_event(
    *,
    experiment_id: str,
    run_id: str,
    channel_id: str,
    topic: str | None,
    title: str,
    schema_version: str,
) -> None:
    """Append pipeline run trace event to registry JSONL in fail-open mode."""
    registry_path = Path(os.getenv("EXPERIMENT_REGISTRY_PATH", "output/telemetry/experiments.jsonl"))
    payload = {
        "experiment_id": experiment_id,
        "run_id": run_id,
        "channel_id": channel_id,
        "topic": (topic or "").strip() or None,
        "title": (title or "").strip() or None,
    }
    event = {
        "event_type": "pipeline_run",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "experiment_id": experiment_id,
        "schema_version": schema_version,
        "created_by": "pipeline",
        "payload": payload,
    }

    registry_path.parent.mkdir(parents=True, exist_ok=True)
    with registry_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")


def _validate_performance_snapshot(snapshot: dict) -> tuple[bool, dict]:
    """Validate required performance snapshot fields before append."""
    if not isinstance(snapshot, dict):
        return False, {"reason": "not_a_dict"}

    missing_fields: list[str] = []
    invalid_fields: list[str] = []

    for field in _REQUIRED_SNAPSHOT_FIELDS:
        value = snapshot.get(field)
        if value is None:
            missing_fields.append(field)
            continue
        if not str(value).strip():
            invalid_fields.append(field)

    day_raw = str(snapshot.get("day") or "").strip()
    if day_raw:
        try:
            datetime.fromisoformat(day_raw)
        except Exception:
            invalid_fields.append("day")

    created_raw = str(snapshot.get("created_at") or "").strip()
    if created_raw:
        try:
            datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
        except Exception:
            invalid_fields.append("created_at")

    is_valid = not missing_fields and not invalid_fields
    return is_valid, {
        "missing_fields": missing_fields,
        "invalid_fields": invalid_fields,
    }


def run_full_pipeline(
    topic: str | None = None,
    generate_only: bool = False,
    privacy: str = os.getenv("DEFAULT_PRIVACY", "public"),
    channel_cfg=None,
    publish_at: str | None = None,
    posting_slot: str | None = None,
    experiment_id: str | None = None,
) -> dict:
    """Tam pipeline: icerik -> ses -> video -> YouTube yukle."""
    # Aktif config belirle
    cfg = channel_cfg if channel_cfg else _default_config
    cfg.ensure_directories()
    result = {"channel": getattr(cfg, "channel_id", "default")}
    result["started_at"] = datetime.now(timezone.utc).isoformat()
    runtime_build_identity = _build_runtime_build_identity()
    result["runtime_build_identity"] = runtime_build_identity
    result["build_sha"] = runtime_build_identity.get("git_sha_short", "unknown")
    result["commit_sha"] = runtime_build_identity.get("git_sha_full", result["build_sha"])
    result["scheduler_pid"] = int(runtime_build_identity.get("process_pid") or os.getpid())
    result["thumbnail_metadata"] = {}
    result["rejection_reasons"] = []
    slot = posting_slot or _resolve_posting_slot(publish_at)
    result["slot"] = slot
    result["content_id"] = generate_content_id()
    result["run_id"] = generate_run_id()
    resolved_experiment_id = _resolve_experiment_id(explicit_experiment_id=experiment_id, cfg=cfg)
    result["experiment_id"] = resolved_experiment_id
    live_collector_enabled, analytics_live_status = _resolve_analytics_live_runtime(cfg)
    result["live_collector_enabled"] = bool(live_collector_enabled)
    result["analytics_live_status"] = analytics_live_status
    result["collector_evaluator_path"] = {
        "mode": "mock_first",
        "live_collector_enabled": bool(live_collector_enabled),
        "analytics_live_status": analytics_live_status,
    }
    # Keep observability fields present in production result, even before later stages fill them.
    result["thumbnail_variants"] = []
    result["selected_thumbnail_variant"] = None
    result["thumbnail_selection_policy"] = str(getattr(cfg, "thumbnail_selection_policy", "") or "first").strip().lower() or "first"
    result["audio_metadata"] = {}
    result["audio_warning"] = None
    result["analytics_warning"] = None
    result["pipeline_retry_count"] = 0
    result["upload_retry_count"] = 0
    result["final_status"] = "in_progress"
    _invoke_fact_bundle_pipeline_adapter(cfg, result)
    shadow_mode_enabled = _content_quality_shadow_mode_enabled()

    telemetry_metadata = {
        "experiment_id": resolved_experiment_id,
        "experiment_group": os.getenv("EXPERIMENT_GROUP"),
        "prompt_version": getattr(cfg, "prompt_version", None) or os.getenv("PROMPT_VERSION"),
        "channel_dna_version": getattr(cfg, "channel_dna_version", None) or os.getenv("CHANNEL_DNA_VERSION"),
        "thumbnail_strategy": getattr(cfg, "thumbnail_strategy", None) or os.getenv("THUMBNAIL_STRATEGY"),
        "tts_strategy": getattr(cfg, "tts_strategy", None) or os.getenv("TTS_STRATEGY"),
        "model_version": os.getenv("MODEL_VERSION"),
        "runtime_build_identity": runtime_build_identity,
    }

    def _record_warning(field: str, *, code: str, message: str, extra: dict | None = None):
        previous = result.get(field)
        count = 1
        if isinstance(previous, dict):
            count = int(previous.get("count", 0) or 0) + 1
        warning = {
            "code": code,
            "message": message,
            "count": count,
        }
        if isinstance(extra, dict):
            warning.update(extra)
        result[field] = warning
        return warning

    if result.get("analytics_live_status") == "no_go_api_not_enabled":
        _record_warning(
            "analytics_warning",
            code="analytics_live_no_go",
            message="Live analytics collector disabled until YouTube Analytics API go-decision.",
            extra={"live_collector_enabled": False},
        )

    def _refresh_observability_fields() -> None:
        audio_metadata = result.get("audio_mix_metadata")
        if not isinstance(audio_metadata, dict):
            audio_metadata = {}
            if result.get("music_track_id"):
                audio_metadata["music_track_id"] = result.get("music_track_id")
            if result.get("ducking_applied") is not None:
                audio_metadata["ducking_applied"] = result.get("ducking_applied")
            if result.get("loudness_target") is not None:
                audio_metadata["loudness_target"] = result.get("loudness_target")
        result["audio_metadata"] = audio_metadata

        if not isinstance(result.get("thumbnail_variants"), list):
            result["thumbnail_variants"] = []
        if "selected_thumbnail_variant" not in result:
            result["selected_thumbnail_variant"] = None
        if not result.get("thumbnail_selection_policy"):
            result["thumbnail_selection_policy"] = "first"
        if "audio_warning" not in result:
            result["audio_warning"] = None
        if "analytics_warning" not in result:
            result["analytics_warning"] = None

    shadow_engine = None

    def _run_shadow_checkpoint(checkpoint: str, **kwargs) -> None:
        if not shadow_engine:
            return
        try:
            row = shadow_engine.evaluate_and_store(checkpoint=checkpoint, **kwargs)
            result.setdefault("shadow_quality", {}).setdefault("checkpoints", []).append(
                {
                    "checkpoint": checkpoint,
                    "overall_score": row.get("overall_score"),
                    "finding_count": row.get("finding_count"),
                    "severity": row.get("severity"),
                    "created_at": row.get("created_at"),
                    "storage_status": "success",
                }
            )
            logger.info(
                "shadow_quality run_id=%s channel_id=%s checkpoint=%s overall_score=%s finding_count=%s severity=%s shadow_mode=%s storage=success",
                result.get("run_id"),
                result.get("channel"),
                checkpoint,
                row.get("overall_score"),
                row.get("finding_count"),
                row.get("severity"),
                True,
            )
        except Exception as exc:
            result.setdefault("shadow_quality", {}).setdefault("checkpoints", []).append(
                {
                    "checkpoint": checkpoint,
                    "overall_score": None,
                    "finding_count": 0,
                    "severity": "none",
                    "storage_status": "failed",
                    "error_type": exc.__class__.__name__,
                }
            )
            logger.warning(
                "shadow_quality run_id=%s channel_id=%s checkpoint=%s overall_score=%s finding_count=%s severity=%s shadow_mode=%s storage=failure error_type=%s",
                result.get("run_id"),
                result.get("channel"),
                checkpoint,
                "none",
                0,
                "none",
                True,
                exc.__class__.__name__,
            )

    def _derive_thumbnail_text(title_value: str) -> str:
        words = [w for w in str(title_value or "").split() if w.strip()]
        return " ".join(words[:7]).strip()

    def _emit(stage: str, event_type: str, payload: dict | None = None):
        try:
            _refresh_observability_fields()
            merged_payload = dict(payload or {})
            # Explicitly expose runtime metadata for production observability.
            merged_payload["experiment_id"] = result.get("experiment_id")
            merged_payload["thumbnail_variants"] = result.get("thumbnail_variants") or []
            merged_payload["selected_thumbnail_variant"] = result.get("selected_thumbnail_variant")
            merged_payload["thumbnail_selection_policy"] = result.get("thumbnail_selection_policy")
            merged_payload["audio_metadata"] = result.get("audio_metadata") or {}
            merged_payload["audio_warning"] = result.get("audio_warning")
            merged_payload["analytics_warning"] = result.get("analytics_warning")
            merged_payload["analytics_live_status"] = result.get("analytics_live_status")
            merged_payload["live_collector_enabled"] = bool(result.get("live_collector_enabled", False))
            merged_payload["runtime_build_identity"] = dict(runtime_build_identity)
            merged_payload["git_sha_full"] = runtime_build_identity.get("git_sha_full")
            merged_payload["git_sha_short"] = runtime_build_identity.get("git_sha_short")
            merged_payload["process_pid"] = runtime_build_identity.get("process_pid")
            merged_payload["process_started_at_utc"] = runtime_build_identity.get("process_started_at_utc")
            merged_payload["python_executable"] = runtime_build_identity.get("python_executable")
            merged_payload["working_directory"] = runtime_build_identity.get("working_directory")
            envelope = build_event_envelope(
                content_id=result["content_id"],
                run_id=result["run_id"],
                channel_id=result.get("channel"),
                stage=stage,
                event_type=event_type,
                payload=merged_payload,
                experiment_id=telemetry_metadata.get("experiment_id"),
                experiment_group=telemetry_metadata.get("experiment_group"),
                prompt_version=telemetry_metadata.get("prompt_version"),
                channel_dna_version=telemetry_metadata.get("channel_dna_version"),
                thumbnail_strategy=telemetry_metadata.get("thumbnail_strategy"),
                tts_strategy=telemetry_metadata.get("tts_strategy"),
                model_version=telemetry_metadata.get("model_version"),
            )
            emit_event(envelope, logger=logger)
            try:
                obs_payload = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "channel": result.get("channel"),
                    "topic": topic or result.get("title"),
                    "generation_id": result.get("content_id"),
                    "stage": stage,
                    "event_type": event_type,
                    "selected_topic_reason": str(result.get("optimization_guidance") or "")[:300],
                    "selected_visuals": result.get("selected_visuals") or [],
                    "rejection_reasons": result.get("rejection_reasons") or [],
                    "quality_guard_decisions": {
                        "content_quality": result.get("content_quality"),
                        "automatic_qa": result.get("automatic_qa"),
                        "script_quality": result.get("script_quality"),
                    },
                    "render_result": result.get("render_metrics") or {},
                    "upload_result": {
                        "video_id": result.get("video_id"),
                        "youtube_url": result.get("youtube_url"),
                        "error": result.get("upload_error"),
                    },
                    "retry_count": int(result.get("pipeline_retry_count", 0) or 0) + int(result.get("upload_retry_count", 0) or 0),
                    "failure_stage": stage if event_type == "stage_failed" else None,
                    "final_status": result.get("final_status"),
                    "content_type": "video",
                }
                record_production_event(obs_payload)
            except Exception:
                pass
        except Exception as e:
            # Telemetry must be fail-open and never affect production flow.
            warning = _record_warning(
                "telemetry_warning",
                code="telemetry_emit_failed",
                message="Telemetry event emit failed; pipeline continued.",
                extra={
                    "stage": stage,
                    "event_type": event_type,
                    "error_type": e.__class__.__name__,
                },
            )
            logger.warning(
                "Telemetry emit fail-open: code=%s stage=%s event_type=%s error_type=%s count=%s",
                warning.get("code"),
                warning.get("stage"),
                warning.get("event_type"),
                warning.get("error_type"),
                warning.get("count"),
            )

    def _standardize_audio_mix_metadata(*, mix: object, scope: str):
        if not isinstance(mix, dict) or not mix:
            return

        try:
            track_id = str(mix.get("music_track_id") or mix.get("track_id") or "").strip()
            ducking_applied = mix.get("ducking_applied")
            loudness_target = mix.get("loudness_target")
            if loudness_target is None:
                loudness_target = mix.get("loudness_target_lufs")

            payload = {
                "schema_version": AUDIO_METADATA_SCHEMA_VERSION,
                "audio_mix_metadata": mix,
                "music_track_id": track_id,
                "ducking_applied": ducking_applied,
                "loudness_target": loudness_target,
            }
            warning_payload = mix.get("audio_warning")
            if isinstance(warning_payload, dict):
                payload["audio_warning"] = warning_payload

            errors = validate_audio_metadata_contract(payload)
            if errors:
                raise ValueError(errors[0])

            if scope == "video":
                result["audio_mix_metadata"] = payload
                result["music_track_id"] = payload["music_track_id"]
                result["ducking_applied"] = payload["ducking_applied"]
                result["loudness_target"] = payload["loudness_target"]
                result["audio_metadata"] = payload
            else:
                result["short_audio_mix_metadata"] = payload
        except Exception as e:
            warning = _record_warning(
                "audio_warning",
                code="audio_metadata_validation_failed",
                message="Audio metadata validation failed; pipeline continued.",
                extra={
                    "scope": scope,
                    "error_type": e.__class__.__name__,
                },
            )
            logger.warning(
                "Audio metadata fail-open: code=%s scope=%s error_type=%s count=%s",
                warning.get("code"),
                warning.get("scope"),
                warning.get("error_type"),
                warning.get("count"),
            )
        finally:
            _refresh_observability_fields()

    def _extract_diversity_rejection_reasons(rejected_attempts: list | None) -> list[str]:
        reasons: list[str] = []
        for item in rejected_attempts or []:
            if not isinstance(item, dict):
                continue
            raw = item.get("reasons")
            if isinstance(raw, list):
                reasons.extend(str(x) for x in raw if str(x).strip())
        return reasons

    def _attach_thumbnail_validation_metadata(
        *,
        content_type: str,
        thumbnail_path: str,
        variant_id: str,
        rejected_attempts: list | None,
    ):
        raw_reasons = _extract_diversity_rejection_reasons(rejected_attempts)
        rejection_reasons = normalize_rejection_reasons(raw_reasons)

        quality = {
            "safe_area_pass": "SAFE_AREA_VIOLATION" not in rejection_reasons,
            "text_density_ratio": 0.0,
            "text_density_pass": "TEXT_DENSITY_EXCEEDED" not in rejection_reasons,
            "subject_clarity_pass": "SUBJECT_CLARITY_LOW" not in rejection_reasons,
            "brand_consistency_pass": "BRAND_INCONSISTENT" not in rejection_reasons,
            "diversity_pass": "DUPLICATE_OR_LOW_DIVERSITY" not in rejection_reasons,
            "contrast_pass": "LOW_CONTRAST" not in rejection_reasons,
            "overall_pass": len(rejection_reasons) == 0,
        }

        metadata = {
            "schema_version": THUMBNAIL_METADATA_SCHEMA_VERSION,
            "channel_id": str(result.get("channel", "default")),
            "content_id": str(result.get("content_id", "")),
            "thumbnail_path": str(thumbnail_path),
            "variant_id": str(variant_id),
            "evaluated_at_utc": datetime.now(timezone.utc).isoformat(),
            "quality": quality,
            "rejection_reasons": rejection_reasons,
            "diversity": {
                "window_size": 30,
                "similarity_score": 0.0,
                "similarity_threshold": 0.78,
            },
            "brand_profile_version": "v1",
        }

        try:
            result.setdefault("thumbnail_metadata", {})[content_type] = metadata
            merged_reasons = list(result.get("rejection_reasons") or [])
            for reason in rejection_reasons:
                if reason not in merged_reasons:
                    merged_reasons.append(reason)
            result["rejection_reasons"] = merged_reasons

            errors = validate_thumbnail_metadata_contract(metadata)
            if errors:
                result.setdefault("thumbnail_validation_errors", {})[content_type] = errors
                warning = _record_warning(
                    "validation_warning",
                    code="thumbnail_metadata_validation_failed",
                    message="Thumbnail metadata validation failed; pipeline continued.",
                    extra={
                        "content_type": content_type,
                        "error_count": len(errors),
                        "first_error": errors[0],
                    },
                )
                logger.warning(
                    "Validation fail-open: code=%s content_type=%s error_count=%s count=%s",
                    warning.get("code"),
                    warning.get("content_type"),
                    warning.get("error_count"),
                    warning.get("count"),
                )
        except Exception as e:
            warning = _record_warning(
                "validation_warning",
                code="thumbnail_validator_failed",
                message="Thumbnail validator execution failed; pipeline continued.",
                extra={
                    "content_type": content_type,
                    "error_type": e.__class__.__name__,
                },
            )
            logger.warning(
                "Validation fail-open: code=%s content_type=%s error_type=%s count=%s",
                warning.get("code"),
                warning.get("content_type"),
                warning.get("error_type"),
                warning.get("count"),
            )

    def _attach_thumbnail_experiment_binding_metadata(*, thumbnail_path: str):
        try:
            base_prompt = str(getattr(content, "thumbnail_prompt", "") or getattr(content, "title", "") or "").strip()
            fallback_prompt = str(getattr(content, "title", "") or "thumbnail variant").strip()
            prompt_a = base_prompt or fallback_prompt
            prompt_b = (prompt_a + " | alt").strip()

            candidates = generate_thumbnail_candidates(
                experiment_id=resolved_experiment_id,
                channel_id=str(result.get("channel", "default")),
                content_id=str(result.get("content_id", "")),
                strategy="default_ab",
                candidates=[
                    {"thumbnail_path": thumbnail_path, "prompt": prompt_a},
                    {"thumbnail_path": thumbnail_path, "prompt": prompt_b},
                ],
                count=2,
            )
            events = register_thumbnail_variant_bindings(
                experiment_id=resolved_experiment_id,
                candidates=candidates,
            )

            result["thumbnail_variants"] = [asdict(item) for item in candidates]
            result["thumbnail_variant_registry_events"] = events

            try:
                selection_policy = str(getattr(cfg, "thumbnail_selection_policy", "") or "first").strip().lower() or "first"
                selected_variant = select_thumbnail_candidate(
                    candidates=result.get("thumbnail_variants") or [],
                    policy=selection_policy,
                    content_id=str(result.get("content_id", "")) or None,
                    video_id=str(result.get("video_id", "")) or None,
                )
                result["thumbnail_selection_policy"] = selection_policy
                result["selected_thumbnail_variant"] = selected_variant
            except Exception as e:
                warning = _record_warning(
                    "thumbnail_selection_warning",
                    code="thumbnail_selection_failed",
                    message="Thumbnail selection failed; pipeline continued.",
                    extra={"error_type": e.__class__.__name__},
                )
                logger.warning(
                    "Thumbnail selection fail-open: code=%s error_type=%s count=%s",
                    warning.get("code"),
                    warning.get("error_type"),
                    warning.get("count"),
                )
        except Exception as e:
            warning = _record_warning(
                "thumbnail_experiment_warning",
                code="thumbnail_experiment_binding_failed",
                message="Thumbnail experiment binding failed; pipeline continued.",
                extra={"error_type": e.__class__.__name__},
            )
            logger.warning(
                "Thumbnail experiment fail-open: code=%s error_type=%s count=%s",
                warning.get("code"),
                warning.get("error_type"),
                warning.get("count"),
            )

    fact_provider = build_default_fact_provider()
    fact_check_metadata: dict | None = None

    def _telegram_fact_check_alert(message: str):
        try:
            from .scheduler_utils import send_telegram

            send_telegram(message)
        except Exception:
            pass

    def _run_fact_check_guard(before_stage: str, script: str, *, suppress_retryable_alert: bool = False):
        nonlocal fact_check_metadata
        _emit("fact_check", "stage_started", {"before_stage": before_stage})
        try:
            metadata = validate_script_factual_freshness(script, fact_provider)
            fact_check_metadata = metadata
            result["fact_check"] = metadata
            result["fact_check_metadata"] = metadata
            try:
                setattr(content, "fact_check_metadata", metadata)
            except Exception:
                pass
            result["job_status"] = "fact_check_passed"
            _emit(
                "fact_check",
                "stage_completed",
                {
                    "before_stage": before_stage,
                    "fact_check_status": metadata.get("fact_check_status"),
                    "sources": metadata.get("sources", []),
                    "volatile_claims_checked": metadata.get("volatile_claims_checked", []),
                    "checked_at": metadata.get("checked_at"),
                },
            )
        except FactCheckFailed as e:
            reason = str(e)
            failed_metadata = {
                "fact_check_status": "failed",
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "sources": (e.metadata or {}).get("sources", []),
                "volatile_claims_checked": (e.metadata or {}).get("volatile_claims_checked", []),
                "failure_reason": reason,
            }
            fact_check_metadata = failed_metadata
            result["fact_check"] = failed_metadata
            result["fact_check_metadata"] = failed_metadata
            result["job_status"] = "failed_fact_check"
            _emit(
                "fact_check",
                "stage_failed",
                {
                    "before_stage": before_stage,
                    "error": reason[:300],
                },
            )
            if not (suppress_retryable_alert and _is_unverifiable_claim_failure(reason)):
                _telegram_fact_check_alert(
                    "🚫 <b>Fact Check FAIL</b>\n"
                    f"📺 Kanal: {result.get('channel', 'default')}\n"
                    f"⛔ Aşama öncesi: {before_stage}\n"
                    f"🧾 Sebep: {reason[:250]}"
                )
            raise RuntimeError(f"failed_fact_check: {reason}") from e

    def _generate_content(generator: ContentGenerator, *, generation_topic: str | None, additional_guidance: str | None = None):
        nonlocal content
        try:
            if additional_guidance is None:
                content = generator.generate_and_save(generation_topic)
            else:
                try:
                    content = generator.generate_and_save(generation_topic, additional_guidance=additional_guidance)
                except TypeError:
                    content = generator.generate_and_save(generation_topic)
        except TopicDomainBlockedError as topic_error:
            trace = dict(getattr(topic_error, "trace", {}) or {})
            msg = str(topic_error or "")
            msg_lower = msg.lower()
            is_collision = "topic_provenance_collision" in msg_lower
            setattr(topic_error, "_skip_scheduler_pipeline_retry", True)
            setattr(topic_error, "_quarantine_reason", "topic_provenance_collision" if is_collision else "topic_domain_blocked")

            guard_reason_codes = list(getattr(topic_error, "_guard_reason_codes", []) or [])
            if is_collision and "topic_provenance_collision" not in guard_reason_codes:
                guard_reason_codes.append("topic_provenance_collision")
            if (not is_collision) and "topic_domain_blocked" not in guard_reason_codes:
                guard_reason_codes.append("topic_domain_blocked")
            setattr(topic_error, "_guard_reason_codes", sorted(set(str(code).strip().lower() for code in guard_reason_codes if str(code).strip())))

            collision_path = ""
            if is_collision and ":" in msg:
                collision_path = msg.split(":", 1)[1].strip()

            setattr(topic_error, "_run_id", str(result.get("run_id", "") or ""))
            setattr(topic_error, "_content_id", str(result.get("content_id", "") or ""))
            setattr(topic_error, "_topic", str(generation_topic or trace.get("selected_topic") or ""))
            setattr(topic_error, "_detected_domain", str(trace.get("detected_domain") or "unknown"))
            setattr(topic_error, "_detected_channel", str(trace.get("channel_id") or result.get("channel") or ""))
            setattr(topic_error, "_triggering_validator", "topic_provenance_validator" if is_collision else "topic_domain_validator")
            setattr(topic_error, "_pipeline_stage", "content_generation")
            setattr(topic_error, "_error_type", "topic_provenance_collision" if is_collision else "topic_domain_blocked")
            setattr(topic_error, "_collision_path", collision_path)
            setattr(topic_error, "_original_topic_source", str(trace.get("provider") or "unknown"))
            setattr(topic_error, "_provenance_score", trace.get("provenance_score"))
            setattr(topic_error, "_confidence_score", trace.get("confidence_score"))
            setattr(topic_error, "_regeneration_count", int(result.get("pipeline_retry_count", 0) or 0))
            setattr(topic_error, "_regeneration_limit", 1)
            raise
        result["title"] = content.title
        result["script_path"] = str(getattr(content, "saved_path", "") or f"{cfg.scripts_dir}/{content.created_at[:10]}_{content.title[:30]}.json")

    @contextmanager
    def _stage(stage: str, start_payload: dict | None = None, complete_payload_fn=None):
        _emit(stage, "stage_started", start_payload)
        try:
            yield
        except Exception as e:
            _emit(stage, "stage_failed", {"error": str(e)[:300]})
            raise
        else:
            payload = {}
            if callable(complete_payload_fn):
                try:
                    payload = complete_payload_fn() or {}
                except Exception:
                    payload = {}
            _emit(stage, "stage_completed", payload)

    # ─── ADIM 1: Icerik Uretimi ────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info(f"ADIM 1/4 - Icerik Uretimi [{result['channel']}]")
    logger.info("=" * 60)
    with _stage(
        "content_generation",
        start_payload={"generate_only": generate_only},
        complete_payload_fn=lambda: {"title": result.get("title", "")[:120]},
    ):
        generator_kwargs = {
            "channel_cfg": cfg,
            "provenance_context": {
                "run_id": result.get("run_id"),
                "content_id": result.get("content_id"),
                "channel_id": result.get("channel"),
                "channel_slug": str(result.get("channel") or "").strip().lower(),
                "expected_niche": getattr(cfg, "niche", None),
                "runtime_build_identity": runtime_build_identity,
                "output_dir": getattr(cfg, "output_dir", "output"),
            },
        }
        try:
            generator = ContentGenerator(**generator_kwargs)
        except TypeError as e:
            if "unexpected keyword argument 'provenance_context'" in str(e):
                generator = ContentGenerator(channel_cfg=cfg)
            else:
                raise
        telemetry_metadata["model_version"] = telemetry_metadata.get("model_version") or getattr(generator, "model", None)
        content: VideoContent
        live_optimization_state = {}
        try:
            live_optimization_state = load_channel_optimization_state(str(result.get("channel", "default")))
            if live_optimization_state:
                result["optimization_state"] = live_optimization_state
                result["optimization_guidance"] = build_optimization_guidance(live_optimization_state)
        except Exception:
            live_optimization_state = {}

        optimization_guidance = result.get("optimization_guidance") or ""
        _generate_content(
            generator,
            generation_topic=topic,
            additional_guidance=optimization_guidance or None,
        )

    if _production_quality_platform_enabled():
        _script_quality_regeneration_count = 0
        script_quality = score_script_quality(
            title=getattr(content, "title", ""),
            script=getattr(content, "script", ""),
            description=getattr(content, "description", ""),
            topic=topic or getattr(content, "title", ""),
            cta_text=getattr(content, "next_video_teaser", ""),
            recent_scripts=[],
        )
        result["script_quality"] = script_quality
        while script_quality.get("overall_score", 0.0) < float(script_quality.get("threshold", 62.0)):
            if _script_quality_regeneration_count >= 1:
                raise RuntimeError(
                    f"script_quality_blocked: score={script_quality.get('overall_score')} threshold={script_quality.get('threshold')}"
                )
            _script_quality_regeneration_count += 1
            result["pipeline_retry_count"] = int(result.get("pipeline_retry_count", 0)) + 1
            retry_guidance = (
                "Script quality below production threshold. Regenerate with stronger hook, "
                "higher information density, clearer structure, and a concrete CTA."
            )
            _generate_content(generator, generation_topic=topic, additional_guidance=retry_guidance)
            script_quality = score_script_quality(
                title=getattr(content, "title", ""),
                script=getattr(content, "script", ""),
                description=getattr(content, "description", ""),
                topic=topic or getattr(content, "title", ""),
                cta_text=getattr(content, "next_video_teaser", ""),
                recent_scripts=[],
            )
            result["script_quality"] = script_quality

    if shadow_mode_enabled:
        try:
            from .shadow_content_quality import (
                SHADOW_CONTENT_QUALITY_SCHEMA_VERSION,
                SHADOW_RESULTS_PATH,
                ShadowContentQualityEngine,
                build_shadow_evaluation_context,
            )

            shadow_context = build_shadow_evaluation_context(
                run_id=str(result.get("run_id", "")),
                content_id=str(result.get("content_id", "")),
                channel_id=str(result.get("channel", "")),
                content_type="mixed",
                topic=str(topic or getattr(content, "title", "") or ""),
                title=str(getattr(content, "title", "") or ""),
                script=str(getattr(content, "script", "") or ""),
                description=str(getattr(content, "description", "") or ""),
                thumbnail_prompt=str(getattr(content, "thumbnail_prompt", "") or ""),
                cta_text=str(getattr(content, "next_video_teaser", "") or ""),
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            shadow_engine = ShadowContentQualityEngine(context=shadow_context, results_path=SHADOW_RESULTS_PATH)
            result["shadow_quality"] = {
                "enabled": True,
                "schema_version": SHADOW_CONTENT_QUALITY_SCHEMA_VERSION,
                "evaluation_id": shadow_context.evaluation_id,
                "results_path": str(SHADOW_RESULTS_PATH),
                "mode": "advisory",
                "checkpoints": [],
            }
            _run_shadow_checkpoint(checkpoint="generation")
            _run_shadow_checkpoint(
                checkpoint="description",
                description=str(getattr(content, "description", "") or ""),
            )
        except Exception as exc:
            logger.warning(
                "shadow_quality run_id=%s channel_id=%s checkpoint=%s overall_score=%s finding_count=%s severity=%s shadow_mode=%s storage=failure error_type=%s",
                result.get("run_id"),
                result.get("channel"),
                "context_init",
                "none",
                0,
                "none",
                True,
                exc.__class__.__name__,
            )
            result["shadow_quality"] = {
                "enabled": True,
                "schema_version": "v2",
                "evaluation_id": None,
                "results_path": "logs/shadow_content_quality_results.jsonl",
                "mode": "advisory",
                "checkpoints": [
                    {
                        "checkpoint": "context_init",
                        "storage_status": "failed",
                        "error_type": exc.__class__.__name__,
                    }
                ],
            }

    try:
        _append_pipeline_run_registry_event(
            experiment_id=resolved_experiment_id,
            run_id=result["run_id"],
            channel_id=str(result.get("channel", "default")),
            topic=topic,
            title=getattr(content, "title", ""),
            schema_version=DEFAULT_SCHEMA_VERSION,
        )
    except Exception as e:
        warning = _record_warning(
            "registry_warning",
            code="pipeline_registry_event_append_failed",
            message="Pipeline registry event append failed; pipeline continued.",
            extra={"error_type": e.__class__.__name__},
        )
        logger.warning(
            "Registry fail-open: code=%s error_type=%s count=%s",
            warning.get("code"),
            warning.get("error_type"),
            warning.get("count"),
        )

    diversity_video_record = None
    thumbnail_experiments = {}
    diversity_short_record = None
    try:
        from .channel_visual_profiles import get_channel_visual_profile
        from .thumbnail_history import load_recent_thumbnail_history
        from .thumbnail_experiments import build_thumbnail_experiment_bundle
        from .visual_diversity import enforce_thumbnail_diversity

        visual_profile = get_channel_visual_profile(
            str(result.get("channel", "default")),
            niche=getattr(content, "niche", ""),
        )
        recent_history = load_recent_thumbnail_history()

        video_guard = enforce_thumbnail_diversity(
            channel_id=str(result.get("channel", "default")),
            content_type="video",
            slot=slot,
            topic=content.title,
            thumbnail_prompt=getattr(content, "thumbnail_prompt", "") or content.title,
            profile=visual_profile,
            recent_history=recent_history,
            publish_at=publish_at,
        )
        diversity_video_record = dict(video_guard.get("record") or {})
        content.thumbnail_prompt = diversity_video_record.get("thumbnail_prompt") or content.thumbnail_prompt
        thumbnail_experiments = build_thumbnail_experiment_bundle(
            channel_id=str(result.get("channel", "default")),
            content_type="video",
            slot=slot,
            topic=content.title,
            title=content.title,
            thumbnail_prompt=getattr(content, "thumbnail_prompt", "") or content.title,
            profile=visual_profile,
            recent_history=recent_history,
            publish_at=publish_at,
        )
        content.thumbnail_prompt = thumbnail_experiments.get("selected_prompt") or content.thumbnail_prompt
        result["thumbnail_diversity"] = {
            "video": {
                "accepted": bool(video_guard.get("accepted")),
                "regenerated": bool(video_guard.get("regenerated")),
                "attempts": int(video_guard.get("attempts") or 0),
                "rejected_attempts": video_guard.get("rejected_attempts") or [],
            }
        }
        result["thumbnail_experiments"] = {
            "experiment_id": resolved_experiment_id,
            "selected_variant_id": thumbnail_experiments.get("selected_variant_id"),
            "selected_prompt": thumbnail_experiments.get("selected_prompt"),
            "variants": [
                {
                    "variant_id": item.get("variant_id"),
                    "thumbnail_prompt": item.get("thumbnail_prompt"),
                    "thumbnail_attention_score": item.get("thumbnail_attention_score"),
                    "accepted": item.get("accepted"),
                    "regenerated": item.get("regenerated"),
                    "attempts": item.get("attempts"),
                }
                for item in thumbnail_experiments.get("variants", [])
            ],
        }
    except Exception:
        # Diversity guard is fail-open and must never block production runs.
        result.setdefault("thumbnail_diversity", {})
        result["thumbnail_diversity"]["video"] = {
            "accepted": False,
            "regenerated": False,
            "attempts": 0,
            "rejected_attempts": [],
        }
        result.setdefault("thumbnail_experiments", {})
        result["thumbnail_experiments"]["experiment_id"] = resolved_experiment_id

    try:
        result["analytics_join_metadata"] = build_analytics_join_metadata(
            content_id=result["content_id"],
            run_id=result["run_id"],
            channel_id=result.get("channel"),
            telemetry_metadata=telemetry_metadata,
            prompt_metadata=getattr(content, "prompt_metadata", None),
            channel_dna_metadata=getattr(content, "channel_dna_metadata", None),
            quality_score_metadata=getattr(content, "quality_score_metadata", None),
        )
    except Exception:
        result["analytics_join_metadata"] = {}

    try:
        result["editor_review_metadata"] = build_editor_review_metadata(
            title=getattr(content, "title", ""),
            description=getattr(content, "description", ""),
            script=getattr(content, "script", ""),
            tags=getattr(content, "tags", None),
        )
    except Exception:
        result["editor_review_metadata"] = {}

    if generate_only:
        logger.info("Sadece icerik uretme modu.")
        _refresh_observability_fields()
        return result

    # ── İÇERİK KALİTE KAPI (channel-topic fit + script freshness + metadata completeness) ─
    # Runs before TTS/render/upload so blocked content never enters the expensive render path.
    _cq_regeneration_count = 0
    def _run_content_quality_gate() -> None:
        nonlocal _cq_regeneration_count, content
        try:
            from .content_quality_guard import (
                MetadataBundle, evaluate_content_quality,
            )
        except ImportError:
            return  # guard not available — fail-open only on ImportError

        def _make_bundle() -> MetadataBundle:
            try:
                desc = content.seo_description()[:500]
            except Exception:
                desc = getattr(content, "description", "") or ""
            return MetadataBundle(
                title=getattr(content, "title", ""),
                description=desc,
                tags=list(getattr(content, "tags", []) or []),
                category_id=str(getattr(content, "category_id", "") or getattr(cfg, "category_id", "") or ""),
                script=getattr(content, "script", ""),
                thumbnail_prompt=getattr(content, "thumbnail_prompt", "") or "",
                niche=str(getattr(cfg, "niche", "") or ""),
                channel_id=str(result.get("channel", "")),
            )

        dec = evaluate_content_quality(
            _make_bundle(),
            getattr(content, "script", ""),
            topic or getattr(content, "title", ""),
            regeneration_count=_cq_regeneration_count,
        )
        result["content_quality"] = {
            "publish_decision": dec.publish_decision,
            "block_reasons": list(dec.block_reasons or []),
            "scores": dict(dec.scores or {}),
            "script_similarity": dec.script_similarity,
            "regeneration_count": _cq_regeneration_count,
        }
        if dec.publish_decision != "block":
            logger.info("[%s] Content quality gate: ALLOW", result.get("channel"))
            return

        if _cq_regeneration_count >= 1:
            logger.error(
                "[%s] Content quality gate BLOCK after regeneration: %s",
                result.get("channel"), dec.block_reasons,
            )
            raise RuntimeError(f"content_quality_blocked: {'; '.join(dec.block_reasons)}")

        logger.warning(
            "[%s] Content quality gate BLOCK (attempt 1) — regenerating: %s",
            result.get("channel"), dec.block_reasons,
        )
        _cq_regeneration_count += 1
        retry_guidance = (
            f"Previous content was blocked: {'; '.join((dec.block_reasons or ['quality check'])[:2])}. "
            "Generate a completely different topic and script that strictly matches the channel niche."
        )
        _generate_content(generator, generation_topic=None, additional_guidance=retry_guidance)
        # Second attempt
        dec2 = evaluate_content_quality(
            _make_bundle(),
            getattr(content, "script", ""),
            topic or getattr(content, "title", ""),
            regeneration_count=1,
        )
        if dec2.publish_decision == "block":
            logger.error(
                "[%s] Content quality gate BLOCK (final): %s",
                result.get("channel"), dec2.block_reasons,
            )
            raise RuntimeError(f"content_quality_blocked: {'; '.join(dec2.block_reasons)}")
        logger.info("[%s] Content quality gate: regenerated content ALLOW", result.get("channel"))

    if _content_quality_gate_enabled() or _production_quality_platform_enabled():
        _run_content_quality_gate()

    try:
        _run_fact_check_guard("tts", content.script, suppress_retryable_alert=True)
    except RuntimeError as error:
        reason = str(error)
        if _is_unverifiable_claim_failure(reason):
            logger.warning("Fact check unverifiable claim detected; regenerating content once with stricter guidance")
            result["fact_check_regeneration_attempted"] = True
            retry_topic = _build_retry_topic(topic, content.title, reason)
            retry_guidance = _build_retry_guidance(reason)
            result["fact_check_regeneration_topic"] = retry_topic
            _generate_content(
                generator,
                generation_topic=retry_topic,
                additional_guidance=retry_guidance,
            )
            _run_fact_check_guard("tts", content.script)
        else:
            raise

    # ─── ADIM 2: Sesli Anlatiom ────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info(f"ADIM 2/4 - Edge TTS [{result['channel']}]")
    logger.info("=" * 60)
    with _stage("tts", complete_payload_fn=lambda: {"audio_path": str(result.get("audio_path", ""))[:180]}):
        tts = TTSEngine(channel_cfg=cfg)
        audio_path = tts.generate_audio(content.script)
        result["audio_path"] = audio_path
        chain = getattr(tts, "last_tts_fallback_chain", None)
        if isinstance(chain, list) and chain:
            result["tts_fallback_chain"] = chain
        warning = getattr(tts, "last_tts_warning", None)
        if isinstance(warning, dict) and warning:
            result["tts_warning"] = warning

    # ─── ADIM 2.5: Stok Video Klipleri + Grafik ──────────────────────────────
    logger.info("Pexels video klipleri indiriliyor...")
    with _stage("media_fetch", complete_payload_fn=lambda: {"media_count": len(image_paths)}):
        fetcher = ImageFetcher(channel_cfg=cfg)
        from datetime import datetime as _dt
        media_dir = f"{cfg.output_dir}/clips/{_dt.now().strftime('%Y%m%d_%H%M%S')}"

        # İçerikten gelen özgün Pexels sorgusu varsa kullan, yoksa kanal default'u
        pexels_query = getattr(content, "pexels_search", None) or getattr(cfg, "pexels_query", None)

        # Storyblocks (premium) varsa önce dene, yoksa Pexels kullan
        image_paths = []
        try:
            from .premium_services import has_storyblocks, fetch_storyblocks_clips
            if has_storyblocks():
                image_paths = fetch_storyblocks_clips(
                    pexels_query or content.title, count=4, output_dir=media_dir
                )
                if image_paths:
                    logger.info(f"Storyblocks: {len(image_paths)} premium klip")
        except Exception as e:
            logger.warning(f"Storyblocks atlandı: {e}")

        if not image_paths:
            image_paths = fetcher.fetch_video_clips(
                content.title, count=4, output_dir=media_dir, query_override=pexels_query
            )

        # Finansal grafik üret — video ortasına (değişken pozisyon) ekle
        chart_path = None
        try:
            from .chart_generator import generate_chart, generate_placeholder_chart
            chart_data = getattr(content, "chart_data", None)
            chart_out = f"{media_dir}/chart.png"
            if chart_data and isinstance(chart_data, dict) and chart_data.get("type"):
                chart_path = generate_chart(chart_data, chart_out)
            else:
                chart_path = generate_placeholder_chart(content.title, chart_out)
            if chart_path and image_paths:
                # Grafiği kliplerin ortasına veya 1/3'üne yerleştir (ilk kare değil)
                insert_pos = max(1, len(image_paths) // 2)
                image_paths.insert(insert_pos, chart_path)
                logger.info(f"Grafik pozisyon {insert_pos}'e eklendi: {chart_path}")
            elif chart_path:
                image_paths = [chart_path]
        except Exception as e:
            logger.warning(f"Grafik oluşturulamadı: {e}")

        result["selected_visuals"] = [str(item) for item in (image_paths or [])]

        if _production_quality_platform_enabled():
            _qa_regeneration_count = 0
            while True:
                qa_payload = {
                    "channel": result.get("channel"),
                    "niche": getattr(cfg, "niche", ""),
                    "topic": topic or getattr(content, "title", ""),
                    "title": getattr(content, "title", ""),
                    "script": getattr(content, "script", ""),
                    "description": getattr(content, "description", ""),
                    "tags": list(getattr(content, "tags", []) or []),
                    "thumbnail_prompt": getattr(content, "thumbnail_prompt", ""),
                    "selected_visuals": result.get("selected_visuals") or [],
                    "rejection_reasons": result.get("rejection_reasons") or [],
                    "script_similarity": ((result.get("content_quality") or {}).get("script_similarity", 0.0)),
                    "shorts_enabled": True,
                }
                automatic_qa = evaluate_automatic_qa(qa_payload)
                result["automatic_qa"] = automatic_qa
                if automatic_qa.get("decision") != "block":
                    break
                if _qa_regeneration_count >= 1:
                    raise RuntimeError(f"automatic_qa_blocked: {', '.join(automatic_qa.get('blocked_checks') or [])}")
                _qa_regeneration_count += 1
                result["pipeline_retry_count"] = int(result.get("pipeline_retry_count", 0)) + 1
                retry_guidance = (
                    "Production QA blocked previous output. Regenerate with stronger channel-topic fit, "
                    "clean metadata consistency, and a clearly relevant thumbnail concept."
                )
                _generate_content(generator, generation_topic=topic, additional_guidance=retry_guidance)

    # ─── ADIM 3: Video Montaji ────────────────────────────────────────────────
    _run_fact_check_guard("render", content.script)
    logger.info("=" * 60)
    logger.info(f"ADIM 3/4 - Video Montaji [{result['channel']}]")
    logger.info("=" * 60)
    render_started_at = None
    with _stage("render", complete_payload_fn=lambda: {"video_path": str(result.get("video_path", ""))[:180]}):
        render_started_at = datetime.now(timezone.utc)
        creator = VideoCreator(channel_cfg=cfg)
        video_path = creator.create_video(
            audio_path, content.title,
            image_paths=image_paths or None,
            script=content.script,
        )
        _attach_audio_mix_metadata(result, creator)
        _standardize_audio_mix_metadata(mix=result.get("audio_mix"), scope="video")
        # Thumbnail için konuya özel ayrı fotoğraf çek (video klipten farklı)
        try:
            thumb_bg = None
            # Öncelik: DALL-E 3 (varsa) → Pexels foto → Pexels video frame
            from .premium_services import has_dalle, generate_dalle_thumbnail
            if has_dalle():
                dalle_prompt = getattr(content, "thumbnail_prompt", content.title)
                dalle_path = f"{cfg.videos_dir}/thumb_dalle_{__import__('uuid').uuid4().hex[:8]}.jpg"
                thumb_bg = generate_dalle_thumbnail(dalle_prompt, dalle_path)
                if thumb_bg:
                    logger.info("DALL-E 3 thumbnail kullanılıyor")
            if not thumb_bg:
                thumb_bg = fetcher.fetch_thumbnail_photo(content.title)
            if not thumb_bg:
                thumb_bg = image_paths[0] if image_paths else None
        except Exception:
            thumb_bg = image_paths[0] if image_paths else None
        thumbnail_path = creator.create_thumbnail(content.title, image_path=thumb_bg)
        result["video_path"] = video_path
        result["thumbnail_path"] = thumbnail_path
        _attach_thumbnail_experiment_binding_metadata(thumbnail_path=thumbnail_path)
        _attach_thumbnail_validation_metadata(
            content_type="video",
            thumbnail_path=thumbnail_path,
            variant_id=str(thumbnail_experiments.get("selected_variant_id") or "video_default"),
            rejected_attempts=((result.get("thumbnail_diversity") or {}).get("video", {}).get("rejected_attempts") or []),
        )
        _run_shadow_checkpoint(
            checkpoint="thumbnail_metadata",
            thumbnail_text=_derive_thumbnail_text(getattr(content, "title", "")),
        )

    try:
        from .thumbnail_history import load_recent_thumbnail_history

        recent_prompts = []
        for item in load_recent_thumbnail_history():
            prompt = str(item.get("thumbnail_prompt") or "").strip()
            if prompt:
                recent_prompts.append(prompt)
        thumbnail_intelligence = evaluate_thumbnail_intelligence(
            channel_id=str(result.get("channel", "default")),
            topic=str(topic or getattr(content, "title", "")),
            thumbnail_prompt=str(getattr(content, "thumbnail_prompt", "") or ""),
            rejection_reasons=list(result.get("rejection_reasons") or []),
            recent_thumbnail_prompts=recent_prompts[-120:],
            ctr_evidence={
                "click_through_rate": ((result.get("performance_snapshot") or {}).get("click_through_rate")),
            },
        )
        result["thumbnail_intelligence"] = thumbnail_intelligence
    except Exception:
        pass

    try:
        from .thumbnail_history import append_thumbnail_history

        if diversity_video_record:
            entry = {
                "channel_id": str(result.get("channel", "default")),
                "content_type": "video",
                "slot": slot,
                "topic": content.title,
                "thumbnail_prompt": diversity_video_record.get("thumbnail_prompt", getattr(content, "thumbnail_prompt", "")),
                "visual_style": diversity_video_record.get("visual_style", ""),
                "main_subject": diversity_video_record.get("main_subject", ""),
                "background": diversity_video_record.get("background", ""),
                "color_palette": diversity_video_record.get("color_palette", ""),
                "camera_angle": diversity_video_record.get("camera_angle", ""),
                "mood": diversity_video_record.get("mood", ""),
                "fingerprint": diversity_video_record.get("fingerprint", ""),
                "day": diversity_video_record.get("day", datetime.now(timezone.utc).date().isoformat()),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            append_thumbnail_history(entry)
    except Exception:
        pass

    try:
        render_finished_at = datetime.now(timezone.utc)
        result["render_metrics"] = build_render_metrics(
            render_started_at=render_started_at or render_finished_at,
            render_finished_at=render_finished_at,
            render_status="completed",
            output_resolution=f"{getattr(cfg, 'video_width', 1920)}x{getattr(cfg, 'video_height', 1080)}",
            output_fps=24,
        )
        result["render_metrics"]["experiment_id"] = resolved_experiment_id
    except Exception as e:
        result["render_metrics"] = {}
        warning = _record_warning(
            "metrics_warning",
            code="render_metrics_build_failed",
            message="Render metrics build failed; pipeline continued.",
            extra={"error_type": e.__class__.__name__},
        )
        logger.warning(
            "Metrics fail-open: code=%s error_type=%s count=%s",
            warning.get("code"),
            warning.get("error_type"),
            warning.get("count"),
        )

    # ─── ADIM 3.5: YouTube Short ──────────────────────────────────────────────
    _emit("shorts_render", "stage_started")
    short_path = None
    short_render_error = None
    for short_attempt in range(1, 3):  # 2 deneme hakkı
        try:
            logger.info(f"YouTube Short oluşturuluyor (deneme {short_attempt})...")
            from .shorts_creator import ShortsCreator
            sc = ShortsCreator(channel_cfg=cfg)
            short_path = sc.create_short(
                script=content.script,
                title=content.title,
                hook=content.hook,
                image_paths=image_paths[:2] if image_paths else None,  # 2 clip: RAM tasarrufu
            )
            result["short_path"] = short_path
            short_mix = getattr(sc, "last_audio_mix_metadata", None)
            if isinstance(short_mix, dict) and short_mix:
                result["short_audio_mix"] = short_mix
                _standardize_audio_mix_metadata(mix=short_mix, scope="short")
            logger.info(f"Short hazır: {short_path}")
            break
        except Exception as e:
            logger.warning(f"Short oluşturulamadı (deneme {short_attempt}/2): {e}")
            if short_attempt == 2:
                short_render_error = e
                logger.error(f"Short kalıcı olarak başarısız: {e}")
    if result.get("short_path"):
        _emit("shorts_render", "stage_completed", {"short_created": True})
    else:
        if short_render_error is not None:
            _emit("shorts_render", "stage_failed", {"error": str(short_render_error)[:300]})
        else:
            _emit("shorts_render", "stage_failed", {"error": "short_not_created"})

    if shadow_engine:
        short_text = ""
        short_duration_seconds = 0.0
        try:
            from .shorts_creator import _extract_short_script

            short_text = _extract_short_script(str(getattr(content, "script", "") or ""), str(getattr(content, "hook", "") or ""))
            short_duration_seconds = 58.0 if result.get("short_path") else 0.0
        except Exception:
            short_text = ""
            short_duration_seconds = 0.0
        _run_shadow_checkpoint(
            checkpoint="shorts",
            short_script=short_text,
            short_title=f"{str(getattr(content, 'title', '') or '')} #Shorts".strip(),
            short_duration_seconds=short_duration_seconds,
        )

    # ─── ADIM 4: YouTube Yukleme ──────────────────────────────────────────────
    _run_fact_check_guard("upload", content.script)
    logger.info("=" * 60)
    logger.info(f"ADIM 4/4 - YouTube [{result['channel']}]")
    logger.info("=" * 60)
    uploader = YouTubeUploader(channel_cfg=cfg)
    upload_error = None
    idempotency_key = build_idempotency_key(
        channel=str(result.get("channel", "default")),
        generation_id=str(result.get("content_id", "")),
        publish_at=publish_at,
        title=str(getattr(content, "title", "")),
    )
    ownership_manifest_path = persist_ownership_manifest(
        channel_id=str(result.get("channel", "")),
        content_id=str(result.get("content_id", "")),
        run_id=str(result.get("run_id", "")),
        niche=str(getattr(cfg, "niche", "")),
        title=str(getattr(content, "title", "")),
        topic=str(topic or getattr(content, "title", "")),
        script=str(getattr(content, "script", "")),
        script_path=str(result.get("script_path", "")),
        video_path=str(video_path),
        thumbnail_path=str(thumbnail_path) if thumbnail_path else None,
    )
    precheck = evaluate_upload_precheck(
        channel_id=str(result.get("channel", "")),
        content_id=str(result.get("content_id", "")),
        run_id=str(result.get("run_id", "")),
        niche=str(getattr(cfg, "niche", "")),
        title=str(getattr(content, "title", "")),
        topic=str(topic or getattr(content, "title", "")),
        script=str(getattr(content, "script", "")),
        script_path=str(result.get("script_path", "")),
        video_path=str(video_path),
        thumbnail_path=str(thumbnail_path) if thumbnail_path else None,
        manifest_path=ownership_manifest_path,
    )
    result["upload_precheck"] = precheck
    if precheck.get("status") == "blocked":
        result["upload_metadata"] = {
            "experiment_id": resolved_experiment_id,
            "video_id": None,
            "privacy": privacy,
            "publish_at": publish_at,
            "idempotency_key": idempotency_key,
            "ownership_manifest_path": str(ownership_manifest_path or ""),
            "precheck_blocked": True,
            "guard_reason_codes": list(precheck.get("guard_reason_codes") or []),
        }
        _emit(
            "upload",
            "stage_failed",
            {
                "error": "upload_precheck_blocked",
                "guard_reason_codes": list(precheck.get("guard_reason_codes") or []),
            },
        )
        logger.error("Upload precheck blocked: %s", precheck)
    else:
        try:
            with _stage(
                "upload",
                start_payload={"privacy": privacy, "publish_at": publish_at},
                complete_payload_fn=lambda: {"video_id": str(result.get("video_id", ""))},
            ):
                existing_upload = get_registered_upload(idempotency_key)
                if existing_upload and str(existing_upload.get("video_id") or "").strip():
                    video_id = str(existing_upload.get("video_id"))
                    result["upload_metadata"] = {
                        "experiment_id": resolved_experiment_id,
                        "video_id": video_id,
                        "privacy": privacy,
                        "publish_at": publish_at,
                        "idempotency_key": idempotency_key,
                          "ownership_manifest_path": str(ownership_manifest_path),
                        "duplicate_prevented": True,
                    }
                else:
                    def _upload_once():
                        return uploader.upload_video(
                            video_path=video_path,
                            content=content,
                            thumbnail_path=thumbnail_path,
                            privacy=privacy,
                            publish_at=publish_at,
                        )

                    def _on_upload_retry(attempt: int, _exc: Exception) -> None:
                        result["upload_retry_count"] = int(result.get("upload_retry_count", 0)) + 1

                    video_id, recovery = run_stage_with_recovery(
                        stage="upload",
                        fn=_upload_once,
                        max_attempts=1,
                        base_backoff_seconds=4.0,
                        on_retry=_on_upload_retry,
                    )
                    if not str(video_id or "").strip():
                        raise RuntimeError("upload_response_missing_id")
                    result["upload_recovery"] = recovery
                    register_upload(
                        idempotency_key,
                        {
                            "video_id": video_id,
                            "channel": result.get("channel"),
                            "title": getattr(content, "title", ""),
                            "youtube_url": f"https://youtube.com/watch?v={video_id}",
                        },
                    )
                result["video_id"] = video_id
                result["youtube_url"] = f"https://youtube.com/watch?v={video_id}"
                result["upload_metadata"] = {
                    "experiment_id": resolved_experiment_id,
                    "video_id": video_id,
                    "privacy": privacy,
                    "publish_at": publish_at,
                    "idempotency_key": idempotency_key,
                      "ownership_manifest_path": str(ownership_manifest_path),
                }
                # Register script fingerprint ONLY after confirmed upload
                try:
                    from .content_quality_guard import register_published_script
                    register_published_script(
                        channel_id=str(result.get("channel", "")),
                        video_id=video_id,
                        title=getattr(content, "title", ""),
                        topic=topic or getattr(content, "title", ""),
                        script=getattr(content, "script", ""),
                    )
                except Exception as _reg_exc:
                    logger.debug("Script fingerprint registration failed (non-critical): %s", _reg_exc)
                try:
                    result["youtube_channel_stats"] = uploader.get_channel_stats()
                except Exception:
                    result["youtube_channel_stats"] = {}
        except Exception as e:
            upload_error = e
            result["upload_error"] = str(e)
            failure_kind = _classify_upload_failure(str(e))
            result["upload_metadata"] = {
                "experiment_id": resolved_experiment_id,
                "video_id": None,
                "privacy": privacy,
                "publish_at": publish_at,
                "error": str(e),
                "failure_kind": failure_kind,
                  "ownership_manifest_path": str(ownership_manifest_path),
            }
            logger.error(
                "Upload başarısız, snapshot yine kaydedilecek: %s (failure_kind=%s)",
                e,
                failure_kind,
            )

    # ─── ADIM 4.5: Short Yukle ────────────────────────────────────────────────
    _emit("shorts_upload", "stage_started")
    shorts_upload_error = None
    short_upload_skipped_reason = None
    if upload_error:
        short_upload_skipped_reason = "main_upload_failed"
    elif result.get("upload_precheck", {}).get("status") == "blocked":
        short_upload_skipped_reason = "main_upload_blocked"
    elif result.get("short_path"):
        try:
            from .content_generator import VideoContent as VC
            from .thumbnail_history import append_thumbnail_history, load_recent_thumbnail_history
            from .visual_diversity import enforce_thumbnail_diversity
            from .channel_visual_profiles import get_channel_visual_profile

            short_title = (content.title + " #Shorts")[:100]  # BUG FIX: parantez doğru yerde
            short_slot = slot
            short_thumbnail_path = thumbnail_path

            try:
                short_profile = get_channel_visual_profile(
                    str(result.get("channel", "default")),
                    niche=getattr(content, "niche", ""),
                )
                short_guard = enforce_thumbnail_diversity(
                    channel_id=str(result.get("channel", "default")),
                    content_type="short",
                    slot=short_slot,
                    topic=short_title,
                    thumbnail_prompt=getattr(content, "thumbnail_prompt", short_title),
                    profile=short_profile,
                    recent_history=load_recent_thumbnail_history(),
                    publish_at=publish_at,
                )
                diversity_short_record = dict(short_guard.get("record") or {})
                if "thumbnail_diversity" not in result:
                    result["thumbnail_diversity"] = {}
                result["thumbnail_diversity"]["short"] = {
                    "accepted": bool(short_guard.get("accepted")),
                    "regenerated": bool(short_guard.get("regenerated")),
                    "attempts": int(short_guard.get("attempts") or 0),
                    "rejected_attempts": short_guard.get("rejected_attempts") or [],
                }

                # Build a distinct thumbnail for short to avoid same-day concept overlap.
                short_thumb_bg = None
                try:
                    from .premium_services import has_dalle, generate_dalle_thumbnail
                    if has_dalle():
                        short_prompt = diversity_short_record.get("thumbnail_prompt") or short_title
                        short_dalle_path = f"{cfg.videos_dir}/thumb_short_dalle_{__import__('uuid').uuid4().hex[:8]}.jpg"
                        short_thumb_bg = generate_dalle_thumbnail(short_prompt, short_dalle_path)
                except Exception:
                    short_thumb_bg = None

                if not short_thumb_bg:
                    if image_paths:
                        short_thumb_bg = image_paths[-1]
                    else:
                        short_thumb_bg = thumb_bg

                short_thumbnail_path = creator.create_thumbnail(short_title, image_path=short_thumb_bg)
            except Exception:
                short_thumbnail_path = thumbnail_path

            _attach_thumbnail_validation_metadata(
                content_type="short",
                thumbnail_path=short_thumbnail_path,
                variant_id="short_default",
                rejected_attempts=((result.get("thumbnail_diversity") or {}).get("short", {}).get("rejected_attempts") or []),
            )

            short_content = VC(
                title=short_title,
                description=content.seo_description()[:5000],
                tags=content.tags + ["Shorts", "YouTube Shorts"],
                script=content.script,
                thumbnail_prompt=(
                    diversity_short_record.get("thumbnail_prompt")
                    if isinstance(diversity_short_record, dict)
                    else content.thumbnail_prompt
                ),
                category_id=content.category_id,
                niche=content.niche,
            )
            short_id = uploader.upload_video(
                video_path=result["short_path"],
                content=short_content,
                thumbnail_path=short_thumbnail_path,
                privacy="public",
                publish_at=None,
            )
            if not str(short_id or "").strip():
                raise RuntimeError("short_upload_missing_video_id")
            result["short_video_id"] = str(short_id)
            result["short_url"] = f"https://youtube.com/shorts/{short_id}"
            result["short_thumbnail_path"] = short_thumbnail_path

            if diversity_short_record:
                append_thumbnail_history(
                    {
                        "channel_id": str(result.get("channel", "default")),
                        "content_type": "short",
                        "slot": short_slot,
                        "topic": short_title,
                        "thumbnail_prompt": diversity_short_record.get("thumbnail_prompt", short_content.thumbnail_prompt),
                        "visual_style": diversity_short_record.get("visual_style", ""),
                        "main_subject": diversity_short_record.get("main_subject", ""),
                        "background": diversity_short_record.get("background", ""),
                        "color_palette": diversity_short_record.get("color_palette", ""),
                        "camera_angle": diversity_short_record.get("camera_angle", ""),
                        "mood": diversity_short_record.get("mood", ""),
                        "fingerprint": diversity_short_record.get("fingerprint", ""),
                        "day": diversity_short_record.get("day", datetime.now(timezone.utc).date().isoformat()),
                        "created_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
            logger.info(f"Short yuklendi: {result['short_url']}")
        except Exception as e:
            shorts_upload_error = e
            logger.error(f"Short yuklenemedi: {e}")
    if result.get("short_path"):
        if short_upload_skipped_reason:
            _emit("shorts_upload", "stage_completed", {"short_uploaded": False, "skipped": True, "reason": short_upload_skipped_reason})
        elif result.get("short_url"):
            _emit("shorts_upload", "stage_completed", {"short_uploaded": True})
        else:
            _emit(
                "shorts_upload",
                "stage_failed",
                {"error": str(shorts_upload_error)[:300] if shorts_upload_error else "short_upload_failed"},
            )
    else:
        _emit("shorts_upload", "stage_completed", {"short_uploaded": False, "skipped": True})

    if shadow_engine:
        try:
            from .shadow_content_quality import infer_playlist_recommendation_from_title

            playlist_reco = infer_playlist_recommendation_from_title(str(getattr(content, "title", "") or ""))
        except Exception:
            playlist_reco = None
        _run_shadow_checkpoint(
            checkpoint="seo_discovery",
            description=str(getattr(content, "description", "") or ""),
            tags=list(getattr(content, "tags", []) or []),
            playlist_recommendation=playlist_reco,
            card_recommendation=None,
            end_screen_recommendation=None,
        )

    try:
        performance_snapshot = build_performance_snapshot(
            channel_id=str(result.get("channel", "default")),
            content_id=result["content_id"],
            run_id=result["run_id"],
            title=getattr(content, "title", ""),
            youtube_url=result.get("youtube_url"),
            short_url=result.get("short_url"),
            video_id=result.get("video_id"),
            short_video_id=result.get("short_video_id"),
            publish_at=publish_at,
            thumbnail_path=result.get("thumbnail_path"),
            thumbnail_strategy=telemetry_metadata.get("thumbnail_strategy"),
            render_metrics=result.get("render_metrics"),
            analytics_join_metadata=result.get("analytics_join_metadata"),
            quality_score_metadata=getattr(content, "quality_score_metadata", None),
            youtube_stats=result.get("youtube_channel_stats"),
            youtube_analytics=result.get("youtube_analytics", {}),
        )
        performance_snapshot["experiment_id"] = resolved_experiment_id
        result["performance_snapshot"] = performance_snapshot
    except Exception as e:
        result["performance_snapshot"] = {}
        warning = _record_warning(
            "metrics_warning",
            code="performance_snapshot_build_failed",
            message="Performance snapshot build failed; pipeline continued.",
            extra={"error_type": e.__class__.__name__},
        )
        logger.warning(
            "Metrics fail-open: code=%s error_type=%s count=%s",
            warning.get("code"),
            warning.get("error_type"),
            warning.get("count"),
        )
    else:
        snapshot_valid, snapshot_issues = _validate_performance_snapshot(performance_snapshot)
        if not snapshot_valid:
            warning = _record_warning(
                "analytics_warning",
                code="performance_snapshot_validation_failed",
                message="Performance snapshot validation failed; append skipped.",
                extra=snapshot_issues,
            )
            logger.warning(
                "Analytics fail-open: code=%s missing=%s invalid=%s count=%s",
                warning.get("code"),
                ",".join(warning.get("missing_fields", []) or []) or "-",
                ",".join(warning.get("invalid_fields", []) or []) or "-",
                warning.get("count"),
            )
            result.setdefault("performance_snapshot_append_skipped", True)
        else:
            try:
                append_performance_snapshot(performance_snapshot)
            except Exception as e:
                warning = _record_warning(
                    "metrics_warning",
                    code="performance_snapshot_append_failed",
                    message="Performance snapshot append failed; pipeline continued.",
                    extra={"error_type": e.__class__.__name__},
                )
                logger.warning(
                    "Metrics fail-open: code=%s error_type=%s count=%s",
                    warning.get("code"),
                    warning.get("error_type"),
                    warning.get("count"),
                )

    logger.info("=" * 60)
    if result.get("video_id"):
        logger.info(f"✅ TAMAMLANDI! Video: {result.get('youtube_url')}")
    else:
        logger.error("❌ TAMAMLANAMADI: geçerli video_id oluşmadı")
    if result.get("short_url"):
        logger.info(f"✅ Short: {result['short_url']}")
    logger.info("=" * 60)

    result["topic"] = topic or getattr(content, "title", "")
    result["script"] = getattr(content, "script", "")
    result["description"] = getattr(content, "description", "")
    result["tags"] = list(getattr(content, "tags", []) or [])
    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    if result.get("video_id"):
        result["final_status"] = "success"
    elif result.get("upload_precheck", {}).get("status") == "blocked":
        result["final_status"] = "blocked"
    elif result.get("upload_error"):
        result["final_status"] = "failed"
    else:
        result["final_status"] = "blocked"

    try:
        write_production_evidence(result)
    except Exception:
        pass
    try:
        update_production_observability_latest()
        update_production_dashboard(
            scheduler_status="pipeline_run",
            build_sha=str(result.get("build_sha") or "unknown"),
            scheduler_pid=result.get("scheduler_pid"),
            last_error=result.get("upload_error"),
        )
    except Exception:
        pass

    _refresh_observability_fields()
    return result
