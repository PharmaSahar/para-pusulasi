# Queue Publish Catch-up Postmortem (2026-07-10)

## Ozet

Scheduler restart sonrasinda gecmiste kalmis `publish_at` kayitlari JSON kuyrugunda kaldi.
Bu kayitlar `initial_fill()` tarafinda "kuyrukta video mevcut" olarak algilandigi icin:

- yayin bildirimi callback'i kacmis oldu
- yeni render zinciri otomatik baslamadi
- aktif iki kanal (`para_pusulasi`, `kariyer_pusulasi`) gecikmis entry ile bloklandi

## Belirti

- `output/queue/channel_queue.json` icinde gecmis saatli entry'ler kaldi
- `logs/scheduler.log` icinde ilgili saatlerde `Upload zamanı` satiri yoktu
- startup sonrasinda sadece `Kuyrukta video mevcut, render atlandı.` goruldu

## Kök Neden

Scheduler boot akisi su siradaydi:

1. `setup_schedule()`
2. `initial_fill()`

Fakat boot sirasinda gecikmis queue entry'lerini tuketen bir adim yoktu.
Dolayisiyla gecmis kayitlar temizlenmeden `initial_fill()` calisti.

## Duzeltme

`scheduler.py` icine `catch_up_overdue_queue_entries()` eklendi.
Bu adim startup'ta:

- `publish_at <= now` olan queue kayitlarini atomik olarak cikariyor
- yayin bildirimi gonderiyor
- kanal basina tek yeni render zinciri baslatiyor

## Dogrulama

- Temp queue senaryosunda overdue entry silindi, future entry kaldi
- render submit kanali beklendigi gibi tetiklendi
- mevcut canli kuyrukta gecikmis `para_pusulasi` ve `kariyer_pusulasi` entry'leri manuel catch-up ile dustu

## Sonraki Izleme

- Scheduler restart sonrasinda gecmis queue entry tekrar birikiyor mu izlenmeli
- `logs/scheduler.log` icinde startup catch-up satirlari kontrol edilmeli
- Gerekirse bu helper icin kalici test eklenmeli
