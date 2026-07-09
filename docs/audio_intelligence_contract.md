# Audio Intelligence Contract

## 1. Amaç
Audio Intelligence hattının amacı, üretim pipeline içinde ses/müzik kalitesini ölçülebilir ve tekrarlanabilir bir standarda oturtmaktır. Bu sözleşme, loudness hedefleri, ducking kuralları, metadata şemaları ve fail-open davranışı için tek referans kaynaktır.

## 2. Scope / Out of Scope
### Scope
- Music selection kararına ait metadata standardı.
- Audio mix çıktısına ait metadata standardı.
- Loudness hedefi ve tolerans bandı.
- Ducking uygulanma koşulları ve parametreleri.
- Warning ve rejection reason kodları.
- Uploadsuz smoke test kabul kriterleri.

### Out of Scope
- Yeni scheduler davranışı.
- Yeni thumbnail/analytics karar katmanı.
- Upload API tarafında davranış değişikliği.
- Live analytics ile öğrenen audio policy.

## 3. Loudness Standardı
- Hedef integrated loudness: -16.0 LUFS.
- Tolerans bandı: +/- 1.5 LUFS.
- True peak üst sınırı: -1.0 dBTP.
- Hedef karşılanmazsa pipeline durdurulmaz; warning üretilir.

## 4. Ducking Kuralları
- Konuşma segmenti algılandığında müzik ducking uygulanır.
- Varsayılan ducking gain reduction: -12 dB.
- Attack: 120 ms.
- Release: 280 ms.
- Konuşma yoksa ducking uygulanmaz.
- Ducking hesaplama/mix hatası pipeline durdurmaz; fail-open warning yazılır.

## 5. Music Selection Metadata Schema
Zorunlu alanlar:
- schema_version: string
- channel_id: string
- content_id: string
- track_id: string
- selection_strategy: string
- selection_source: string
- selected_at_utc: string (ISO-8601)

Opsiyonel alanlar:
- mood: string
- tempo_bpm: number
- energy: number
- license_tier: string

## 6. Audio Mix Metadata Schema
Zorunlu alanlar:
- schema_version: string
- channel_id: string
- content_id: string
- mix_applied: boolean
- ducking_applied: boolean
- loudness_target_lufs: number
- loudness_measured_lufs: number
- true_peak_dbtp: number
- mixed_at_utc: string (ISO-8601)

Opsiyonel alanlar:
- music_track_id: string
- ducking_gain_db: number
- ducking_attack_ms: number
- ducking_release_ms: number
- warning_codes: list[string]

## 7. Fail-Open Davranış
- Audio selection/mix/validation hataları pipeline akışını kesmemelidir.
- Hata halinde result içine standart warning alanı yazılır.
- Warning alanı, hata sınıfını ve kodunu içermelidir.
- Fail-open yalnız audio katmanıyla sınırlıdır; crash/restart gerektiren sistemik hatalar bu sözleşmenin dışındadır.

## 8. Warning / Rejection Reason Listesi
Warning reason kodları:
- audio_track_not_found
- audio_selection_failed
- audio_ducking_failed
- audio_loudness_out_of_range
- audio_mix_failed
- audio_metadata_validation_failed

Rejection reason kodları (mix çıktısı geçersiz ama pipeline devam):
- invalid_loudness_measurement
- invalid_true_peak_measurement
- invalid_music_track_id
- invalid_ducking_parameters

## 9. Smoke Test Kriterleri
Tek video, upload olmadan doğrulama:
1. Audio mix adımı tamamlanır.
2. audio_mix_metadata alanı result içinde oluşur.
3. ducking_applied alanı boolean döner.
4. loudness_target_lufs alanı mevcut olur.
5. Warning oluşursa standart warning kodlarıyla yazılır.

## 10. Acceptance Criteria
- Bu sözleşme dosyası Phase 2 dokümanından referanslanmış olmalı.
- A2 validator implementation bu şemaları doğrulamalı.
- A3 fail-open standardizasyonu warning kodlarını bu listedeki değerlerle üretmeli.
- A4 smoke testte upload olmadan metadata alanları doğrulanmalı.
