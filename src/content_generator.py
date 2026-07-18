"""
Gelismis Icerik Uretici - v2.0
Claude AI + Ust Duzey Prompt Muhendisligi
"""
import json
import logging
import os
import random
import re
import hashlib
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import anthropic

from .channel_dna import build_channel_dna_metadata
from .channel_manager import resolve_allow_market_language
from .config import config
from .prompt_registry import build_prompt_metadata
from .quality_scoring import build_quality_scores

logger = logging.getLogger(__name__)
_ANTHROPIC_GATE_LOCK = threading.Lock()
_LAST_ANTHROPIC_CALL_AT = 0.0
DEFAULT_CHANNEL_NAME = "Genel Kanal"
DEFAULT_SEO_LABEL = "Video Rehberi"

# ─────────────────────────────────────────────────────────────────────────────
# SISTEM PROMPTU - Kanal Kimligi ve Icerik Stratejisi
# ─────────────────────────────────────────────────────────────────────────────
CHANNEL_PERSONA = """Sen Turkiye odakli egitici bir YouTube kanalinin icerik direktoru ve bas senaristsin.

KANAL KIMLIGIN:
- Kanal adi: Kanal kimligi
- Slogan: "Bilgiyi eyleme donustur"
- Ton: Samimi, gercekci, heyecanli ama kanita dayali
- Hedef kitle: Turkiye'de 25-50 yas arasi, pratik ve uygulanabilir bilgi arayan izleyiciler
- Dil: Akici Turkce, teknik terimler varsa kisa aciklama

VIRAL ICERIK FORMULUN (Bu formulu her videon icin uygula):
1. HOOK (0-30 sn): Sok edici bir istatistik veya soru ile baslat
    - "Turkiye'de her 10 kisiden 8'i surekli erteledigi bir hedefe sahip"
    - "Bu videoyu izleyenler ortalama 3 hafta icinde ilk adimi atiyor"
2. ONCEKI VIDEODAN REFERANS (30-45 sn): Kanal surekliligini kur
3. ANA ICERIK (Bolumler halinde, her bolum 2-3 dk): Net, ogretici, somut
4. GERCEK RAKAMLAR: Konuya uygun somut ve dogrulanabilir degerler kullan
5. 2026 GUNCEL VERILERI: Alanin guncel durumunu gercek kaynaklarla anlat
6. CTA (Orta): "Abone ol, bildirimi ac" - izleyiciyi kaybetme
7. SONUC + SONRAKI VIDEO DUYURUSU: Merak birak, bir sonraki konuyu duyur

BASLIK KURALLARI (YouTube Algoritmasini Kir):
- Sayi + Somut Sonuc + Yil: "30 Gunde 7 Adimla Duzenli Rutin Kurma (2026 Rehberi)"
- Merak + Kayip Korkusu: "Bu Hatayi Yapiyorsan Ilerlemen Duruyor"
- Karsilastirma: "Iki Farkli Yontemi 30 Gun Denedim: Hangisi Calisti?"
- Kisisel Hikaye: "Bir Izleyicinin Aliskanlik Donusumunu 1 Gun Takip Ettim"
- Soru: "Neden Zenginler Daha Zengin Olur? (Cevap Sizi Sok Edecek)"

KISALTMALAR:
- Alan terimlerini ilk geciste kisa ve acik sekilde tanimla
- Verileri konuya uygun ve dogrulanabilir bicimde aktar
- Yuzde degerleri gerekiyorsa acik bir baglamla birlikte ver
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
CORE_MARKET_NICHES = {"kisisel_finans", "borsa", "kripto"}


def _is_market_sensitive_niche(niche: str | None) -> bool:
    return (niche or "").strip().lower() in MARKET_SENSITIVE_NICHES


class TopicDomainBlockedError(RuntimeError):
    """Raised when no domain-valid topic candidate can be selected."""

    def __init__(self, message: str, *, trace: dict | None = None):
        super().__init__(message)
        self.trace = trace or {}
        setattr(self, "_skip_scheduler_pipeline_retry", True)


def _json_sha256(payload: object) -> str:
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _slugify(value: str) -> str:
    normalized = _normalize_alignment_text(value)
    compact = re.sub(r"\s+", "-", normalized).strip("-")
    return compact or "unknown"


def _validate_topic_candidate(
    topic: str,
    *,
    niche: str | None,
    channel_topics: list[str] | None = None,
    channel_name: str | None = None,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    normalized_niche = (niche or "").strip().lower()
    has_market_term = bool(MARKET_TOPIC_RE.search(topic or ""))
    has_domain_anchor = _text_has_domain_anchor(
        topic,
        normalized_niche,
        channel_topics,
        channel_name,
    )

    if normalized_niche in CORE_MARKET_NICHES:
        if not has_market_term and not has_domain_anchor:
            reasons.append("missing_market_domain_anchor")
    else:
        if has_market_term:
            reasons.append("market_term_not_allowed_for_non_market_niche")
        if not has_domain_anchor:
            reasons.append("missing_expected_domain_anchor")

    return len(reasons) == 0, reasons


def _filter_candidates_with_reasons(
    candidates: list[str],
    *,
    niche: str | None,
    channel_topics: list[str] | None = None,
    channel_name: str | None = None,
    stage: str,
) -> tuple[list[str], list[dict]]:
    approved: list[str] = []
    rejected: list[dict] = []
    seen: set[str] = set()

    for raw in candidates or []:
        topic = str(raw or "").strip()
        lowered = topic.lower()
        if not topic or lowered in seen:
            continue
        seen.add(lowered)

        ok, reasons = _validate_topic_candidate(
            topic,
            niche=niche,
            channel_topics=channel_topics,
            channel_name=channel_name,
        )
        if ok:
            approved.append(topic)
            continue
        rejected.append(
            {
                "stage": stage,
                "candidate": topic,
                "reasons": reasons,
            }
        )

    return approved, rejected


def _normalize_alignment_text(value: str | None) -> str:
    raw = (value or "").strip().lower()
    replacements = str.maketrans({
        "ç": "c",
        "ğ": "g",
        "ı": "i",
        "ö": "o",
        "ş": "s",
        "ü": "u",
    })
    cleaned = raw.translate(replacements)
    return re.sub(r"[^a-z0-9\s]", " ", cleaned)


def _extract_alignment_tokens(values: list[str]) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        for token in _normalize_alignment_text(value).split():
            if len(token) >= 4:
                tokens.add(token)
    return tokens


def _domain_anchor_tokens(
    niche: str | None,
    channel_topics: list[str] | None = None,
    channel_name: str | None = None,
) -> set[str]:
    values = list(channel_topics or [])
    if channel_name:
        values.append(channel_name)
    if niche:
        values.append(str(niche))
    values.extend(TOPIC_CATEGORIES.get((niche or "").strip().lower(), []))
    return _extract_alignment_tokens(values)


def _text_has_domain_anchor(
    text: str,
    niche: str | None,
    channel_topics: list[str] | None = None,
    channel_name: str | None = None,
) -> bool:
    anchors = _domain_anchor_tokens(niche, channel_topics, channel_name)
    if not anchors:
        return True
    text_tokens = set(_normalize_alignment_text(text).split())
    return bool(text_tokens & anchors)


MARKET_TOPIC_RE = re.compile(
    r"\b(bist\w*|borsa\w*|hisse\w*|dolar\w*|usd\w*|try\w*|bitcoin\w*|ethereum\w*|btc\w*|eth\w*|kripto\w*|altin\w*|faiz\w*|enflasyon\w*|yatirim\w*|temettu\w*|portfoy\w*|teknik\s+analiz|temel\s+analiz|risk\s+yonetimi)\b",
    re.IGNORECASE,
)


def _content_has_niche_mismatch(
    data: dict,
    niche: str | None,
    channel_topics: list[str] | None = None,
    channel_name: str | None = None,
) -> bool:
    normalized_niche = (niche or "").strip().lower()
    if normalized_niche in CORE_MARKET_NICHES:
        return False

    combined_text = " ".join(
        str(data.get(field, "")) for field in ("title", "description", "script", "thumbnail_prompt", "pexels_search")
    )
    has_domain_anchor = _text_has_domain_anchor(
        combined_text,
        normalized_niche,
        channel_topics,
        channel_name,
    )
    # Sadece domain anchor yoksa mismatch say — market keyword tek başına yeterli değil
    # (egitim kanalı "yatırım yapmak" gibi metaforik ifadeler kullanabilir)
    if not has_domain_anchor:
        return True
    # Market keyword VE domain anchor beraber varsa mismatch değil (finansal eğitim içeriği meşru)
    return False


def _niche_alignment_guidance(niche: str | None) -> str:
    normalized = (niche or "").strip().lower() or "genel"
    return (
        f"Bu kanalın ana nişi {normalized}. Dolar, TL, borsa, hisse, faiz, enflasyon, bitcoin, kripto, altın, yatırım gibi finans terimlerini kullanma. "
        "Konu kanalın kendi alanındaki temel prensiplere ve günlük örneklere odaklansın."
    )


def _niche_alignment_retry_guidance(
    niche: str | None,
    channel_topics: list[str] | None = None,
    channel_name: str | None = None,
) -> str:
    normalized = (niche or "").strip().lower() or "genel"
    anchors = sorted(_domain_anchor_tokens(niche, channel_topics, channel_name))
    anchor_text = ", ".join(anchors[:8]) if anchors else normalized
    return (
        f"SON DENEME: Bu kanalın ana nişi {normalized}. "
        f"Başlık, hook ve script içinde bu alanı açıkça temsil eden en az iki somut işaret kullan: {anchor_text}. "
        "Genel motivasyon veya finans benzetmelerine kayma; konu doğrudan kanalın günlük yaşam/pratik alanında kalsın."
    )


def _anthropic_error_text(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    body = getattr(exc, "body", None)
    body_text = ""
    if isinstance(body, dict):
        body_text = json.dumps(body, ensure_ascii=False)
    elif body is not None:
        body_text = str(body)
    parts = [str(exc), body_text]
    if status_code is not None:
        parts.append(f"http {status_code}")
    return " ".join(part for part in parts if part).strip()


def _mark_provider_exception(exc: Exception, *, error_text: str, recorded: bool, skip_scheduler_retry: bool) -> Exception:
    setattr(exc, "_provider_error_text", error_text)
    setattr(exc, "_provider_failure_recorded", recorded)
    setattr(exc, "_skip_scheduler_pipeline_retry", skip_scheduler_retry)
    return exc


def _is_retryable_anthropic_exception(exc: Exception, *, error_text: str) -> bool:
    retryable_names = {
        "RateLimitError",
        "OverloadedError",
        "InternalServerError",
        "ServiceUnavailableError",
        "APIConnectionError",
        "APITimeoutError",
    }
    if exc.__class__.__name__ in retryable_names:
        return True

    status_code = getattr(getattr(exc, "response", None), "status_code", None)
    if status_code in {429, 500, 503, 529}:
        return True

    txt = (error_text or str(exc) or "").lower()
    return any(
        token in txt
        for token in (
            "rate limit",
            "too many",
            "overloaded",
            "overloaded_error",
            "internalservererror",
            "serviceunavailableerror",
            "connection error",
            "timeout",
            "http 429",
            "http 500",
            "http 503",
            "http 529",
        )
    )


def _env_flag_true(name: str, default: bool = False) -> bool:
    raw = str(os.getenv(name, "1" if default else "0")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _is_fail_open_eligible_provider_error(error_text: str) -> bool:
    txt = (error_text or "").lower()
    return any(
        token in txt
        for token in (
            "anthropic circuit open",
            "credit balance is too low",
            "insufficient credit",
            "invalid api key",
            "authentication",
            "unauthorized",
            "http 401",
            "http 403",
        )
    )


def _build_local_fail_open_content_payload(*, topic: str, niche: str | None, next_topic_hint: str, channel_name: str) -> dict:
    niche_label = (niche or "genel").strip() or "genel"
    title = f"{topic} | Pratik Rehber"
    script = (
        f"Bugun {topic} konusunu sade ve uygulanabilir bir yol haritasiyla ele aliyoruz. "
        "Bu icerik hizli uygulanabilir adimlar sunar ve varsayimsal egitim amaclidir.\n\n"
        "Birinci adim: Durumu netlestir. Hedefini tek cumleyle yaz ve neyi degistirmek istedigini tarif et.\n"
        "Ikinci adim: Kucuk ve olculebilir bir rutin belirle. Her gun kisa ama duzenli uygulama yap.\n"
        "Ucuncu adim: Hata gunlugu tut. Hangi davranis seni geri cekiyor, hangi davranis seni ileri tasiyor kaydet.\n"
        "Dorduncu adim: Haftalik gozden gecirme yap. Plani sade tut, ise yaramayani cikar ve etkili olani buyut.\n"
        "Besinci adim: Riskleri onceden yaz. Beklenmeyen bir durumda alternatif bir sonraki adimi simdiden belirle.\n\n"
        "Bu yontem hizli sonuc vadi degil, surdurulebilir ilerleme odaklidir. Kisa vadede netlik, orta vadede istikrar, "
        "uzun vadede birikimli etki saglar. Uygulama sirasinda kendi baglamina gore oranlari ve adimlari sadeleştirebilirsin.\n\n"
        f"Bir sonraki videoda su soruyu inceleyecegiz: {next_topic_hint}."
    )
    return {
        "title": title[:95],
        "hook": f"{topic} konusunda en cok yapilan yanlisi 60 saniyede duzeltelim.",
        "description": (
            f"{channel_name} kanalinda {topic} icin uygulanabilir bir yol haritasi. "
            "Bu bolumde temel prensipler, adim adim uygulama plani ve haftalik kontrol listesi yer alir. "
            "Icerik egitim amaclidir ve izleyicinin kendi durumuna gore uyarlanmalidir."
        ),
        "tags": [
            topic,
            niche_label,
            "rehber",
            "egitim",
            "pratik adimlar",
            "uygulama plani",
            "turkiye",
            "2026",
        ],
        "script": script,
        "thumbnail_prompt": f"{topic} konusu icin yuksek kontrast, tek odakli, okunakli Turkce baslikli thumbnail",
        "category_id": "27",
        "next_video_teaser": f"Sonraki adim: {next_topic_hint}",
        "pexels_search": f"{niche_label} practical guide education",
        "chart_data": None,
    }


@contextmanager
def _acquire_anthropic_rate_gate(min_interval_seconds: float):
    global _LAST_ANTHROPIC_CALL_AT

    with _ANTHROPIC_GATE_LOCK:
        now = time.monotonic()
        wait_seconds = max(0.0, float(min_interval_seconds) - max(0.0, now - float(_LAST_ANTHROPIC_CALL_AT)))
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        try:
            yield
        finally:
            _LAST_ANTHROPIC_CALL_AT = time.monotonic()


def _filter_trending_topics_for_niche(
    topics: list[str],
    *,
    niche: str | None,
    channel_topics: list[str] | None = None,
    channel_name: str | None = None,
) -> list[str]:
    approved, _ = _filter_candidates_with_reasons(
        list(topics or []),
        niche=niche,
        channel_topics=channel_topics,
        channel_name=channel_name,
        stage="legacy_filter",
    )
    return approved


def _fallback_topics_for_niche(niche: str | None, channel_topics: list[str] | None = None) -> list[str]:
    # Fail-closed: fallback is channel-scoped only.
    fallback = list(channel_topics or [])
    return _filter_trending_topics_for_niche(
        fallback,
        niche=niche,
        channel_topics=channel_topics,
        channel_name=None,
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
        try:
            setattr(self, "saved_path", path)
        except Exception:
            pass
        logger.info("Script kaydedildi: " + path)
        return path

    def seo_description(self) -> str:
        """SEO + affiliate + cross-promotion aciklama."""
        try:
            from .monetization import get_description_with_affiliate, get_cross_promotion
            has_monetization = True
        except Exception:
            has_monetization = False

        channel_label = str(getattr(self, "channel_name", "") or "").strip()
        first_line = f"{self.title} | {channel_label or DEFAULT_SEO_LABEL}"
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
    channel_name: str = DEFAULT_CHANNEL_NAME,
    channel_topics: list[str] | None = None,
    allow_market_language: bool | None = None,
) -> str:
    year = datetime.now().year
    trending = _load_trending_context(niche=niche, channel_topics=channel_topics)
    avoid = ""
    if used_titles:
        last_10 = used_titles[-10:]
        avoid = "\n\nKESINLIKLE BUNLARI TEKRAR ONERME (zaten yapildi):\n" + "\n".join(f"- {t}" for t in last_10)

    normalized_niche = (niche or "").strip().lower()
    market_language_enabled = resolve_allow_market_language(
        niche=normalized_niche,
        explicit_value=allow_market_language,
    )
    if market_language_enabled:
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
- Alan dışı terimler ve ilgisiz iddialar ekleme
- Clickbait ama yaniltici olmayan, egitici konular üret
- Gerekmedikçe kesin rakam, hedef yüzde veya tarih içeren başlık kurma
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
    allow_market_language: bool | None = None,
) -> str:
    year = datetime.now().year
    strict_fact_mode = bool(additional_guidance and "FACT-CHECK SAFE MODE" in additional_guidance)
    market_sensitive_niche = resolve_allow_market_language(
        niche=niche,
        explicit_value=allow_market_language,
    )

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
        "VAKA ANALİZİ: Gerçek bir kullanicinin kararlarını adım adım incele",
        "KARŞI GÖRÜŞ: En çok savunulan fikri sorgula, alternatif sun",
        "SAYILARLA KONUŞ: Her iddiayı somut TL rakamıyla destekle",
        "SENARYOLAR: 3 farklı karar, 10 yıl sonra üçünün de sonucunu göster",
    ]
    if market_sensitive_niche:
        narrative_styles.append("VAKA ANALİZİ: Gerçek bir yatırımcının kararlarını adım adım incele")

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

    channel_prompt_identity = "Türk finans YouTube kanalı" if market_sensitive_niche else "Türk YouTube kanalı"
    creator_tone_label = "DOĞAL TÜRK FİNANS YOUTUBER'I TONU" if market_sensitive_niche else "DOĞAL TÜRK YOUTUBER TONU"
    pexels_example = (
        "'crypto trader phone night city' veya 'retirement couple beach sunset happy'"
        if market_sensitive_niche
        else "'teacher explaining whiteboard classroom' veya 'chef preparing healthy meal kitchen'"
    )

    return f"""{channel_prompt_identity} için TAMAMEN ORİJİNAL, YAPAY HİSSETTİRMEYEN senaryo yaz.

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

