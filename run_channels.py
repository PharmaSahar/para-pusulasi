"""
Cok Kanalli Otomasyon Calistirici
Tum kanallari veya secili kanallari zamanlayici ile calistirir.

Kullanim:
  python run_channels.py                     # tum kanallari baslat
  python run_channels.py para_pusulasi       # tek kanal
  python run_channels.py --now               # tum kanallari HEMEN bir kez calistir
  python run_channels.py borsa_akademi --now # tek kanal hemen
"""
import sys
import logging
import schedule
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, ".")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("logs/multi_channel.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("MultiChannel")

from rich.console import Console
from rich.table import Table

console = Console()

DAY_MAP = {
    "Monday": schedule.every().monday,
    "Tuesday": schedule.every().tuesday,
    "Wednesday": schedule.every().wednesday,
    "Thursday": schedule.every().thursday,
    "Friday": schedule.every().friday,
    "Saturday": schedule.every().saturday,
    "Sunday": schedule.every().sunday,
}

DAYS = list(DAY_MAP.keys())


def run_channel_pipeline(channel_id: str):
    """Belirli bir kanal icin pipeline calistir."""
    from src.channel_manager import get_channel
    from src.pipeline import run_full_pipeline

    try:
        cfg = get_channel(channel_id)
        logger.info(f"[{cfg.name}] Pipeline baslatiliyor...")
        result = run_full_pipeline(channel_cfg=cfg)
        logger.info(f"[{cfg.name}] ✅ Tamamlandi: {result.get('youtube_url', 'N/A')}")
        return result
    except Exception as e:
        logger.error(f"[{channel_id}] Pipeline hatasi: {e}", exc_info=True)
        return {}


def setup_all_schedules(channel_ids: list[str]):
    """Tum kanallari zamanlayiciya ekle."""
    from src.channel_manager import get_channel

    table = Table(title="Aktif Zamanlama", border_style="green")
    table.add_column("Kanal")
    table.add_column("Saatler")
    table.add_column("Gorev Sayisi")

    total = 0
    for cid in channel_ids:
        cfg = get_channel(cid)
        for day_name in DAYS:
            for upload_time in cfg.upload_times:
                cid_copy = cid  # closure icin
                DAY_MAP[day_name].at(upload_time).do(run_channel_pipeline, channel_id=cid_copy)
        count = len(DAYS) * len(cfg.upload_times)
        total += count
        table.add_row(cfg.name, " + ".join(cfg.upload_times), str(count))

    console.print(table)
    logger.info(f"Toplam {total} zamanlama aktif ({len(channel_ids)} kanal)")


def run_all_now(channel_ids: list[str]):
    """Tum kanallari hemen, sirayla calistir."""
    console.print(f"[bold yellow]{len(channel_ids)} kanal hemen calistiriliyor...[/bold yellow]")
    for cid in channel_ids:
        console.print(f"\n[cyan]► {cid} baslatiliyor...[/cyan]")
        run_channel_pipeline(cid)


def main():
    args = sys.argv[1:]
    run_now = "--now" in args
    args = [a for a in args if a != "--now"]

    from src.channel_manager import list_channels as lc
    all_channels = lc()

    # Hangi kanallari calistir?
    if args:
        channel_ids = [a for a in args if a in all_channels]
        invalid = [a for a in args if a not in all_channels]
        if invalid:
            console.print(f"[red]Bilinmeyen kanallar: {invalid}[/red]")
            console.print(f"Gecerli kanallar: {all_channels}")
            sys.exit(1)
    else:
        channel_ids = all_channels

    # Token kontrolu
    from src.channel_manager import get_channel
    ready = []
    not_ready = []
    for cid in channel_ids:
        cfg = get_channel(cid)
        if Path(cfg.token_path).exists():
            ready.append(cid)
        else:
            not_ready.append(cid)

    if not_ready:
        console.print(f"[yellow]⚠️  Token eksik kanallar (once setup_channel.py calistirin):[/yellow]")
        for cid in not_ready:
            console.print(f"  python setup_channel.py {cid}")

    if not ready:
        console.print("[red]Hicbir kanal hazir degil![/red]")
        sys.exit(1)

    console.print(f"\n[green]{len(ready)} kanal hazir: {ready}[/green]")

    if run_now:
        run_all_now(ready)
    else:
        console.print("\n[bold]Zamanlayici baslatiliyor...[/bold]")
        setup_all_schedules(ready)
        console.print("[green]Calistiyor. Durdurmak: Ctrl+C[/green]\n")
        while True:
            schedule.run_pending()
            time.sleep(60)


if __name__ == "__main__":
    main()
