"""
İçerik Piramidi Sistemi
Evergreen + Semi-Evergreen + Trend dengesi.
Her kanal için pillar videolar ve seri sistemi.
"""
import json
import random
from datetime import datetime
from pathlib import Path

# ─── İçerik Dağılımı ─────────────────────────────────────────────────────────
CONTENT_MIX = {
    "evergreen": 0.30,       # Sıfırdan rehber, temel kavramlar
    "semi_evergreen": 0.50,  # Yıllık güncel ama uzun vadeli
    "trending": 0.20,        # Güncel haberler, piyasa yorumu
}

# ─── Pillar Video Listesi (Evergreen) ─────────────────────────────────────────
PILLAR_VIDEOS = {
    "kisisel_finans": [
        "Borsa'ya Sıfırdan Başlamak İçin Tam Rehber (Adım Adım)",
        "Aylık 10.000 TL Birikim Planı: Gerçekçi Adımlar",
        "Türkiye'de Emeklilik Planlaması: BES vs Devlet Emekliliği",
        "Enflasyona Karşı Paranızı Nasıl Korursunuz? (Kalıcı Strateji)",
        "Bütçe Yönetimi: Her Ay Borç Ödemekten Nasıl Kurtulursunuz",
        "Yatırım Araçları Karşılaştırması: Borsa, Altın, Dolar, Kripto",
        "Pasif Gelir Nedir? Türkiye'de Gerçekten Mümkün Mü?",
        "Finansal Özgürlük Hesabı: Kaç TL Biriktirmem Gerekiyor?",
        "50/30/20 Bütçe Kuralı Türkiye'de Çalışır Mı?",
        "Acil Fon Nedir ve Kaç Aylık Gelir Biriktirmeli?",
    ],
    "borsa": [
        "Borsa Nedir? Türkiye'de Nasıl Hisse Senedi Alınır",
        "Teknik Analiz Temelleri: Mum Grafikleri, Destek-Direnç",
        "Temel Analiz Nasıl Yapılır? F/K, PD/DD, ROE Açıklaması",
        "BIST'te Temettü Yatırımı: Pasif Gelir İçin Rehber",
        "Risk Yönetimi: Stop-Loss, Portföy Çeşitlendirme",
        "ETF ve Fon Yatırımı: Pasif Borsa Yatırımı Rehberi",
        "Hisse Senedi Seçim Kriterleri: Neye Bakmalıyım?",
        "BIST vs Nasdaq: Yabancı Borsaya Nasıl Yatırım Yapılır?",
        "Kısa Vadeli vs Uzun Vadeli Yatırım: Hangisi Size Uygun?",
        "Portföy Nasıl Oluşturulur: Başlangıç Rehberi",
    ],
    "kripto": [
        "Kripto Para Nedir? Sıfırdan Başlayanlar İçin Tam Rehber",
        "Bitcoin Nasıl Alınır? Türk Borsalarında Güvenli Alım",
        "Kripto Cüzdan Nedir? Cold Wallet vs Hot Wallet",
        "DeFi Nedir? Merkezsiz Finans Başlangıç Rehberi",
        "Kripto Vergilendirme Türkiye: Ne Ödemem Gerekiyor?",
        "Altcoin Seçimi: Hangi Kriterlere Dikkat Edilmeli?",
        "Kripto Dolandırıcılığı: En Yaygın 10 Tuzak",
        "Bitcoin vs Ethereum: Farklar ve Hangisini Almalı?",
        "Kripto Portföy Yönetimi: Çeşitlendirme Stratejisi",
        "Staking Nedir? Kripto ile Pasif Gelir Nasıl Kazanılır?",
    ],
    "kariyer": [
        "Türkiye'de Maaş Müzakeresi: %30 Zam Nasıl İstenir",
        "Remote Çalışma Rehberi: Yabancı Şirket, Türkiye'den",
        "LinkedIn Profili Nasıl Olmalı? İş Bulduran Profil Sırları",
        "Freelance'a Nasıl Başlanır? Upwork, Fiverr Türk Rehberi",
        "Kariyer Değişikliği: 30'larında Yeni Bir Mesleğe Geçmek",
        "İşten Çıkarılma Tazminatı: Haklarınızı Biliyor musunuz?",
        "Uzaktan Çalışırken Verimlilik: En İyi 15 Yöntem",
        "CV Nasıl Yazılır? İnsan Kaynakları Uzmanından Sırlar",
        "İş Görüşmesi Soruları ve Cevapları: Tam Hazırlık",
        "Yan Gelir Kaynakları: Çalışırken Ek Para Nasıl Kazanılır?",
    ],
    "girisimcilik": [
        "Türkiye'de Şirket Kurma: A'dan Z'ye Adımlar ve Maliyetler",
        "E-Ticaret'e Nasıl Başlanır? Trendyol, Hepsiburada Rehberi",
        "Startup Fikri Var, Ne Yapmalıyım? Türkiye'de Girişimcilik",
        "Dijital Ürün Satışı: Kurs, e-Kitap ile Pasif Gelir",
        "Dropshipping Türkiye: Gerçekten Çalışıyor mu?",
        "Instagram ile Para Kazanma: 10.000 Takipçiden Gelire",
        "Yatırımcı Bulmak: Türkiye'de Melek Yatırımcı ve VC",
        "İş Planı Nasıl Yazılır? Bankadan Kredi Almak İçin",
        "Franchise vs Kendi İşi: Hangisi Daha Karlı?",
        "Online Kurs Hazırlama ve Satma: Adım Adım Rehber",
    ],
    "saglik": [
        "Sağlıklı Beslenme Rehberi: Türk Mutfağıyla Nasıl Sağlıklı Yenir?",
        "Bağışıklık Sistemini Güçlendirme: Kanıtlanmış Yöntemler",
        "Uyku Kalitesini Artırma: Bilimsel 10 Yöntem",
        "Stres Yönetimi: Kronik Stresten Nasıl Kurtulunur?",
        "Evde Egzersiz Programı: Alet Gerekmeden Fit Kalma",
        "Su İçmenin Önemi: Günde Kaç Litre İçmeli?",
        "Şeker Bağımlılığı Nasıl Kırılır?",
        "Sağlıklı Kilo Verme: Diyet Değil Yaşam Tarzı",
        "Vitamin ve Mineral Eksikliği: Belirtiler ve Çözümler",
        "Zihinsel Sağlık: Türkiye'de Terapist Bulma Rehberi",
    ],
    "teknoloji": [
        "Yapay Zeka ile Verimliliği Artırma: ChatGPT, Claude Rehberi",
        "Python'a Sıfırdan Başlamak: 2026 Tam Rehber",
        "Siber Güvenlik: Kendinizi Online Nasıl Korursunuz?",
        "Freelance Yazılımcı Olmak: Türkiye'den Dünyaya",
        "AI ile Para Kazanma: Gerçekçi Yöntemler",
        "YouTube Otomasyonu: AI ile İçerik Üretimi",
        "No-Code Araçları: Kod Yazmadan Uygulama Geliştirme",
        "Dijital Dönüşüm: Küçük İşletmeler İçin Rehber",
        "Veri Analizi Öğrenme: Excel'den Python'a Geçiş",
        "Blockchain Teknolojisi Nedir? Teknik Olmayan Rehber",
    ],
    "egitim": [
        "Hızlı Öğrenme Teknikleri: Feynman, Pomodoro ve Daha Fazlası",
        "Online Kurs Seçimi: Udemy, Coursera Hangisi?",
        "Hafıza Güçlendirme: Bilimsel Yöntemler",
        "Yabancı Dil Öğrenme: 6 Ayda B2 Seviyesi Mümkün Mü?",
        "Hedef Belirleme ve Gerçekleştirme: SMART Yöntemi",
        "Kitap Okuma Hızını Artırma: Hızlı Okuma Teknikleri",
        "Üniversite Seçimi Rehberi: Türkiye'de 2026",
        "Öğrenci Bütçesi: Harçlıkla Nasıl Geçinilir?",
        "Sınav Kaygısı ile Başa Çıkma: Psikolojik Yöntemler",
        "Sertifika Kursları: Kariyere Değer Katan Belgeler",
    ],
    "gayrimenkul": [
        "Türkiye'de Ev Almak: A'dan Z'ye Süreç ve Maliyetler",
        "Kira mı Alma mı? Türkiye'de Gerçekçi Hesap",
        "Gayrimenkul Yatırımı için Şehir Seçimi: 2026 Analizi",
        "Kira Geliri ile Pasif Gelir: Gerçekçi Rakamlar",
        "Konut Kredisi Hesaplama: En Uygun Banka Hangisi?",
        "Tapu İşlemleri Nasıl Yapılır? Adım Adım Rehber",
        "Kiracı Hakları ve Ev Sahibi Hakları Türkiye",
        "Ticari Gayrimenkul Yatırımı: Dükkan, Depo, Ofis",
        "Yurt Dışında Gayrimenkul Almak: Türkler İçin Rehber",
        "REIT/GYO Nedir? Gayrimenkul Fonu ile Yatırım",
    ],
    "psikoloji": [
        "Öz Güven Nasıl Kazanılır? Bilimsel Yöntemler",
        "Toksik İlişkilerden Nasıl Çıkılır?",
        "Kaygı Bozukluğu ile Başa Çıkma: Uzman Tavsiyeleri",
        "Sınır Koyma Sanatı: Hayır Diyebilmek",
        "Motivasyonu Nasıl Canlı Tutarsınız? Sabah Rutini",
        "Ertelemeciliği Yenmek: Prokrastinasyon Rehberi",
        "İlişkilerde İletişim: Sağlıklı Çift İlişkisi Sırları",
        "Öfke Kontrolü: Patlamadan Önce Ne Yapmalı?",
        "Özgüven ile Kibir Arasındaki Fark",
        "Mindfulness Nedir? Günlük 10 Dakika Meditasyon",
    ],
}

