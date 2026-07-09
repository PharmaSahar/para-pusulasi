"""
Gelismis Icerik Uretici - v2.0
Claude AI + Ust Duzey Prompt Muhendisligi
"""
import json
import logging
import os
import random
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import anthropic

from .channel_dna import build_channel_dna_metadata
from .config import config
from .prompt_registry import build_prompt_metadata
from .quality_scoring import build_quality_scores

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# SISTEM PROMPTU - Kanal Kimligi ve Icerik Stratejisi
# ─────────────────────────────────────────────────────────────────────────────
CHANNEL_PERSONA = """Sen "Para Pusulas" adli Turkiye'nin en hizli buyuyen kisisel finans YouTube kanalinin icerik direktoru ve bas senaristsin.

KANAL KIMLIGIN:
- Kanal adi: Para Pusulasi
- Slogan: "Paranizi calismaya gonderin!"
- Ton: Samimi, gercekci, heyecanli ama bilimsel temelli
- Hedef kitle: Turkiye'de 25-50 yas, aylik 15.000-80.000 TL gelirli, yatirim yapmak isteyen bireyler
- Dil: Akici Turkce, teknik terimler varsa kisa aciklama

VIRAL ICERIK FORMULUN (Bu formulu her videon icin uygula):
1. HOOK (0-30 sn): Sok edici bir istatistik veya soru ile baslat
   - "Turkiye'de her 10 kisi 8'i emekli oluncaya kadar yeterli birikimi yok"
   - "Bu videoyu izleyenler ortalama 3 ay sonra ilk yatirimlarini yapti"
2. ONCEKI VIDEODAN REFERANS (30-45 sn): Kanal surekliligini kur
3. ANA ICERIK (Bolumler halinde, her bolum 2-3 dk): Net, ogretici, somut
4. GERCEK RAKAMLAR: Hep 5.000-250.000 TL arasi kullan, kucuk rakamlardan kac
5. 2026 GUNCEL VERILERI: Enflasyon, BIST, dolar kuru gercekligi
6. CTA (Orta): "Abone ol, bildirimi ac" - izleyiciyi kaybetme
7. SONUC + SONRAKI VIDEO DUYURUSU: Merak birak, bir sonraki konuyu duyur

BASLIK KURALLARI (YouTube Algoritmasini Kir):
- Sayi + Somut Sonuc + Yil: "37.000 TL ile 8 Ayda %94 Getiri (2026 Gercek Hesabi)"
- Merak + Kayip Korkusu: "Bu Hatadan Habersizseniz Birikimleriniz Eriyecek"
- Karsilastirma: "Borsa mi Altin mi? 10.000 TL ile 12 Ay Test Ettim"
- Kisisel Hikaye: "Maasimin %40'ini Biriktiren Adamla 1 Gun Gecirdim"
- Soru: "Neden Zenginler Daha Zengin Olur? (Cevap Sizi Sok Edecek)"

KISALTMALAR:
- TL rakamlarini hep buyuk goster: 25.000 TL, 100.000 TL
- BIST, BTC, ETH gibi kisaltmalari ilk geciste acikla
- Yuzde degerleri somut goster: "Her ay 7.500 TL ayirarak..."
"""

CONTENT_SAFETY_BOUNDARY = """

KANAL UYUMLULUK VE FACT-CHECK SINIRI:
- Kanalin ana konusu finans veya piyasa degilse, BIST, hisse, dolar kuru, Bitcoin, altin, faiz ve enflasyon gibi piyasa referanslarini kendiliginden ekleme.
- Bu tur piyasa referanslarini ancak konu dogrudan bunun uzerineyse ve dogrulanabilir bicimde ele aliniyorsa kullan.
- Dogrulanamayan fiyat hedefi, endeks seviyesi, yuzde oran veya tarih iddiasi uretme.
- Egitim, saglik, teknoloji, kariyer ve girisim konularinda gereksiz finansal iddialar yerine alanin kendi temel prensiplerine odaklan.
"""

