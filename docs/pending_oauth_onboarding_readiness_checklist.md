# Pending OAuth Onboarding Readiness Checklist

Bu kontrol listesi `pending_oauth` durumundaki kanallari metadata repair, upload ve analytics akislarina hazir hale getirmek icindir.

## Amac

Bir kanal `metadata_repair` icin ancak su artefaktlar olustugunda calisabilir:

- `channels/<channel_id>/`
- `channels/<channel_id>/.env`
- `channels/<channel_id>/client_secrets.json`
- `channels/<channel_id>/youtube_token.pickle`

## Sirali Akis

1. Kanal klasoru olusmus olmali.
2. Kanal `.env` dosyasi olusmus olmali.
3. `client_secrets.json` kanal klasorunde bulunmali.
4. Google hesabinin YouTube kanali olusturulmus olmali.
5. Google Cloud test user / OAuth izinleri tamamlanmis olmali.
6. `python setup_channel.py <channel_id>` ile OAuth token alinmis olmali.
7. `youtube_token.pickle` olustuktan sonra dry-run metadata repair kosulabilmeli.
8. Dry-run temizse apply-limit ile kademeli guncelleme yapilmali.

## Operasyon Komutlari

Hazirlik iskeleti olustur:

```bash
PYTHONPATH=. .venv-2/bin/python ops/scaffold_pending_oauth_channels.py
```

Toplu `client_secrets` doldurma sablonlari:

```text
ops/client_secrets_bulk_map_template.json
ops/client_secrets_bulk_map_template.csv
```

Blokaj raporu uret:

```bash
PYTHONPATH=. .venv-2/bin/python ops/pending_oauth_metadata_repair_report.py
```

OAuth token geldikce otomatik repair tetikle:

```bash
PYTHONPATH=. .venv-2/bin/python ops/run_metadata_repair_when_oauth_ready.py --once
```

Token olusan kanallari registry/tracker ile senkronize et:

```bash
PYTHONPATH=. .venv-2/bin/python ops/sync_oauth_ready_channels.py --apply
```

Sürekli izle:

```bash
PYTHONPATH=. .venv-2/bin/python ops/run_metadata_repair_when_oauth_ready.py --watch --interval-seconds 900
```

## Hazirlik Kriteri

Bir kanal `repair_ready` sayilmasi icin en az su iki dosya zorunludur:

- `channels/<channel_id>/youtube_token.pickle`
- `channels/<channel_id>/client_secrets.json`

Pratikte `.env` de beklenir; scaffold araci bunu placeholder olarak olusturur.

## Apply Politikasi

- Ilk gecis: `--only-problematic --max-videos 20`
- Ilk mutasyon: `--apply --apply-limit 1`
- Her apply sonrasi verify dry-run zorunlu
- Quota hatasi varsa watch mode ile tekrar dene

## Not

`pending_oauth` kanallarda token yokken repair kosmaya calismak anlamsizdir; once onboarding artefaktlari tamamlanmalidir.
