"""
Tam Otomasyon Pipeline - Tek ve Cok Kanalli Mod
"""
import logging
import os
from pathlib import Path

from .config import config as _default_config
from .content_generator import ContentGenerator, VideoContent
from .image_fetcher import ImageFetcher
from .tts_engine import TTSEngine
from .video_creator_pro import VideoCreator
from .youtube_uploader import YouTubeUploader

logger = logging.getLogger(__name__)


def run_full_pipeline(
    topic: str | None = None,
    generate_only: bool = False,
    privacy: str = os.getenv("DEFAULT_PRIVACY", "public"),
    channel_cfg=None,
    publish_at: str | None = None,
) -> dict:
    """Tam pipeline: icerik -> ses -> video -> YouTube yukle."""
    # Aktif config belirle
    cfg = channel_cfg if channel_cfg else _default_config
    cfg.ensure_directories()
    result = {"channel": getattr(cfg, "channel_id", "default")}

    # ─── ADIM 1: Icerik Uretimi ────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info(f"ADIM 1/4 - Icerik Uretimi [{result['channel']}]")
    logger.info("=" * 60)
    generator = ContentGenerator(channel_cfg=cfg)
    content: VideoContent = generator.generate_and_save(topic)
    result["title"] = content.title
    result["script_path"] = f"{cfg.scripts_dir}/{content.created_at[:10]}_{content.title[:30]}.json"

    if generate_only:
        logger.info("Sadece icerik uretme modu.")
        return result

    # ─── ADIM 2: Sesli Anlatiom ────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info(f"ADIM 2/4 - Edge TTS [{result['channel']}]")
    logger.info("=" * 60)
    tts = TTSEngine(channel_cfg=cfg)
    audio_path = tts.generate_audio(content.script)
    result["audio_path"] = audio_path

    # ─── ADIM 2.5: Stok Video Klipleri + Grafik ──────────────────────────────
    logger.info("Pexels video klipleri indiriliyor...")
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
    logger.info("=" * 60)
    logger.info(f"ADIM 3/4 - Video Montaji [{result['channel']}]")
    logger.info("=" * 60)
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

    # ─── ADIM 3.5: YouTube Short ──────────────────────────────────────────────
    short_path = None
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
                logger.error(f"Short kalıcı olarak başarısız: {e}")

    # ─── ADIM 4: YouTube Yukleme ──────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info(f"ADIM 4/4 - YouTube [{result['channel']}]")
    logger.info("=" * 60)
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
    if result.get("short_path"):
        try:
            from .content_generator import VideoContent as VC
            short_title = (content.title + " #Shorts")[:100]  # BUG FIX: parantez doğru yerde
            short_content = VC(
                title=short_title,
                description=content.seo_description()[:5000],
                tags=content.tags + ["Shorts", "YouTube Shorts"],
                script=content.script,
                thumbnail_prompt=content.thumbnail_prompt,
                category_id=content.category_id,
                niche=content.niche,
            )
            short_id = uploader.upload_video(
                video_path=result["short_path"],
                content=short_content,
                thumbnail_path=thumbnail_path,
                privacy="public",
                publish_at=None,
            )
            result["short_url"] = f"https://youtube.com/shorts/{short_id}"
            logger.info(f"Short yuklendi: {result['short_url']}")
        except Exception as e:
            logger.error(f"Short yuklenemedi: {e}")

    logger.info("=" * 60)
    logger.info(f"✅ TAMAMLANDI! Video: {result['youtube_url']}")
    if result.get("short_url"):
        logger.info(f"✅ Short: {result['short_url']}")
    logger.info("=" * 60)

    return result
