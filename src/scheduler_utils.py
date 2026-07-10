"""
Scheduler Sağlık ve Bakım Araçları
- Disk temizleme (eski render dosyaları)
- Bellek temizleme
- Akıllı retry
- Telegram bildirimleri
- Topic deduplication
"""
import gc
import json
import logging
import os
import re
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger("SchedulerUtils")

# ─── BÜYÜME MİLESTONE TAKİBİ ─────────────────────────────────────────────────
# Toplam yüklenen video sayısına göre otomatik yükseltme hatırlatması

MILESTONES_FILE = "output/queue/milestones.json"

UPGRADE_MILESTONES = [
    {
        "videos": 300,
        "title": "🎯 Milestone: 300 Video!",
        "message": (
            "Tebrikler! 300 video yüklendi.\n\n"
            "💡 <b>ElevenLabs Pro'ya geçme zamanı</b> ($99/ay)\n"
            "• 600k kredi/ay → 1 kanal için tüm yıl yeter\n"
            "• Ses kalitesi dramatik artış\n"
            "• Ticari lisans dahil\n"
            "• elevenlabs.io/app/subscription"
        ),
    },
    {
        "videos": 1500,
        "title": "🚀 Milestone: 1.500 Video!",
        "message": (
            "1.500 video — sistem tam otomasyonda!\n\n"
            "💡 <b>ElevenLabs Scale değerlendirin</b> ($299/ay)\n"
            "• 1.8M kredi/ay → 5-6 kanal için yeter\n"
            "• Ekip işbirliği özelliği\n"
            "• elevenlabs.io/app/subscription"
        ),
    },
    {
        "videos": 5000,
        "title": "🏆 Milestone: 5.000 Video!",
        "message": (
            "5.000 video — profesyonel medya şirketi seviyesi!\n\n"
            "💡 <b>ElevenLabs Business düşünün</b> ($990/ay)\n"
            "• 6M kredi/ay → tüm 10 kanal ElevenLabs ile çalışır\n"
            "• 10 Profesyonel Ses Klonu hakkı\n"
            "• Düşük gecikme streaming API\n"
            "• elevenlabs.io/app/subscription"
        ),
    },
    {
        "videos": 15000,
        "title": "🌟 Milestone: 15.000 Video!",
        "message": (
            "15.000 video — Enterprise seviyesi!\n\n"
            "💡 <b>ElevenLabs Enterprise</b> (özel fiyat)\n"
            "• Özel kredi hacmi + volume indirim\n"
            "• SLA garantisi\n"
            "• Satış ekibiyle görüş: elevenlabs.io/enterprise"
        ),
    },
]


def _load_milestones() -> dict:
    p = Path(MILESTONES_FILE)
    if not p.exists():
        return {"reached": [], "total_videos": 0}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"reached": [], "total_videos": 0}


def _save_milestones(data: dict):
    Path(MILESTONES_FILE).parent.mkdir(parents=True, exist_ok=True)
    Path(MILESTONES_FILE).write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def check_growth_milestones(new_video_count: int = 1):
    """
    Her video yüklemesinde çağır.
    Milestone geçildiyse Telegram'a hatırlatma gönderir (bir kez).
    """
    data = _load_milestones()
    data["total_videos"] = data.get("total_videos", 0) + new_video_count
    total = data["total_videos"]
    reached = set(data.get("reached", []))

    for ms in UPGRADE_MILESTONES:
        key = str(ms["videos"])
        if total >= ms["videos"] and key not in reached:
            reached.add(key)
            send_telegram(
                f"{ms['title']}\n"
                f"📊 Toplam yüklenen video: <b>{total}</b>\n\n"
                f"{ms['message']}"
            )
            logger.info(f"Milestone ulaşıldı: {ms['videos']} video")

    data["reached"] = list(reached)
    _save_milestones(data)


def get_total_uploaded_videos() -> int:
    """Şimdiye kadar yüklenen toplam video sayısını döndür."""
    return _load_milestones().get("total_videos", 0)


