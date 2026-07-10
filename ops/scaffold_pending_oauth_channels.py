#!/usr/bin/env python3
"""Create minimal channel scaffolding for pending OAuth channels."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "channels/channel_registry.json"
OUT = ROOT / "logs/pending_oauth_scaffold_20260710.json"

ENV_TEMPLATE = """# Placeholder channel env\n# Fill channel-specific values before production use.\nANTHROPIC_API_KEY=\nYOUTUBE_CLIENT_ID=\nYOUTUBE_CLIENT_SECRET=\nYOUTUBE_ANALYTICS_TOKEN_PATH=\nPEXELS_API_KEY=\nELEVENLABS_API_KEY=\nELEVENLABS_VOICE_ID=\n"""

CLIENT_SECRETS_TEMPLATE = {
    "installed": {
        "client_id": "REPLACE_ME",
        "project_id": "REPLACE_ME",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_secret": "REPLACE_ME",
        "redirect_uris": [
            "http://localhost"
        ]
    }
}

DIRS = [
    "branding",
    "output",
    "output/audio",
    "output/scripts",
    "output/videos",
]


def main() -> int:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    channels = registry.get("channels", {})

    items: list[dict[str, object]] = []
    for channel_id, config in channels.items():
        if config.get("status") != "pending_oauth":
            continue

        base_dir = ROOT / "channels" / channel_id
        created_dirs = []
        for rel_dir in DIRS:
            path = base_dir / rel_dir
            if not path.exists():
                path.mkdir(parents=True, exist_ok=True)
                created_dirs.append(str(path.relative_to(ROOT)))
            else:
                path.mkdir(parents=True, exist_ok=True)

        env_path = base_dir / ".env"
        env_created = False
        if not env_path.exists():
            env_path.write_text(ENV_TEMPLATE, encoding="utf-8")
            env_created = True

        secrets_path = base_dir / "client_secrets.json"
        secrets_created = False
        if not secrets_path.exists():
            secrets_path.write_text(json.dumps(CLIENT_SECRETS_TEMPLATE, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            secrets_created = True

        items.append(
            {
                "channel": channel_id,
                "created_dirs": created_dirs,
                "env_created": env_created,
                "client_secrets_created": secrets_created,
            }
        )

    summary = {
        "generated_at": datetime.now().isoformat(),
        "pending_channels": len(items),
        "env_created": sum(1 for item in items if item["env_created"]),
        "client_secrets_created": sum(1 for item in items if item["client_secrets_created"]),
        "dirs_touched": sum(len(item["created_dirs"]) for item in items),
    }

    OUT.write_text(json.dumps({"summary": summary, "items": items}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(OUT.relative_to(ROOT)), "summary": summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
