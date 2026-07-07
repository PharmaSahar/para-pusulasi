"""
Gelir Çeşitlendirme ve Çok Platform Sistemi
- Affiliate link yönetimi
- Instagram/Twitter içerik üretimi
- Sponsorluk şablonları
"""
import os

# ─── Affiliate Linkler ────────────────────────────────────────────────────────
AFFILIATE_LINKS = {
    "kisisel_finans": {
        "Binance (Kripto Borsasi)": "https://www.binance.com/register?ref=PUSULASI",
    },
    "kripto": {
        "Binance (Kripto Borsasi) - %20 islem ucreti indirimi": "https://www.binance.com/register?ref=PUSULASI",
    },
    "borsa": {
        "Binance (Kripto Borsasi)": "https://www.binance.com/register?ref=PUSULASI",
    },
    "girisimcilik": {
        "Binance (Kripto Borsasi)": "https://www.binance.com/register?ref=PUSULASI",
    },
}

AFFILIATE_DISCLAIMER = """
---
🔗 TÜM LİNKLER: https://linktr.ee/sahar.noorizadehtehrani

📧 İletişim & İşbirliği: para@eduofficial.org

⚠️ SORUMLULUK REDDİ: Bu video yatırım tavsiyesi değildir. 
Tüm yatırım kararları kişisel finansal durumunuza göre verilmelidir.
{links}
"""


def get_description_with_affiliate(niche: str, base_description: str) -> str:
    """Açıklamaya Linktree + affiliate linklerini ekle."""
    links = AFFILIATE_LINKS.get(niche, {})
    if links:
        link_text = "\n🔗 REFERANS LİNKLER:\n" + "\n".join(f"• {name}: {url}" for name, url in list(links.items())[:3])
    else:
        link_text = ""

    disclaimer = AFFILIATE_DISCLAIMER.format(links=link_text)
    return base_description + disclaimer


# ─── Sosyal Medya İçerik Üretici ─────────────────────────────────────────────
def generate_twitter_thread(title: str, hook: str, key_points: list[str]) -> str:
    """Video'dan Twitter thread oluştur."""
    threads = [
        f"🧵 {title}\n\n{hook}\n\nThread 👇",
    ]
    for i, point in enumerate(key_points[:5], 1):
        threads.append(f"{i}/ {point}")

    threads.append(
        f"📺 Tam video:\nyoutube.com/watch?v=VIDEO_ID\n\n"
        f"Beğendiyseniz RT yapın! 🔁\n\n#Finans #Yatırım #ParaPusulasi"
    )
    return "\n\n".join(threads)


def generate_instagram_caption(title: str, hook: str) -> str:
    """Video'dan Instagram caption oluştur."""
    return (
        f"💡 {title}\n\n"
        f"{hook}\n\n"
        f"Tam anlatım YouTube kanalımızda! 👆 Bio linke tıklayın.\n\n"
        f"#ParaPusulasi #Finans #Yatırım #Borsa #KişiselFinans "
        f"#TürkFinans #Birikim #Tasarruf #GelirArtırma"
    )


def generate_telegram_post(title: str, youtube_url: str, key_insight: str) -> str:
    """Telegram kanalı için post oluştur."""
    return (
        f"📊 *Yeni Video: {title}*\n\n"
        f"💡 Bu videoda öğrenecekleriniz:\n"
        f"{key_insight}\n\n"
        f"🎬 İzlemek için: {youtube_url}\n\n"
        f"⭐ Beğendiyseniz arkadaşlarınızla paylaşın!"
    )


# ─── A/B Başlık Testi ─────────────────────────────────────────────────────────
def generate_title_variants(base_title: str, niche: str) -> list[str]:
    """3 farklı başlık varyantı oluştur — A/B testi için."""
    variants = [base_title]

    # Varyant 2: Sayı ekle
    if not any(c.isdigit() for c in base_title[:20]):
        num_variant = base_title.replace("Nasıl", "5 Adımda Nasıl").replace("Rehberi", "3 Adım Rehberi")
        if num_variant != base_title:
            variants.append(num_variant)

    # Varyant 3: Merak çekici
    curiosity_prefixes = [
        "Kimsenin Söylemediği: ",
        "Dikkat! ",
        "Şok Edici: ",
        "Gizli Kalan: ",
    ]
    import random
    prefix = random.choice(curiosity_prefixes)
    if len(prefix + base_title) <= 60:
        variants.append(prefix + base_title)
    else:
        variants.append(base_title[:55] + "...")

    return variants[:3]


# ─── Çapraz Kanal Tanıtım ─────────────────────────────────────────────────────
CROSS_PROMOTION_TEMPLATES = {
    "kisisel_finans": {
        "mention_borsa": "Borsa yatırımı hakkında daha detaylı bilgi için @BorsaAkademi kanalımıza göz atın!",
        "mention_kripto": "Kripto para konusunda merak ettikleriniz için @KriptoRehber kanalımızda detaylı videolar var!",
    },
    "borsa": {
        "mention_finans": "Genel finansal planlama için @ParaPusulasi kanalımıza göz atın!",
    },
    "kripto": {
        "mention_finans": "Kripto dışı yatırım araçları için @ParaPusulasi kanalına bakın!",
        "mention_teknoloji": "Blockchain teknolojisi detayları için @TeknolojiPusulasi!",
    },
}


def get_cross_promotion(source_niche: str) -> str:
    """Video sonuna eklenecek çapraz kanal tanıtımı."""
    promotions = CROSS_PROMOTION_TEMPLATES.get(source_niche, {})
    if not promotions:
        return ""
    return "\n\n🔗 **Diğer Kanallarımız:**\n" + "\n".join(f"• {v}" for v in list(promotions.values())[:2])
