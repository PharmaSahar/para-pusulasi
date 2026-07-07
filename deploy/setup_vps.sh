#!/bin/bash
# Para Pusulası - Hetzner VPS Kurulum Scripti
# Ubuntu 22.04 LTS üzerinde çalışır
# Kullanım: curl -sL [URL] | bash

set -e
echo "==================================="
echo " Para Pusulası VPS Kurulum"
echo "==================================="

# Sistem güncellemesi
apt-get update -q && apt-get upgrade -y -q

# Gerekli paketler
apt-get install -y -q \
    python3.11 python3.11-venv python3-pip \
    ffmpeg \
    git \
    wget curl \
    screen tmux \
    nginx \
    certbot

# Proje klasörü
mkdir -p /opt/parapusulasi
cd /opt/parapusulasi

# Python sanal ortam
python3.11 -m venv venv
source venv/bin/activate

echo "✅ Sistem hazır"
echo ""
echo "Sonraki adım: Projeyi transfer edin"
echo "  rsync -avz /Users/klara/Downloads/adsız\\ klasör/ root@SUNUCU_IP:/opt/parapusulasi/"
