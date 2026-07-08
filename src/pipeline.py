"""
Tam Otomasyon Pipeline - Tek ve Cok Kanalli Mod
"""
import logging
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .config import config as _default_config
from .content_generator import ContentGenerator, VideoContent
from .editor_review import build_editor_review_metadata
from .fact_sources import build_default_fact_provider
from .factual_freshness import FactCheckFailed, validate_script_factual_freshness
from .image_fetcher import ImageFetcher
from .analytics_join import build_analytics_join_metadata
from .render_metrics import build_render_metrics
from .telemetry import (
    build_event_envelope,
    emit_event,
    generate_content_id,
    generate_run_id,
)
from .tts_engine import TTSEngine
from .video_creator_pro import VideoCreator
from .youtube_uploader import YouTubeUploader

logger = logging.getLogger(__name__)


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


def run_full_pipeline(
    topic: str | None = None,
    generate_only: bool = False,
    privacy: str = os.getenv("DEFAULT_PRIVACY", "public"),
    channel_cfg=None,
    publish_at: str | None = None,
    posting_slot: str | None = None,
) -> dict:
    """Tam pipeline: icerik -> ses -> video -> YouTube yukle."""
    # Aktif config belirle
    cfg = channel_cfg if channel_cfg else _default_config
    cfg.ensure_directories()
    result = {"channel": getattr(cfg, "channel_id", "default")}
    slot = posting_slot or _resolve_posting_slot(publish_at)
    result["slot"] = slot
    result["content_id"] = generate_content_id()
    result["run_id"] = generate_run_id()

    telemetry_metadata = {
        "experiment_id": os.getenv("EXPERIMENT_ID"),
        "experiment_group": os.getenv("EXPERIMENT_GROUP"),
        "prompt_version": getattr(cfg, "prompt_version", None) or os.getenv("PROMPT_VERSION"),
        "channel_dna_version": getattr(cfg, "channel_dna_version", None) or os.getenv("CHANNEL_DNA_VERSION"),
        "thumbnail_strategy": getattr(cfg, "thumbnail_strategy", None) or os.getenv("THUMBNAIL_STRATEGY"),
        "tts_strategy": getattr(cfg, "tts_strategy", None) or os.getenv("TTS_STRATEGY"),
        "model_version": os.getenv("MODEL_VERSION"),
    }

    def _emit(stage: str, event_type: str, payload: dict | None = None):
        try:
            envelope = build_event_envelope(
                content_id=result["content_id"],
                run_id=result["run_id"],
                channel_id=result.get("channel"),
                stage=stage,
                event_type=event_type,
                payload=payload or {},
                experiment_id=telemetry_metadata.get("experiment_id"),
                experiment_group=telemetry_metadata.get("experiment_group"),
                prompt_version=telemetry_metadata.get("prompt_version"),
                channel_dna_version=telemetry_metadata.get("channel_dna_version"),
                thumbnail_strategy=telemetry_metadata.get("thumbnail_strategy"),
                tts_strategy=telemetry_metadata.get("tts_strategy"),
                model_version=telemetry_metadata.get("model_version"),
            )
            emit_event(envelope, logger=logger)
        except Exception:
            # Telemetry must be fail-open and never affect production flow.
            pass

    fact_provider = build_default_fact_provider()
    fact_check_metadata: dict | None = None

    def _telegram_fact_check_alert(message: str):
        try:
            from .scheduler_utils import send_telegram

            send_telegram(message)
        except Exception:
            pass

    def _run_fact_check_guard(before_stage: str, script: str):
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
            _telegram_fact_check_alert(
                "🚫 <b>Fact Check FAIL</b>\n"
                f"📺 Kanal: {result.get('channel', 'default')}\n"
                f"⛔ Aşama öncesi: {before_stage}\n"
                f"🧾 Sebep: {reason[:250]}"
            )
            raise RuntimeError(f"failed_fact_check: {reason}") from e

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
        generator = ContentGenerator(channel_cfg=cfg)
        telemetry_metadata["model_version"] = telemetry_metadata.get("model_version") or getattr(generator, "model", None)
        content: VideoContent = generator.generate_and_save(topic)
        result["title"] = content.title
        result["script_path"] = f"{cfg.scripts_dir}/{content.created_at[:10]}_{content.title[:30]}.json"

    diversity_video_record = None
    diversity_short_record = None
    try:
        from .channel_visual_profiles import get_channel_visual_profile
        from .thumbnail_history import load_recent_thumbnail_history
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
        result["thumbnail_diversity"] = {
            "video": {
                "accepted": bool(video_guard.get("accepted")),
                "regenerated": bool(video_guard.get("regenerated")),
                "attempts": int(video_guard.get("attempts") or 0),
                "rejected_attempts": video_guard.get("rejected_attempts") or [],
            }
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
        return result

    _run_fact_check_guard("tts", content.script)

    # ─── ADIM 2: Sesli Anlatiom ────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info(f"ADIM 2/4 - Edge TTS [{result['channel']}]")
    logger.info("=" * 60)
    with _stage("tts", complete_payload_fn=lambda: {"audio_path": str(result.get("audio_path", ""))[:180]}):
        tts = TTSEngine(channel_cfg=cfg)
        audio_path = tts.generate_audio(content.script)
        result["audio_path"] = audio_path

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
    except Exception:
        result["render_metrics"] = {}

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

    # ─── ADIM 4: YouTube Yukleme ──────────────────────────────────────────────
    _run_fact_check_guard("upload", content.script)
    logger.info("=" * 60)
    logger.info(f"ADIM 4/4 - YouTube [{result['channel']}]")
    logger.info("=" * 60)
    with _stage(
        "upload",
        start_payload={"privacy": privacy, "publish_at": publish_at},
        complete_payload_fn=lambda: {"video_id": str(result.get("video_id", ""))},
    ):
        uploader = YouTubeUploader(channel_cfg=cfg)
        video_id = uploader.upload_video(
            video_path=video_path,
            content=content,
            thumbnail_path=thumbnail_path,
            privacy=privacy,
            publish_at=publish_at,
        )
        result["video_id"] = video_id
        result["youtube_url"] = f"https://youtube.com/watch?v={video_id}"

    # ─── ADIM 4.5: Short Yukle ────────────────────────────────────────────────
    _emit("shorts_upload", "stage_started")
    shorts_upload_error = None
    if result.get("short_path"):
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
        if result.get("short_url"):
            _emit("shorts_upload", "stage_completed", {"short_uploaded": True})
        else:
            _emit(
                "shorts_upload",
                "stage_failed",
                {"error": str(shorts_upload_error)[:300] if shorts_upload_error else "short_upload_failed"},
            )
    else:
        _emit("shorts_upload", "stage_completed", {"short_uploaded": False, "skipped": True})

    logger.info("=" * 60)
    logger.info(f"✅ TAMAMLANDI! Video: {result['youtube_url']}")
    if result.get("short_url"):
        logger.info(f"✅ Short: {result['short_url']}")
    logger.info("=" * 60)

    return result