TOPIC_CATEGORIES = {
    "kisisel_finans": [
        "BIST'te en cok temettü veren hisseler",
        "Enflasyona karsi portfoy stratejileri",
        "Emekli sandigi vs ozel BES karsilastirmasi",
        "Kira geliri vs borsa getirisi",
        "Dolar endeksli yatirim araclari",
        "Aylık 10.000 TL biriktirme stratejileri",
        "Kripto portfoy yonetimi 2026",
        "FIRE hareketi Turkiye'de mumkun mu",
        "Konut yatirimi vs finansal yatirim",
        "Vergi avantajli yatirim araclari",
    ],
    "teknoloji": [
        "Yapay zeka ile para kazanma yollari",
        "Freelance yazilimci olmak 2026",
        "Pasif gelir yaratan dijital urunler",
        "NFT ve Web3 gercekligi",
        "AI araclarla verimlilik",
    ],
    "egitim": [
        "Calisma disiplini kurma yollari",
        "Not alma ve ozetleme teknikleri",
        "Daha hizli ogrenme yontemleri",
        "Online kurs secme rehberi",
        "Sinav hazirlik rutini",
    ],
    "saglik": [
        "Saglikli beslenme aliskanliklari",
        "Uyku kalitesini artirma yollari",
        "Stres yonetimi ve nefes teknikleri",
        "Evde uygulanabilir egzersiz rutinleri",
        "Uzun omur ve gunluk saglik aliskanliklari",
    ],
    "kariyer": [
        "Maas pazarligi yaparken dikkat edilmesi gerekenler",
        "Remote calisma duzeni kurma",
        "LinkedIn profilini guclendirme",
        "Freelance kariyer baslangici",
        "Is gorusmesi hazirlik sistemi",
    ],
    "girisimcilik": [
        "Startup fikrini test etme",
        "E-ticaret baslangic adimlari",
        "Pazarlama kanali secimi",
        "Pasif gelir modelleri",
        "Ilk musteri bulma yontemleri",
    ],
}

MARKET_SENSITIVE_NICHES = {"kisisel_finans", "borsa", "kripto", "gayrimenkul"}


def _is_market_sensitive_niche(niche: str | None) -> bool:
    return (niche or "").strip().lower() in MARKET_SENSITIVE_NICHES


MARKET_TOPIC_RE = re.compile(
    r"\b(bist\w*|borsa\w*|hisse\w*|dolar\w*|usd\w*|try\w*|bitcoin\w*|ethereum\w*|btc\w*|eth\w*|kripto\w*|altin\w*|faiz\w*|enflasyon\w*|yatirim\w*|temettu\w*|portfoy\w*|teknik\s+analiz|temel\s+analiz|risk\s+yonetimi)\b",
    re.IGNORECASE,
)


def _filter_trending_topics_for_niche(
    topics: list[str],
    *,
    niche: str | None,
    channel_topics: list[str] | None = None,
) -> list[str]:
    if _is_market_sensitive_niche(niche):
        return topics

    filtered: list[str] = []
    seen: set[str] = set()
    normalized_channel_topics = [topic.lower() for topic in (channel_topics or [])]

    for topic in topics:
        lowered = topic.strip().lower()
        if not lowered or lowered in seen:
            continue
        seen.add(lowered)

        has_market_keyword = bool(MARKET_TOPIC_RE.search(topic))
        mentions_channel_topic = any(token in lowered for token in normalized_channel_topics)
        if has_market_keyword and not mentions_channel_topic:
            continue
        filtered.append(topic)

    return filtered


def _fallback_topics_for_niche(niche: str | None, channel_topics: list[str] | None = None) -> list[str]:
    fallback = list(channel_topics or [])
    fallback.extend(TOPIC_CATEGORIES.get((niche or "").strip().lower(), []))
    return _filter_trending_topics_for_niche(
        fallback,
        niche=niche,
        channel_topics=channel_topics,
    )


