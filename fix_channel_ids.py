"""Registry'deki tüm channel ID'leri doğru değerlerle güncelle."""
import json
from pathlib import Path

reg = json.loads(Path('channels/channel_registry.json').read_text())

MAPPING = {
    'para_pusulasi': 'UC6tU7UqYylfSA75pj3rEY_Q',
    'borsa_akademi': 'UCwQERXHCUOngXXTnJ9goBSQ',
    'kripto_rehber': 'UCyFK7LdIPM01fAf3f0W2x9Q',
    'kariyer_pusulasi': 'UC-LxyfIrfqWDfFCzJLVBwEg',
    'saglik_pusulasi': 'UCFgiTIusu01pgxviXU33jBQ',
    'teknoloji_pusulasi': 'UCZgzLieTfwq6_euBi1nEsrQ',
    'egitim_rehberi': 'UCVmjUlrK8L5rA-To5iGDbIw',
    'gayrimenkul_tv': 'UCIAevq41ewEZORIZ7ODMOoA',
    'girisim_okulu': 'UCvfuE893JTeSJx72j3eq3hQ',
}

for cid, ch_id in MAPPING.items():
    if cid in reg['channels']:
        reg['channels'][cid]['youtube_channel_id'] = ch_id
        reg['channels'][cid]['status'] = 'active'

Path('channels/channel_registry.json').write_text(
    json.dumps(reg, indent=2, ensure_ascii=False)
)
print('Registry guncellendi.')
for k, v in MAPPING.items():
    print(f'  {k}: {v}')