# ─── DISK TEMİZLEME ──────────────────────────────────────────────────────────

def cleanup_old_renders(max_age_hours: int = 48, min_free_gb: float = 2.0):
    """
    48 saatten eski render dosyalarını sil.
    Disk dolmak üzereyse daha agresif temizlik yap.
    """
    deleted_mb = 0
    free_gb = get_free_disk_gb()

    # Disk kritik seviyedeyse daha agresif temizle
    age_hours = max_age_hours if free_gb > min_free_gb else 6

    cutoff = datetime.now() - timedelta(hours=age_hours)
    cleanup_dirs = []

    # Kanal bazlı output klasörleri
    for channel_dir in Path("channels").glob("*/output"):
        cleanup_dirs.append(channel_dir)

    # Ana output klasörü
    cleanup_dirs.append(Path("output"))

    for base_dir in cleanup_dirs:
        for subdir in ["videos", "audio", "clips", "shorts"]:
            target = base_dir / subdir
            if not target.exists():
                continue
            for f in target.iterdir():
                if not f.is_file():
                    continue
                # Thumbnail'leri koru
                if f.suffix in (".jpg", ".jpeg", ".png"):
                    continue
                try:
                    mtime = datetime.fromtimestamp(f.stat().st_mtime)
                    if mtime < cutoff:
                        size_mb = f.stat().st_size / 1_048_576
                        f.unlink()
                        deleted_mb += size_mb
                except Exception as e:
                    logger.warning(f"Silme hatası {f}: {e}")

    if deleted_mb > 0:
        logger.info(f"Disk temizleme: {deleted_mb:.0f} MB silindi. Boş: {get_free_disk_gb():.1f} GB")

    return deleted_mb


def get_free_disk_gb() -> float:
    """Mevcut boş disk alanını GB olarak döndür."""
    try:
        stat = shutil.disk_usage(".")
        return stat.free / 1_073_741_824
    except Exception:
        return 99.0


def check_disk_space(min_gb: float = 1.5) -> bool:
    """Disk yeterliyse True, kritik seviyedeyse False döndür."""
    free = get_free_disk_gb()
    if free < min_gb:
        logger.error(f"⚠️ DİSK KRİTİK: {free:.1f} GB kaldı! Temizlik başlıyor...")
        cleanup_old_renders(max_age_hours=6)
        return get_free_disk_gb() > 0.5
    return True


# ─── BELLEK YÖNETİMİ ─────────────────────────────────────────────────────────

def force_cleanup():
    """MoviePy ve diğer kütüphanelerden sonra belleği temizle."""
    try:
        # MoviePy video clip'lerini kapat
        import moviepy
        # Garbage collection
        gc.collect()
        # Önbelleği boşalt
        try:
            import torch
            torch.cuda.empty_cache()
        except ImportError:
            pass
    except Exception:
        pass
    gc.collect()


# ─── AKILLI RETRY ────────────────────────────────────────────────────────────

def with_retry(func, max_attempts: int = 3, base_delay: float = 30.0, *args, **kwargs):
    """
    Fonksiyonu en fazla max_attempts kez dene.
    Başarısız olursa üstel geri çekilme (exponential backoff) uygula.
    """
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_error = e
            error_str = str(e).lower()

            # Kesinlikle tekrar denenmeyecek hatalar
            fatal_errors = [
                "invalid_request_error",
                "invalid video keywords",
                "authentication",
                "quota",
                "credit balance",
            ]
            if any(fe in error_str for fe in fatal_errors):
                logger.error(f"Fatal hata (retry yok): {e}")
                raise

            if attempt < max_attempts:
                delay = base_delay * (2 ** (attempt - 1))  # 30s, 60s, 120s
                logger.warning(f"Deneme {attempt}/{max_attempts} başarısız. {delay:.0f}s bekliyor... Hata: {e}")
                time.sleep(delay)
            else:
                logger.error(f"Tüm {max_attempts} deneme başarısız: {e}")

    raise last_error


