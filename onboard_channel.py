"""
Toplu Kanal Onboarding Araci
Yeni bir kanal eklemek icin gereken tum adimlari otomatize eder.
Google hesabi olusturma HARIC her sey otomatik.

Kullanim:
  python onboard_channel.py borsa_akademi borsa.akademi.yt@gmail.com
  python onboard_channel.py --status          # tum kanallar durumu
  python onboard_channel.py --next            # sonraki kurulmamis kanali goster
"""
import sys
import csv
import json
import shutil
import subprocess
from pathlib import Path
from datetime import datetime

sys.path.insert(0, ".")

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()
TRACKER_PATH = "channels/channels_tracker.csv"


def show_status():
    """Tum kanallar durumunu goster."""
    rows = _read_tracker()
    table = Table(title="Kanal Durumu", border_style="cyan")
    table.add_column("Kanal", style="cyan")
    table.add_column("Gmail")
    table.add_column("Nis")
    table.add_column("Durum")
    table.add_column("Token")
    table.add_column("Abone")

    active = sum(1 for r in rows if r["status"] == "active")
    pending = sum(1 for r in rows if r["status"] == "pending")

    for r in rows:
        status_color = "green" if r["status"] == "active" else "yellow"
        token_icon = "✅" if r["token_ready"] == "TRUE" else "❌"
        table.add_row(
            r["channel_id"],
            r["gmail"],
            r["niche"],
            f"[{status_color}]{r['status']}[/{status_color}]",
            token_icon,
            r.get("subscribers", "0"),
        )

    console.print(table)
    console.print(f"\n[green]{active} aktif[/green] | [yellow]{pending} beklemede[/yellow] | Toplam: {len(rows)}")


def show_next():
    """Kurulmamis bir sonraki kanali goster."""
    rows = _read_tracker()
    for r in rows:
        if r["token_ready"] != "TRUE":
            console.print(Panel(
                f"[bold]Sonraki Kanal:[/bold] {r['channel_id']}\n"
                f"Gmail: [cyan]{r['gmail']}[/cyan]\n"
                f"YouTube Kanal Adi: [yellow]{r['youtube_channel_name']}[/yellow]\n"
                f"Nis: {r['niche']}\n\n"
                f"[dim]Adimlar:[/dim]\n"
                f"1. Gmail hesabi olustur: {r['gmail']}\n"
                f"2. YouTube'a gir → Kanal olustur: '{r['youtube_channel_name']}'\n"
                f"3. Google Cloud Console'da bu hesabi test kullanicisi ekle\n"
                f"4. Calistir: [bold]python setup_channel.py {r['channel_id']}[/bold]",
                title="Siraki Adim",
                border_style="yellow",
            ))
            return
    console.print("[green]Tum kanallar kurulmus![/green]")


def onboard_channel(channel_id: str, gmail: str = ""):
    """Yeni bir kanali sisteme ekle."""
    from src.channel_manager import get_channel
    from src.youtube_auth import get_authenticated_service

    console.print(Panel(
        f"[bold cyan]{channel_id}[/bold cyan] onboarding baslatiliyor...",
        border_style="cyan",
    ))

    # 1. Kanal klasorlerini olustur
    cfg = get_channel(channel_id)
    cfg.ensure_directories()
    console.print("✅ Klasor yapisi olusturuldu")

    # 2. Watermark kopyala
    wm_src = "assets/branding/watermark_150x150.png"
    wm_dst = f"{cfg.base_dir}/branding/watermark_150x150.png"
    if Path(wm_src).exists() and not Path(wm_dst).exists():
        shutil.copy(wm_src, wm_dst)
        console.print("✅ Watermark kopyalandi")

    # 3. .env dosyasi olustur (ana .env'den kopyala)
    channel_env = f"{cfg.base_dir}/.env"
    if not Path(channel_env).exists():
        shutil.copy(".env", channel_env)
        console.print(f"✅ .env olusturuldu: {channel_env}")

    # 4. YouTube OAuth
    console.print(f"\n[yellow]YouTube kimlik dogrulamasi ({cfg.name}):[/yellow]")
    if gmail:
        console.print(f"[dim]Gmail: {gmail} - bu hesapla giris yapin![/dim]")

    try:
        svc = get_authenticated_service(channel_cfg=cfg)
        ch = svc.channels().list(part="snippet,statistics", mine=True).execute()
        if ch.get("items"):
            yt_name = ch["items"][0]["snippet"]["title"]
            subs = ch["items"][0]["statistics"].get("subscriberCount", "0")
            console.print(f"✅ YouTube baglandi: '{yt_name}' ({subs} abone)")
            _update_tracker(channel_id, {"token_ready": "TRUE", "status": "active",
                                          "youtube_channel_name": yt_name, "gmail": gmail or ""})
        else:
            console.print("[yellow]⚠️  YouTube kanali bulunamadi, once kanal olusturun[/yellow]")
    except Exception as e:
        console.print(f"[red]Hata: {e}[/red]")

    # 5. Kanal logosu olustur
    _generate_channel_branding(cfg)
    console.print(f"✅ Kanal logosu olusturuldu")

    console.print(f"\n[green bold]✅ {channel_id} hazir![/green bold]")
    console.print(f"Calistir: [cyan]python run_channels.py {channel_id}[/cyan]")


def _generate_channel_branding(cfg):
    """Kanal rengine gore watermark olustur."""
    try:
        from PIL import Image, ImageDraw, ImageFont
        import numpy as np

        W, H = 150, 150
        bg_color = tuple(cfg.color_bg) + (200,)
        primary = tuple(cfg.color_primary) + (255,)

        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([(5, 5), (145, 145)], fill=bg_color)
        draw.ellipse([(5, 5), (145, 145)], outline=primary, width=3)

        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 13)
        except Exception:
            font = ImageFont.load_default()

        name_parts = cfg.name.split()
        y = 55
        for part in name_parts[:2]:
            bb = draw.textbbox((0, 0), part, font=font)
            x = (W - (bb[2] - bb[0])) // 2
            draw.text((x, y), part, font=font, fill=primary)
            y += 18

        out = f"{cfg.base_dir}/branding/watermark_150x150.png"
        img.save(out, "PNG")
    except Exception:
        pass  # Hata olursa varsayilan watermark kullanilir


def _read_tracker() -> list[dict]:
    path = Path(TRACKER_PATH)
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _update_tracker(channel_id: str, updates: dict):
    rows = _read_tracker()
    for row in rows:
        if row["channel_id"] == channel_id:
            row.update(updates)
            if not row.get("created_date"):
                row["created_date"] = datetime.now().strftime("%Y-%m-%d")
    fieldnames = rows[0].keys() if rows else []
    with open(TRACKER_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args or args[0] == "--status":
        show_status()
    elif args[0] == "--next":
        show_next()
    elif args[0].startswith("--"):
        console.print("[red]Bilinmeyen komut.[/red]")
    else:
        channel_id = args[0]
        gmail = args[1] if len(args) > 1 else ""
        onboard_channel(channel_id, gmail)
