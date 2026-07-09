# Thumbnail Intelligence Contract (Sprint T1)

## 1. Amaç
Thumbnail Intelligence katmanının kalite, güvenlik, tutarlılık ve çeşitlilik kararlarını üretimden önce standart bir kontratla sabitlemek.

Bu kontratın hedefi:
- Thumbnail üretim kalitesini ölçülebilir kriterlerle tanımlamak.
- Reddedilme nedenlerini standartlaştırmak.
- A/B ve performans analizleri için gerekli metadata alanlarını zorunlu hale getmek.

## 2. Scope / Out Of Scope

### Scope
- Thumbnail kalite kriterleri ve minimum geçiş eşiği.
- Safe-area (güvenli alan) kuralları.
- Text density (metin yoğunluğu) limitleri.
- Face/object clarity (yüz/nesne netliği) kriterleri.
- Brand consistency kuralları.
- Duplicate/diversity guard politikası.
- Rejection reason listesi ve kodları.
- Metadata şeması.

### Out Of Scope
- Yeni görsel model sağlayıcı entegrasyonu.
- CTR modelleme veya otomatik winner selection.
- Yayın sırasında dinamik thumbnail değiştirme orkestrasyonu.
- İnsan kreatif ekip sürecinin tamamen kaldırılması.

## 3. Thumbnail Kalite Kriterleri
Bir thumbnail'in "pass" alması için aşağıdaki çekirdek kriterlerin tamamı sağlanmalıdır:
- Odak netliği: ana konu (yüz veya ana nesne) görselde tek bakışta ayrışmalı.
- Kompozisyon dengesi: ana odak, kadrajın kenarlarında kırpılma riski taşımamalı.
- Renk kontrastı: metin/odak ve arka plan arasında yeterli ayrım olmalı.
- Gürültü kontrolü: aşırı karmaşık ve dikkat dağıtan detay yoğunluğu olmamalı.
- Mobil okunabilirlik: küçük ekranda ana mesaj 1 saniye içinde anlaşılmalı.

## 4. Safe-Area Kuralları
Thumbnail 1280x720 varsayımı ile güvenli alan kuralları:
- Dış güvenli kenar boşluğu: her tarafta minimum %5.
- Kritik içerik (yüz, logo, ana nesne, ana metin) bu alanın dışına taşmamalı.
- Sol alt ve sağ alt köşelerde platform overlay riskleri için ek dikkat uygulanmalı.
- Metin blokları alt kenara yapışık yerleşmemeli.

## 5. Text Density Limiti
Metin kullanım politikası:
- Toplam metin uzunluğu önerilen üst sınır: 6 kelime.
- Maksimum satır sayısı: 2.
- Maksimum farklı font stili: 2.
- Görsel alanın metinle kaplanan oranı üst sınır: %20.

Red kuralı:
- Metin alanı > %20 veya 2 satırdan fazla ise `TEXT_DENSITY_EXCEEDED`.

## 6. Face/Object Clarity Kriterleri
- Ana odak (yüz/nesne) en az bir net bölge içinde olmalı (bulanıklık düşük).
- Ana odak arka plandan kontrast ile ayrışmalı.
- Yüz varsa göz bölgesi veya ifade okunabilir olmalı.
- Nesne varsa sınıfı ilk bakışta anlaşılmalı (belirsiz siluet olmamalı).

Red kuralı:
- Ana odak net değilse `SUBJECT_CLARITY_LOW`.

## 7. Brand Consistency Kuralları
- Kanalın tanımlı renk paleti ile çelişen aşırı sapma olmamalı.
- Kanal tonu ile uyumsuz tipografi kullanılmamalı.
- Zorunlu marka ögeleri (varsa logo/etiket) güvenli alanda ve tutarlı pozisyonda olmalı.
- Aynı kanal içinde kısa süreli üretimlerde stil kimliği dramatik biçimde değişmemeli.

Red kuralı:
- Marka profiline aykırı tasarım `BRAND_INCONSISTENT`.

## 8. Duplicate/Diversity Guard
Amaç: tekrar eden veya birbirine aşırı benzeyen thumbnail'leri engellemek.

Kurallar:
- Aynı kanal için yakın geçmiş penceresinde (örn. son 30 thumbnail) benzer kompozisyon tekrarları sınırlanır.
- Başlık farklı olsa bile görsel şablon tekrar puanı eşik üzerindeyse reddedilir.
- Varyant üretiminde en az bir görsel eksen (renk, kadraj, tipografi, odak yerleşimi) anlamlı farklılaşma göstermelidir.

Red kuralı:
- Benzerlik eşiği aşılırsa `DUPLICATE_OR_LOW_DIVERSITY`.

## 9. Rejection Reason Listesi
Standart red kodları:
- `SAFE_AREA_VIOLATION`: Kritik ögeler güvenli alan dışına taşıyor.
- `TEXT_DENSITY_EXCEEDED`: Metin yoğunluğu limiti aşıldı.
- `SUBJECT_CLARITY_LOW`: Yüz/nesne netliği düşük.
- `BRAND_INCONSISTENT`: Kanal marka kimliği ile uyumsuz.
- `DUPLICATE_OR_LOW_DIVERSITY`: Yakın geçmişe göre aşırı benzer.
- `LOW_CONTRAST`: Metin/odak ayrımı yetersiz.
- `VISUAL_CLUTTER`: Kompozisyon aşırı kalabalık.

## 10. Metadata Schema
Her thumbnail değerlendirmesi için minimum metadata:

```json
{
  "schema_version": "thumbnail_intelligence_v1",
  "channel_id": "string",
  "content_id": "string",
  "thumbnail_path": "string",
  "variant_id": "string",
  "evaluated_at_utc": "ISO-8601",
  "quality": {
    "safe_area_pass": true,
    "text_density_ratio": 0.0,
    "text_density_pass": true,
    "subject_clarity_pass": true,
    "brand_consistency_pass": true,
    "diversity_pass": true,
    "contrast_pass": true,
    "overall_pass": true
  },
  "rejection_reasons": [],
  "diversity": {
    "window_size": 30,
    "similarity_score": 0.0,
    "similarity_threshold": 0.0
  },
  "brand_profile_version": "string"
}
```

## 11. Sprint T1 Acceptance Criteria
- Bu kontrat dokümanı repoda yayınlanmış ve referanslı olmalı.
- Kriter başlıklarının tamamı (kalite, safe-area, text density, clarity, brand, diversity, rejection, metadata) dokümante edilmeli.
- Rejection reason listesi standart kodlarla sabitlenmiş olmalı.
- Metadata şeması zorunlu alanlarıyla tanımlanmış olmalı.
- Faz 2 plan dokümanında bu kontrata açık referans bulunmalı.

Not:
- Sprint T1 yalnızca kontrat/sözleşme katmanıdır.
- Üretim motoru, skorlayıcı veya A/B orkestrasyon implementasyonu Sprint T1 kapsamı dışındadır.