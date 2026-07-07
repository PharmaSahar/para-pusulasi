"""Gayrimenkul TV hızlı bağla."""
import json, requests, re
from pathlib import Path
from src.channel_manager import get_channel
from src.youtube_auth import get_authenticated_service

# Channel ID bul
for url in ['https://www.youtube.com/@GayrimenkulTV-u8z', 
            'https://www.youtube.com/channel/UCGayrimenkulTV']:
    try:
        r = requests.get(url, headers={'User-Agent':'Mozilla/5.0'}, timeout=10)
        m = re.search(r'"channelId":"(UC[a-zA-Z0-9_-]+)"', r.text)
        if m:
            ch_id = m.group(1)
            print(f'ID bulundu: {ch_id}')
            break
    except Exception:
        continue
else:
    # Manuel gir
    ch_id = input('Channel ID manuel gir (UCxxxxx): ').strip()

# Registry güncelle
reg = json.loads(Path('channels/channel_registry.json').read_text())
reg['channels']['gayrimenkul_tv']['youtube_channel_id'] = ch_id
reg['channels']['gayrimenkul_tv']['status'] = 'active'
Path('channels/channel_registry.json').write_text(json.dumps(reg, indent=2, ensure_ascii=False))

# Klasörü geri al
pending = Path('channels/_pending/gayrimenkul_tv')
target = Path('channels/gayrimenkul_tv')
if pending.exists() and not target.exists():
    import shutil
    shutil.move(str(pending), str(target))

# OAuth
cfg = get_channel('gayrimenkul_tv')
svc = get_authenticated_service(cfg)
if Path(cfg.token_path).exists():
    print('Token OK - Gayrimenkul TV baglandı!')
else:
    print('Token YOK')