# ─── Seri Sistemi ─────────────────────────────────────────────────────────────
SERIES_TEMPLATES = {
    "kisisel_finans": [
        {
            "name": "Borsa 101",
            "episodes": [
                "Borsa Nedir? Neden Önemlidir?",
                "İlk Hisse Nasıl Alınır?",
                "Teknik Analiz Temelleri",
                "Temel Analiz Nasıl Yapılır",
                "Risk Yönetimi ve Stop-Loss",
                "Portföy Çeşitlendirme",
                "Temettü Stratejisi",
                "Uzun Vadeli Yatırım Felsefesi",
            ],
        },
        {
            "name": "Para Yönetimi 101",
            "episodes": [
                "Bütçe Nasıl Yapılır?",
                "Acil Fon Nedir ve Nasıl Biriktirilir?",
                "Borç Ödemek mi Yatırım mı?",
                "Sigorta Türleri: Hangisini Almalısınız?",
                "Vergi Optimizasyonu: Yasal Tasarruf Yolları",
                "Emeklilik Planlaması: 35 Yaşında Başlamak",
            ],
        },
    ],
    "borsa": [
        {
            "name": "BIST Analiz Serisi",
            "episodes": [
                "BIST 100'ü Okumak",
                "Sektör Analizi Nasıl Yapılır?",
                "Bilanço Okuma Rehberi",
                "Nakit Akışı Analizi",
                "DCF ile Hisse Değerleme",
                "Teknik Analiz ile Alım-Satım Noktaları",
            ],
        },
        {
            "name": "Temettü Yatırımı Serisi",
            "episodes": [
                "Temettü Nedir? Neden Önemli?",
                "Temettü Verimine Göre Hisse Seçimi",
                "BIST'in En İyi Temettü Hisseleri",
                "Temettü Takvimi ve Strateji",
                "Temettü ile Emeklilik Planı",
            ],
        },
    ],
    "kripto": [
        {
            "name": "Kripto 101",
            "episodes": [
                "Blockchain Nedir? Temel Kavramlar",
                "Bitcoin: Dijital Altın mı Spekülasyon mu?",
                "Ethereum ve Akıllı Kontratlar",
                "DeFi'ye Giriş: Merkezsiz Finans",
                "NFT Nedir? Gerçek Değeri Var mı?",
                "Kripto Güvenliği: Varlıklarınızı Koruyun",
                "Kripto Vergi Rehberi",
                "Kripto Portföy Stratejisi",
            ],
        },
    ],
    "kariyer": [
        {
            "name": "Kariyer Hızlandırma Serisi",
            "episodes": [
                "Kariyer Planlaması: 5 Yıllık Yol Haritası",
                "LinkedIn'i Silah Gibi Kullanmak",
                "Maaş Müzakeresi Taktikleri",
                "Network Kurma Sanatı",
                "Terfi İçin Neler Yapmalısınız?",
                "Kariyer Değişikliği Rehberi",
            ],
        },
    ],
    "girisimcilik": [
        {
            "name": "Sıfırdan Girişim Serisi",
            "episodes": [
                "İş Fikri Nasıl Bulunur?",
                "Fikri Doğrulamak: MVP Nedir?",
                "Şirket Kurma: Yasal Süreç",
                "İlk Müşterileri Bulmak",
                "Dijital Pazarlama ile Büyüme",
                "Finansman: Banka, Melek, VC",
                "Ölçeklendirme Stratejileri",
            ],
        },
    ],
    "saglik": [
        {
            "name": "Sağlıklı Yaşam 101",
            "episodes": [
                "Sağlıklı Beslenmenin Temelleri",
                "Egzersiz Planı: Haftada 3 Gün",
                "Uyku Optimizasyonu",
                "Stres Yönetimi Teknikleri",
                "Vitamin ve Mineral Rehberi",
                "Zihinsel Sağlık: Farkındalık",
            ],
        },
    ],
    "teknoloji": [
        {
            "name": "AI ile Çalışma Serisi",
            "episodes": [
                "ChatGPT ile Verimliliği 2x Artırın",
                "Claude ile İçerik Üretimi",
                "AI ile Kod Yazma: GitHub Copilot",
                "AI Görsel Araçları: Midjourney, DALL-E",
                "AI ile İş Otomasyonu",
                "AI Kariyer Fırsatları",
            ],
        },
    ],
    "egitim": [
        {
            "name": "Öğrenmeyi Öğrenmek Serisi",
            "episodes": [
                "Beyin Nasıl Öğrenir? Bilim",
                "Pomodoro Tekniği ile Odaklanma",
                "Feynman Metodu: Derin Anlama",
                "Aralıklı Tekrar: Anki Rehberi",
                "Zihin Haritası ile Not Alma",
                "Aktif Öğrenme vs Pasif Okuma",
            ],
        },
    ],
    "gayrimenkul": [
        {
            "name": "Ev Alma Rehberi Serisi",
            "episodes": [
                "Ev Almadan Önce Bilmeniz Gerekenler",
                "Bütçe Hesaplama: Ne Kadar Ödeyebilirsiniz?",
                "Konut Kredisi Süreci",
                "Emlak Ekspertizi Neden Şart?",
                "Tapu Devri ve Vergi Rehberi",
                "İlk Evinizi Aldıktan Sonra",
            ],
        },
    ],
    "psikoloji": [
        {
            "name": "Zihin Gücü Serisi",
            "episodes": [
                "Öz Farkındalık: Kendinizi Tanıyın",
                "Olumsuz Düşüncelerle Başa Çıkma",
                "Alışkanlık Oluşturma Bilimi",
                "Duygusal Zeka Nasıl Geliştirilir?",
                "Motivasyon: İçsel vs Dışsal",
                "Mindfulness: Günlük Pratik",
                "Mutluluk Bilimi: Pozitif Psikoloji",
            ],
        },
    ],
}