def _get_trending_topics(niche: str | None = None, channel_topics: list[str] | None = None) -> list[str]:
    """Return niche-aware trending seeds for topic generation."""
    normalized_niche = (niche or "").strip().lower()

    if _is_market_sensitive_niche(normalized_niche):
        return [
            "Merkez Bankasi faiz kararinin portfoya etkisi",
            "2026 BIST 100 tahminleri ve firsat hisseleri",
            "Dolar/TL volatilitesinde portfoy koruma",
            "Kripto piyasasindaki son gelismeler ve etkileri",
            "Enflasyona karsi en iyi 5 yatirim araci",
            "Borsa yeni baslayanlarin en cok yaptigi 7 hata",
            "BES emeklilik sisteminde degisiklikler ne anlama geliyor",
            "2026'da gayrimenkul yatirimi mantikli mi",
        ]

    niche_topics = list(TOPIC_CATEGORIES.get(normalized_niche, []))
    if channel_topics:
        niche_topics.extend(channel_topics)

    deduped: list[str] = []
    seen: set[str] = set()
    for topic in niche_topics:
        lowered = topic.strip().lower()
        if not lowered or lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(topic)
    return _filter_trending_topics_for_niche(
        deduped,
        niche=niche,
        channel_topics=channel_topics,
    )


def _load_used_titles() -> list[str]:
    """Onceden uretilmis basliklar - tekrar onlemek icin."""
    titles = []
    scripts_dir = config.scripts_dir
    if not Path(scripts_dir).exists():
        return []
    for path in Path(scripts_dir).glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if "title" in data:
                titles.append(data["title"])
        except Exception:
            pass
    return titles


# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class VideoContent:
    title: str
    description: str
    tags: list[str]
    script: str
    thumbnail_prompt: str
    category_id: str
    niche: str
    hook: str = ""
    next_video_teaser: str = ""
    pexels_search: str = ""   # Konuya özgün Pexels arama terimi
    chart_data: dict = field(default_factory=dict)  # Finansal grafik verisi
    prompt_metadata: dict = field(default_factory=dict)
    channel_dna_metadata: dict = field(default_factory=dict)
    quality_score_metadata: dict = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "description": self.description,
            "tags": self.tags,
            "script": self.script,
            "thumbnail_prompt": self.thumbnail_prompt,
            "category_id": self.category_id,
            "niche": self.niche,
            "hook": self.hook,
            "next_video_teaser": self.next_video_teaser,
            "pexels_search": self.pexels_search,
            "chart_data": self.chart_data,
            "prompt_metadata": self.prompt_metadata,
            "channel_dna_metadata": self.channel_dna_metadata,
            "quality_score_metadata": self.quality_score_metadata,
            "created_at": self.created_at,
        }

    def save(self, path: str | None = None) -> str:
        if not path:
            safe_title = "".join(c for c in self.title[:40] if c.isalnum() or c in " _-").strip()
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = f"{config.scripts_dir}/{ts}_{safe_title}.json"
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Script kaydedildi: " + path)
        return path

    def seo_description(self) -> str:
        """SEO + affiliate + cross-promotion aciklama."""
        try:
            from .monetization import get_description_with_affiliate, get_cross_promotion
            has_monetization = True
        except Exception:
            has_monetization = False

        first_line = f"{self.title} | Para Pusulasi"
        chapters = (
            "⏱️ BOLUMLER:\n"
            "00:00 Giris - Hook\n"
            "00:30 Kanal Tanitimi\n"
            "01:30 Temel Kavramlar\n"
            "04:00 Gercek Rakamlar ve Hesaplamalar\n"
            "07:30 Adim Adim Rehber\n"
            "10:00 Yapilan Hatalar\n"
            "11:00 Ozet ve Bir Sonraki Video\n"
            "11:30 Abone Ol"
        )
        tag_sentence = ""
        if self.tags:
            tag_sentence = f"\nAnahtar kelimeler: {', '.join(self.tags[:6])}."
        hashtags = " ".join(f"#{t.replace(' ', '').replace('-', '')}" for t in self.tags[:15])
        cross_promo = get_cross_promotion(self.niche) if has_monetization else ""
        base = f"{first_line}\n\n{self.description}\n\n{chapters}{tag_sentence}{cross_promo}\n\n{hashtags}"
        if has_monetization:
            return get_description_with_affiliate(self.niche, base)
        return base


