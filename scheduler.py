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

# VPS CPX22: 2 vCPU ama MoviePy çok RAM yer → 1 paralel render (OOM engeli)
MAX_PARALLEL_RENDERS = 1

TZ = pytz.timezone("Europe/Istanbul")
QUEUE_FILE = "output/queue/channel_queue.json"

# Thread havuzu
render_executor = ThreadPoolExecutor(max_workers=MAX_PARALLEL_RENDERS, thread_name_prefix="render")
render_locks = {}  # Her kanal için kilit — aynı anda iki render başlamasın


# ─── Yardımcı Fonksiyonlar ────────────────────────────────────────────────────

def load_queue() -> dict:
    Path(QUEUE_FILE).parent.mkdir(parents=True, exist_ok=True)
    if not Path(QUEUE_FILE).exists():
        return {}
    try:
        return json.loads(Path(QUEUE_FILE).read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_queue(data: dict):
    Path(QUEUE_FILE).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


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
            notify_upload, notify_error, save_used_topic, is_topic_used,
        )
    except ImportError:
        def check_disk_space(**kw): return True
        def cleanup_old_renders(**kw): return 0
        def force_cleanup():
            import gc; gc.collect()
        def notify_upload(*a, **kw): pass
        def notify_error(*a, **kw): pass
        def save_used_topic(*a): pass
        def is_topic_used(*a): return False

    if channel_id not in render_locks:
        render_locks[channel_id] = threading.Lock()

    if not render_locks[channel_id].acquire(blocking=False):
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
                if any(x in error_str for x in ["credit balance", "quota", "invalid_request", "invalidtags", "authentication"]):
                    logger.error(f"[{cfg.name}] Fatal hata (retry yok): {e}")
                    notify_error(cfg.name, str(e)[:150])
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

            # Kuyruk güncelle
            queue = load_queue()
            if channel_id not in queue:
                queue[channel_id] = []
            queue[channel_id].append({
                "video_id": result["video_id"],
                "title": result["title"],
                "youtube_url": result.get("youtube_url", ""),
                "publish_at": publish_at,
                "rendered_at": datetime.now(TZ).isoformat(),
            })
            save_queue(queue)
            logger.info(f"[{cfg.name}] ✅ Zamanlandı: '{result['title'][:50]}' → {publish_at}")

            # Telegram bildirimi
            notify_upload(
                cfg.name,
                result.get("title", ""),
                result.get("youtube_url", ""),
                result.get("short_url", ""),
            )

            # Cross-promotion: diğer kanallar saatler arayla beğensin
            try:
                from src.cross_promotion import queue_likes_for_video
                queue_likes_for_video(result["video_id"], channel_id)
            except Exception as _cp_e:
                logger.warning(f"[{cfg.name}] Beğeni sıralama hatası: {_cp_e}")

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
            from src.channel_manager import get_channel
            cfg = get_channel(channel_id)
            from src.scheduler_utils import notify_error
            notify_error(cfg.name, str(e)[:150])
        except Exception:
            pass
    finally:
        render_locks[channel_id].release()
        force_cleanup()  # Belleği temizle


def on_upload_time(channel_id: str):
    """
    Upload zamanı geldiğinde çağrılır.
    YouTube o videoyu otomatik yayınlıyor — Telegram'a bildir.
    """
    from src.channel_manager import get_channel
    cfg = get_channel(channel_id)
    logger.info(f"[{cfg.name}] Upload zamanı — YouTube otomatik yayınlıyor.")

    # Kuyruktaki videoyu bul ve Telegram'a bildirim gönder
    try:
        from src.scheduler_utils import send_telegram
        queue = load_queue()
        entries = queue.get(channel_id, [])
        if entries:
            entry = entries[0]
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
        queue, freed = cleanup_stale_queue(queue, TZ)
        if freed:
            save_queue(queue)
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
    try:
        time.sleep(10)  # Scheduler tam yüklendikten sonra başlat
        from src.cross_promotion import check_and_subscribe_new_channels
        check_and_subscribe_new_channels()
    except Exception as e:
        logger.warning(f"Abone kontrol hatası: {e}")


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
    queue = load_queue()
    queue, freed = cleanup_stale_queue(queue, TZ)
    if freed:
        save_queue(queue)
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


def process_likes_job():
    """Her 30 dk’da bir: zamanı gelen beğenileri işle."""
    try:
        from src.cross_promotion import process_pending_likes
        process_pending_likes()
    except Exception as e:
        logger.warning(f"Beğeni işleme hatası: {e}")

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
    """
    Her saatte bir: kanalların tüm yakın slotlarını doldur.
    Günde 2 upload olan kanallar 2 video kuyruğa alır.
    """
    try:
        queue = load_queue()
        from src.scheduler_utils import cleanup_stale_queue
        queue, freed = cleanup_stale_queue(queue, TZ)
        if freed:
            save_queue(queue)

        ready = get_ready_channels()
        now = datetime.now(TZ)

        for cid in ready:
            try:
                from src.channel_manager import get_channel
                cfg = get_channel(cid)
                existing = queue.get(cid, [])
                occupied = [e.get("publish_at","") for e in existing]
                needed_slots = len(cfg.upload_times)  # kaç slot/gün varsa o kadar video

                # Eksik slot sayısı kadar render başlat
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

def main():
    args = sys.argv[1:]

    if "--list" in args or "--status" in args:
        show_status()
        return

    from rich.console import Console
    console = Console()

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

    console.print(f"\n[bold green]Para Pusulası Scheduler v4.0[/bold green]")
    console.print(f"[dim]{len(ready)} kanal aktif | MAX {MAX_PARALLEL_RENDERS} paralel render[/dim]\n")

    # Başlangıçta eski dosyaları temizle
    cleanup_old_renders(max_age_hours=48)

    # Zamanlama kur
    ready_channels = setup_schedule()

    # Günlük bakım (gece 03:00)
    schedule.every().day.at("03:00").do(maintenance_job)

    # Her 30 dk bekleyen beğenileri işle
    schedule.every(30).minutes.do(process_likes_job)

    # Her saatte boş kuyruğu olan kanalları doldur (restart güvencesi)
    schedule.every(1).hour.do(fill_empty_queues_job)

    # Ön render başlat (arka planda)
    threading.Thread(target=initial_fill, daemon=True, name="initial-fill").start()

    # Telegram startup bildirimi
    notify_startup(len(ready))

    # Yeni kanallar için abone kontrolü (arka planda)
    threading.Thread(
        target=_startup_subscribe_check, daemon=True, name="subscribe-check"
    ).start()

    console.print("[green]Çalışıyor. Durdurmak: Ctrl+C[/green]")
    console.print("[dim]Her upload sonrası sonraki video otomatik render edilir.[/dim]\n")

    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()

