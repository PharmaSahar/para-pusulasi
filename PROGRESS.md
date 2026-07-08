# PROGRESS — Para Pusulası YouTube Otomasyon

> Bu dosya scheduler tarafından otomatik güncellenir. Elle de güncellenebilir.

---

## Son Güncelleme
**Tarih:** 2026-07-08  
**Claude Session:** 78929f53-2a82-4dab-9555-043051939a38  

## Son Tamamlanan Görev
- Tek-kök cutover tamamlandı: canlı scheduler artık canonical root olan `/Users/klara/Downloads/adsız klasör` içinden çalışıyor
- Aktif çalışma dalı `feature/regeneration-on-planning` olarak sabitlendi
- Fact Bundle pipeline adapter canlı canonical root üzerinde `enabled` olarak doğrulandı
- `unverifiable_volatile_claim` için tek-seferlik regeneration canlıda doğrulandı
- Regeneration retry akışı sertleştirildi: spekülatif fiyat hedeflerine geri dönen tekrar üretim yerine risk yönetimi odaklı güvenli konu + strict prompt guidance eklendi
- `tests/test_factual_freshness.py` hedefli regresyon paketi geçti (`12 passed`)
- Tek-kök cutover scripti kalıcı olarak repo içine taşındı: `deploy/single_root_cutover.sh`
- Kalıcı operasyon notu eklendi: `docs/single_root_operations.md`

## Yarım Kalan Görev
- Canonical root üzerinden en az bir tam upload / shorts_upload döngüsü daha izlenmeli
- Yardımcı worktree'ler (`para-pusulasi-production`, `para-pusulasi-merge-regeneration`) hemen silinmeyecek; son manuel onay sonrası kaldırılacak
- YouTube API quota artışı onayı bekleniyor
- Bazı kanallarda YouTube custom thumbnail/comment yetkisi yok (403)
- OpenAI image erişimi doğrulanmadığı için DALL-E kapalı tutuluyor

## Bir Sonraki Adım
- Canonical root logu üzerinden upload / shorts_upload sinyallerini izlemeye devam et
- Yardımcı worktree kaldırma kararı öncesi `docs/single_root_operations.md` checklist'ini kullan
- Kripto ve volatil piyasa başlıklarında yeni retry sertleştirmesinin hata oranını gözlemle

## Aktif Kanallar (9/9)
| Kanal | Durum | Bugün Yayın |
|---|---|---|
| Para Pusulası | ✅ | 20:00 |
| Borsa Akademi | ✅ | 20:30 |
| Kripto Rehber | ✅ | 21:00 |
| Kariyer Pusulası | ✅ | 21:30 |
| Girişim Okulu | ✅ | 22:00 |
| Sağlık Pusulası | ✅ Render aktif | — |
| Teknoloji Pusulası | ✅ Render aktif | — |
| Eğitim Rehberi | ✅ Render aktif | — |
| Gayrimenkul TV | ✅ | 12:00 |

## Notlar (Operasyonel)
- Canonical canlı log artık `logs/production_scheduler.out` altında takip edilmeli.
- PID dosyaları yalnız kayıt amaçlıdır; süreç doğruluğu için `pgrep` + `lsof -a -d cwd -p <pid>` kullanılmalı.
- Eski production worktree yeni log üretmiyor; ancak güvenlik nedeniyle hemen silinmeyecek.
- DALL-E yeniden açılacaksa önce hesap/model erişimi doğrulanmalı, sonra OPENAI_IMAGE_ENABLED=true yapılmalı.