{creator_tone_label}:
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
    "thumbnail_prompt": "Konuya OZGUN Ingilizce gorsel promptu: tek ana fikir, yuksek kontrast, sinematik isik, 1 odak nesne veya yuz ifadesi. Keep all text inside the central-left safe area. Do not place text near the bottom 22% or right 20% of the frame. Use maximum 2 short lines. Large readable Turkish title only. 'business finance' gibi genel terimler KULLANMA",
    "pexels_search": "Bu videonun KONUSUNA ÖZGÜ 3-5 kelimelik İngilizce Pexels arama terimi (örn: {pexels_example})",
    "chart_data": "Varsa bu videoda gösterilebilecek 1 veri seti (JSON formatında): {{'type': 'bar|line|pie', 'title': 'Grafik başlığı', 'data': {{'labels': [...], 'values': [...]}}}}, yoksa null",
  "category_id": "27"
}}
}}"""


# ─────────────────────────────────────────────────────────────────────────────
class ContentGenerator:
    def __init__(self, channel_cfg=None, provenance_context: dict | None = None):
        from .config import config as _cfg
        cfg = channel_cfg if channel_cfg else _cfg
        max_retries_raw = str(os.getenv("ANTHROPIC_MAX_RETRIES", "1")).strip()
        try:
            max_retries = int(max_retries_raw)
        except Exception:
            max_retries = 1
        self.client = anthropic.Anthropic(api_key=cfg.anthropic_api_key, max_retries=max(0, max_retries))
        self.niche = cfg.niche
        self.model = "claude-opus-4-5"
        # Kanal personasini kullan
        if channel_cfg and hasattr(channel_cfg, "persona"):
            self._persona = channel_cfg.persona
            self._channel_name = channel_cfg.name
        else:
            self._persona = None
            self._channel_name = DEFAULT_CHANNEL_NAME

        self._channel_topics = list(getattr(channel_cfg, "topics", []) or [])
        self._provenance_context = dict(provenance_context or {})
        self._last_topic_trace: dict = {}

        self._channel_dna_overrides = self._resolve_channel_dna_overrides(channel_cfg)
        self._explicit_allow_market_language = (
            getattr(channel_cfg, "allow_market_language", None) if channel_cfg else None
        )

    def _system_prompt(self) -> str:
        base_persona = self._persona or CHANNEL_PERSONA
        return f"{base_persona.rstrip()}\n{CONTENT_SAFETY_BOUNDARY}"

    @staticmethod
    def _resolve_channel_dna_overrides(channel_cfg) -> dict:
        if not channel_cfg:
            return {
                "tone": "acik, guvenilir, alan-odakli",
                "audience": "Kanalin kendi nisine ilgi duyan izleyici kitlesi",
                "voice_archetype": "alan rehberi",
                "evidence_style": "dogrulanabilir kaynak ve pratik ornek odakli",
                "forbidden_patterns": [],
                "signature_structure": [],
                "channel_dna_version": "v1",
            }

        niche_label = str(getattr(channel_cfg, "niche", "") or "genel").strip().lower() or "genel"
        channel_name = str(getattr(channel_cfg, "name", "") or "kanal").strip() or "kanal"
        explicit_forbidden = getattr(channel_cfg, "forbidden_patterns", None)
        explicit_signature = getattr(channel_cfg, "signature_structure", None)

        return {
            "tone": getattr(channel_cfg, "tone", None) or "acik, guvenilir, alan-odakli",
            "audience": getattr(channel_cfg, "audience", None) or f"{channel_name} kanalinin {niche_label} odakli izleyici kitlesi",
            "voice_archetype": getattr(channel_cfg, "voice_archetype", None) or f"{niche_label} rehberi",
            "evidence_style": getattr(channel_cfg, "evidence_style", None) or "dogrulanabilir kaynak ve pratik ornek odakli",
            "forbidden_patterns": explicit_forbidden if explicit_forbidden is not None else [],
            "signature_structure": explicit_signature if explicit_signature is not None else [],
            "channel_dna_version": getattr(channel_cfg, "channel_dna_version", None) or "v1",
        }

    def _active_channel_allows_market_language(self, *, topic_hint: str | None = None) -> bool:
        # topic_hint is intentionally ignored: authorization is explicit policy-only.
        _ = topic_hint
        return resolve_allow_market_language(
            niche=self.niche,
            explicit_value=getattr(self, "_explicit_allow_market_language", None),
        )

    def _anthropic_create(self, **kwargs):
        from .scheduler_utils import get_provider_circuit_status, record_provider_failure, record_provider_success

        try:
            min_interval = max(0.0, float(os.getenv("ANTHROPIC_MIN_REQUEST_INTERVAL_SECONDS", "8")))
        except ValueError:
            min_interval = 8.0
        try:
            max_attempts = max(1, int(os.getenv("ANTHROPIC_MAX_RETRIES", "3")))
        except ValueError:
            max_attempts = 3

        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            circuit = get_provider_circuit_status("anthropic")
            if circuit.get("is_open"):
                retry_after = max(1, int(circuit.get("retry_after_seconds", 0) or 0))
                circuit_error = RuntimeError(f"Anthropic circuit open; retry after {retry_after}s")
                raise _mark_provider_exception(
                    circuit_error,
                    error_text=str(circuit_error),
                    recorded=False,
                    skip_scheduler_retry=True,
                )

            try:
                with _acquire_anthropic_rate_gate(min_interval):
                    response = self.client.messages.create(**kwargs)
                record_provider_success("anthropic", note=f"messages_create_ok_attempt_{attempt}")
                return response
            except Exception as exc:
                error_text = _anthropic_error_text(exc)
                retryable = _is_retryable_anthropic_exception(exc, error_text=error_text)
                last_error = exc
                if retryable and attempt < max_attempts:
                    continue

                recorded = False
                skip_scheduler_retry = retryable
                if retryable or not getattr(exc, "_provider_failure_recorded", False):
                    record_provider_failure("anthropic", error_text)
                    recorded = True

                raise _mark_provider_exception(
                    exc,
                    error_text=error_text,
                    recorded=recorded,
                    skip_scheduler_retry=skip_scheduler_retry,
                )

        if last_error is not None:
            raise last_error
        raise RuntimeError("Anthropic create failed without response")

    def generate_topic_ideas(self, count: int = 10) -> list[str]:
        used = _load_used_titles()
        channel_topics = list(getattr(self, "_channel_topics", []) or [])
        channel_name = getattr(self, "_channel_name", DEFAULT_CHANNEL_NAME)
        normalized_niche = (self.niche or "").strip().lower()

        trace = {
            "provider": "unknown",
            "raw_provider_rows": [],
            "normalized_provider_rows": [],
            "pre_filter_candidates": [],
            "rejected_candidates": [],
            "post_filter_candidates": [],
            "fallback_invoked": False,
            "fallback_source": None,
            "fallback_candidates": [],
            "final_ranked_list": [],
            "selected_index": None,
            "selected_topic": None,
            "expected_niche": normalized_niche,
        }

        # Google Trends'den güncel konuları al
        trending_from_web = []
        try:
            trends_module = None
            trend_getter = globals().get("get_trending_topics_with_metadata")
            seasonal_getter = globals().get("get_seasonal_boost_topics")
            legacy_trend_getter = globals().get("get_trending_topics")
            if not callable(trend_getter) or not callable(seasonal_getter):
                from . import trends_fetcher as trends_module

                trend_getter = trend_getter if callable(trend_getter) else getattr(trends_module, "get_trending_topics_with_metadata", None)
                seasonal_getter = seasonal_getter if callable(seasonal_getter) else getattr(trends_module, "get_seasonal_boost_topics", None)
                legacy_trend_getter = legacy_trend_getter if callable(legacy_trend_getter) else getattr(trends_module, "get_trending_topics", None)
            if not callable(trend_getter) or not callable(seasonal_getter):
                raise RuntimeError("trend_provider_unavailable")

            trend_meta = trend_getter(self.niche, count=4)
            trace["provider"] = str(trend_meta.get("provider") or "unknown")
            trace["raw_provider_rows"] = list(trend_meta.get("raw_provider_rows") or [])
            trace["normalized_provider_rows"] = list(trend_meta.get("normalized_provider_rows") or [])
            trending_from_web = list(trend_meta.get("topics") or [])

            # Compatibility path for legacy tests/callers that patch get_trending_topics.
            if trace["provider"] == "static_fallback" and callable(legacy_trend_getter):
                legacy_topics = list(legacy_trend_getter(self.niche, count=4) or [])
                if legacy_topics != trending_from_web:
                    trending_from_web = legacy_topics
                    trace["normalized_provider_rows"] = list(legacy_topics)
                    trace["raw_provider_rows"] = [
                        {"keyword": str(self.niche or "").strip().lower(), "query": item, "value": None}
                        for item in legacy_topics
                    ]
                    trace["provider"] = "legacy_trends_override"

            seasonal = seasonal_getter(self.niche)
            pre_filter = (list(seasonal or []) + trending_from_web)[:4]
            trace["pre_filter_candidates"] = list(pre_filter)

            trending_from_web, rejected = _filter_candidates_with_reasons(
                pre_filter,
                niche=self.niche,
                channel_topics=channel_topics,
                channel_name=channel_name,
                stage="provider_pre_filter",
            )
            trace["rejected_candidates"].extend(rejected)
            trace["post_filter_candidates"] = list(trending_from_web)
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
            channel_name=channel_name,
            channel_topics=channel_topics,
            allow_market_language=self._active_channel_allows_market_language(),
        ) + trend_hint + avoid
        logger.info(f"'{self.niche}' icin {count} konu uretiliyor...")

        response = self._anthropic_create(
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

        # Non-market channels remain provider-anchored (fail-closed).
        # Market-sensitive channels can still blend AI suggestions after trend anchors.
        if self._active_channel_allows_market_language():
            ranked_candidates = list(trending_from_web[:2]) + [t for t in ai_topics if t not in trending_from_web]
        else:
            ranked_candidates = list(trending_from_web[:count])
        trace["final_ranked_list"] = list(ranked_candidates)

        combined, rejected = _filter_candidates_with_reasons(
            ranked_candidates,
            niche=self.niche,
            channel_topics=channel_topics,
            channel_name=channel_name,
            stage="final_candidate_filter",
        )
        trace["rejected_candidates"].extend(rejected)

        if not combined:
            trace["fallback_invoked"] = True
            trace["fallback_source"] = "channel_scoped"
            combined = _fallback_topics_for_niche(self.niche, channel_topics)

            fallback_candidates, fallback_rejected = _filter_candidates_with_reasons(
                list(channel_topics or []),
                niche=self.niche,
                channel_topics=channel_topics,
                channel_name=channel_name,
                stage="channel_scoped_fallback",
            )
            trace["fallback_candidates"] = list(fallback_candidates)
            trace["rejected_candidates"].extend(fallback_rejected)

        if not combined and self._active_channel_allows_market_language():
            market_fallback = [item for item in ai_topics if str(item).strip()]
            if market_fallback:
                trace["fallback_invoked"] = True
                trace["fallback_source"] = "market_ai_fallback"
                trace["fallback_candidates"] = list(market_fallback)
                combined = list(market_fallback)

        if not combined:
            trace["post_filter_candidates"] = []
            self._last_topic_trace = trace
            raise TopicDomainBlockedError(
                f"topic_domain_blocked:no_valid_candidate niche={normalized_niche}",
                trace=trace,
            )

        trace["post_filter_candidates"] = list(combined)
        self._last_topic_trace = trace
        logger.info(f"{len(combined[:count])} konu hazir.")
        return combined[:count]

    def _topic_provenance_path(self) -> Path | None:
        provenance_ctx = dict(getattr(self, "_provenance_context", {}) or {})
        run_id = str(provenance_ctx.get("run_id") or "").strip()
        content_id = str(provenance_ctx.get("content_id") or "").strip()
        channel_id = str(provenance_ctx.get("channel_id") or provenance_ctx.get("channel_slug") or "").strip()
        if not run_id or not content_id or not channel_id:
            return None
        output_root = str(provenance_ctx.get("output_dir") or "output").strip() or "output"
        return Path(output_root) / "topic_provenance" / channel_id / run_id / f"{content_id}.json"

    def _persist_topic_provenance(self, *, selected_index: int, selected_topic: str, final_topics: list[str]) -> None:
        path = self._topic_provenance_path()
        if path is None:
            return

        provenance_ctx = dict(getattr(self, "_provenance_context", {}) or {})
        trace = dict(getattr(self, "_last_topic_trace", {}) or {})
        trace["selected_index"] = selected_index
        trace["selected_topic"] = selected_topic
        trace["final_ranked_list"] = list(trace.get("final_ranked_list") or final_topics)

        runtime_identity = dict(provenance_ctx.get("runtime_build_identity") or {})
        payload = {
            "run_id": provenance_ctx.get("run_id"),
            "content_id": provenance_ctx.get("content_id"),
            "channel_id": provenance_ctx.get("channel_id"),
            "channel_slug": provenance_ctx.get("channel_slug") or _slugify(str(self._channel_name or "")),
            "expected_niche": self.niche,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "provider_name": trace.get("provider"),
            "raw_provider_rows": trace.get("raw_provider_rows") or [],
            "normalized_provider_rows": trace.get("normalized_provider_rows") or [],
            "pre_filter_candidates": trace.get("pre_filter_candidates") or [],
            "rejected_candidates": trace.get("rejected_candidates") or [],
            "post_filter_candidates": trace.get("post_filter_candidates") or [],
            "fallback_invoked": bool(trace.get("fallback_invoked", False)),
            "fallback_source": trace.get("fallback_source"),
            "fallback_candidates": trace.get("fallback_candidates") or [],
            "final_ranked_list": list(final_topics),
            "selected_index": selected_index,
            "selected_topic": selected_topic,
            "provenance_attempt": 1,
            "runtime_build_identity": runtime_identity,
        }
        payload["hashes"] = {
            "raw_provider_rows": _json_sha256(payload["raw_provider_rows"]),
            "normalized_provider_rows": _json_sha256(payload["normalized_provider_rows"]),
            "pre_filter_candidates": _json_sha256(payload["pre_filter_candidates"]),
            "rejected_candidates": _json_sha256(payload["rejected_candidates"]),
            "post_filter_candidates": _json_sha256(payload["post_filter_candidates"]),
            "final_ranked_list": _json_sha256(payload["final_ranked_list"]),
            "runtime_build_identity": _json_sha256(payload["runtime_build_identity"]),
        }
        payload["hashes"]["payload"] = _json_sha256(payload)

        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            try:
                existing = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                existing = {}
            identity_keys = ("run_id", "content_id", "channel_id")
            existing_identity = {key: existing.get(key) for key in identity_keys}
            attempted_identity = {key: payload.get(key) for key in identity_keys}
            if existing_identity != attempted_identity:
                raise TopicDomainBlockedError(
                    f"topic_provenance_collision:{path}",
                    trace={
                        "path": str(path),
                        "existing_identity": existing_identity,
                        "attempted_identity": attempted_identity,
                    },
                )
            existing_hashes = existing.get("hashes") if isinstance(existing.get("hashes"), dict) else {}
            payload["provenance_attempt"] = int(existing.get("provenance_attempt") or 1) + 1
            payload["replaces_provenance"] = {
                "previous_payload_hash": existing_hashes.get("payload"),
                "previous_selected_topic": existing.get("selected_topic"),
                "previous_timestamp_utc": existing.get("timestamp_utc"),
            }

        payload["hashes"]["payload"] = _json_sha256(payload)

        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(path)

    def _validate_explicit_topic_or_block(self, topic: str) -> tuple[str, bool]:
        """Validate an explicitly supplied topic (retry/resume/manual) before generation."""
        channel_topics = list(getattr(self, "_channel_topics", []) or [])
        channel_name = getattr(self, "_channel_name", DEFAULT_CHANNEL_NAME)
        approved, rejected = _filter_candidates_with_reasons(
            [topic],
            niche=self.niche,
            channel_topics=channel_topics,
            channel_name=channel_name,
            stage="explicit_topic_validation",
        )
        if approved:
            return approved[0], False

        fallback, fallback_rejected = _filter_candidates_with_reasons(
            list(channel_topics or []),
            niche=self.niche,
            channel_topics=channel_topics,
            channel_name=channel_name,
            stage="explicit_topic_fallback",
        )
        self._last_topic_trace = {
            "provider": "explicit_input",
            "raw_provider_rows": [{"query": topic}],
            "normalized_provider_rows": [topic],
            "pre_filter_candidates": [topic],
            "rejected_candidates": list(rejected) + list(fallback_rejected),
            "post_filter_candidates": list(fallback),
            "fallback_invoked": True,
            "fallback_source": "channel_scoped",
            "fallback_candidates": list(fallback),
            "final_ranked_list": list(fallback),
            "selected_index": None,
            "selected_topic": None,
            "expected_niche": (self.niche or "").strip().lower(),
        }
        if fallback:
            return fallback[0], True

        raise TopicDomainBlockedError(
            f"topic_domain_blocked:explicit_topic_invalid niche={(self.niche or '').strip().lower()}",
            trace=self._last_topic_trace,
        )

    def generate_video_content(
        self,
        topic: str,
        prev_title: str | None = None,
        additional_guidance: str | None = None,
        next_topic_hint: str | None = None,
    ) -> VideoContent:
        channel_topics = list(getattr(self, "_channel_topics", []) or [])
        channel_name = getattr(self, "_channel_name", DEFAULT_CHANNEL_NAME)
        channel_dna_overrides = getattr(self, "_channel_dna_overrides", {})
        if next_topic_hint:
            next_hint = next_topic_hint
        elif hasattr(self, "_explicit_allow_market_language"):
            next_hint = "Bir sonraki videoda yaygin bir hatayi adim adim duzeltecegiz"
        else:
            # Compatibility path for tests constructing generator via __new__.
            next_hint = "Bir sonraki videoda yaygin bir hatayi adim adim duzeltecegiz"
        allow_market_language = self._active_channel_allows_market_language(topic_hint=topic)

        logger.info("Icerik uretiliyor: " + topic)

        prompt_variants = [additional_guidance or ""]
        if not allow_market_language:
            retry_guidance = " ".join(
                part
                for part in [
                    additional_guidance,
                    _niche_alignment_retry_guidance(
                        self.niche,
                        channel_topics,
                        channel_name,
                    ),
                ]
                if part
            ).strip()
            aligned_guidance = " ".join(
                part for part in [additional_guidance, _niche_alignment_guidance(self.niche)] if part
            ).strip()
            prompt_variants.extend([retry_guidance, aligned_guidance])

        data = None
        raw_chart = None
        last_error: Exception | None = None
        prompt = ""
        for attempt, guidance in enumerate(prompt_variants[:3]):
            try:
                prompt = _build_content_prompt(
                    topic,
                    prev_title,
                    next_hint,
                    getattr(self, '_last_content_type', 'semi_evergreen'),
                    additional_guidance=guidance or None,
                    niche=self.niche,
                    allow_market_language=allow_market_language,
                )
            except TypeError as exc:
                if "allow_market_language" not in str(exc):
                    raise
                # Compatibility path for tests/callers monkeypatching older signature.
                prompt = _build_content_prompt(
                    topic,
                    prev_title,
                    next_hint,
                    getattr(self, '_last_content_type', 'semi_evergreen'),
                    additional_guidance=guidance or None,
                    niche=self.niche,
                )
            try:
                response = self._anthropic_create(
                    model=self.model,
                    max_tokens=8192,
                    system=self._system_prompt(),
                    messages=[{"role": "user", "content": prompt}],
                    temperature=1,  # Maksimum yaraticilik
                )
                raw = response.content[0].text.strip()
            except Exception as exc:
                last_error = exc
                error_text = _anthropic_error_text(exc)
                if _env_flag_true("ANTHROPIC_FAIL_OPEN_LOCAL_CONTENT", default=True) and _is_fail_open_eligible_provider_error(error_text):
                    logger.warning(
                        "Anthropic fail-open local fallback activated: channel=%s niche=%s reason=%s",
                        channel_name,
                        self.niche,
                        error_text[:180],
                    )
                    data = _build_local_fail_open_content_payload(
                        topic=topic,
                        niche=self.niche,
                        next_topic_hint=next_hint,
                        channel_name=channel_name,
                    )
                    raw_chart = data.get("chart_data")
                    break
                continue

            # Markdown kod blogu temizle
            if raw.startswith("```"):
                lines = raw.splitlines()
                end = next((i for i, l in enumerate(lines[1:], 1) if l.startswith("```") ), len(lines))
                raw = "\n".join(lines[1:end])

            try:
                candidate = json.loads(raw)
            except Exception as exc:
                last_error = exc
                continue

            if _content_has_niche_mismatch(
                candidate,
                self.niche,
                channel_topics=channel_topics,
                channel_name=channel_name,
            ):
                last_error = ValueError(f"niche_alignment_failed:{self.niche}")
                continue

            data = candidate
            raw_chart = data.get("chart_data")
            if isinstance(raw_chart, str):
                try:
                    raw_chart = json.loads(raw_chart)
                except Exception:
                    raw_chart = {}
            break

        if data is None:
            raise ValueError(f"niche_alignment_failed:{self.niche}") from last_error

        try:
            prompt_metadata = build_prompt_metadata(
                prompt,
                prompt_type="content_generation",
                template_id="content_generator_v2_json",
                provider_model_family="anthropic_claude",
                input_field_presence={
                    "topic": bool(str(topic or "").strip()),
                    "prev_title": bool(str(prev_title or "").strip()),
                    "next_topic_hint": bool(str(next_hint or "").strip()),
                    "additional_guidance": bool(str(guidance or "").strip()),
                    "niche": bool(str(self.niche or "").strip()),
                },
                blueprint_goal_references=[
                    "narrative_structure",
                    "hook_type",
                    "retention_first_30s",
                    "thumbnail_topic_relevance",
                    "seo_keyword_strategy",
                    "shorts_hook",
                    "safety_unsupported_claim_controls",
                ],
            )
        except TypeError:
            # Compatibility fallback for legacy one-arg callables in tests and custom hooks.
            try:
                prompt_metadata = build_prompt_metadata(prompt)
            except Exception:
                prompt_metadata = {}
        except Exception:
            prompt_metadata = {}

        try:
            channel_dna_metadata = build_channel_dna_metadata(**channel_dna_overrides)
        except Exception:
            channel_dna_metadata = {}

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
        try:
            setattr(content, "channel_name", str(channel_name or "").strip() or DEFAULT_CHANNEL_NAME)
        except Exception:
            pass
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
        next_topic_hint = None
        selected_index = 0
        selected_from_topic_ideas = False

        if topic:
            topic, fallback_used = self._validate_explicit_topic_or_block(str(topic))
            selected_index = 0
            if fallback_used:
                next_topic_hint = None

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
                selected_from_topic_ideas = True
                selected_index = 0
                topic = topics[selected_index]
                next_topic_hint = topics[selected_index + 1] if len(topics) > (selected_index + 1) else None
                logger.info("Secilen konu: " + topic)

        current_trace = dict(getattr(self, "_last_topic_trace", {}) or {})
        if (not selected_from_topic_ideas) and (not current_trace.get("raw_provider_rows")):
            self._last_topic_trace = {
                "provider": "internal_topic_source",
                "raw_provider_rows": [{"query": str(topic)}],
                "normalized_provider_rows": [str(topic)],
                "pre_filter_candidates": [str(topic)],
                "rejected_candidates": [],
                "post_filter_candidates": [str(topic)],
                "fallback_invoked": False,
                "fallback_source": None,
                "fallback_candidates": [],
                "final_ranked_list": [str(topic)],
                "selected_index": selected_index,
                "selected_topic": str(topic),
                "expected_niche": (self.niche or "").strip().lower(),
            }

        self._persist_topic_provenance(
            selected_index=selected_index,
            selected_topic=str(topic),
            final_topics=list((getattr(self, "_last_topic_trace", {}) or {}).get("post_filter_candidates") or [topic]),
        )

        prev_title = self._get_last_title()
        content = self.generate_video_content(
            topic,
            prev_title,
            additional_guidance=additional_guidance,
            next_topic_hint=next_topic_hint,
        )
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
