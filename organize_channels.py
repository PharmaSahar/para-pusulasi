"""Kanal klasörlerini düzenle."""
import json, shutil
from pathlib import Path

reg = json.loads(Path('channels/channel_registry.json').read_text())

# Girişim Okulu geri al
if Path('channels/_pending/girisim_okulu').exists():
    shutil.move('channels/_pending/girisim_okulu', 'channels/girisim_okulu')
    print('Girisim Okulu geri alindi')

# Token olan kanalları aktif yap
ACTIVE = ['para_pusulasi','borsa_akademi','kripto_rehber',
          'kariyer_pusulasi','girisim_okulu','saglik_pusulasi',
          'teknoloji_pusulasi']

for cid in ACTIVE:
    token = Path(f'channels/{cid}/youtube_token.pickle')
    if token.exists():
        reg['channels'][cid]['status'] = 'active'

Path('channels/channel_registry.json').write_text(
    json.dumps(reg, indent=2, ensure_ascii=False))

print('\nchannels/ klasoru:')
for d in sorted(Path('channels').iterdir()):
    if d.is_dir() and not d.name.startswith('_'):
        token = 'token OK' if (d/'youtube_token.pickle').exists() else 'token YOK'
        print(f'  {d.name}/  ({token})')
