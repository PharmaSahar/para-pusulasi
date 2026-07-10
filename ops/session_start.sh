#!/bin/bash
# Para Pusulası — Oturum Başlangıç Kontrol Komutu
# Kullanım: bash ops/session_start.sh

set -euo pipefail
cd "$(dirname "$0")/.."

VENV=".venv-2/bin/python"
VPS="root@168.119.126.103"
SSH="ssh -i ~/.ssh/hetzner_vps -o StrictHostKeyChecking=no"

echo "════════════════════════════════════════════════════"
echo "  Para Pusulası — Oturum Başlangıç Raporu"
echo "  $(date '+%Y-%m-%d %H:%M')"
echo "════════════════════════════════════════════════════"

echo ""
echo "── 1. GIT DURUMU ──────────────────────────────────"
git log --oneline -3
echo ""
DIRTY=$(git status --short | grep -v "^??" | wc -l | tr -d ' ')
UNTRACKED=$(git status --short | grep "^??" | wc -l | tr -d ' ')
echo "Değiştirilmiş: $DIRTY  |  Untracked: $UNTRACKED"

echo ""
echo "── 2. TESTLER ─────────────────────────────────────"
$VENV -m pytest tests/ -q --tb=no 2>&1 | tail -3

echo ""
echo "── 3. VPS DURUM ───────────────────────────────────"
$SSH $VPS "
  echo 'Servis: '$(systemctl is-active parapusulasi)
  echo 'RAM: '$(free -h | awk '/Mem:/{print \$3\" / \"\$2}')
  echo 'Disk: '$(df -h / | awk 'NR==2{print \$3\" / \"\$2\" (\" \$5\")\"}')
  echo 'Son video: '$(grep 'TAMAMLANDI.*youtube' /opt/parapusulasi/logs/vps_scheduler.log 2>/dev/null | tail -1 | awk '{print \$1,\$2}')
  echo 'Hata (son): '$(grep '\[ERROR\]' /opt/parapusulasi/logs/vps_scheduler.log 2>/dev/null | tail -1 | grep -v telemetry | cut -c1-80 || echo 'yok')
" 2>/dev/null

echo ""
echo "── 4. BUGÜN YÜKLEMELERİ ──────────────────────────"
TODAY=$(date '+%Y-%m-%d')
$SSH $VPS "grep '$TODAY.*TAMAMLANDI.*youtube' /opt/parapusulasi/logs/vps_scheduler.log 2>/dev/null | wc -l | tr -d ' '" 2>/dev/null
echo "video bugün"
$SSH $VPS "grep '$TODAY.*Short yuklendi' /opt/parapusulasi/logs/vps_scheduler.log 2>/dev/null | wc -l | tr -d ' '" 2>/dev/null
echo "short bugün"

echo ""
echo "── 5. KUYRUK DURUMU ───────────────────────────────"
$SSH $VPS "
cd /opt/parapusulasi && source venv/bin/activate && python3 -c \"
import json, sys
sys.path.insert(0,'.')
from pathlib import Path
q = json.loads(Path('output/queue/channel_queue.json').read_text()) if Path('output/queue/channel_queue.json').exists() else {}
for c in ['para_pusulasi','borsa_akademi','kripto_rehber','kariyer_pusulasi','girisim_okulu','saglik_pusulasi','teknoloji_pusulasi','egitim_rehberi','gayrimenkul_tv']:
    n = len(q.get(c,[]))
    print(f'  {c:25} {\\\"✅\\\" if n>0 else \\\"❌ BOŞ\\\"}')
\" 2>/dev/null
" 2>/dev/null

echo ""
echo "════════════════════════════════════════════════════"
echo "  Hazır. Ne yapmak istiyorsun?"
echo "════════════════════════════════════════════════════"
