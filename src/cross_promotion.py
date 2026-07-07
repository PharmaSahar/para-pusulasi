"""
Cross-Promotion Modülü
----------------------
1. Yeni kanal eklenince tüm mevcut kanallar otomatik abone olur (tek seferlik)
2. Video yüklenince diğer kanallar saatler arayla beğenir (spam tespit edilmesin)
"""
import json
import logging
import random
import time
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# Durum dosyaları
PENDING_LIKES_FILE   = "channels/pending_likes.json"
SUBSCRIPTIONS_FILE   = "channels/subscriptions_done.json"


# ─── Yardımcı: Aktif kanalları getir ──────────────────────────────────────────

def get_active_channels():
    """Token dosyası olan tüm aktif kanalların config listesini döndür."""
    from .channel_manager import load_registry, get_channel
    registry = load_registry()
    active = []
    for cid, data in registry.get("channels", {}).items():
        if data.get("status") != "active":
            continue
        try:
            cfg = get_channel(cid)
            if Path(cfg.token_path).exists():
                active.append(cfg)
        except Exception as e:
            logger.debug(f"[{cid}] config yüklenemedi: {e}")
    return active


def get_youtube_channel_id(channel_id: str) -> str | None:
    """Registry'den kanalın YouTube kanal ID'sini al."""
    from .channel_manager import load_registry
    registry = load_registry()
    return registry.get("channels", {}).get(channel_id, {}).get("youtube_channel_id")


# ─── 1. OTOMATİK ABONE ────────────────────────────────────────────────────────

def _load_subscriptions() -> dict:
    p = Path(SUBSCRIPTIONS_FILE)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_subscriptions(data: dict):
    Path(SUBSCRIPTIONS_FILE).parent.mkdir(parents=True, exist_ok=True)
    Path(SUBSCRIPTIONS_FILE).write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def subscribe_all_to_channel(target_channel_id: str):
    """
    Tüm aktif kanalları target_channel_id kanalına abone et.
    Zaten abone olanlar atlanır. Sonuç subscriptions_done.json'a kaydedilir.
    """
    target_yt_id = get_youtube_channel_id(target_channel_id)
    if not target_yt_id:
        logger.warning(f"[{target_channel_id}] YouTube kanal ID bulunamadı, abone olunamadı.")
        return

    subs = _load_subscriptions()
    already = set(subs.get(target_channel_id, []))
    channels = get_active_channels()

    for cfg in channels:
        if cfg.channel_id == target_channel_id:
            continue  # Kendine abone olmaz
        if cfg.channel_id in already:
            logger.info(f"[{cfg.channel_id}] → {target_channel_id} zaten abone, atlanıyor.")
            continue

        try:
            from .youtube_auth import get_authenticated_service
            service = get_authenticated_service(channel_cfg=cfg)
            service.subscriptions().insert(
                part="snippet",
                body={
                    "snippet": {
                        "resourceId": {
                            "kind": "youtube#channel",
                            "channelId": target_yt_id,
                        }
                    }
                },
            ).execute()
            already.add(cfg.channel_id)
            logger.info(f"✅ [{cfg.channel_id}] → [{target_channel_id}] abone oldu")
            time.sleep(random.uniform(3, 7))  # YouTube rate limit

        except Exception as e:
            err = str(e).lower()
            if "subscriptionduplicate" in err or "already subscribed" in err:
                already.add(cfg.channel_id)  # Zaten aboneyse kaydet
                logger.info(f"[{cfg.channel_id}] zaten abone (API teyit)")
            else:
                logger.warning(f"[{cfg.channel_id}] abone olamadı: {e}")

    subs[target_channel_id] = sorted(already)
    _save_subscriptions(subs)
    logger.info(f"Abone işlemi tamamlandı → [{target_channel_id}]")


