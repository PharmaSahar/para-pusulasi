"""
200 Kanal Genişletme Scripti
10 niş × 20 kanal = 200 kanal
Her niş: 4 TR varyantı + 8 EN varyantı + 4 DE + 4 diğer dil

Çalıştır: python expand_200_channels.py
"""
import json
import os
from pathlib import Path

# ─── 200 KANAL TANIMI ─────────────────────────────────────────────────────────

CHANNEL_PLANS = [

    # ══════════════════════════════════════════════════════════
    # NİŞ 1: KİŞİSEL FİNANS (TR)
    # ══════════════════════════════════════════════════════════
    {
        "channel_id": "para_pusulasi",          # AKTIF - OAuth var
        "name": "Para Pusulası",
        "niche": "kisisel_finans", "language": "tr",
        "slogan": "Paranızı Çalıştırın!",
        "tagline": "Finans & Yatırım Rehberi",
        "upload_times": ["08:00", "20:00"],
        "color_primary": [212, 175, 55], "color_bg": [10, 18, 40],
        "pexels_query": "personal finance money investment savings",
        "status": "active",
    },
    {
        "channel_id": "para_kocu",
        "name": "Para Koçu",
        "niche": "kisisel_finans", "language": "tr",
        "slogan": "Finansal Özgürlüğe Giden Yol",
        "tagline": "Birikim & Yatırım Koçu",
        "upload_times": ["08:15", "20:15"],
        "color_primary": [34, 197, 94], "color_bg": [10, 30, 20],
        "pexels_query": "financial freedom savings goals success",
        "status": "pending_oauth",
    },
    {
        "channel_id": "zenginlik_pusulasi",
        "name": "Zenginlik Pusulası",
        "niche": "kisisel_finans", "language": "tr",
        "slogan": "Servet İnşa Et",
        "tagline": "Servet & Emeklilik Planlaması",
        "upload_times": ["08:30", "20:30"],
        "color_primary": [251, 191, 36], "color_bg": [20, 10, 0],
        "pexels_query": "wealth building investment passive income",
        "status": "pending_oauth",
    },
    {
        "channel_id": "butce_ustasi",
        "name": "Bütçe Ustası",
        "niche": "kisisel_finans", "language": "tr",
        "slogan": "Her Kuruşu Değerlendir",
        "tagline": "Bütçe & Tasarruf Uzmanı",
        "upload_times": ["08:45", "20:45"],
        "color_primary": [99, 102, 241], "color_bg": [15, 15, 35],
        "pexels_query": "budget planning savings frugal living",
        "status": "pending_oauth",
    },

    # ══════════════════════════════════════════════════════════
    # NİŞ 2: BORSA / HİSSE SENEDİ (TR)
    # ══════════════════════════════════════════════════════════
    {
        "channel_id": "borsa_akademi",          # AKTIF - OAuth var
        "name": "Borsa Akademi",
        "niche": "borsa", "language": "tr",
        "slogan": "BIST'i Öğren, Kazan!",
        "tagline": "Hisse & Borsa Rehberi",
        "upload_times": ["09:00", "21:00"],
        "color_primary": [239, 68, 68], "color_bg": [20, 10, 10],
        "pexels_query": "stock market trading charts bull market",
        "status": "active",
    },
    {
        "channel_id": "bist_analiz",
        "name": "BIST Analiz",
        "niche": "borsa", "language": "tr",
        "slogan": "Teknik Analiz ile Kazan",
        "tagline": "BIST 100 Teknik Analiz",
        "upload_times": ["09:15", "21:15"],
        "color_primary": [16, 185, 129], "color_bg": [5, 20, 15],
        "pexels_query": "stock chart technical analysis trading",
        "status": "pending_oauth",
    },
    {
        "channel_id": "temetu_akademi",
        "name": "Temettü Akademi",
        "niche": "borsa", "language": "tr",
        "slogan": "Temettüyle Pasif Gelir",
        "tagline": "Temettü Yatırımı Rehberi",
        "upload_times": ["09:30", "21:30"],
        "color_primary": [245, 158, 11], "color_bg": [20, 15, 5],
        "pexels_query": "dividend stocks passive income investment",
        "status": "pending_oauth",
    },
    {
        "channel_id": "hisse_radar",
        "name": "Hisse Radar",
        "niche": "borsa", "language": "tr",
        "slogan": "Doğru Hisseyi Bul",
        "tagline": "Hisse Analizi & Tarama",
        "upload_times": ["09:45", "21:45"],
        "color_primary": [168, 85, 247], "color_bg": [20, 10, 30],
        "pexels_query": "stock trading financial analysis market research",
        "status": "pending_oauth",
    },

    # ══════════════════════════════════════════════════════════
    # NİŞ 3: KRİPTO (TR)
    # ══════════════════════════════════════════════════════════
    {
        "channel_id": "kripto_rehber",          # AKTIF - OAuth var
        "name": "Kripto Rehber",
        "niche": "kripto", "language": "tr",
        "slogan": "Kripto'yu Sıfırdan Öğren!",
        "tagline": "Bitcoin & Kripto Para Rehberi",
        "upload_times": ["10:00", "22:00"],
        "color_primary": [249, 115, 22], "color_bg": [20, 10, 5],
        "pexels_query": "cryptocurrency bitcoin blockchain digital",
        "status": "active",
    },
    {
        "channel_id": "bitcoin_akademi",
        "name": "Bitcoin Akademi",
        "niche": "kripto", "language": "tr",
        "slogan": "Bitcoin'in Gücünü Keşfet",
        "tagline": "Bitcoin & Blockchain Eğitimi",
        "upload_times": ["10:15", "22:15"],
        "color_primary": [251, 191, 36], "color_bg": [20, 12, 0],
        "pexels_query": "bitcoin cryptocurrency trading investment",
        "status": "pending_oauth",
    },
    {
        "channel_id": "altcoin_radar",
        "name": "Altcoin Radar",
        "niche": "kripto", "language": "tr",
        "slogan": "100x Altcoin Ara",
        "tagline": "Altcoin Analizi & Haberleri",
        "upload_times": ["10:30", "22:30"],
        "color_primary": [6, 182, 212], "color_bg": [5, 20, 25],
        "pexels_query": "cryptocurrency altcoin trading blockchain",
        "status": "pending_oauth",
    },
    {
        "channel_id": "web3_pusulasi",
        "name": "Web3 Pusulası",
        "niche": "kripto", "language": "tr",
        "slogan": "Web3 & NFT Dünyasına Gir",
        "tagline": "Web3, NFT & Metaverse",
        "upload_times": ["10:45", "22:45"],
        "color_primary": [139, 92, 246], "color_bg": [15, 5, 30],
        "pexels_query": "web3 nft digital art blockchain technology",
        "status": "pending_oauth",
    },

    # ══════════════════════════════════════════════════════════
    # NİŞ 4: KARİYER & MAAŞ (TR)
    # ══════════════════════════════════════════════════════════
    {
        "channel_id": "kariyer_pusulasi",       # AKTIF - OAuth var
        "name": "Kariyer Pusulası",
        "niche": "kariyer", "language": "tr",
        "slogan": "Kariyerinde Zirveye Çık!",
        "tagline": "Kariyer & Maaş Rehberi",
        "upload_times": ["11:00", "23:00"],
        "color_primary": [59, 130, 246], "color_bg": [10, 15, 25],
        "pexels_query": "career success professional business meeting",
        "status": "active",
    },
    {
        "channel_id": "maas_kocu",
        "name": "Maaş Koçu",
        "niche": "kariyer", "language": "tr",
        "slogan": "Maaşını 2 Katına Çıkar",
        "tagline": "Maaş Müzakeresi & İş Hayatı",
        "upload_times": ["11:15", "23:15"],
        "color_primary": [20, 184, 166], "color_bg": [5, 20, 18],
        "pexels_query": "salary negotiation career promotion success",
        "status": "pending_oauth",
    },
    {
        "channel_id": "girisimci_akademi",
        "name": "Girişimci Akademi",
        "niche": "girisim", "language": "tr",
        "slogan": "Kendi İşini Kur!",
        "tagline": "Girişimcilik & Startup Rehberi",
        "upload_times": ["11:30", "23:30"],
        "color_primary": [234, 88, 12], "color_bg": [20, 10, 5],
        "pexels_query": "startup entrepreneur business innovation office",
        "status": "pending_oauth",
    },
    {
        "channel_id": "freelance_pusulasi",
        "name": "Freelance Pusulası",
        "niche": "kariyer", "language": "tr",
        "slogan": "Uzaktan Çalış, Özgür Ol!",
        "tagline": "Freelance & Uzaktan Çalışma",
        "upload_times": ["11:45", "23:45"],
        "color_primary": [16, 185, 129], "color_bg": [5, 20, 15],
        "pexels_query": "freelance remote work laptop digital nomad",
        "status": "pending_oauth",
    },

    # ══════════════════════════════════════════════════════════
    # NİŞ 5: GAYRİMENKUL (TR)
    # ══════════════════════════════════════════════════════════
    {
        "channel_id": "gayrimenkul_tv",
        "name": "Gayrimenkul TV",
        "niche": "gayrimenkul", "language": "tr",
        "slogan": "Ev Al, Kiraya Ver, Kazan!",
        "tagline": "Gayrimenkul Yatırım Rehberi",
        "upload_times": ["12:00", "00:00"],
        "color_primary": [245, 158, 11], "color_bg": [20, 15, 5],
        "pexels_query": "real estate luxury property investment",
        "status": "pending_oauth",
    },
    {
        "channel_id": "konut_rehberi",
        "name": "Konut Rehberi",
        "niche": "gayrimenkul", "language": "tr",
        "slogan": "Doğru Evi Doğru Fiyata Al",
        "tagline": "Ev Alma & Satma Rehberi",
        "upload_times": ["12:15", "00:15"],
        "color_primary": [99, 102, 241], "color_bg": [15, 15, 30],
        "pexels_query": "house buying real estate mortgage property",
        "status": "pending_oauth",
    },

    # ══════════════════════════════════════════════════════════
    # NİŞ 6-10: SAĞLIK / TEKNOLOJİ / EĞİTİM / PSİKOLOJİ (TR)
    # ══════════════════════════════════════════════════════════
    {
        "channel_id": "saglik_pusulasi",
        "name": "Sağlık Pusulası",
        "niche": "saglik", "language": "tr",
        "slogan": "Sağlıklı Yaşam, Mutlu Hayat",
        "tagline": "Sağlık & Wellness Rehberi",
        "upload_times": ["12:30", "00:30"],
        "color_primary": [34, 197, 94], "color_bg": [5, 20, 10],
        "pexels_query": "health wellness fitness medical nutrition",
        "status": "pending_oauth",
    },
    {
        "channel_id": "teknoloji_pusulasi",
        "name": "Teknoloji Pusulası",
        "niche": "teknoloji", "language": "tr",
        "slogan": "Teknolojiyi Kazan!",
        "tagline": "Teknoloji & Yapay Zeka",
        "upload_times": ["12:45", "00:45"],
        "color_primary": [6, 182, 212], "color_bg": [5, 20, 25],
        "pexels_query": "technology innovation artificial intelligence digital",
        "status": "pending_oauth",
    },
    {
        "channel_id": "egitim_rehberi",
        "name": "Eğitim Rehberi",
        "niche": "egitim", "language": "tr",
        "slogan": "Öğren, Büyü, Kazan!",
        "tagline": "Online Eğitim & Kişisel Gelişim",
        "upload_times": ["13:00", "01:00"],
        "color_primary": [168, 85, 247], "color_bg": [15, 8, 28],
        "pexels_query": "education learning university success student",
        "status": "pending_oauth",
    },
    {
        "channel_id": "psikoloji_okulu",
        "name": "Psikoloji Okulu",
        "niche": "psikoloji", "language": "tr",
        "slogan": "Zihnini Güçlendir!",
        "tagline": "Psikoloji & Kişisel Gelişim",
        "upload_times": ["13:15", "01:15"],
        "color_primary": [244, 114, 182], "color_bg": [20, 10, 18],
        "pexels_query": "psychology mental health mindfulness meditation",
        "status": "pending_oauth",
    },

    # ══════════════════════════════════════════════════════════
    # İNGİLİZCE KANALLAR (EN) - 10 niş × 8 = 80 kanal
    # ══════════════════════════════════════════════════════════
    {
        "channel_id": "finance_compass_en",
        "name": "Finance Compass",
        "niche": "kisisel_finans", "language": "en",
        "slogan": "Navigate Your Financial Future",
        "tagline": "Personal Finance & Investment",
        "upload_times": ["14:00", "02:00"],
        "color_primary": [212, 175, 55], "color_bg": [10, 18, 40],
        "pexels_query": "personal finance money investment wealth",
        "status": "pending_oauth",
    },
    {
        "channel_id": "stock_academy_en",
        "name": "Stock Academy",
        "niche": "borsa", "language": "en",
        "slogan": "Master the Stock Market",
        "tagline": "Stock Market & Investing",
        "upload_times": ["14:15", "02:15"],
        "color_primary": [239, 68, 68], "color_bg": [20, 10, 10],
        "pexels_query": "stock market trading wall street finance",
        "status": "pending_oauth",
    },
    {
        "channel_id": "crypto_compass_en",
        "name": "Crypto Compass",
        "niche": "kripto", "language": "en",
        "slogan": "Navigate the Crypto World",
        "tagline": "Bitcoin & Cryptocurrency Guide",
        "upload_times": ["14:30", "02:30"],
        "color_primary": [249, 115, 22], "color_bg": [20, 10, 5],
        "pexels_query": "cryptocurrency bitcoin blockchain trading",
        "status": "pending_oauth",
    },
    {
        "channel_id": "career_compass_en",
        "name": "Career Compass",
        "niche": "kariyer", "language": "en",
        "slogan": "Navigate Your Career Path",
        "tagline": "Career Growth & Salary Tips",
        "upload_times": ["14:45", "02:45"],
        "color_primary": [59, 130, 246], "color_bg": [10, 15, 25],
        "pexels_query": "career success professional business leadership",
        "status": "pending_oauth",
    },
    {
        "channel_id": "real_estate_compass_en",
        "name": "Real Estate Compass",
        "niche": "gayrimenkul", "language": "en",
        "slogan": "Build Wealth Through Real Estate",
        "tagline": "Real Estate Investment Guide",
        "upload_times": ["15:00", "03:00"],
        "color_primary": [245, 158, 11], "color_bg": [20, 15, 5],
        "pexels_query": "real estate investment property wealth",
        "status": "pending_oauth",
    },
    {
        "channel_id": "wealth_builder_en",
        "name": "Wealth Builder",
        "niche": "kisisel_finans", "language": "en",
        "slogan": "Build Generational Wealth",
        "tagline": "Wealth Building & FIRE Movement",
        "upload_times": ["15:15", "03:15"],
        "color_primary": [34, 197, 94], "color_bg": [5, 20, 10],
        "pexels_query": "wealth building financial independence retire early",
        "status": "pending_oauth",
    },
    {
        "channel_id": "dividend_king_en",
        "name": "Dividend King",
        "niche": "borsa", "language": "en",
        "slogan": "Live Off Dividends",
        "tagline": "Dividend Investing Guide",
        "upload_times": ["15:30", "03:30"],
        "color_primary": [16, 185, 129], "color_bg": [5, 18, 12],
        "pexels_query": "dividend stocks passive income investment",
        "status": "pending_oauth",
    },
    {
        "channel_id": "tech_finance_en",
        "name": "Tech Finance",
        "niche": "teknoloji", "language": "en",
        "slogan": "Where Tech Meets Finance",
        "tagline": "Tech Stocks & AI Investment",
        "upload_times": ["15:45", "03:45"],
        "color_primary": [6, 182, 212], "color_bg": [5, 18, 22],
        "pexels_query": "technology innovation investment stocks future",
        "status": "pending_oauth",
    },
    {
        "channel_id": "startup_compass_en",
        "name": "Startup Compass",
        "niche": "girisim", "language": "en",
        "slogan": "From Idea to IPO",
        "tagline": "Startup & Entrepreneurship Guide",
        "upload_times": ["16:00", "04:00"],
        "color_primary": [234, 88, 12], "color_bg": [20, 8, 3],
        "pexels_query": "startup entrepreneur innovation success office",
        "status": "pending_oauth",
    },
    {
        "channel_id": "health_wealth_en",
        "name": "Health & Wealth",
        "niche": "saglik", "language": "en",
        "slogan": "Healthy Body, Wealthy Mind",
        "tagline": "Health, Wellness & Finance",
        "upload_times": ["16:15", "04:15"],
        "color_primary": [244, 114, 182], "color_bg": [20, 8, 15],
        "pexels_query": "health wellness fitness success lifestyle",
        "status": "pending_oauth",
    },

    # ══════════════════════════════════════════════════════════
    # ALMANCA KANALLAR (DE)
    # ══════════════════════════════════════════════════════════
    {
        "channel_id": "finanz_kompass_de",
        "name": "Finanz Kompass",
        "niche": "kisisel_finans", "language": "de",
        "slogan": "Navigiere deine Finanzen",
        "tagline": "Persönliche Finanzen & Investitionen",
        "upload_times": ["16:30", "04:30"],
        "color_primary": [212, 175, 55], "color_bg": [10, 18, 40],
        "pexels_query": "personal finance money investment savings",
        "status": "pending_oauth",
    },
    {
        "channel_id": "aktien_akademie_de",
        "name": "Aktien Akademie",
        "niche": "borsa", "language": "de",
        "slogan": "Meistere die Börse",
        "tagline": "Aktien & Börsen Guide",
        "upload_times": ["16:45", "04:45"],
        "color_primary": [239, 68, 68], "color_bg": [20, 10, 10],
        "pexels_query": "stock market trading finance investing",
        "status": "pending_oauth",
    },
    {
        "channel_id": "krypto_kompass_de",
        "name": "Krypto Kompass",
        "niche": "kripto", "language": "de",
        "slogan": "Navigiere die Krypto-Welt",
        "tagline": "Bitcoin & Kryptowährungen",
        "upload_times": ["17:00", "05:00"],
        "color_primary": [249, 115, 22], "color_bg": [20, 10, 5],
        "pexels_query": "cryptocurrency bitcoin blockchain digital",
        "status": "pending_oauth",
    },
    {
        "channel_id": "karriere_kompass_de",
        "name": "Karriere Kompass",
        "niche": "kariyer", "language": "de",
        "slogan": "Deine Karriere, deine Regeln",
        "tagline": "Karriere & Gehaltsverhandlung",
        "upload_times": ["17:15", "05:15"],
        "color_primary": [59, 130, 246], "color_bg": [10, 15, 25],
        "pexels_query": "career success business professional leadership",
        "status": "pending_oauth",
    },
    {
        "channel_id": "immobilien_kompass_de",
        "name": "Immobilien Kompass",
        "niche": "gayrimenkul", "language": "de",
        "slogan": "Reich mit Immobilien",
        "tagline": "Immobilien Investment Guide",
        "upload_times": ["17:30", "05:30"],
        "color_primary": [245, 158, 11], "color_bg": [20, 15, 5],
        "pexels_query": "real estate property investment house luxury",
        "status": "pending_oauth",
    },
]

