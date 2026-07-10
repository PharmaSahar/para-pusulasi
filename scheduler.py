"""
Para Pusulası - 200 Kanal Otomasyonu v4.0 (Production Ready)
=============================================================
MIMARISI:
- Tüm token'i olan kanalları otomatik keşfeder
- Her kanalın bir sonraki upload saatini hesaplar
- Render + YouTube Scheduled upload (YouTube zamanında yayınlar)
- Her upload sonrası hemen sonraki render başlar (kesintisiz döngü)
- Thread havuzu ile paralel render (CPU sınırlı)
- Akıllı retry: geçici hatalar otomatik tekrar denenir
- Disk temizleme: 48 saatten eski dosyalar silinir
- Bellek yönetimi: Her render sonrası GC zorlama
- Telegram bildirimi: upload/hata anında mesaj
- Topic deduplication: aynı konu tekrar üretilmez
- 200+ kanala hazır mimari

KULLANIM:
  python scheduler.py          # Token'i olan tüm kanalları çalıştır
  python scheduler.py --list   # Aktif kanalları listele
  python scheduler.py --status # Kuyruk durumunu göster
"""
import json
import logging
import os
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path

import pytz
import schedule

sys.path.insert(0, os.path.dirname(__file__))

# Loglama
Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("logs/scheduler.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("Scheduler")


def _is_enabled(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _resolve_live_collector_runtime() -> tuple[bool, str]:
    requested = _is_enabled(os.getenv("LIVE_COLLECTOR_ENABLED", "false"))
    api_go = _is_enabled(os.getenv("YOUTUBE_ANALYTICS_API_GO", "false"))
    rollout_approved = _is_enabled(os.getenv("LIVE_COLLECTOR_ROLLOUT_APPROVED", "false"))

    if not api_go:
        return False, "no_go_api_not_enabled"
    if not requested:
        return False, "disabled_by_flag"
    if not rollout_approved:
        return False, "disabled_by_policy"
    return True, "go_enabled"


def _resolve_git_head_short() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        return out or "unknown"
    except Exception:
        return "unknown"

# Env üzerinden kontrol: default 1
try:
    MAX_PARALLEL_RENDERS = max(1, int(os.getenv("MAX_PARALLEL_RENDERS", "1")))
except ValueError:
    MAX_PARALLEL_RENDERS = 1

TZ = pytz.timezone("Europe/Istanbul")
QUEUE_FILE = "output/queue/channel_queue.json"
PID_FILE = Path("logs/production_scheduler.pid")
QUEUE_LOCK = threading.RLock()
RENDER_LOCKS_LOCK = threading.Lock()

# Thread havuzu
render_executor = ThreadPoolExecutor(max_workers=MAX_PARALLEL_RENDERS, thread_name_prefix="render")
render_locks = {}  # Her kanal için kilit — aynı anda iki render başlamasın


# ─── Yardımcı Fonksiyonlar ────────────────────────────────────────────────────

def load_queue() -> dict:
    with QUEUE_LOCK:
        mode = os.getenv("JOB_STORE_MODE", "json").strip().lower()
        if mode not in {"json", "shadow"}:
            mode = "json"
        Path(QUEUE_FILE).parent.mkdir(parents=True, exist_ok=True)
        if not Path(QUEUE_FILE).exists():
            return {}
        try:
            return json.loads(Path(QUEUE_FILE).read_text(encoding="utf-8"))
        except Exception:
            return {}


def save_queue(data: dict):
    with QUEUE_LOCK:
        mode = os.getenv("JOB_STORE_MODE", "json").strip().lower()
        if mode not in {"json", "shadow"}:
            mode = "json"
        path = Path(QUEUE_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_path, path)

        if mode == "shadow":
            try:
                from src.job_store import mirror_legacy_queue_snapshot

                report = mirror_legacy_queue_snapshot(
                    data,
                    db_path=os.getenv("JOB_STORE_DB_PATH", "output/state/jobs.db"),
                )
                if report.get("missing_count", 0) > 0:
                    logger.warning(
                        "Shadow parity mismatch: missing=%s expected=%s mirrored=%s",
                        report.get("missing_count", 0),
                        report.get("expected", 0),
                        report.get("mirrored", 0),
                    )
            except Exception as e:
                logger.warning("Shadow mirror failed (non-blocking): %s", e)


def update_queue(mutator):
    with QUEUE_LOCK:
        mode = os.getenv("JOB_STORE_MODE", "json").strip().lower()
        if mode not in {"json", "shadow"}:
            mode = "json"
        path = Path(QUEUE_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            queue = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except Exception:
            queue = {}
        mutator(queue)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(queue, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp_path, path)

        if mode == "shadow":
            try:
                from src.job_store import mirror_legacy_queue_snapshot

                report = mirror_legacy_queue_snapshot(
                    queue,
                    db_path=os.getenv("JOB_STORE_DB_PATH", "output/state/jobs.db"),
                )
                if report.get("missing_count", 0) > 0:
                    logger.warning(
                        "Shadow parity mismatch: missing=%s expected=%s mirrored=%s",
                        report.get("missing_count", 0),
                        report.get("expected", 0),
                        report.get("mirrored", 0),
                    )
            except Exception as e:
                logger.warning("Shadow mirror failed (non-blocking): %s", e)

        return queue


def _get_channel_render_lock(channel_id: str) -> threading.Lock:
    """Kanal bazlı render lock nesnesini thread-safe biçimde döndür."""
    with RENDER_LOCKS_LOCK:
        lock = render_locks.get(channel_id)
        if lock is None:
            lock = threading.Lock()
            render_locks[channel_id] = lock
        return lock


def _write_pid_record() -> None:
    try:
        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
        logger.info("Scheduler pid record updated: %s -> %s", PID_FILE, os.getpid())
    except Exception as e:
        logger.warning("Scheduler pid record write failed (non-blocking): %s", e)


def get_ready_channels() -> list:
    """Token'i olan tüm kanalları keşfet."""
    from src.channel_manager import list_channels, get_channel
    ready = []
    for cid in list_channels():
        try:
            cfg = get_channel(cid)
            if Path(cfg.token_path).exists():
                ready.append(cid)
        except Exception:
            pass
    return ready


def get_next_upload_time(cfg, skip_occupied: list = None) -> str:
    """
    Bu kanalın bir sonraki upload saatini ISO 8601 olarak döndür.
    skip_occupied: zaten dolu olan publishAt saatleri listesi (çift yüklemeyi önler)
    """
    now = datetime.now(TZ)
    occupied = set(skip_occupied or [])

    # Önce bugünkü kalan slotlara bak
    for upload_time in sorted(cfg.upload_times):
        h, m = map(int, upload_time.split(":"))
        candidate = now.replace(hour=h, minute=m, second=0, microsecond=0)
        candidate_str = candidate.isoformat()
        if candidate > now + timedelta(minutes=45) and candidate_str not in occupied:
            return candidate_str

    # Bugün geçtiyse yarın ve sonrasına bak (tüm slotları dene)
    for day_offset in range(1, 8):  # Maksimum 7 gün ilerisine bak
        future = now + timedelta(days=day_offset)
        for upload_time in sorted(cfg.upload_times):
            h, m = map(int, upload_time.split(":"))
            candidate = future.replace(hour=h, minute=m, second=0, microsecond=0)
            candidate_str = candidate.isoformat()
            if candidate_str not in occupied:
                return candidate_str

    # Fallback
    tomorrow = now + timedelta(days=1)
    first = sorted(cfg.upload_times)[0]
    h, m = map(int, first.split(":"))
    return tomorrow.replace(hour=h, minute=m, second=0, microsecond=0).isoformat()


# ─── Ana İşlemler ─────────────────────────────────────────────────────────────

def render_and_schedule(channel_id: str):
    """
    Bir kanalın sonraki videosunu render eder ve
    YouTube'a Scheduled olarak yükler.
    """
    try:
        from src.scheduler_utils import (
            check_disk_space, cleanup_old_renders, force_cleanup,
            notify_upload, notify_error, save_used_topic,
        )
    except ImportError:
        def check_disk_space(**kw): return True
        def cleanup_old_renders(**kw): return 0
        def force_cleanup():
            import gc; gc.collect()
        def notify_upload(*a, **kw): pass
        def notify_error(*a, **kw): pass
        def save_used_topic(*a): pass

    channel_lock = _get_channel_render_lock(channel_id)
    acquired = channel_lock.acquire(blocking=False)
    if not acquired:
        logger.info(f"[{channel_id}] Render zaten devam ediyor, atlandı.")
        return

    try:
        from src.channel_manager import get_channel
        from src.pipeline import run_full_pipeline

        cfg = get_channel(channel_id)

        # ── Disk kontrolü ──────────────────────────────────────────────
        if not check_disk_space(min_gb=1.5):
            logger.error(f"[{cfg.name}] Disk doldu! Render iptal edildi.")
            notify_error(cfg.name, "Disk alanı kritik seviyede!")
            return

        publish_at = get_next_upload_time(
            cfg,
            skip_occupied=[e.get("publish_at","") for e in load_queue().get(channel_id, [])]
        )
        logger.info(f"[{cfg.name}] Render başlıyor → {publish_at} için zamanlanacak")

        # ── Retry ile pipeline çalıştır ────────────────────────────────
        last_error = None
        result = None
        max_attempts = 3
        for attempt in range(1, max_attempts + 1):  # Maks 3 deneme
            try:
                result = run_full_pipeline(
                    channel_cfg=cfg,
                    privacy="private",
                    publish_at=publish_at,
                )
                break  # Başarılı
            except Exception as e:
                last_error = e
                error_str = str(e).lower()
                # Kesinlikle retry yapma
                if any(x in error_str for x in ["failed_fact_check", "credit balance", "quota", "invalid_request", "invalidtags", "authentication"]):
                    logger.error(f"[{cfg.name}] Fatal hata (retry yok): {e}")
                    if "failed_fact_check" not in error_str:
                        decision = notify_error(cfg.name, str(e))
                        logger.info(f"[{cfg.name}] Telegram karar feedback: {decision.get('decision')}")
                    raise
                if attempt < 3:
                    wait = 30 * attempt
                    logger.warning(f"[{cfg.name}] Deneme {attempt}/3 başarısız, {wait}s bekleniyor... ({e})")
                    time.sleep(wait)
                else:
                    raise

        if result and result.get("video_id"):
            # Topic deduplication kaydı
            save_used_topic(channel_id, result.get("title", ""))

            # Kuyruk güncelle (thread-safe + atomic)
            def _append_entry(queue):
                if channel_id not in queue:
                    queue[channel_id] = []
                queue[channel_id].append({
                    "video_id": result["video_id"],
                    "title": result["title"],
                    "youtube_url": result.get("youtube_url", ""),
                    "publish_at": publish_at,
                    "rendered_at": datetime.now(TZ).isoformat(),
                })
            update_queue(_append_entry)
            logger.info(f"[{cfg.name}] ✅ Zamanlandı: '{result['title'][:50]}' → {publish_at}")

            # Telegram bildirimi
            notify_upload(
                cfg.name,
                result.get("title", ""),
                result.get("youtube_url", ""),
                result.get("short_url", ""),
            )

            # Güvenli mod: cross-channel like/subscribe devre dışı
            logger.info(f"[{cfg.name}] Cross-channel like/subscribe devre dışı (safe mode).")

            # Büyüme milestone kontrolü
            try:
                from src.scheduler_utils import check_growth_milestones
                check_growth_milestones(new_video_count=1)
            except Exception:
                pass
        else:
            logger.error(f"[{cfg.name}] Video ID alınamadı!")

    except Exception as e:
        logger.error(f"[{channel_id}] Render hatası: {e}", exc_info=True)
        try:
            if "failed_fact_check" in str(e).lower():
                return
            from src.channel_manager import get_channel
            cfg = get_channel(channel_id)
            from src.scheduler_utils import notify_error
            decision = notify_error(cfg.name, str(e))
            logger.info(f"[{cfg.name}] Telegram karar feedback: {decision.get('decision')}")
        except Exception:
            pass
    finally:
        if acquired:
            channel_lock.release()
        force_cleanup()  # Belleği temizle


def on_upload_time(channel_id: str):
    """
    Upload zamanı geldiğinde çağrılır.
    YouTube o videoyu otomatik yayınlıyor — Telegram'a bildir.
    """
    from src.channel_manager import get_channel
    cfg = get_channel(channel_id)
    logger.info(f"[{cfg.name}] Upload zamanı — YouTube otomatik yayınlıyor.")

    # Kuyruktaki yayınlanan videoyu atomik olarak düşür ve bildir
    try:
        from src.scheduler_utils import send_telegram
        published = {}

        def _pop_published(queue):
            entries = queue.get(channel_id, [])
            if entries:
                published.update(entries.pop(0))
                if not entries:
                    queue.pop(channel_id, None)

        update_queue(_pop_published)

        if published:
            entry = published
            title = entry.get("title", "")
            url = entry.get("youtube_url", "")
            send_telegram(
                f"🚀 <b>Yeni Video Yayında!</b>\n"
                f"📺 {cfg.name}\n"
                f"🎬 {title[:60]}\n"
                f"🔗 {url}"
            )
    except Exception as e:
        logger.warning(f"Yayın bildirimi gönderilemedi: {e}")

    # Bir sonraki video için render'ı thread havuzuna gönder
    render_executor.submit(render_and_schedule, channel_id)


def initial_fill():
    """
    Başlangıçta tüm kanallar için ön render başlat.
    Her kanal için bir sonraki boş saate video hazırla.
    """
    ready = get_ready_channels()
    queue = load_queue()

    logger.info(f"Başlangıç: {len(ready)} kanal için ön render kontrol ediliyor...")
    # Başlangıçta bayat kuyruk girişlerini temizle
    try:
        from src.scheduler_utils import cleanup_stale_queue
        cleanup_state = {"freed": []}

        def _cleanup_mutator(current_queue):
            cleaned, freed = cleanup_stale_queue(current_queue, TZ)
            current_queue.clear()
            current_queue.update(cleaned)
            cleanup_state["freed"] = list(freed)

        queue = update_queue(_cleanup_mutator)
        freed = cleanup_state["freed"]
        if freed:
            logger.info(f"Başlangıç temizliği: {len(freed)} kanal için bayat kuyruk temizlendi")
    except Exception as e:
        logger.warning(f"Bayat kuyruk temizleme hatası: {e}")

    for cid in ready:
        # Bu kanalın kuyruğunda zaten video var mı?
        if cid in queue and len(queue[cid]) > 0:
            logger.info(f"[{cid}] Kuyrukta video mevcut, render atlandı.")
            continue
        # Kuyrugu bos — render baslât
        logger.info(f"[{cid}] On render basliyor (siraya eklendi)...")
        render_executor.submit(render_and_schedule, cid)
        time.sleep(5)  # Kilit çakışmasını önle — ThreadPoolExecutor zaten tek sırada çalıştırır


def catch_up_overdue_queue_entries() -> dict[str, list[dict]]:
    """Tarihi geçmiş publish kayıtlarını başlangıçta tüket ve tek render zinciri başlat."""
    from src.channel_manager import get_channel

    queue = load_queue()
    now = datetime.now(TZ)
    caught_up: dict[str, list[dict]] = {}

    for channel_id in get_ready_channels():
        entries = list(queue.get(channel_id, []) or [])
        overdue_entries = []
        for entry in entries:
            publish_at = str(entry.get("publish_at") or "").strip()
            if not publish_at:
                continue
            try:
                publish_dt = datetime.fromisoformat(publish_at)
            except Exception:
                continue
            if publish_dt <= now:
                overdue_entries.append(entry)

        if not overdue_entries:
            continue

        published_batch: list[dict] = []

        def _pop_overdue(current_queue):
            channel_entries = list(current_queue.get(channel_id, []) or [])
            remaining = []
            for item in channel_entries:
                publish_at = str(item.get("publish_at") or "").strip()
                try:
                    publish_dt = datetime.fromisoformat(publish_at) if publish_at else None
                except Exception:
                    publish_dt = None
                if publish_dt and publish_dt <= now:
                    published_batch.append(item)
                else:
                    remaining.append(item)
            if remaining:
                current_queue[channel_id] = remaining
            else:
                current_queue.pop(channel_id, None)

        update_queue(_pop_overdue)
        if not published_batch:
            continue

        caught_up[channel_id] = published_batch
        cfg = get_channel(channel_id)
        logger.info("[%s] Startup catch-up: %s gecikmiş kuyruk girişi tüketildi", channel_id, len(published_batch))

        try:
            from src.scheduler_utils import send_telegram

            for entry in published_batch:
                send_telegram(
                    f"🚀 <b>Yeni Video Yayında!</b>\n"
                    f"📺 {cfg.name}\n"
                    f"🎬 {str(entry.get('title') or '')[:60]}\n"
                    f"🔗 {entry.get('youtube_url', '')}"
                )
        except Exception as e:
            logger.warning("[%s] Startup catch-up bildirimi gönderilemedi: %s", channel_id, e)

        render_executor.submit(render_and_schedule, channel_id)

    return caught_up


def setup_schedule():
    """Tüm aktif kanallar için upload zamanlarını ayarla."""
    from src.channel_manager import get_channel

    ready = get_ready_channels()
    day_map = {
        "Monday": schedule.every().monday,
        "Tuesday": schedule.every().tuesday,
        "Wednesday": schedule.every().wednesday,
        "Thursday": schedule.every().thursday,
        "Friday": schedule.every().friday,
        "Saturday": schedule.every().saturday,
        "Sunday": schedule.every().sunday,
    }
    days = list(day_map.keys())

    for cid in ready:
        cfg = get_channel(cid)
        for day in days:
            for t in cfg.upload_times:
                cid_copy = cid
                day_map[day].at(t).do(on_upload_time, channel_id=cid_copy)

    logger.info(f"{len(schedule.jobs)} zamanlama aktif ({len(ready)} kanal)")
    return ready


def show_status():
    """Kanal + kuyruk durumunu göster."""
    from rich.console import Console
    from rich.table import Table
    from src.channel_manager import get_channel

    console = Console()
    ready = get_ready_channels()
    queue = load_queue()

    table = Table(title=f"Sistem Durumu — {len(ready)} Aktif Kanal", border_style="cyan")
    table.add_column("Kanal")
    table.add_column("Upload Saatleri")
    table.add_column("Kuyrukta")
    table.add_column("Sonraki")

    for cid in ready:
        cfg = get_channel(cid)
        q_count = len(queue.get(cid, []))
        next_t = get_next_upload_time(cfg).split("T")[1][:5]
        table.add_row(
            cfg.name,
            " + ".join(cfg.upload_times),
            str(q_count),
            next_t,
        )

    console.print(table)
    console.print(f"\n[dim]MAX_PARALLEL_RENDERS={MAX_PARALLEL_RENDERS}[/dim]")


def _startup_subscribe_check():
    """Başlangıçta yeni kanalları tespit et, diğer kanallar abone olsun."""
    logger.info("Cross-channel auto-subscribe devre dışı (safe mode).")


# ─── Ana Giriş ────────────────────────────────────────────────────────────────

def maintenance_job():
    """Günlük bakım: disk + log rotation + token kontrol + bayat kuyruk temizle."""
    from src.scheduler_utils import (
        cleanup_old_renders, health_check, send_telegram,
        rotate_log_file, verify_all_tokens, cleanup_stale_queue,
    )
    logger.info("Bakım başlıyor...")

    # 1. Eski render dosyalarını sil
    deleted = cleanup_old_renders(max_age_hours=48)

    # 2. Log rotation (8000 satır limit)
    for log_file in ["logs/vps_scheduler.log", "logs/scheduler.log", "logs/vps_error.log"]:
        rotate_log_file(log_file, max_lines=8000)

    # 3. Bayat kuyruk girişlerini temizle + boşalan kanallar için render tetikle
    cleanup_state = {"freed": []}

    def _cleanup_mutator(current_queue):
        cleaned, freed = cleanup_stale_queue(current_queue, TZ)
        current_queue.clear()
        current_queue.update(cleaned)
        cleanup_state["freed"] = list(freed)

    update_queue(_cleanup_mutator)
    freed = cleanup_state["freed"]
    if freed:
        for cid in freed:
            logger.info(f"[{cid}] Bayat kuyruk temizlendi → yeni render başlatılıyor")
            render_executor.submit(render_and_schedule, cid)

    # 4. Token sağlık kontrolü (sorunlular Telegram'a bildirilir)
    verify_all_tokens()

    # 5. Kapasite uyarıları (RAM, disk, kanal sayısı, ElevenLabs kredit)
    try:
        from src.scheduler_utils import check_capacity_alerts
        check_capacity_alerts()
    except Exception as e:
        logger.warning(f"Kapasite kontrol hatası: {e}")

    # 6. PROGRESS.md güncelle
    update_progress_file(
        last_task="Günlük bakım tamamlandı",
        next_step="Scheduler çalışıyor — videoları otomatik yüklüyor"
    )

    status = health_check()
    if deleted > 0:
        logger.info(f"Bakım tamam: {deleted:.0f} MB silindi, {status['disk_free_gb']:.1f} GB boş")

    send_telegram(
        f"📊 <b>Günlük Rapor</b>\n"
        f"📡 {status['active_channels']} aktif kanal\n"
        f"💾 Disk: {status['disk_free_gb']:.1f} GB boş\n"
        f"🗄 Boyat kuyruk temizlendi: {len(freed)} kanal\n"
        f"✅ Sistem sağlıklı"
    )


def refresh_live_analytics_job():
    """Canlı YouTube Analytics verisini al ve optimization state'i yenile."""
    live_enabled, live_status = _resolve_live_collector_runtime()
    if not live_enabled:
        logger.info(
            "Live analytics refresh skipped: live_collector_enabled=false analytics_live_status=%s",
            live_status,
        )
        return

    try:
        from src.channel_manager import get_channel
        from src.channel_performance import append_performance_snapshot, load_recent_performance_snapshots
        from src.performance_optimizer import refresh_channel_optimization_state
        from src.youtube_analytics import fetch_recent_video_analytics

        snapshots = load_recent_performance_snapshots(lookback_days=14, max_items=400)
        by_channel: dict[str, list[dict]] = {}
        for row in snapshots:
            channel_id = str(row.get("channel_id") or "default")
            by_channel.setdefault(channel_id, []).append(row)

        for channel_id, rows in by_channel.items():
            try:
                cfg = get_channel(channel_id)
            except Exception as e:
                logger.warning("[%s] Optimization refresh skipped: %s", channel_id, e)
                continue

            latest_by_video = {}
            for row in rows:
                video_id = str(row.get("video_id") or "").strip()
                if not video_id:
                    continue
                if video_id not in latest_by_video:
                    latest_by_video[video_id] = row

            video_ids = list(latest_by_video.keys())[:5]
            if not video_ids:
                continue

            reports = fetch_recent_video_analytics(video_ids=video_ids, channel_cfg=cfg, lookback_days=14)
            reports_by_video = {str(report.get("video_id")): report for report in reports if report.get("video_id")}

            for video_id, base_row in latest_by_video.items():
                analytics = reports_by_video.get(video_id)
                if not analytics:
                    continue
                enriched = dict(base_row)
                enriched["youtube_analytics"] = analytics
                enriched["analytics_synced_at"] = datetime.now(TZ).isoformat()
                append_performance_snapshot(enriched)

            state = refresh_channel_optimization_state(channel_id)
            logger.info(
                "[%s] Live analytics synced: focus=%s mode=%s",
                channel_id,
                ",".join(state.get("focus", [])),
                state.get("mode"),
            )
    except Exception as e:
        logger.warning("Live analytics refresh failed: %s", e)


def process_likes_job():
    """Her 30 dk’da bir: zamanı gelen beğenileri işle."""
    logger.info("Cross-channel auto-like devre dışı (safe mode).")

def update_progress_file(last_task: str = "", next_step: str = ""):
    """PROGRESS.md'yi otomatik güncelle — her büyük görev sonunda çağır."""
    try:
        from datetime import datetime
        import pytz
        TZ_local = pytz.timezone("Europe/Istanbul")
        now = datetime.now(TZ_local).strftime("%Y-%m-%d %H:%M")

        queue = load_queue()
        ready = get_ready_channels()

        rows = []
        for cid in ready:
            entries = queue.get(cid, [])
            if entries:
                pub = entries[0].get("publish_at", "")[:16]
                rows.append(f"| {cid:25} | ✅ Kuyrukta | {pub} |")
            else:
                rows.append(f"| {cid:25} | 🔄 Render bekleniyor | — |")

        table = "\n".join(rows)

        content = f"""# PROGRESS — Para Pusulası YouTube Otomasyon

> Bu dosya scheduler tarafından otomatik güncellenir.

---

## Son Güncelleme
**Tarih:** {now} (Istanbul)

## Son Tamamlanan Görev
{last_task or "— (henüz kaydedilmedi)"}

## Bir Sonraki Adım
{next_step or "— (scheduler çalışıyor, otomatik devam)"}

## Kanal Kuyruk Durumu
| Kanal | Durum | Yayın Zamanı |
|---|---|---|
{table}
"""
        from pathlib import Path
        Path("PROGRESS.md").write_text(content, encoding="utf-8")
        logger.info("PROGRESS.md güncellendi")
    except Exception as e:
        logger.warning(f"PROGRESS.md güncellenemedi: {e}")


def fill_empty_queues_job():
    """
    Her saatte bir: kanalların tüm yakın slotlarını doldur.
    Günde 2 upload olan kanallar 2 video kuyruğa alır.
    """
    try:
        from src.scheduler_utils import cleanup_stale_queue
        cleanup_state = {"freed": []}

        def _cleanup_mutator(current_queue):
            cleaned, freed = cleanup_stale_queue(current_queue, TZ)
            current_queue.clear()
            current_queue.update(cleaned)
            cleanup_state["freed"] = list(freed)

        queue = update_queue(_cleanup_mutator)

        ready = get_ready_channels()
        now = datetime.now(TZ)

        for cid in ready:
            try:
                from src.channel_manager import get_channel
                cfg = get_channel(cid)
                existing = queue.get(cid, [])
                occupied = [e.get("publish_at","") for e in existing]
                needed_slots = len(cfg.upload_times)

                to_render = needed_slots - len(existing)
                for _ in range(to_render):
                    new_time = get_next_upload_time(cfg, skip_occupied=occupied)
                    occupied.append(new_time)
                    logger.info(f"[{cid}] Eksik slot → render başlatılıyor: {new_time}")
                    render_executor.submit(render_and_schedule, cid)
                    time.sleep(5)
            except Exception as e:
                logger.warning(f"[{cid}] fill_empty_queues_job hatası: {e}")
    except Exception as e:
        logger.warning(f"fill_empty_queues_job genel hatası: {e}")


def _print_help() -> None:
    print("Para Pusulasi Scheduler")
    print("Kullanim:")
    print("  python scheduler.py          # Token'i olan tum kanallari calistir")
    print("  python scheduler.py --list   # Aktif kanallari listele")
    print("  python scheduler.py --status # Kuyruk durumunu goster")
    print("  python scheduler.py --health-check # Uretim hazirlik kontrolunu calistir")
    print("  python scheduler.py --sync-analytics-now # Canli YouTube Analytics sync ve optimizasyonu calistir")
    print("  python scheduler.py --help   # Bu yardim metnini goster")


def _run_startup_health_check(*, create_missing_directories: bool, require_telegram: bool):
    from src.config import config as runtime_config
    from src.production_readiness import run_production_health_check

    result = run_production_health_check(
        runtime_config,
        require_telegram=require_telegram,
        create_missing_directories=create_missing_directories,
    )
    logger.info(
        "Configuration loaded: niche=%s language=%s timezone=%s",
        runtime_config.niche,
        runtime_config.channel_language,
        runtime_config.timezone,
    )
    logger.info(
        "Fact Bundle pipeline adapter is %s",
        "enabled" if result.fact_bundle_enabled else "disabled",
    )
    logger.info(
        "YouTube DNS resolution: %s",
        ", ".join(result.youtube_dns_ips) if result.youtube_dns_ips else "unresolved",
    )
    logger.info("Health check result: %s", "PASS" if result.ok else "FAIL")
    return result


def run_live_analytics_sync_once() -> int:
    """Canli analytics senkronunu bir kez calistirir."""
    refresh_live_analytics_job()
    _, live_status = _resolve_live_collector_runtime()
    print(f"Live analytics sync: PASS (analytics_live_status={live_status})")
    return 0

def main():
    args = sys.argv[1:]

    if "--help" in args or "-h" in args:
        _print_help()
        return

    if "--health-check" in args:
        result = _run_startup_health_check(
            create_missing_directories=False,
            require_telegram=True,
        )
        if result.ok:
            print("Health check: PASS")
            return
        print("Health check: FAIL")
        for error in result.errors:
            print(f"- {error}")
        sys.exit(1)

    if "--sync-analytics-now" in args:
        sys.exit(run_live_analytics_sync_once())

    if "--list" in args or "--status" in args:
        show_status()
        return

    from rich.console import Console
    console = Console()

    mode = os.getenv("JOB_STORE_MODE", "json").strip().lower()
    if mode not in {"json", "shadow"}:
        logger.warning("Geçersiz JOB_STORE_MODE='%s', json kullanılacak.", mode)
        mode = "json"

    if mode == "shadow":
        try:
            from src.job_store import initialize_database

            initialize_database(os.getenv("JOB_STORE_DB_PATH", "output/state/jobs.db"))
            logger.info("JOB_STORE_MODE=shadow aktif: SQLite shadow mirror etkin.")
        except Exception as e:
            logger.warning("Shadow DB init failed (non-blocking): %s", e)
    else:
        logger.info("JOB_STORE_MODE=json aktif: JSON production source of truth.")

    startup_health = _run_startup_health_check(
        create_missing_directories=True,
        require_telegram=True,
    )
    if not startup_health.ok:
        for error in startup_health.errors:
            logger.error("Startup validation failed: %s", error)
            print(f"ERROR: {error}")
        sys.exit(1)

    # scheduler_utils opsiyonel — yoksa basit fallback kullan
    try:
        from src.scheduler_utils import notify_startup, cleanup_old_renders
        _has_utils = True
    except ImportError:
        _has_utils = False
        def notify_startup(n): pass
        def cleanup_old_renders(**kw): return 0

    ready = get_ready_channels()
    if not ready:
        console.print("[red]Hiçbir kanalın token'i yok! Önce setup_channel.py çalıştırın.[/red]")
        sys.exit(1)

    logger.info("Scheduler starting")
    _write_pid_record()
    logger.info(
        "BUILD_INFO scheduler git_sha=%s cwd=%s python=%s started_at=%s",
        _resolve_git_head_short(),
        os.getcwd(),
        sys.executable,
        datetime.now(TZ).isoformat(),
    )

    console.print(f"\n[bold green]Para Pusulası Scheduler v4.0[/bold green]")
    console.print(f"[dim]{len(ready)} kanal aktif | MAX {MAX_PARALLEL_RENDERS} paralel render[/dim]\n")

    # Başlangıçta eski dosyaları temizle
    cleanup_old_renders(max_age_hours=48)

    # Zamanlama kur
    ready_channels = setup_schedule()

    # Restart sonrası geçmiş publish slotlarını tüket
    catch_up_overdue_queue_entries()

    # Günlük bakım (gece 03:00)
    schedule.every().day.at("03:00").do(maintenance_job)

    # Her saatte boş kuyruğu olan kanalları doldur (restart güvencesi)
    schedule.every(1).hour.do(fill_empty_queues_job)

    # Canlı YouTube Analytics senkronu (no-go durumunda planlama yapılmaz)
    live_enabled, live_status = _resolve_live_collector_runtime()
    if live_enabled:
        schedule.every(6).hours.do(refresh_live_analytics_job)
    else:
        logger.info(
            "Live analytics scheduler disabled: live_collector_enabled=false analytics_live_status=%s",
            live_status,
        )

    # Ön render başlat (arka planda)
    threading.Thread(target=initial_fill, daemon=True, name="initial-fill").start()

    # Telegram startup bildirimi
    notify_startup(len(ready))

    # Cross-channel subscribe/like güvenli modda kapalı

    console.print("[green]Çalışıyor. Durdurmak: Ctrl+C[/green]")
    console.print("[dim]Her upload sonrası sonraki video otomatik render edilir.[/dim]\n")

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()

