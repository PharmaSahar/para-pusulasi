"""
Yeni Kanal Kurulum Scripti
Her kanal icin YouTube OAuth kimlik dogrulamasini yapar ve token'i kaydeder.

Kullanim:
  python setup_channel.py                    # tum kanallari listele
  python setup_channel.py borsa_akademi      # tek kanal kur
  python setup_channel.py --all              # tum kanallari kur (sirayla)
"""
import sys
import os
import unicodedata
from datetime import datetime
sys.path.insert(0, ".")
os.chdir(os.path.dirname(os.path.abspath(__file__)) if "__file__" in dir() else ".")

from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()


def _normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return "".join(ch for ch in ascii_text.lower() if ch.isalnum())


def _channel_matches(cfg, yt_name: str, yt_id: str | None = None) -> bool:
    expected_id = getattr(cfg, "youtube_channel_id", "") or ""
    if expected_id and yt_id:
        return expected_id == yt_id
    return _normalize_name(cfg.name) == _normalize_name(yt_name)


def _archive_mismatched_token(cfg, yt_name: str, yt_id: str | None = None) -> str:
    src = Path(cfg.token_path)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = src.with_name(f"{src.stem}.mismatch_{stamp}.pickle")
    if src.exists():
        src.rename(dst)
    detail = yt_name if not yt_id else f"{yt_name} ({yt_id})"
    console.print(f"[red]Yanlis kanal token'i algilandi ve arsivlendi: {detail} -> {dst}[/red]")
    return str(dst)


def setup_channel(channel_id: str):
    from src.channel_manager import get_channel
    from src.youtube_auth import get_authenticated_service

    cfg = get_channel(channel_id)
    cfg.ensure_directories()

    console.print(Panel(
        f"[bold cyan]{cfg.name}[/bold cyan]\n{cfg.slogan}\nNis: {cfg.niche}",
        title=f"Kanal Kurulumu: {channel_id}",
        border_style="cyan",
    ))

    if Path(cfg.token_path).exists():
        console.print(f"[green]✅ Token zaten mevcut: {cfg.token_path}[/green]")
        if _test_connection(cfg):
            return
        console.print("[yellow]Mevcut token bu kanal ile eslesmedigi icin yeniden yetkilendirme yapilacak.[/yellow]")

    console.print(f"\n[yellow]YouTube kimlik dogrulamasi baslatiliyor...[/yellow]")
    console.print(f"[dim]Not: {cfg.name} icin farkli bir Google hesabi kullanin![/dim]\n")

    try:
        svc = get_authenticated_service(channel_cfg=cfg)
        ch = svc.channels().list(part="snippet,id", mine=True).execute()
        if ch.get("items"):
            yt_name = ch["items"][0]["snippet"]["title"]
            yt_id = ch["items"][0].get("id")
            if not _channel_matches(cfg, yt_name, yt_id):
                _archive_mismatched_token(cfg, yt_name, yt_id)
                console.print(f"[red]Beklenen kanal: {cfg.name} | Baglanan kanal: {yt_name}[/red]")
                return
            console.print(f"[green]✅ Baglandi: YouTube Kanali = '{yt_name}'[/green]")
        else:
            console.print("[yellow]⚠️  Kanal bulunamadi, lutfen YouTube kanali olusturun.[/yellow]")
    except Exception as e:
        console.print(f"[red]❌ Hata: {e}[/red]")


def _test_connection(cfg):
    from src.youtube_auth import get_authenticated_service
    try:
        svc = get_authenticated_service(channel_cfg=cfg)
        ch = svc.channels().list(part="snippet,statistics,id", mine=True).execute()
        if ch.get("items"):
            item = ch["items"][0]
            name = item["snippet"]["title"]
            yt_id = item.get("id")
            if not _channel_matches(cfg, name, yt_id):
                _archive_mismatched_token(cfg, name, yt_id)
                return False
            subs = item["statistics"].get("subscriberCount", "?")
            console.print(f"  Kanal: {name} | Abone: {subs}")
            return True
    except Exception as e:
        console.print(f"  [red]Baglanti hatasi: {e}[/red]")
    return False


def list_channels():
    from src.channel_manager import get_all_channels
    channels = get_all_channels()

    table = Table(title="10 Kanal Sistemi", border_style="cyan")
    table.add_column("ID", style="cyan")
    table.add_column("Kanal Adi")
    table.add_column("Nis")
    table.add_column("Yukleme Saatleri")
    table.add_column("Token", style="green")

    for cfg in channels:
        has_token = "✅" if Path(cfg.token_path).exists() else "❌"
        times = " + ".join(cfg.upload_times)
        table.add_row(cfg.channel_id, cfg.name, cfg.niche, times, has_token)

    console.print(table)


if __name__ == "__main__":
    args = sys.argv[1:]

    if not args:
        list_channels()
        console.print("\n[dim]Kullanim: python setup_channel.py <channel_id>[/dim]")
        console.print("[dim]Ornek:    python setup_channel.py borsa_akademi[/dim]")
        console.print("[dim]Hepsi:    python setup_channel.py --all[/dim]")

    elif args[0] == "--all":
        from src.channel_manager import list_channels as lc
        for cid in lc():
            console.print(f"\n{'─'*50}")
            setup_channel(cid)

    elif args[0] == "--list":
        list_channels()

    else:
        setup_channel(args[0])