def get_content_type_for_next_video(channel_id: str, scripts_dir: str) -> str:
    """Sonraki videonun içerik türünü belirle (piramit dengesini koru)."""
    # Son 10 videoyu analiz et
    recent_types = _analyze_recent_content(scripts_dir, limit=10)
    trending_ratio = recent_types.count("trending") / max(len(recent_types), 1)
    evergreen_ratio = recent_types.count("evergreen") / max(len(recent_types), 1)

    # Dengeyi koru
    if evergreen_ratio < CONTENT_MIX["evergreen"] - 0.05:
        return "evergreen"
    if trending_ratio > CONTENT_MIX["trending"] + 0.05:
        return "semi_evergreen"
    return random.choices(
        ["evergreen", "semi_evergreen", "trending"],
        weights=[CONTENT_MIX["evergreen"], CONTENT_MIX["semi_evergreen"], CONTENT_MIX["trending"]],
    )[0]


def get_pillar_topic(niche: str, used_titles: list) -> str | None:
    """Henüz yapılmamış bir pillar video konusu getir."""
    pillars = PILLAR_VIDEOS.get(niche, [])
    used_lower = [t.lower() for t in used_titles]
    for pillar in pillars:
        if not any(pillar[:20].lower() in u for u in used_lower):
            return pillar
    return None


def get_series_next_episode(niche: str, used_titles: list) -> tuple[str, str] | None:
    """
    Devam eden bir serinin sonraki bölümünü döndür.
    (seri_adı, bölüm_başlığı) döndürür.
    """
    series_list = SERIES_TEMPLATES.get(niche, [])
    for series in series_list:
        name = series["name"]
        for i, episode in enumerate(series["episodes"]):
            full_title = f"{name} #{i+1}: {episode}"
            if not any(episode[:15].lower() in t.lower() for t in used_titles):
                return (name, full_title)
    return None


def _analyze_recent_content(scripts_dir: str, limit: int = 10) -> list:
    """Son yüklenen içeriklerin türlerini analiz et."""
    types = []
    paths = sorted(Path(scripts_dir).glob("*.json"), reverse=True)[:limit]
    for p in paths:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            ctype = data.get("content_type", "semi_evergreen")
            types.append(ctype)
        except Exception:
            types.append("semi_evergreen")
    return types