# ─── Şablon: Toplam 200'e tamamlamak için ──────────────────────────────────────
# (Yukarıda 35 kanal tanımlandı, geri kalanı kod ile otomatik oluşturulacak)

NICHE_TEMPLATES = {
    "kisisel_finans": {
        "colors": [(212, 175, 55), (34, 197, 94), (251, 191, 36), (99, 102, 241)],
        "bg_colors": [(10, 18, 40), (10, 30, 20), (20, 10, 0), (15, 15, 35)],
        "en_queries": ["personal finance money", "savings investment wealth", "financial planning budget", "money management tips"],
    },
    "borsa": {
        "colors": [(239, 68, 68), (16, 185, 129), (245, 158, 11), (168, 85, 247)],
        "bg_colors": [(20, 10, 10), (5, 20, 15), (20, 15, 5), (20, 10, 30)],
        "en_queries": ["stock market trading", "dividend stocks passive income", "technical analysis stocks", "value investing growth"],
    },
    "kripto": {
        "colors": [(249, 115, 22), (251, 191, 36), (6, 182, 212), (139, 92, 246)],
        "bg_colors": [(20, 10, 5), (20, 12, 0), (5, 20, 25), (15, 5, 30)],
        "en_queries": ["cryptocurrency bitcoin blockchain", "bitcoin trading crypto", "altcoin defi yield farming", "web3 nft metaverse"],
    },
}

