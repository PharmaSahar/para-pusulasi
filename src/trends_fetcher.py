"""
Google Trends Entegrasyonu
Turkiye'de trend olan finansal konulari getirir.
"""
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

MARKET_KEYWORDS = (
    "bist",
    "hisse",
    "dolar",
    "usd",
    "try",
    "bitcoin",
    "ethereum",
    "btc",
    "eth",
    "kripto",
    "altin",
    "faiz",
    "enflasyon",
)

# Niş bazlı arama terimleri
NICHE_SEED_KEYWORDS = {
    "kisisel_finans": ["borsa", "dolar", "enflasyon", "yatirim", "faiz", "altın"],
    "borsa": ["BIST", "hisse senedi", "BIST100", "temettü", "borsa"],
    "kripto": ["bitcoin", "ethereum", "kripto para", "BTC", "altcoin"],
    "kariyer": ["is ilanı", "maas", "remote iş", "freelance", "kariyer"],
    "girisimcilik": ["startup", "e-ticaret", "girisim", "iş kurma", "pasif gelir"],
    "saglik": ["diyet", "beslenme", "spor", "sağlık", "psikoloji"],
    "teknoloji": ["yapay zeka", "ChatGPT", "teknoloji", "AI", "yazılım"],
    "egitim": ["online egitim", "kurs", "öğrenme", "üniversite", "sertifika"],
    "gayrimenkul": ["konut", "kira", "emlak", "ev fiyatları", "gayrimenkul"],
    "psikoloji": ["psikoloji", "motivasyon", "stres", "depresyon", "ilişki"],
}


def get_trending_topics(niche: str = "general", count: int = 5) -> list[str]:
    """
    Google Trends'den Türkiye gündem konularını getir.
    pytrends kütüphanesi kullanır.
    """
    return list(get_trending_topics_with_metadata(niche=niche, count=count).get("topics", []))


def get_trending_topics_with_metadata(niche: str = "general", count: int = 5) -> dict:
    """Return trending topics with provider raw/normalized rows for provenance."""
    normalized_niche = str(niche or "").strip().lower()
    meta = {
        "provider": "pytrends",
        "provider_status": "ok",
        "raw_provider_rows": [],
        "normalized_provider_rows": [],
        "topics": [],
        "fallback_invoked": False,
        "fallback_source": None,
    }
    try:
        from pytrends.request import TrendReq
        pytrends = TrendReq(hl="tr-TR", tz=180, timeout=(5, 10))

        seed_keywords = NICHE_SEED_KEYWORDS.get(normalized_niche, [])[:5]
        pytrends.build_payload(seed_keywords, cat=0, timeframe="now 7-d", geo="TR")

        related = pytrends.related_queries()
        topics = []
        for kw in seed_keywords:
            rising = None
            if kw in related:
                rising = related[kw].get("rising")
            if rising is None or len(rising) <= 0:
                continue
            for _, row in rising.head(2).iterrows():
                query = str(row.get("query", "")).strip()
                value = row.get("value")
                payload_row = {
                    "keyword": kw,
                    "query": query,
                    "value": value,
                }
                meta["raw_provider_rows"].append(payload_row)
                if query and len(query) > 3:
                    topics.append(query)
                    meta["normalized_provider_rows"].append(query)
        if topics:
            meta["topics"] = topics[:count]
            logger.info(f"Google Trends'den {len(topics)} trend konu bulundu: {topics[:3]}")
            return meta
    except Exception as e:
        meta["provider_status"] = f"error:{e.__class__.__name__}"
        logger.debug(f"Google Trends hatasi (fallback kullanilacak): {e}")

    # Fallback: niche-scoped static topics only (fail-closed for unknown niches)
    year = datetime.now().year
    fallback_topics = {
        "kisisel_finans": [
            f"Dolar/TL {year} sonu tahminleri",
            f"Enflasyona karsi en iyi yatirim araclari {year}",
            "Merkez Bankasi faiz karari ne anlama geliyor",
            f"BIST 100 {year} firsat hisseleri",
            f"Altin fiyatlari neden yukseliyor {year}",
        ],
        "borsa": [
            f"BIST 100 teknik analiz {year}",
            f"Temettü sezonu {year} en yüksek hisseler",
            "Yabanci yatirimci BIST'te ne aliyor",
        ],
        "kripto": [
            f"Bitcoin {year} sonu hedef fiyat",
            f"Ethereum guncel analiz {year}",
            f"Hangi altcoin alınır {year}",
        ],
        "saglik": [
            "Saglikli beslenme icin gunluk rutinler",
            "Uyku duzenini guclendirme yollari",
            "Stres yonetimi ve zihinsel denge",
        ],
        "teknoloji": [
            "Yapay zeka araclariyla verimlilik",
            "Yazilim ogrenme rotasi",
            "Teknoloji kariyerinde one gecme yollari",
        ],
        "egitim": [
            "Daha hizli ogrenme teknikleri",
            "Calisma disiplini kurma yolları",
            "Sinav ve beceri odakli gelisim planı",
        ],
        "kariyer": [
            "Maas pazarligi stratejileri",
            "Remote is duzeni kurma",
            "LinkedIn profilini guclendirme",
        ],
        "girisimcilik": [
            "Startup fikrini dogrulama",
            "Ilk musteriye ulasma",
            "E-ticaret baslangic adimlari",
        ],
        "psikoloji": [
            "Stresle basa cikma yontemleri",
            "Ozguven gelistirme aliskanliklari",
            "Iliski ve duygu duzenleme becerileri",
        ],
        "gayrimenkul": [
            f"{year}'da konut aliminda dikkat edilmesi gerekenler",
            "Kira pazari dinamikleri",
            "Yatirimlik konut secim kriterleri",
        ],
    }
    fallback = list(fallback_topics.get(normalized_niche, []))[:count]
    meta["fallback_invoked"] = True
    meta["fallback_source"] = f"static_niche:{normalized_niche or 'unknown'}"
    meta["provider"] = "static_fallback"
    meta["topics"] = fallback
    meta["normalized_provider_rows"] = list(fallback)
    for item in fallback:
        meta["raw_provider_rows"].append({"keyword": normalized_niche, "query": item, "value": None})
    return meta


def get_seasonal_boost_topics(niche: str) -> list[str]:
    """Mevsimsel yüksek talep konuları."""
    month = datetime.now().month
    seasonal = {
        1: ["Yeni yil finansal hedefleri", "Ocak vergi beyannamesi"],
        3: ["Mart temettü haberleri", "Yil basi portfoy degerlendirme"],
        6: ["Yaz sezonu yatirim stratejisi", "Tasinmaz alimi yaz sezonu"],
        9: ["Eylul okullar acildi butce planlama", "Sonbahar borsa stratejisi"],
        12: ["Yil sonu vergi optimizasyonu", "2025 yatirim onerileri"],
    }
    return seasonal.get(month, [])
