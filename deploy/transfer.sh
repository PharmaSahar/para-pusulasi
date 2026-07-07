#!/bin/bash
# Para Pusulası - Projeyi Mac'ten VPS'e Transfer ve Başlatma
# Kullanım: bash deploy/transfer.sh SUNUCU_IP

SERVER_IP=${1:-"SUNUCU_IP"}
PROJECT_DIR="/Users/klara/Downloads/adsız klasör"
REMOTE_DIR="/opt/parapusulasi"

echo "==================================="
echo " Para Pusulası - Sunucu Transferi"
echo " Hedef: root@$SERVER_IP"
echo "==================================="

# Projeyi rsync ile gönder (büyük dosyaları hariç tut)
echo "Proje transfer ediliyor..."
rsync -avz --progress \
    --exclude="venv/" \
    --exclude="output/" \
    --exclude="*.pyc" \
    --exclude="__pycache__/" \
    --exclude=".env" \
    "$PROJECT_DIR/" \
    "root@$SERVER_IP:$REMOTE_DIR/"

# .env dosyasını güvenli transfer
echo ".env transfer ediliyor..."
scp "$PROJECT_DIR/.env" "root@$SERVER_IP:$REMOTE_DIR/.env"

# YouTube token'larını transfer et
echo "Token'lar transfer ediliyor..."
rsync -avz \
    "$PROJECT_DIR/channels/" \
    "root@$SERVER_IP:$REMOTE_DIR/channels/"

# VPS'de bağımlılıkları yükle ve başlat
echo "VPS'de kurulum yapılıyor..."
ssh "root@$SERVER_IP" << 'EOF'
cd /opt/parapusulasi
python3.11 -m venv venv
source venv/bin/activate
pip install -q -r requirements.txt

# Systemd servis olarak kur (her yeniden başlatmada otomatik çalışır)
cat > /etc/systemd/system/parapusulasi.service << 'SVCEOF'
[Unit]
Description=Para Pusulasi YouTube Otomasyonu
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/parapusulasi
ExecStart=/opt/parapusulasi/venv/bin/python /opt/parapusulasi/scheduler.py
Restart=always
RestartSec=30
StandardOutput=append:/opt/parapusulasi/logs/vps_scheduler.log
StandardError=append:/opt/parapusulasi/logs/vps_error.log

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable parapusulasi
systemctl start parapusulasi
systemctl status parapusulasi
EOF

echo ""
echo "==================================="
echo "✅ VPS'de çalışıyor!"
echo ""
echo "Durum: ssh root@$SERVER_IP 'systemctl status parapusulasi'"
echo "Log:   ssh root@$SERVER_IP 'tail -f /opt/parapusulasi/logs/vps_scheduler.log'"
echo "==================================="