LANGUAGES = {
    "tr": "Türkçe", "en": "English", "de": "Deutsch",
    "es": "Español", "fr": "Français", "pt": "Português",
}


def generate_200_channels(existing_plans):
    """Mevcut planlara ek kanallar ekleyerek 200'e tamamla."""
    channels = {c["channel_id"]: c for c in existing_plans}
    niches = ["kisisel_finans", "borsa", "kripto", "kariyer", "gayrimenkul",
              "saglik", "teknoloji", "egitim", "girisim", "psikoloji"]
    langs = ["tr", "en", "de", "es", "fr"]
    counter = 1
    hour = 17
    minute = 45

    while len(channels) < 200:
        for niche in niches:
            for lang in langs:
                if len(channels) >= 200:
                    break
                cid = f"{niche}_{lang}_{counter:03d}"
                if cid in channels:
                    continue
                niche_idx = counter % 4
                tmpl = NICHE_TEMPLATES.get(niche, NICHE_TEMPLATES["kisisel_finans"])
                col = tmpl["colors"][niche_idx % len(tmpl["colors"])]
                bg  = tmpl["bg_colors"][niche_idx % len(tmpl["bg_colors"])]
                query = tmpl["en_queries"][niche_idx % len(tmpl["en_queries"])]

                h_str = f"{hour:02d}:{minute:02d}"
                h2_str = f"{(hour + 12) % 24:02d}:{minute:02d}"
                minute = (minute + 15) % 60
                if minute == 0:
                    hour = (hour + 1) % 24

                channels[cid] = {
                    "channel_id": cid,
                    "name": f"{niche.replace('_', ' ').title()} {lang.upper()} {counter}",
                    "niche": niche, "language": lang,
                    "slogan": "Content Creator Pro",
                    "tagline": f"{niche.replace('_', ' ').title()} Channel",
                    "upload_times": [h_str, h2_str],
                    "color_primary": list(col), "color_bg": list(bg),
                    "pexels_query": query,
                    "status": "pending_oauth",
                }
            counter += 1
            if len(channels) >= 200:
                break

    return channels