# ─────────────────────────────────────────────────────────────────────────────
def _build_topic_prompt(
    count: int,
    used_titles: list[str],
    *,
    niche: str | None = None,
    channel_name: str = "Para Pusulasi",
    channel_topics: list[str] | None = None,
) -> str:
    year = datetime.now().year
    trending = _load_trending_context(niche=niche, channel_topics=channel_topics)
    avoid = ""
    if used_titles:
        last_10 = used_titles[-10:]
        avoid = "\n\nKESINLIKLE BUNLARI TEKRAR ONERME (zaten yapildi):\n" + "\n".join(f"- {t}" for t in last_10)

    normalized_niche = (niche or "").strip().lower()
    if _is_market_sensitive_niche(normalized_niche):
        return f"""{channel_name} kanalı icin {count} adet viral video konusu oner.

KRITERLER:
- {year} Turkiye finans gundemiyle alakali
- Her konu farkli bir alt nisite olmali (borsa, kripto, butce, emeklilik, vs.)
- Basliklar icin somut rakamlar kullan (5.000-250.000 TL arasi)
- Clickbait ama yaniltici olmayan, egitici konular
- Her satira sadece konu yaz, baska hicbir sey ekleme

GUNCEL GUNDEM:
{trending}
{avoid}

{count} konu:"""

    niche_label = normalized_niche or "genel"
    return f"""{channel_name} kanalı icin {count} adet viral video konusu oner.

KRITERLER:
- Konular kanalın ana nişi olan '{niche_label}' ile doğrudan ilgili olsun
- Finansal piyasa, BIST, hisse, dolar kuru, Bitcoin, altın, faiz ve enflasyon iddialarını kendiliğinden ekleme
- Clickbait ama yaniltici olmayan, egitici konular üret
- Gerekmedikçe somut piyasa rakamı, hedef fiyat, yüzde oran veya tarih içeren başlık kurma
- Her satira sadece konu yaz, baska hicbir sey ekleme

NIS ODAKLARI:
{trending}
{avoid}

{count} konu:"""


def _load_trending_context(niche: str | None = None, channel_topics: list[str] | None = None) -> str:
    trends = _get_trending_topics(niche=niche, channel_topics=channel_topics)
    selected = random.sample(trends, min(4, len(trends)))
    return "\n".join(f"- {t}" for t in selected)