def check_and_subscribe_new_channels():
    """
    Scheduler başlangıcında veya periyodik olarak çağır.
    Henüz diğer kanalların abone olmadığı aktif kanalları tespit edip abone olur.
    """
    subs = _load_subscriptions()
    channels = get_active_channels()
    channel_ids = {c.channel_id for c in channels}

    for cfg in channels:
        subscribed_by = set(subs.get(cfg.channel_id, []))
        missing = channel_ids - subscribed_by - {cfg.channel_id}
        if missing:
            logger.info(f"[{cfg.channel_id}] için {len(missing)} kanal henüz abone değil → abone olunuyor...")
            subscribe_all_to_channel(cfg.channel_id)


# ─── 2. ZAMANLANMIŞ BEĞENİ ────────────────────────────────────────────────────

def _load_pending() -> list:
    p = Path(PENDING_LIKES_FILE)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_pending(pending: list):
    Path(PENDING_LIKES_FILE).parent.mkdir(parents=True, exist_ok=True)
    Path(PENDING_LIKES_FILE).write_text(
        json.dumps(pending, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def queue_likes_for_video(video_id: str, source_channel_id: str):
    """
    Video yüklendikten sonra diğer kanalların beğenisini sıraya ekle.
    İlk beğeni 1-2 saat sonra, her sonraki 40-80 dk arayla rastgele.
    """
    channels = get_active_channels()
    others = [c for c in channels if c.channel_id != source_channel_id]
    if not others:
        return

    random.shuffle(others)
    pending = _load_pending()

    # Zaten sırada var mı kontrol et
    already_queued = {
        (e["video_id"], e["liker_channel_id"])
        for e in pending
        if not e.get("done")
    }

    delay_min = random.randint(70, 130)       # İlk beğeni 70-130 dk sonra
    for cfg in others:
        if (video_id, cfg.channel_id) in already_queued:
            continue

        execute_at = (datetime.now() + timedelta(minutes=delay_min)).isoformat()
        pending.append({
            "video_id": video_id,
            "liker_channel_id": cfg.channel_id,
            "execute_at": execute_at,
            "done": False,
        })
        logger.info(f"Beğeni sıralandı: [{cfg.channel_id}] → {video_id} @ {execute_at[:16]}")
        delay_min += random.randint(45, 85)   # Sonraki kanal 45-85 dk daha geç

    _save_pending(pending)


def process_pending_likes():
    """
    Zamanı gelen beğenileri işle. Scheduler'dan her 30 dk'da bir çağır.
    """
    pending = _load_pending()
    if not pending:
        return

    now = datetime.now()
    changed = False

    for entry in pending:
        if entry.get("done"):
            continue
        try:
            execute_at = datetime.fromisoformat(entry["execute_at"])
        except Exception:
            entry["done"] = True
            changed = True
            continue

        if now < execute_at:
            continue

        channel_id = entry["liker_channel_id"]
        video_id = entry["video_id"]
        try:
            # Config al
            from .channel_manager import get_channel
            cfg = get_channel(channel_id)
            if not Path(cfg.token_path).exists():
                raise FileNotFoundError(f"Token yok: {cfg.token_path}")

            from .youtube_auth import get_authenticated_service
            service = get_authenticated_service(channel_cfg=cfg)
            service.videos().rate(id=video_id, rating="like").execute()
            logger.info(f"✅ Beğeni: [{channel_id}] → {video_id}")
            entry["done"] = True
            changed = True
            time.sleep(random.uniform(2, 5))

        except Exception as e:
            err = str(e).lower()
            if "videoratingdisabled" in err or "forbidden" in err or "notfound" in err:
                logger.warning(f"[{channel_id}] beğeni kalıcı hata, atlanıyor: {e}")
                entry["done"] = True  # Kalıcı hata → tekrar deneme
            else:
                logger.warning(f"[{channel_id}] beğeni başarısız (tekrar denenecek): {e}")
                # execute_at'i 30 dk öteye al — geçici hata
                entry["execute_at"] = (now + timedelta(minutes=30)).isoformat()
            changed = True

    if changed:
        # 7 günden eski tamamlananları temizle
        cutoff = (datetime.now() - timedelta(days=7)).isoformat()
        pending = [
            e for e in pending
            if not e.get("done") or e.get("execute_at", "") > cutoff
        ]
        _save_pending(pending)