def setup_channel_dirs(channels):
    """Her kanal için klasör yapısı oluştur."""
    for cid, cfg in channels.items():
        base = Path(f"channels/{cid}")
        for sub in ["branding", "output/videos", "output/audio", "output/scripts", "output/clips"]:
            (base / sub).mkdir(parents=True, exist_ok=True)
    print(f"✅ {len(channels)} kanal için klasör yapısı oluşturuldu")


def save_registry(channels):
    """channel_registry.json güncelle."""
    reg_path = Path("channels/channel_registry.json")
    existing = json.loads(reg_path.read_text()) if reg_path.exists() else {"channels": {}}
    existing_channels = existing.get("channels", {})

    # Mevcut kanalları koru (OAuth tokenları vs.)
    for cid, cfg in channels.items():
        if cid not in existing_channels:
            existing_channels[cid] = cfg
        else:
            # Sadece eksik alanları güncelle
            for k, v in cfg.items():
                if k not in existing_channels[cid]:
                    existing_channels[cid][k] = v

    existing["channels"] = existing_channels
    reg_path.write_text(json.dumps(existing, indent=2, ensure_ascii=False))
    print(f"✅ Registry güncellendi: {len(existing_channels)} kanal")
    return existing_channels


def show_summary(channels):
    active = sum(1 for c in channels.values() if c.get("status") == "active")
    pending = sum(1 for c in channels.values() if c.get("status") == "pending_oauth")
    by_lang = {}
    for c in channels.values():
        lang = c.get("language", "?")
        by_lang[lang] = by_lang.get(lang, 0) + 1

    print(f"\n{'='*55}")
    print(f"  200 KANAL SİSTEMİ KURULUM ÖZETI")
    print(f"{'='*55}")
    print(f"  Toplam kanal     : {len(channels)}")
    print(f"  Aktif (OAuth ✓)  : {active}")
    print(f"  OAuth bekliyor   : {pending}")
    print(f"\n  Dile göre dağılım:")
    for lang, count in sorted(by_lang.items(), key=lambda x: -x[1]):
        print(f"    {LANGUAGES.get(lang, lang):12s}: {count:3d} kanal")
    print(f"\n  Sonraki adım: python onboard_channel.py --channel-id <ID>")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    print("200 kanal sistemi kuruluyor...")
    all_channels = generate_200_channels(CHANNEL_PLANS)
    print(f"  {len(all_channels)} kanal konfigürasyonu oluşturuldu")
    setup_channel_dirs(all_channels)
    saved = save_registry(all_channels)
    show_summary(saved)