def _build_content_prompt(
    topic: str,
    prev_title: str | None,
    next_topic_hint: str,
    content_type: str = "semi_evergreen",
    additional_guidance: str | None = None,
    niche: str | None = None,
) -> str:
    year = datetime.now().year
    strict_fact_mode = bool(additional_guidance and "FACT-CHECK SAFE MODE" in additional_guidance)
    market_sensitive_niche = _is_market_sensitive_niche(niche)

    # SONSUZ ÇEŞİTLİLİK: Sabit şablon değil, parametrik sistem
    # Her parametre bağımsız rastgele → 10×8×6×5×4 = 9,600 benzersiz kombinasyon

    openings = [
        "Korkutucu bir istatistikle başla — izleyicinin aklına kazın",
        "Gerçek bir Türk vatandaşının 30 saniyeyi geçmeyen şaşırtıcı hikayesi",
        "Tartışmalı bir soru sor, cevabını videoyu izlemeden veremezler",
        "Yaygın bir inanışın tamamen yanlış olduğunu iddia et",
        "En az 3 kişinin bilmediği bir 'insider sırrı' var gibi başla",
        "Piyasada herkesin yaptığı ama yanlış olan şeyi açıkla",
        "İzleyiciyi bir seçim yapmaya zorla: 'Şu ikisinden hangisi daha mantıklı?'",
        "Son 24 saatte yaşanan bir gelişmenin uzun vadeli sonucunu analiz et",
        "2026'da çoğu insanın yapmadığı ama yapması gereken şeyi söyle",
        "Bir komplo teorisi gibi başla, sonra verilerle çürüt veya doğrula",
    ]

    narrative_styles = [
        "BİLİM + HİKAYE: Araştırma bulgusu + Türkiye'den gerçek örnek",
        "KARŞILAŞTIRMA: İki farklı stratejiyi yan yana koy, verilerle değerlendir",
        "ZAMAN YOLCULUĞU: 5 yıl önce yapılsaydı ne olurdu, şimdi ne olacak?",
        "UZMAN YANILIYOR: Yaygın tavsiyenin neden işe yaramadığını göster",
        "VAKA ANALİZİ: Gerçek bir yatırımcının kararlarını adım adım incele",
        "KARŞI GÖRÜŞ: En çok savunulan fikri sorgula, alternatif sun",
        "SAYILARLA KONUŞ: Her iddiayı somut TL rakamıyla destekle",
        "SENARYOLAR: 3 farklı karar, 10 yıl sonra üçünün de sonucunu göster",
    ]

    evidence_types = [
        "Türkiye İstatistik Kurumu + BDDK verileri ağırlıklı",
        "Başarı + başarısızlık hikayelerini karşılaştırmalı kullan",
        "Matematiksel hesaplama: 'Şöyle hesaplarsak...' formatı",
        "Uluslararası karşılaştırma: 'Almanya'da böyle, Türkiye'de şöyle'",
        "Tarihsel veri: 'Son 10 yılda şu yaşandı, şimdi...'",
        "Uzman görüşü: Gerçek isimleri al, alıntı yap",
    ]

    emotional_angles = [
        "FIRSATÇILIK: 'Şu an yapamayanlar 5 yıl pişman olacak'",
        "KORUMA: 'Birikimlerinizi şu tehlike yiyor, bunu durdurun'",
        "MERAK: 'Zenginlerin bilip paylaşmadığı bilgi' çekimi",
        "İLHAM: 'Sıradan bir Türk vatandaşı bunu yaparak...'",
        "ÖFKE: 'Sistem sizi kandırıyor ama bunu yaparsan kurtulursun'",
    ]

    pacing_styles = [
        "HIZLI: Kısa cümleler, sık geçişler, enerji yüksek",
        "ANALİTİK: Her iddianın arkasında kaynak, yavaş ama derin",
        "SAMİMİ SOHBET: Arkadaşla konuşur gibi, samimi, espri var",
        "HABERDAR: Gazeteci tonu, olayları aktarır, yorumlar",
    ]

    # Her çalıştırmada farklı kombinasyon
    chosen = {
        "opening": random.choice(openings),
        "narrative": random.choice(narrative_styles),
        "evidence": random.choice(evidence_types),
        "emotion": random.choice(emotional_angles),
        "pacing": random.choice(pacing_styles),
    }

    type_instruction = {
        "evergreen": "Tarih veya geçici rakam KULLANMA — video 2-3 yıl boyunca değerini korusun.",
        "semi_evergreen": f"{year} verilerini kullan ama temel bilgiler zamansız olsun.",
        "trending": f"Bu hafta gündemde olan meseleyi yorumla — hız ve güncellik öncelikli.",
    }.get(content_type, "")

    extra_guidance = f"\nEK YONLENDIRME: {additional_guidance}\n" if additional_guidance else ""
    title_rule = "60 karakter altı, özgün, viral başlık"
    number_style_rule = "• Rakamları net ver: 'Yani ayda 7.500 TL — yılda 90.000 TL'"
    real_world_rule = "• Türkiye gerçekliğini yansıt: enflasyon, kira, maaş baskısı"
    strict_mode_block = ""

    if market_sensitive_niche and not strict_fact_mode:
        title_rule = f"60 karakter altı, özgün, {year} içeren viral başlık"
    else:
        number_style_rule = "• Canlı piyasa rakamı, hedef fiyat, kesin yüzde veya tarih verme; gerekiyorsa yalnızca açıkça varsayımsal eğitim örneği kullan"
        strict_mode_block = """
FACT-CHECK SAFE MODE AKTIF:
• Başlıkta, hook'ta ve scriptte kesin fiyat hedefi, endeks seviyesi, yıl sonu tahmini, ETF/onay tarihi veya son tarih yazma
• 'X olacak', 'Y seviyesine gelir', 'şu tarihte kesin olur' gibi ifadeleri kullanma
• Konuyu risk yönetimi, temel prensipler, tarihsel dersler ve davranışsal hatalar üzerinden anlat
• Volatil piyasa örnekleri vereceksen, bunları açıkça tarihsel veya varsayımsal eğitim örneği olarak etiketle
"""
        if not market_sensitive_niche:
            real_world_rule = "• Kanalın kendi alanındaki günlük, somut ve pratik örnekleri kullan; alakasız piyasa referansları ekleme"

    return f"""Türk finans YouTube kanalı için TAMAMEN ORİJİNAL, YAPAY HİSSETTİRMEYEN senaryo yaz.

KONU: {topic}
YIL: {year}
İÇERİK TÜRÜ: {type_instruction}
{extra_guidance}

BU VİDEO İÇİN SEÇILEN YARATICI PARAMETRELER:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎬 AÇILIŞ STİLİ: {chosen["opening"]}
📖 ANLATIM YAKLAŞIMI: {chosen["narrative"]}
📊 KANIT TÜRÜ: {chosen["evidence"]}
💡 DUYGUSAL AÇI: {chosen["emotion"]}
⚡ TEMPO: {chosen["pacing"]}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Bu parametreler bu video için özel tasarlandı. Başka video gibi OLMAMALI.
Yapıyı kendin oluştur — senaryo akışı bu parametrelerin kombinasyonundan doğsun.

KESİNLİKLE YASAKLANAN İFADELER:
✗ "Ekranda gördüğünüz gibi..." (görsel yok, ses-odaklı içerik)
✗ "Grafikte de görüldüğü üzere..." (grafik yok)
✗ "Bu videonun X. dakikasında..." (yapay zaman referansı)
✗ "Geçen haftaki videomuzda işlemiştik..." (her video bağımsız)
✗ "Bir önceki videodan hatırlayacağınız..." (yapmacık)
✗ "Merhaba sevgili izleyiciler..." (robotik)
✗ "Bugünkü konumuz şu..." (sıkıcı standart)
✗ "Videoyu izlemeye devam ederseniz..." (izleyiciyi kaçırır)

DOĞAL TÜRK FİNANS YOUTUBER'I TONU:
• Samimi, konuşma dili ama bilgi dolu
• "Bak sana şunu söyleyeyim..." "Şimdi düşün bir..." gibi geçişler
{number_style_rule}
{real_world_rule}
• İzleyicinin hayatına dokunan anlar yarat

{strict_mode_block}

Sadece JSON döndür:

{{
    "title": "{title_rule}",
  "hook": "İlk 30 saniye — seçilen açılış stiline göre özgün, şaşırtıcı (görsel referans YASAK)",
  "description": "SEO açıklaması: 5 paragraf, 300+ kelime, başlık keywordlerini içersin",
  "tags": ["minimum 20 Türkçe/İngilizce etiket"],
  "script": "TAM SENARYO (2000+ kelime) — seçilen parametrelere göre ÖZGÜN yapı. Klişe bölüm başlıkları KULLANMA.",
  "next_video_teaser": "Bir cümle merak bırak: '{next_topic_hint}'",
    "thumbnail_prompt": "Konuya ÖZGÜN İngilizce görsel: tek ana fikir, yüksek kontrast, mobilde okunur boş alan, net duygu, sinematik ışık, 1 odak nesne veya yüz ifadesi — 'business finance' gibi genel terimler KULLANMA",
  "pexels_search": "Bu videonun KONUSUNA ÖZGÜ 3-5 kelimelik İngilizce Pexels arama terimi (örn: 'crypto trader phone night city' veya 'retirement couple beach sunset happy')",
  "chart_data": "Varsa bu videoda gösterilebilecek 1 finansal veri seti (JSON formatında): {{'type': 'bar|line|pie', 'title': 'Grafik başlığı', 'data': {{'labels': [...], 'values': [...]}}}}, yoksa null",
  "category_id": "27"
}}
}}"""