# ─── TELEGRAM BİLDİRİMLERİ ───────────────────────────────────────────────────

def send_telegram(message: str):
    """Telegram üzerinden bildirim gönder. Token her çağrıda env'den okunur."""
    # Her çağrıda env'den oku — modül import sırasında değil (dotenv geç yükleniyor)
    from dotenv import dotenv_values
    import pathlib
    env = {}
    for env_path in [".env", "/opt/parapusulasi/.env"]:
        if pathlib.Path(env_path).exists():
            env = dotenv_values(env_path)
            break
    token = env.get("TELEGRAM_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = env.get("TELEGRAM_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        return
    try:
        import requests
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        requests.post(url, json={
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=10)
    except Exception as e:
        logger.warning(f"Telegram bildirimi gönderilemedi: {e}")


def notify_upload(channel_name: str, title: str, url: str, short_url: str = ""):
    send_telegram(
        f"✅ <b>Yeni Video Yüklendi!</b>\n"
        f"📺 Kanal: {channel_name}\n"
        f"🎬 {title[:60]}\n"
        f"🔗 {url}"
        + (f"\n📱 Short: {short_url}" if short_url else "")
    )


def notify_error(channel_name: str, error: str) -> dict:
    error_text = _summarize_error_for_telegram(error)
    decision = _classify_error_decision(error_text)
    alert_key = f"render_error::{channel_name.strip().lower()}::{decision['decision']}::{error_text.strip().lower()}"
    cooldown_hours = 6 if decision["decision"] == "skip_current_item" else 2
    if not _should_alert(alert_key, cooldown_hours=cooldown_hours):
        logger.info("Telegram render error alert suppressed by cooldown: %s", alert_key)
        return decision

    send_telegram(
        f"⚠️ <b>Render Hatası</b>\n"
        f"📺 Kanal: {channel_name}\n"
        f"❌ {error_text}\n"
        f"🧭 Karar: {decision['decision_label']}\n"
        f"🔧 Aksiyon: {decision['action_label']}"
    )
    _mark_alert_sent(alert_key)
    return decision


def _summarize_error_for_telegram(error: str, max_len: int = 220) -> str:
    """Ham exception metnini Telegram için okunur bir özete indirger."""
    raw = " ".join(str(error or "").split())
    if not raw:
        return "Bilinmeyen hata"

    status_match = re.search(r"status_code:\s*(\d+)", raw)
    status_code = status_match.group(1) if status_match else None

    detail = None
    for pattern in (
        r"['\"]message['\"]:\s*['\"]([^'\"]+)['\"]",
        r"['\"]code['\"]:\s*['\"]([^'\"]+)['\"]",
    ):
        m = re.search(pattern, raw)
        if m:
            detail = m.group(1)
            break

    cleaned = re.sub(r"headers:\s*\{.*?\},\s*", "", raw)
    summary = cleaned
    if status_code and detail:
        summary = f"HTTP {status_code} - {detail}"
    elif status_code:
        summary = f"HTTP {status_code} - {cleaned}"
    elif detail:
        summary = detail

    if len(summary) > max_len:
        summary = summary[: max_len - 3] + "..."
    return summary


def _classify_error_decision(summary: str) -> dict:
    """Render hatasından operasyon kararı türetir."""
    txt = str(summary or "").lower()

    if any(k in txt for k in ("invalid api key", "unauthorized", "http 401", "authentication")):
        return {
            "decision": "continue_without_provider",
            "decision_label": "Uretim devam (problemli provider disi)",
            "action_label": "API anahtari kontrol et; fallback TTS ile devam",
            "retry": False,
        }

    if any(k in txt for k in ("quota", "credit balance", "http 429", "rate limit")):
        return {
            "decision": "continue_with_backoff",
            "decision_label": "Uretim devam (bekleme/backoff)",
            "action_label": "Kota/kredi yenilenene kadar yeniden deneme araligini artir",
            "retry": True,
        }

    if any(k in txt for k in ("failed_fact_check", "fact check fail", "niche_alignment_failed")):
        return {
            "decision": "skip_current_item",
            "decision_label": "Bu icerik atlandi, sonraki isleme gec",
            "action_label": "Kanal ve topic policy kontrolu",
            "retry": False,
        }

    if any(k in txt for k in ("timeout", "connection", "response ended prematurely", "dns", "chunkedencodingerror")):
        return {
            "decision": "retry_then_continue",
            "decision_label": "Gecici hata: retry sonra devam",
            "action_label": "Ag kararliligi kontrolu, fallback kullan",
            "retry": True,
        }

    return {
        "decision": "continue_with_monitoring",
        "decision_label": "Uretim devam, izleme artirildi",
        "action_label": "Ayni hata tekrarlarsa manuel inceleme",
        "retry": True,
    }


def notify_startup(active_channels: int):
    send_telegram(
        f"🚀 <b>Para Pusulası Scheduler Başladı</b>\n"
        f"📡 {active_channels} aktif kanal\n"
        f"💾 Boş disk: {get_free_disk_gb():.1f} GB"
    )


# ─── TOPIC DEDUPLİKASYON ─────────────────────────────────────────────────────

USED_TOPICS_FILE = "output/queue/used_topics.json"


def load_used_topics() -> dict:
    """Daha önce kullanılmış konuları yükle."""
    Path(USED_TOPICS_FILE).parent.mkdir(parents=True, exist_ok=True)
    if not Path(USED_TOPICS_FILE).exists():
        return {}
    try:
        return json.loads(Path(USED_TOPICS_FILE).read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_used_topic(channel_id: str, title: str):
    """Kullanılmış konuyu kaydet."""
    topics = load_used_topics()
    if channel_id not in topics:
        topics[channel_id] = []
    # Sadece son 200 başlığı tut
    topics[channel_id] = (topics[channel_id] + [title])[-200:]
    Path(USED_TOPICS_FILE).write_text(
        json.dumps(topics, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def is_topic_used(channel_id: str, title: str, similarity_threshold: float = 0.7) -> bool:
    """Bu başlık veya çok benzeri daha önce kullanıldı mı?"""
    topics = load_used_topics()
    used = topics.get(channel_id, [])
    if not used:
        return False

    title_lower = title.lower()
    title_words = set(title_lower.split())

    for prev in used[-50:]:  # Son 50 başlığa bak
        prev_words = set(prev.lower().split())
        if not prev_words:
            continue
        # Jaccard benzerlik
        intersection = len(title_words & prev_words)
        union = len(title_words | prev_words)
        if union > 0 and intersection / union >= similarity_threshold:
            return True

    return False


# ─── SİSTEM SAĞLIK KONTROLÜ ──────────────────────────────────────────────────

def health_check() -> dict:
    """Sistemin genel sağlığını kontrol et."""
    from pathlib import Path
    status = {
        "timestamp": datetime.now().isoformat(),
        "disk_free_gb": get_free_disk_gb(),
        "disk_ok": get_free_disk_gb() > 1.5,
        "scheduler_running": True,
    }

    # Kanal tokenlarını kontrol et
    from src.channel_manager import list_channels, get_channel
    active = 0
    for cid in list_channels():
        try:
            cfg = get_channel(cid)
            if Path(cfg.token_path).exists():
                active += 1
        except Exception:
            pass
    status["active_channels"] = active

    return status


# ─── AKILLI UYARI SİSTEMİ ────────────────────────────────────────────────────
# Her bakımda kapasite eşiklerini kontrol et, gerektiğinde Telegram'a uyar

ALERTS_FILE = "output/queue/alerts_sent.json"

def _load_alerts() -> dict:
    p = Path(ALERTS_FILE)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}

def _save_alerts(data: dict):
    Path(ALERTS_FILE).parent.mkdir(parents=True, exist_ok=True)
    Path(ALERTS_FILE).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def _should_alert(key: str, cooldown_hours: int = 24) -> bool:
    """Aynı uyarıyı belirli süre içinde tekrar gönderme."""
    alerts = _load_alerts()
    last = alerts.get(key)
    if not last:
        return True
    try:
        last_dt = datetime.fromisoformat(last)
        return (datetime.now() - last_dt).total_seconds() > cooldown_hours * 3600
    except Exception:
        return True

def _mark_alert_sent(key: str):
    alerts = _load_alerts()
    alerts[key] = datetime.now().isoformat()
    _save_alerts(alerts)


def check_capacity_alerts():
    """
    Kapasite eşiklerini kontrol et — kritik noktalarda Telegram uyarısı gönder.
    Her gece bakımda çağrılır.
    """
    alerts_sent = []

    # ── 1. RAM KULLANIMI ─────────────────────────────────────────────────────
    try:
        import psutil
        ram = psutil.virtual_memory()
        ram_pct = ram.percent
        ram_used_gb = ram.used / 1e9
        ram_total_gb = ram.total / 1e9

        if ram_pct > 90 and _should_alert("ram_critical", cooldown_hours=6):
            send_telegram(
                f"🚨 <b>ACİL: RAM KRİTİK %{ram_pct:.0f}</b>\n"
                f"💾 {ram_used_gb:.1f} GB / {ram_total_gb:.1f} GB kullanılıyor\n"
                f"⚡ Hemen VPS yükselt:\n"
                f"• CPX32 → CPX42 (16 GB, €69/ay)\n"
                f"• console.hetzner.com → Servers → Rescale"
            )
            _mark_alert_sent("ram_critical")
            alerts_sent.append("RAM KRİTİK")

        elif ram_pct > 75 and _should_alert("ram_warning", cooldown_hours=24):
            send_telegram(
                f"⚠️ <b>RAM Uyarısı: %{ram_pct:.0f}</b>\n"
                f"💾 {ram_used_gb:.1f} GB / {ram_total_gb:.1f} GB\n"
                f"💡 Yakında VPS planı yükseltmesini düşün:\n"
                f"• CPX32 (8 GB) → CPX42 (16 GB, €69/ay)\n"
                f"• console.hetzner.com"
            )
            _mark_alert_sent("ram_warning")
            alerts_sent.append("RAM uyarı")
    except ImportError:
        pass  # psutil yoksa atla

    # ── 2. DİSK KULLANIMI ───────────────────────────────────────────────────
    free_gb = get_free_disk_gb()
    total_gb = shutil.disk_usage(".").total / 1e9
    used_pct = (1 - free_gb / total_gb) * 100

    if used_pct > 85 and _should_alert("disk_critical", cooldown_hours=12):
        send_telegram(
            f"🚨 <b>Disk %{used_pct:.0f} Dolu!</b>\n"
            f"💾 {free_gb:.1f} GB kaldı / {total_gb:.0f} GB toplam\n"
            f"🔧 Çözüm:\n"
            f"• Eski render dosyaları temizleniyor...\n"
            f"• Veya Hetzner'da Volume ekle"
        )
        _mark_alert_sent("disk_critical")
        cleanup_old_renders(max_age_hours=24)
        alerts_sent.append("Disk kritik")

    elif used_pct > 70 and _should_alert("disk_warning", cooldown_hours=24):
        send_telegram(
            f"⚠️ <b>Disk %{used_pct:.0f} Dolu</b>\n"
            f"💾 {free_gb:.1f} GB kaldı\n"
            f"💡 Yakında yer açmak gerekebilir"
        )
        _mark_alert_sent("disk_warning")
        alerts_sent.append("Disk uyarı")

    # ── 3. KANAL SAYISI EŞİKLERİ ────────────────────────────────────────────
    try:
        from src.channel_manager import list_channels, get_channel
        active_channels = sum(
            1 for cid in list_channels()
            if Path(get_channel(cid).token_path).exists()
        )

        if active_channels >= 18 and _should_alert("channel_vps2", cooldown_hours=72):
            send_telegram(
                f"📡 <b>2. VPS Zamanı! ({active_channels} kanal)</b>\n"
                f"🔴 Tek VPS ile 20+ kanal verimli çalışmaz\n"
                f"💡 Yapılacak:\n"
                f"• 2. VPS aç (Hetzner CPX32)\n"
                f"• Kanalları ikiye böl (9+9)\n"
                f"• Ben kurulumu yaparım, söyle yeter"
            )
            _mark_alert_sent("channel_vps2")
            alerts_sent.append(f"{active_channels} kanal → 2. VPS")

        elif active_channels >= 13 and _should_alert("channel_cpx42", cooldown_hours=72):
            send_telegram(
                f"📊 <b>VPS Yükseltme Zamanı! ({active_channels} kanal)</b>\n"
                f"💡 CPX32 → CPX42 (16 GB RAM) yükselt\n"
                f"• console.hetzner.com → Servers → Rescale → CPX42\n"
                f"• €69/ay — 30 kanala kadar yeterli"
            )
            _mark_alert_sent("channel_cpx42")
            alerts_sent.append(f"{active_channels} kanal → CPX42")
    except Exception:
        pass

    # ── 4. ELEVENLABS KREDİ ──────────────────────────────────────────────────
    try:
        el_key = os.getenv("ELEVENLABS_API_KEY", "")
        if el_key and not el_key.startswith("your_"):
            import requests as _req
            r = _req.get("https://api.elevenlabs.io/v1/user",
                        headers={"xi-api-key": el_key}, timeout=8)
            if r.status_code == 200:
                sub = r.json().get("subscription", {})
                used = sub.get("character_count", 0)
                limit = sub.get("character_limit", 1)
                remaining_pct = (1 - used / limit) * 100

                if remaining_pct < 10 and _should_alert("el_critical", cooldown_hours=12):
                    send_telegram(
                        f"🔴 <b>ElevenLabs Kredi %{remaining_pct:.0f} Kaldı!</b>\n"
                        f"📊 {limit - used:,} / {limit:,} karakter\n"
                        f"💡 Seçenekler:\n"
                        f"• Creator → Pro yükselt ($99/ay, 600k kredi)\n"
                        f"• elevenlabs.io/app/subscription\n"
                        f"• Veya o 2 kanalı Azure'a geç (ücretsiz)"
                    )
                    _mark_alert_sent("el_critical")
                    alerts_sent.append("ElevenLabs kritik")

                elif remaining_pct < 25 and _should_alert("el_warning", cooldown_hours=24):
                    send_telegram(
                        f"⚠️ <b>ElevenLabs Kredi %{remaining_pct:.0f} Kaldı</b>\n"
                        f"📊 {limit - used:,} karakter kaldı\n"
                        f"💡 Yakında yükseltme gerekebilir:\n"
                        f"• elevenlabs.io/app/subscription → Pro ($99/ay)"
                    )
                    _mark_alert_sent("el_warning")
                    alerts_sent.append("ElevenLabs uyarı")
    except Exception:
        pass

    if alerts_sent:
        logger.info(f"Kapasite uyarıları gönderildi: {alerts_sent}")

    return alerts_sent


# ─── TOKEN SAĞLIK KONTROLÜ ───────────────────────────────────────────────────

def check_token_health(channel_cfg) -> tuple:
    """
    OAuth token geçerliliğini kontrol et.
    Süresi dolmuşsa yenilemeyi dene.
    Döner: (gecerli: bool, mesaj: str)
    """
    try:
        import pickle
        token_path = Path(channel_cfg.token_path)
        if not token_path.exists():
            return False, "Token dosyası yok — yeniden auth gerekli"

        with open(token_path, "rb") as f:
            creds = pickle.load(f)

        if not creds:
            return False, "Token boş"

        # Süresi dolmuş ama refresh_token varsa yenile
        if creds.expired:
            if not creds.refresh_token:
                return False, "Token süresi dolmuş, yenileme imkânsız — auth.py çalıştır"
            try:
                from google.auth.transport.requests import Request as GRequest
                creds.refresh(GRequest())
                with open(token_path, "wb") as f:
                    pickle.dump(creds, f)
                return True, "Token otomatik yenilendi ✅"
            except Exception as e:
                return False, f"Token yenileme başarısız: {e}"

        return True, "Token geçerli"
    except Exception as e:
        return False, f"Token kontrol hatası: {e}"


def verify_all_tokens() -> dict:
    """
    Tüm kanalların tokenlarını kontrol et.
    Sorunlu kanalları Telegram'a bildir.
    """
    from src.channel_manager import list_channels, get_channel
    results = {}
    broken = []

    for cid in list_channels():
        try:
            cfg = get_channel(cid)
            if not Path(cfg.token_path).exists():
                continue  # Token yoksa zaten inactive
            ok, msg = check_token_health(cfg)
            results[cid] = {"ok": ok, "msg": msg}
            if not ok:
                broken.append(f"• {cfg.name}: {msg}")
                logger.warning(f"[{cid}] Token sorunu: {msg}")
        except Exception as e:
            results[cid] = {"ok": False, "msg": str(e)}

    if broken:
        send_telegram(
            f"🔑 <b>Token Sorunu Tespit Edildi!</b>\n"
            f"Aşağıdaki kanallarda yeniden OAuth gerekiyor:\n\n"
            + "\n".join(broken)
            + "\n\n<code>python auth.py --channel KANAL_ID</code>"
        )

    return results


# ─── LOG ROTATION ─────────────────────────────────────────────────────────────

def rotate_log_file(log_path: str, max_lines: int = 8000):
    """
    Log dosyasını max_lines satıra kırp (en eski satırları at).
    Her gece maintenance_job tarafından çağrılır.
    """
    p = Path(log_path)
    if not p.exists():
        return
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
        if len(lines) > max_lines:
            trimmed = lines[-max_lines:]
            p.write_text("\n".join(trimmed) + "\n", encoding="utf-8")
            logger.info(f"Log rotate: {p.name} {len(lines)} → {max_lines} satır")
    except Exception as e:
        logger.warning(f"Log rotate hatası: {e}")


# ─── KUYRUK BAYAT GİRİŞ TEMİZLEME ────────────────────────────────────────────

def cleanup_stale_queue(queue: dict, tz, stale_hours: int = 3) -> tuple:
    """
    publishAt süresi geçmiş kuyruk girişlerini temizle.
    Servis o saatte kapalıysa kanal sıkışıp kalmasın.
    Döner: (temizlenmiş_kuyruk, temizlenen_kanal_listesi)
    """
    now = datetime.now(tz)
    cleaned = {}
    freed_channels = []

    for cid, entries in queue.items():
        valid = []
        removed = 0
        for entry in entries:
            publish_at_str = entry.get("publish_at", "")
            if not publish_at_str:
                valid.append(entry)
                continue
            try:
                pub_time = datetime.fromisoformat(publish_at_str)
                if pub_time.tzinfo is None:
                    import pytz
                    pub_time = pytz.utc.localize(pub_time)
                age = (now - pub_time).total_seconds() / 3600
                if age < stale_hours:
                    valid.append(entry)  # Henüz taze, tut
                else:
                    removed += 1  # Süresi geçmiş, at
            except Exception:
                valid.append(entry)  # Parse edilemezse tut

        cleaned[cid] = valid
        if removed > 0:
            freed_channels.append(cid)
            logger.info(f"[{cid}] {removed} bayat kuyruk girişi temizlendi → yeni render tetiklenecek")

    return cleaned, freed_channels

