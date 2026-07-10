#!/usr/bin/env python3
"""Report metadata-repair blockers for channels still pending OAuth."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "channels/channel_registry.json"
JSON_OUT = ROOT / "logs/metadata_repair_pending_oauth_blockers_20260710.json"
MD_OUT = ROOT / "logs/metadata_repair_pending_oauth_blockers_20260710.md"


def main() -> int:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    channels = registry.get("channels", {})

    items: list[dict[str, object]] = []
    for channel_id, config in channels.items():
        if config.get("status") != "pending_oauth":
            continue

        base_dir = ROOT / "channels" / channel_id
        items.append(
            {
                "channel": channel_id,
                "dir_exists": base_dir.exists(),
                "token_exists": (base_dir / "youtube_token.pickle").exists(),
                "client_secrets_exists": (base_dir / "client_secrets.json").exists(),
                "env_exists": (base_dir / ".env").exists(),
            }
        )

    summary = {
        "generated_at": datetime.now().isoformat(),
        "total_pending_oauth": len(items),
        "dir_exists": sum(1 for item in items if item["dir_exists"]),
        "token_exists": sum(1 for item in items if item["token_exists"]),
        "client_secrets_exists": sum(1 for item in items if item["client_secrets_exists"]),
        "env_exists": sum(1 for item in items if item["env_exists"]),
        "repair_ready_estimate": sum(1 for item in items if item["dir_exists"] and item["token_exists"]),
    }

    JSON_OUT.write_text(
        json.dumps({"summary": summary, "items": items}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        "# Metadata Repair Pending OAuth Blockers (2026-07-10)",
        "",
        f"- total_pending_oauth: {summary['total_pending_oauth']}",
        f"- repair_ready_estimate (dir+token): {summary['repair_ready_estimate']}",
        f"- token_exists: {summary['token_exists']}",
        f"- client_secrets_exists: {summary['client_secrets_exists']}",
        f"- env_exists: {summary['env_exists']}",
        "",
        "| channel | dir_exists | token_exists | client_secrets_exists | env_exists |",
        "|---|---|---|---|---|",
    ]
    for item in items:
        lines.append(
            "| {channel} | {dir_exists} | {token_exists} | {client_secrets_exists} | {env_exists} |".format(
                channel=item["channel"],
                dir_exists=str(item["dir_exists"]).lower(),
                token_exists=str(item["token_exists"]).lower(),
                client_secrets_exists=str(item["client_secrets_exists"]).lower(),
                env_exists=str(item["env_exists"]).lower(),
            )
        )

    MD_OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "json_report": str(JSON_OUT.relative_to(ROOT)),
                "md_report": str(MD_OUT.relative_to(ROOT)),
                "summary": summary,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