# ─────────────────────────────────────────────────────────────────────────────
class ContentGenerator:
    def __init__(self, channel_cfg=None):
        from .config import config as _cfg
        cfg = channel_cfg if channel_cfg else _cfg
        self.client = anthropic.Anthropic(api_key=cfg.anthropic_api_key)
        self.niche = cfg.niche
        self.model = "claude-opus-4-5"
        # Kanal personasini kullan
        if channel_cfg and hasattr(channel_cfg, "persona"):
            self._persona = channel_cfg.persona
            self._channel_name = channel_cfg.name
        else:
            self._persona = None
            self._channel_name = "Para Pusulasi"

        self._channel_topics = list(getattr(channel_cfg, "topics", []) or [])

        self._channel_dna_overrides = self._extract_channel_dna_overrides(channel_cfg)

    def _system_prompt(self) -> str:
        base_persona = self._persona or CHANNEL_PERSONA
        return f"{base_persona.rstrip()}\n{CONTENT_SAFETY_BOUNDARY}"

    @staticmethod
    def _extract_channel_dna_overrides(channel_cfg) -> dict:
        if not channel_cfg:
            return {}
        candidate_fields = {
            "tone": getattr(channel_cfg, "tone", None),
            "audience": getattr(channel_cfg, "audience", None),
            "voice_archetype": getattr(channel_cfg, "voice_archetype", None),
            "evidence_style": getattr(channel_cfg, "evidence_style", None),
            "forbidden_patterns": getattr(channel_cfg, "forbidden_patterns", None),
            "signature_structure": getattr(channel_cfg, "signature_structure", None),
            "channel_dna_version": getattr(channel_cfg, "channel_dna_version", None),
        }
        return {key: value for key, value in candidate_fields.items() if value is not None}

    def generate_topic_ideas(self, count: int = 10) -> list[str]:
        used = _load_used_titles()

        # Google Trends'den güncel konuları al
        trending_from_web = []
        try:
            from .trends_fetcher import get_trending_topics, get_seasonal_boost_topics
            trending_from_web = get_trending_topics(self.niche, count=4)
            seasonal = get_seasonal_boost_topics(self.niche)
            trending_from_web = (seasonal + trending_from_web)[:4]
            trending_from_web = _filter_trending_topics_for_niche(
                trending_from_web,
                niche=self.niche,
                channel_topics=self._channel_topics,
            )
            logger.info(f"Google Trends: {trending_from_web[:2]}")
        except Exception:
            pass

        avoid = ""
        if used:
            last_10 = used[-10:]
            avoid = "\n\nKESINLIKLE BUNLARI TEKRAR ONERME:\n" + "\n".join(f"- {t}" for t in last_10)

        trend_hint = ""
        if trending_from_web:
            trend_hint = f"\n\nSU AN TRENDDE OLAN KONULAR (bunlara benzer konular oner):\n" + "\n".join(f"- {t}" for t in trending_from_web)

        prompt = _build_topic_prompt(
            count,
            used,
            niche=self.niche,
            channel_name=self._channel_name,
            channel_topics=self._channel_topics,
        ) + trend_hint + avoid
        logger.info(f"'{self.niche}' icin {count} konu uretiliyor...")

        response = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=self._system_prompt(),
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text
        ai_topics = [
            line.strip().lstrip("0123456789.-) ").strip()
            for line in raw.strip().splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        combined = trending_from_web[:2] + [t for t in ai_topics if t not in trending_from_web]
        combined = _filter_trending_topics_for_niche(
            combined,
            niche=self.niche,
            channel_topics=self._channel_topics,
        )
        if not combined:
            combined = _fallback_topics_for_niche(self.niche, self._channel_topics)
        logger.info(f"{len(combined[:count])} konu hazir.")
        return combined[:count]

    def generate_video_content(
        self,
        topic: str,
        prev_title: str | None = None,
        additional_guidance: str | None = None,
    ) -> VideoContent:
        # Bir sonraki video ipucu
        topics = self.generate_topic_ideas(count=3)
        next_hint = topics[-1] if topics else "Yatirim hatalarından nasil kacinilir"

        prompt = _build_content_prompt(
            topic,
            prev_title,
            next_hint,
            getattr(self, '_last_content_type', 'semi_evergreen'),
            additional_guidance=additional_guidance,
            niche=self.niche,
        )
        logger.info("Icerik uretiliyor: " + topic)

        try:
            prompt_metadata = build_prompt_metadata(prompt)
        except Exception:
            # Registry is metadata-only and must never block generation.
            prompt_metadata = {}

        try:
            channel_dna_metadata = build_channel_dna_metadata(**self._channel_dna_overrides)
        except Exception:
            # Channel DNA is metadata-only and must never block generation.
            channel_dna_metadata = {}

        response = self.client.messages.create(
            model=self.model,
            max_tokens=8192,
            system=self._system_prompt(),
            messages=[{"role": "user", "content": prompt}],
            temperature=1,  # Maksimum yaraticilik
        )
        raw = response.content[0].text.strip()

        # Markdown kod blogu temizle
        if raw.startswith("```"):
            lines = raw.splitlines()
            end = next((i for i, l in enumerate(lines[1:], 1) if l.startswith("```")), len(lines))
            raw = "\n".join(lines[1:end])

        data = json.loads(raw)
        # chart_data string veya dict olabilir — parse et
        raw_chart = data.get("chart_data")
        if isinstance(raw_chart, str):
            try:
                raw_chart = json.loads(raw_chart)
            except Exception:
                raw_chart = {}

        try:
            quality_score_metadata = build_quality_scores(
                title=data.get("title", ""),
                description=data.get("description", ""),
                script=data.get("script", ""),
                tags=data.get("tags", []),
                thumbnail_prompt=data.get("thumbnail_prompt", ""),
            )
        except Exception:
            # Scoring is metadata-only and must never block generation.
            quality_score_metadata = {}

        content = VideoContent(
            title=data["title"],
            description=data["description"],
            tags=data.get("tags", []),
            script=data["script"],
            thumbnail_prompt=data.get("thumbnail_prompt", ""),
            category_id=data.get("category_id", config.default_category_id),
            niche=self.niche,
            hook=data.get("hook", ""),
            next_video_teaser=data.get("next_video_teaser", ""),
            pexels_search=data.get("pexels_search", ""),
            chart_data=raw_chart or {},
            prompt_metadata=prompt_metadata,
            channel_dna_metadata=channel_dna_metadata,
            quality_score_metadata=quality_score_metadata,
        )
        logger.info("Icerik hazir: " + content.title)
        return content

    def generate_and_save(
        self,
        topic: str | None = None,
        additional_guidance: str | None = None,
    ) -> VideoContent:
        from pathlib import Path as _Path
        from .content_pyramid import (
            get_content_type_for_next_video,
            get_pillar_topic,
            get_series_next_episode,
        )

        # İçerik türünü belirle (evergreen/semi/trend dengesi)
        content_type = get_content_type_for_next_video(self.niche, config.scripts_dir)

        if not topic:
            if content_type == "evergreen":
                used = _load_used_titles()
                pillar = get_pillar_topic(self.niche, used)
                if pillar:
                    topic = pillar
                    logger.info("Pillar video: " + topic)
                else:
                    series = get_series_next_episode(self.niche, used)
                    if series:
                        topic = series[1]
                        logger.info("Seri bolumu: " + topic)

            if not topic:
                topics = self.generate_topic_ideas(count=5)
                topic = topics[0]
                logger.info("Secilen konu: " + topic)

        prev_title = self._get_last_title()
        content = self.generate_video_content(topic, prev_title, additional_guidance=additional_guidance)
        path = content.save()

        # Content type'ı kaydet
        try:
            import json as _json
            data = _json.loads(_Path(path).read_text(encoding="utf-8"))
            data["content_type"] = content_type
            _Path(path).write_text(_json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

        logger.info(f"Icerik turu: {content_type}")
        return content

    def _get_last_title(self) -> str | None:
        used = _load_used_titles()
        return used[-1] if used else None
