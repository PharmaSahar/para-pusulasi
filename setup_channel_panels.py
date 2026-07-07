"""
YouTube Kanal Panel Otomatik Kurulum
4 aktif kanal için:
- Kanal bölümleri (Son Videolar, Popüler)
- Kanal açıklaması ve anahtar kelimeler
- Branding ayarları
"""
import sys
import os
import logging
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')
logger = logging.getLogger(__name__)

from src.channel_manager import get_channel, list_channels
from src.youtube_auth import get_authenticated_service
from pathlib import Path

# Kanal başına özelleştirilmiş açıklamalar
CHANNEL_DESCRIPTIONS = {
    "para_pusulasi": """Türkiye'nin en kapsamlı kişisel finans kanalı! 💰

Her gün yeni video:
✅ Dolar/TL analizi ve tahminler
✅ Borsa ve hisse senedi rehberi  
✅ Kripto para piyasaları
✅ Yatırım stratejileri
✅ Birikim ve tasarruf tüyoları

🔔 Bildirimleri açarak yeni videoları kaçırmayın!

📱 Ücretsiz yatırım hesabı: https://www.binance.com/register?ref=PUSULASI

#ParaPusulası #Finans #Yatırım #Borsa #Kripto""",

    "borsa_akademi": """BIST ve küresel piyasalar için Türkiye'nin borsa akademisi! 📈

Her gün yeni analiz:
✅ BIST 100 teknik analiz
✅ Hisse senedi değerlendirmeleri
✅ Temettü yatırımı rehberi
✅ Grafik okuma teknikleri
✅ Portföy yönetimi stratejileri

🔔 Bildirimleri açın, günlük analizleri kaçırmayın!

#BorsaAkademi #BIST100 #Hisse #TeknikAnaliz #Temettü""",

    "kripto_rehber": """Bitcoin ve kripto para piyasaları için tam rehber! ₿

Her gün yeni içerik:
✅ Bitcoin fiyat analizi
✅ Altcoin araştırmaları
✅ DeFi ve Web3 rehberi
✅ NFT piyasası
✅ Kripto cüzdan güvenliği

🔔 Bildirimleri açın!
💱 Binance ile kripto ticaretine başla: https://www.binance.com/register?ref=PUSULASI

#KriptoRehber #Bitcoin #Kripto #BTC #Ethereum""",

    "kariyer_pusulasi": """Kariyerinde zirveye çıkmak için rehberin! 🚀

Her gün yeni içerik:
✅ Maaş müzakeresi teknikleri
✅ Kariyer gelişimi stratejileri
✅ İş hayatında başarı sırları
✅ Freelance ve uzaktan çalışma
✅ LinkedIn optimizasyonu

🔔 Bildirimleri açarak kariyer fırsatlarını kaçırmayın!

#KariyerPusulası #Kariyer #Maaş #İş #Freelance"""
}

CHANNEL_KEYWORDS = {
    "para_pusulasi": ["kişisel finans", "yatırım", "borsa", "kripto", "dolar", "tasarruf", "emeklilik", "birikim"],
    "borsa_akademi": ["borsa", "BIST", "hisse senedi", "teknik analiz", "temettü", "portföy", "yatırım"],
    "kripto_rehber": ["kripto", "bitcoin", "ethereum", "blockchain", "DeFi", "altcoin", "NFT"],
    "kariyer_pusulasi": ["kariyer", "maaş", "iş", "freelance", "uzaktan çalışma", "LinkedIn", "liderlik"]
}


def setup_channel(channel_id: str):
    """Bir kanalı tam olarak kur."""
    try:
        cfg = get_channel(channel_id)
        token_path = Path(cfg.token_path)
        if not token_path.exists():
            logger.warning(f"[{channel_id}] Token yok, atlanıyor")
            return False

        service = get_authenticated_service(cfg)
        logger.info(f"[{cfg.name}] Bağlandı, düzenleniyor...")

        # 1. Kanal açıklaması ve anahtar kelimeler
        description = CHANNEL_DESCRIPTIONS.get(channel_id, f"{cfg.name} - Finans ve Yatırım Rehberi")
        keywords = CHANNEL_KEYWORDS.get(channel_id, ["finans", "yatırım", "para"])

        channels_resp = service.channels().list(part="snippet,brandingSettings", mine=True).execute()
        if not channels_resp.get("items"):
            logger.error(f"[{channel_id}] Kanal bulunamadı")
            return False

        channel_resource = channels_resp["items"][0]
        channel_yt_id = channel_resource["id"]

        # Kanal bilgilerini güncelle
        update_body = {
            "id": channel_yt_id,
            "brandingSettings": {
                "channel": {
                    "description": description,
                    "keywords": " ".join(f'"{kw}"' for kw in keywords),
                    "country": "TR",
                    "defaultLanguage": cfg.language if hasattr(cfg, 'language') else "tr",
                }
            }
        }

        service.channels().update(
            part="brandingSettings",
            body=update_body
        ).execute()
        logger.info(f"[{cfg.name}] ✅ Açıklama ve anahtar kelimeler güncellendi")

        # 2. Kanal bölümleri ekle
        _add_channel_sections(service, cfg.name)

        return True

    except Exception as e:
        logger.error(f"[{channel_id}] Hata: {e}")
        return False


def _add_channel_sections(service, channel_name: str):
    """Kanal layout bölümleri ekle."""
    # Mevcut bölümleri kontrol et
    try:
        existing = service.channelSections().list(
            part="snippet", mine=True
        ).execute()
        existing_types = {s["snippet"].get("type", "") for s in existing.get("items", [])}
    except Exception:
        existing_types = set()

    sections_to_add = [
        {
            "snippet": {
                "type": "recentUploads",
                "title": "Son Videolar",
                "position": 0,
            }
        },
        {
            "snippet": {
                "type": "singlePlaylist",
                "title": "Öne Çıkan Videolar",
                "position": 1,
            }
        },
    ]

    added = 0
    for section in sections_to_add:
        section_type = section["snippet"]["type"]
        if section_type in existing_types:
            logger.info(f"[{channel_name}] '{section_type}' bölümü zaten var")
            continue
        try:
            service.channelSections().insert(
                part="snippet",
                body=section
            ).execute()
            logger.info(f"[{channel_name}] ✅ '{section['snippet']['title']}' bölümü eklendi")
            added += 1
        except Exception as e:
            logger.warning(f"[{channel_name}] Bölüm eklenemedi ({section_type}): {e}")

    if added == 0 and existing_types:
        logger.info(f"[{channel_name}] Bölümler zaten mevcut")


if __name__ == "__main__":
    active_channels = ["para_pusulasi", "borsa_akademi", "kripto_rehber", "kariyer_pusulasi"]
    
    print("=" * 55)
    print("  YouTube Kanal Panel Otomatik Kurulum")
    print("=" * 55)
    
    success = 0
    for cid in active_channels:
        print(f"\n→ {cid} düzenleniyor...")
        if setup_channel(cid):
            success += 1
    
    print(f"\n{'=' * 55}")
    print(f"  Tamamlandı: {success}/{len(active_channels)} kanal")
    print("=" * 55)
