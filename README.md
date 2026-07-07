# 🎬 YouTube AI Pasif Gelir Otomasyonu

Claude AI + YouTube Data API kullanarak tam otomatik YouTube içerik üretim ve yükleme sistemi.

---

## 📊 SİSTEM MİMARİSİ

```
[Claude API] → Script Üret
      ↓
[gTTS / ElevenLabs] → Sesli Anlatım
      ↓
[MoviePy] → Video Montajı (görseller + ses)
      ↓
[YouTube Data API v3] → Otomatik Yükleme
      ↓
[Scheduler] → Günlük/Haftalık Çalıştırma
```

---

## 💰 PASİF GELİR STRATEJİSİ

### Önerilen Niş Kategoriler (Yüksek RPM = Reklam Geliri)
| Niş | Tahmini RPM | Zorluk |
|-----|------------|--------|
| Kişisel Finans / Yatırım | $5–$15 | Orta |
| Teknoloji / Yazılım | $4–$12 | Düşük |
| Sağlık / Yaşam Tarzı | $3–$8 | Düşük |
| İş Dünyası / Girişimcilik | $6–$18 | Orta |
| Eğitim / Öğrenme | $4–$10 | Düşük |

### Gelir Kaynakları
1. **YouTube AdSense** – 1000 abone + 4000 saat sonrası
2. **Affiliate Marketing** – Video açıklamalarına bağlantı
3. **Sponsorluk** – Niş büyüyünce
4. **Kurs / Dijital Ürün** – Kanaldan yönlendirme

---

## 🚀 KURULUM

### 1. Gereksinimler
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. API Anahtarları
`.env.example` dosyasını `.env` olarak kopyala ve doldur:
```bash
cp .env.example .env
```

**Gerekli API'ler:**
- **Anthropic (Claude):** https://console.anthropic.com
- **YouTube Data API v3:** https://console.cloud.google.com
- **ElevenLabs (isteğe bağlı):** https://elevenlabs.io

### 3. YouTube OAuth Kurulumu
```bash
python src/youtube_auth.py
```

### 4. Çalıştır
```bash
# Tek video üret ve yükle
python main.py --once

# Otomatik zamanlayıcı ile çalıştır
python main.py --schedule

# Sadece içerik üret (yüklemeden)
python main.py --generate-only
```

---

## 📁 PROJE YAPISI

```
youtube-ai-automation/
├── main.py                  # Ana giriş noktası
├── requirements.txt         # Bağımlılıklar
├── .env.example             # Ortam değişkenleri şablonu
├── src/
│   ├── config.py            # Yapılandırma yöneticisi
│   ├── content_generator.py # Claude AI ile içerik üretimi
│   ├── tts_engine.py        # Metinden sese dönüştürme
│   ├── video_creator.py     # Video montajı
│   ├── youtube_uploader.py  # YouTube yükleme
│   ├── youtube_auth.py      # OAuth kimlik doğrulama
│   └── scheduler.py         # Otomasyon zamanlayıcı
├── assets/
│   ├── backgrounds/         # Arka plan görselleri
│   ├── music/               # Fon müziği (telif hakkı yok)
│   └── fonts/               # Yazı tipleri
├── output/
│   ├── scripts/             # Üretilen scriptler
│   ├── audio/               # Oluşturulan ses dosyaları
│   └── videos/              # Hazır videolar
└── logs/
    └── automation.log       # İşlem günlükleri
```

---

## ⚠️ ÖNEMLİ NOTLAR

- YouTube politikalarına uygun içerik üretin
- Tamamen AI üretimi içerikler için açıklama ekleyin
- Başlangıçta haftada 2-3 video idealdir
- İlk 6-12 ay gelir düşük olabilir, sabırlı olun
