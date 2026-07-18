#!/bin/bash
# Watchdog: parapusulasi servisi durmussa Telegram'a bildir + yeniden basla
BOT_TOKEN=$(grep TELEGRAM_BOT_TOKEN /opt/parapusulasi/.env | cut -d= -f2 | tr -d '"')
CHAT_ID=$(grep TELEGRAM_CHAT_ID /opt/parapusulasi/.env | cut -d= -f2 | tr -d '"')

notify() {
    curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
        -d "chat_id=${CHAT_ID}" \
        -d "text=$1" > /dev/null 2>&1
}

if ! systemctl is-active --quiet parapusulasi; then
    notify "ALARM: Para Pusulasi scheduler coktu! Yeniden baslatiliyor..."
    systemctl start parapusulasi
    sleep 5
    if systemctl is-active --quiet parapusulasi; then
        notify "OK: Scheduler yeniden baslatildi"
    else
        notify "KRITIK: Scheduler baslatilAmadi! Manuel mudahale gerekiyor."
    fi
fi
