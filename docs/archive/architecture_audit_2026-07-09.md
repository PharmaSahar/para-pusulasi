# Architecture Audit Report (Line-Level)

Date: 2026-07-09
Scope: Production-core files requested by priority order.

## 1) [src/pipeline.py](src/pipeline.py)

### Finding P1
- Dosya ve satır aralığı: [src/pipeline.py](src/pipeline.py#L162-L789)
- Risk tipi: duplicate logic
- Etki seviyesi: high
- Neden sorun: `run_full_pipeline` tek fonksiyonda içerik üretimi, fact-check, render, short render, upload, telemetry ve snapshot yönetimini topluyor. Hata izolasyonu zorlaşıyor, küçük bir değişiklik tüm akışı etkileyebiliyor.
- Önerilen düzeltme: Stage bazlı executor yapısı (`content_stage`, `fact_check_stage`, `render_stage`, `upload_stage`) ve typed result contract.
- Aksiyon: backlog’a kalmalı (planlı refactor), ancak sprint kapsamına alınmalı.

### Finding P2
- Dosya ve satır aralığı: [src/pipeline.py](src/pipeline.py#L202-L222)
- Risk tipi: observability gap
- Etki seviyesi: medium
- Neden sorun: `_emit` içinde tüm telemetry hataları yutuluyor (`except Exception: pass`), telemetry tamamen sustuğunda operasyon ekibi bunu geç fark edebilir.
- Önerilen düzeltme: Fail-open kalsın ama `logger.warning` ve düşük hacimli sayaç/health sinyali eklensin.
- Aksiyon: hemen yapılmalı.
- Durum: Resolved (2026-07-09)
- Kanıt: [src/pipeline.py](src/pipeline.py#L275) içinde `telemetry_warning` fail-open görünürlüğü eklendi.

### Finding P3
- Dosya ve satır aralığı: [src/pipeline.py](src/pipeline.py#L525-L542)
- Risk tipi: cost leak
- Etki seviyesi: medium
- Neden sorun: Render aşamasında `has_dalle()` aktifse otomatik DALL-E üretimi devreye giriyor; run başına maliyet kontrolü veya budget guard yok.
- Önerilen düzeltme: Channel bazlı günlük/haftalık görsel bütçe limiti ve budget-exhaust fallback (Pexels/local) eklenmeli.
- Aksiyon: hemen yapılmalı.

### Finding P4
- Dosya ve satır aralığı: [src/pipeline.py](src/pipeline.py#L580-L607)
- Risk tipi: observability gap
- Etki seviyesi: medium
- Neden sorun: Shorts render 2 deneme sonunda başarısız olunca sadece log/telemetry düşülüyor; `result` içinde standart bir `short_error_code` yok.
- Önerilen düzeltme: `result["short_render_error"] = {code, message, attempt_count}` standardize edilmeli.
- Aksiyon: hemen yapılmalı.

### Finding P5
- Dosya ve satır aralığı: [src/pipeline.py](src/pipeline.py#L636-L707)
- Risk tipi: quality issue
- Etki seviyesi: medium
- Neden sorun: Short upload için başlık/thumbnail varyasyonu ad hoc; başarılı short yüklemelerde `short_video_id` set edilmiyor ama snapshot bu alanı bekliyor.
- Önerilen düzeltme: `short_video_id` explicit set edilmeli ve short upload sonucu tek bir canonical result contract ile yazılmalı.
- Aksiyon: hemen yapılmalı.

### Finding P6
- Dosya ve satır aralığı: [src/pipeline.py](src/pipeline.py#L783-L789)
- Risk tipi: observability gap
- Etki seviyesi: medium
- Neden sorun: `append_performance_snapshot` başarısızlığında hata yutulup boş snapshot yazılıyor; izleme zincirinde kör nokta yaratıyor.
- Önerilen düzeltme: Snapshot write failure için ayrı hata alanı (`performance_snapshot_error`) ve alarm sinyali eklenmeli.
- Aksiyon: hemen yapılmalı.
- Durum: Mitigated (2026-07-09)
- Kanıt: [src/pipeline.py](src/pipeline.py#L173) ile pre-append validation guard eklendi; invalid row append edilmeden `analytics_warning` ve `performance_snapshot_append_skipped` set ediliyor ([src/pipeline.py](src/pipeline.py#L899), [src/pipeline.py](src/pipeline.py#L910)).

## 2) [scheduler.py](scheduler.py)

### Finding S1
- Dosya ve satır aralığı: [scheduler.py](scheduler.py#L213-L216)
- Risk tipi: production failure
- Etki seviyesi: high
- Neden sorun: `render_locks` sözlüğü lock koruması olmadan mutasyona uğruyor; paralel thread’lerde yarış durumu mümkün.
- Önerilen düzeltme: `render_locks` erişimi için ayrı mutex veya `collections.defaultdict` + global lock kullanılmalı.
- Aksiyon: hemen yapılmalı.
- Durum: Resolved (2026-07-09)
- Kanıt: [scheduler.py](scheduler.py#L58) `RENDER_LOCKS_LOCK` ve [scheduler.py](scheduler.py#L148) `_get_channel_render_lock` ile lock map erişimi güvenli hale getirildi.

### Finding S2
- Dosya ve satır aralığı: [scheduler.py](scheduler.py#L242-L263)
- Risk tipi: production failure
- Etki seviyesi: medium
- Neden sorun: Retry/backoff sırasında worker thread bloklanıyor (`time.sleep`), düşük worker sayısında kuyruk gecikmesini büyütüyor.
- Önerilen düzeltme: Retry işi scheduler kuyruğuna yeniden enqueue edilmeli; thread içinde uzun sleep azaltılmalı.
- Aksiyon: backlog’a kalmalı.

### Finding S3
- Dosya ve satır aralığı: [scheduler.py](scheduler.py#L66-L141)
- Risk tipi: duplicate logic
- Etki seviyesi: medium
- Neden sorun: `load_queue`, `save_queue`, `update_queue` içinde `mode` çözümleme ve shadow mirror tekrarları var; bakım maliyeti ve tutarsızlık riski artıyor.
- Önerilen düzeltme: Tek `QueueStore` abstraction altında JSON/shadow davranışı merkezileştirilmeli.
- Aksiyon: backlog’a kalmalı.

### Finding S4
- Dosya ve satır aralığı: [scheduler.py](scheduler.py#L390-L411)
- Risk tipi: quality issue
- Etki seviyesi: medium
- Neden sorun: `setup_schedule` tüm günler için job kuruyor; kanalın `upload_days` kısıtı dikkate alınmıyor.
- Önerilen düzeltme: `cfg.upload_days` parse edilip yalnız ilgili günlere schedule yazılmalı.
- Aksiyon: hemen yapılmalı.

### Finding S5
- Dosya ve satır aralığı: [scheduler.py](scheduler.py#L617-L649)
- Risk tipi: duplicate logic
- Etki seviyesi: medium
- Neden sorun: `fill_empty_queues_job` içindeki `get_next_upload_time` çağrısı `occupied` üzerinde hesap yapmasına rağmen `new_time` değeri queue’ya persist edilmiyor; aynı slota tekrar render tetikleme riski var.
- Önerilen düzeltme: Slot reservation atomik olarak queue’ya önce yazılmalı, sonra render submit edilmeli.
- Aksiyon: hemen yapılmalı.

### Finding S6
- Dosya ve satır aralığı: [scheduler.py](scheduler.py#L798-L800)
- Risk tipi: observability gap
- Etki seviyesi: low
- Neden sorun: Main loop yalnız `schedule.run_pending()` + sleep; event-loop health/lag metriği yok.
- Önerilen düzeltme: Loop heartbeat ve pending-job lag metriği eklenmeli.
- Aksiyon: backlog’a kalmalı.

## 3) [src/youtube_uploader.py](src/youtube_uploader.py)

### Finding Y1
- Dosya ve satır aralığı: [src/youtube_uploader.py](src/youtube_uploader.py#L105-L106)
- Risk tipi: observability gap
- Etki seviyesi: medium
- Neden sorun: Yorum ekleme hatası üst seviyede tamamen yutuluyor (`except Exception: pass`), sürekli başarısızlıklar görünmez kalıyor.
- Önerilen düzeltme: En azından kanal/video kimliğiyle warning log ve metrik eklenmeli.
- Aksiyon: hemen yapılmalı.

### Finding Y2
- Dosya ve satır aralığı: [src/youtube_uploader.py](src/youtube_uploader.py#L76)
- Risk tipi: quality issue
- Etki seviyesi: medium
- Neden sorun: `defaultLanguage` global `config.channel_language` kullanıyor; `channel_cfg` farklı dildeyse metadata yanlış yazılabilir.
- Önerilen düzeltme: `channel_cfg` öncelikli dil çözümlemesi kullanılmalı.
- Aksiyon: hemen yapılmalı.
- Durum: Resolved (2026-07-09)
- Kanıt: [src/youtube_uploader.py](src/youtube_uploader.py#L35) `_resolve_default_language` ile channel-first language resolution uygulandı.

### Finding Y3
- Dosya ve satır aralığı: [src/youtube_uploader.py](src/youtube_uploader.py#L111-L146)
- Risk tipi: cost leak
- Etki seviyesi: medium
- Neden sorun: Her upload sonrası yorum denemesi quota tüketimini artırıyor; kanal bazlı quota budget/policy guard yok.
- Önerilen düzeltme: Günlük quota bütçe eşiği altına düşünce yorum/opsiyonel API çağrıları otomatik kapatılmalı.
- Aksiyon: backlog’a kalmalı.

### Finding Y4
- Dosya ve satır aralığı: [src/youtube_uploader.py](src/youtube_uploader.py#L164-L199)
- Risk tipi: missing fallback
- Etki seviyesi: medium
- Neden sorun: Resumable upload retry sadece belirli istisnaları ele alıyor; response bozulması/timeout varyantlarında request yeniden oluşturma fallback’i yok.
- Önerilen düzeltme: Retry limit sonrası yeni upload session ile bir kez yeniden başlatma adımı eklenmeli.
- Aksiyon: backlog’a kalmalı.
- Durum: Mitigated (2026-07-09)
- Kanıt: [src/youtube_uploader.py](src/youtube_uploader.py#L51) `_classify_http_error` ve [src/youtube_uploader.py](src/youtube_uploader.py#L218) `_resumable_upload` ile retryability daha güvenli sınıflandırıldı.

## 4) [src/tts_engine.py](src/tts_engine.py)

### Finding T1
- Dosya ve satır aralığı: [src/tts_engine.py](src/tts_engine.py#L73-L76)
- Risk tipi: duplicate logic
- Etki seviyesi: low
- Neden sorun: `elif self.use_azure` bloğu iki kez yazılmış; ikinci koşul unreachable.
- Önerilen düzeltme: Tek koşul bırakılmalı, log mesajı sadeleştirilmeli.
- Aksiyon: hemen yapılmalı.

### Finding T2
- Dosya ve satır aralığı: [src/tts_engine.py](src/tts_engine.py#L96-L99)
- Risk tipi: missing fallback
- Etki seviyesi: high
- Neden sorun: ElevenLabs yolunda hata olursa Edge fallback yok; Azure’da fallback varken ElevenLabs’ta yok.
- Önerilen düzeltme: `self._generate_elevenlabs` çağrısı try/except ile sarılıp hata halinde Edge TTS’e düşülmeli.
- Aksiyon: hemen yapılmalı.
- Durum: Resolved (2026-07-09)
- Kanıt: [src/tts_engine.py](src/tts_engine.py#L92) fallback zinciri Azure → ElevenLabs → Edge olarak zorunlu hale getirildi; structured fallback warning ve görünür chain metadata eklendi.

### Finding T3
- Dosya ve satır aralığı: [src/tts_engine.py](src/tts_engine.py#L208-L216)
- Risk tipi: quality issue
- Etki seviyesi: medium
- Neden sorun: `_save_estimated_timing` içinde `AudioFileClip` context yönetimi yok; uzun çalışmada file handle birikimi olabilir.
- Önerilen düzeltme: `with AudioFileClip(...) as clip:` kullanımı ile deterministik close.
- Aksiyon: backlog’a kalmalı.

### Finding T4
- Dosya ve satır aralığı: [src/tts_engine.py](src/tts_engine.py#L228-L246)
- Risk tipi: production failure
- Etki seviyesi: medium
- Neden sorun: Edge TTS async akışında herhangi bir network kesintisi tüm stage’i fail ediyor; retry/backoff yok.
- Önerilen düzeltme: 2-3 denemelik bounded retry ve hata kodu sınıflandırması eklenmeli.
- Aksiyon: backlog’a kalmalı.

## 5) [src/image_fetcher.py](src/image_fetcher.py)

### Finding I1
- Dosya ve satır aralığı: [src/image_fetcher.py](src/image_fetcher.py#L163-L179)
- Risk tipi: quality issue
- Etki seviyesi: medium
- Neden sorun: `hash(title)` ile seçim Python process’lerinde deterministik değil (hash randomization), “tutarlı seçim” varsayımı bozuluyor.
- Önerilen düzeltme: `hashlib.sha256(title.encode()).hexdigest()` tabanlı stabil index kullanılmalı.
- Aksiyon: hemen yapılmalı.

### Finding I2
- Dosya ve satır aralığı: [src/image_fetcher.py](src/image_fetcher.py#L112-L113)
- Risk tipi: observability gap
- Etki seviyesi: medium
- Neden sorun: Video fetch failure tek satır warning sonrası foto fallback’e geçiyor; hata tipi (quota/network/auth) sınıflandırılmıyor.
- Önerilen düzeltme: structured reason code (`media_fetch_error_code`) ve telemetry alanı eklenmeli.
- Aksiyon: hemen yapılmalı.

### Finding I3
- Dosya ve satır aralığı: [src/image_fetcher.py](src/image_fetcher.py#L195-L200)
- Risk tipi: missing fallback
- Etki seviyesi: medium
- Neden sorun: `_download_file` tek deneme yapıyor; transient ağ hatalarında kolayca boş medya setine düşülüyor.
- Önerilen düzeltme: kısa retry/backoff ve kısmi dosya temizliği eklenmeli.
- Aksiyon: backlog’a kalmalı.

## 6) [src/premium_services.py](src/premium_services.py)

### Finding PR1
- Dosya ve satır aralığı: [src/premium_services.py](src/premium_services.py#L16-L33)
- Risk tipi: duplicate logic
- Etki seviyesi: low
- Neden sorun: `_get_env` her çağrıda `.env` parse ediyor; tüm premium fonksiyonlarda tekrar eden I/O maliyeti var.
- Önerilen düzeltme: düşük TTL’li in-memory cache veya startup config snapshot kullanılmalı.
- Aksiyon: backlog’a kalmalı.

### Finding PR2
- Dosya ve satır aralığı: [src/premium_services.py](src/premium_services.py#L285-L313)
- Risk tipi: production failure
- Etki seviyesi: high
- Neden sorun: HeyGen polling sync/blocking (`40 * 15s`) çalışıyor; worker/thread uzun süre kilitleniyor.
- Önerilen düzeltme: Async job queue + webhook/polling worker modeline ayrıştırılmalı.
- Aksiyon: backlog’a taşındı (high priority).
- Durum: Mitigated-by-policy (2026-07-09)
- Backlog kaydı: HeyGen yalnızca async/background job olarak çalıştırılmalı; production pipeline içindeki default synchronous path'te çalıştırılmamalı.

### Finding PR3
- Dosya ve satır aralığı: [src/premium_services.py](src/premium_services.py#L132-L155)
- Risk tipi: quality issue
- Etki seviyesi: medium
- Neden sorun: Storyblocks cevabında video yerine image preview indirilip clip listesine eklenebiliyor; downstream render beklentisi bozulabilir.
- Önerilen düzeltme: Sadece video MIME (`video/*`) kabul edilmeli, diğerleri elenmeli.
- Aksiyon: hemen yapılmalı.

### Finding PR4
- Dosya ve satır aralığı: [src/premium_services.py](src/premium_services.py#L322-L324)
- Risk tipi: cost leak
- Etki seviyesi: medium
- Neden sorun: `has_dalle` sadece key + flag kontrol ediyor; günlük kanal bütçe limiti yok.
- Önerilen düzeltme: Budget guard ve channel-level premium quota policy eklenmeli.
- Aksiyon: hemen yapılmalı.

## 7) [src/config.py](src/config.py)

### Finding C1
- Dosya ve satır aralığı: [src/config.py](src/config.py#L52-L60)
- Risk tipi: missing fallback
- Etki seviyesi: medium
- Neden sorun: `validate` yalnız 3 anahtarı kontrol ediyor; diğer kritik bağımlılıklar (ör. medya/tts/telemetry path ve premium toggles) startup’ta doğrulanmıyor.
- Önerilen düzeltme: Production profile bazlı genişletilmiş validation matrisi eklenmeli.
- Aksiyon: hemen yapılmalı.

### Finding C2
- Dosya ve satır aralığı: [src/config.py](src/config.py#L74-L80)
- Risk tipi: production failure
- Etki seviyesi: medium
- Neden sorun: `video_resolution` parse işlemi invalid formatta (`1920*1080` vb.) runtime exception üretir; güvenli fallback yok.
- Önerilen düzeltme: Regex doğrulaması ve parse failure’da default çözünürlüğe geri dönüş eklenmeli.
- Aksiyon: hemen yapılmalı.

### Finding C3
- Dosya ve satır aralığı: [src/config.py](src/config.py#L35-L38)
- Risk tipi: quality issue
- Etki seviyesi: low
- Neden sorun: Müzik policy env parse sadece `"true"` eşitliği ile bool dönüştürüyor; `1/yes/on` gibi yaygın değerler false kalabilir.
- Önerilen düzeltme: Ortak `parse_bool` helper ile normalize bool parsing kullanılmalı.
- Aksiyon: backlog’a kalmalı.

## Top Priority Action List
1. ✅ Resolved (2026-07-09): [scheduler.py](scheduler.py#L58) lock yarış riskini kapat.
2. ✅ Resolved (2026-07-09): [src/youtube_uploader.py](src/youtube_uploader.py#L35) upload retry/error classification hardening + channel language fix.
3. ✅ Resolved (2026-07-09): [src/pipeline.py](src/pipeline.py#L275) telemetry fail-open için görünür warning/metric ekle.
4. ✅ Mitigated (2026-07-09): [src/pipeline.py](src/pipeline.py#L173) analytics snapshot validation guard ekle.
5. ✅ Resolved (2026-07-09): [src/tts_engine.py](src/tts_engine.py#L92) ElevenLabs fallback hardening.
6. 🧭 Backlog (High, 2026-07-09): [src/premium_services.py](src/premium_services.py#L285-L313) HeyGen async/background job'a ayrıştırılmalı; production default sync path'te çalışmamalı.

## Documentation Closure Criteria
- Critical bulgular ya kodla çözülmüş ya da backlog kaydına açık şekilde bağlanmış olmalı.
- İlgili mimari karar varsa ilgili ADR kaydına bağlanmış olmalı.
- Release etkisi olan her bulgu, Production Readiness Checklist içinde doğrulanabilir bir maddeye çevrilmiş olmalı.
- Yeni teknik borçlar roadmap veya backlog üzerinde takip edilebilir kayıtla yer almalı.
