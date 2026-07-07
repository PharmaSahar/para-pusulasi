#!/usr/bin/env python3
"""
YouTube AI Pasif Gelir Otomasyonu - Ana Giriş Noktası

Kullanım:
  python main.py --once              → Tek video üret ve yükle
  python main.py --schedule          → Otomatik zamanlayıcı ile çalıştır
  python main.py --generate-only     → Sadece içerik üret, yükleme
  python main.py --topic "Konu"      → Belirli konu için çalıştır
  python main.py --stats             → Kanal istatistiklerini göster
  python main.py --check             → Yapılandırmayı doğrula
"""
import logging
import sys
import click
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

# Logging ayarla
Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("logs/automation.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)
console = Console()


@click.command()
@click.option("--once", is_flag=True, help="Tek bir video üret ve yükle")
@click.option("--schedule", "use_schedule", is_flag=True, help="Zamanlayıcı ile çalıştır")
@click.option("--generate-only", is_flag=True, help="Sadece içerik üret (yükleme)")
@click.option("--topic", default=None, help="Belirli bir video konusu belirt")
@click.option("--stats", is_flag=True, help="Kanal istatistiklerini göster")
@click.option("--check", is_flag=True, help="Yapılandırmayı ve API bağlantılarını doğrula")
@click.option("--privacy", default="public", type=click.Choice(["public", "private", "unlisted"]),
              help="Video gizlilik ayarı (varsayılan: public)")
def main(once, use_schedule, generate_only, topic, stats, check, privacy):
    """🎬 YouTube AI Pasif Gelir Otomasyonu"""
    from src.config import config

    console.print(Panel(
        "[bold cyan]YouTube AI Pasif Gelir Otomasyonu[/bold cyan]\n"
        "Claude AI + YouTube Data API v3",
        border_style="cyan",
    ))

    if check:
        _check_config(config)
        return

    if stats:
        _show_stats()
        return

    # Yapılandırma doğrulama
    missing = config.validate()
    if missing and not generate_only:
        console.print(f"[red]❌ Eksik API anahtarları: {', '.join(missing)}[/red]")
        console.print("→ .env.example dosyasını .env olarak kopyalayıp doldurun.")
        sys.exit(1)
    elif missing and generate_only:
        console.print(f"[yellow]⚠️  YouTube API anahtarları eksik ama sadece içerik üretilecek.[/yellow]")

    if once or topic or generate_only:
        _run_once(topic=topic, generate_only=generate_only, privacy=privacy)

    elif use_schedule:
        console.print("[green]📅 Zamanlayıcı başlatılıyor...[/green]")
        from src.scheduler import start_scheduler
        start_scheduler()

    else:
        console.print("[yellow]Kullanım için --help seçeneğini deneyin.[/yellow]")
        console.print("Örnek: [cyan]python main.py --once[/cyan]")


def _run_once(topic=None, generate_only=False, privacy="public"):
    """Tek bir pipeline çalıştırması."""
    from src.pipeline import run_full_pipeline

    try:
        result = run_full_pipeline(
            topic=topic,
            generate_only=generate_only,
            privacy=privacy,
        )
        _print_result(result)
    except Exception as e:
        logger.error(f"Pipeline hatası: {e}", exc_info=True)
        console.print(f"[red]❌ Hata: {e}[/red]")
        sys.exit(1)


def _print_result(result: dict):
    """Sonuçları güzel formatta yazdır."""
    table = Table(title="Pipeline Sonuçları", border_style="green")
    table.add_column("Alan", style="cyan")
    table.add_column("Değer")

    for key, value in result.items():
        table.add_row(key, str(value))

    console.print(table)
    if "youtube_url" in result:
        console.print(f"\n[bold green]✅ Video yayında:[/bold green] {result['youtube_url']}")


def _show_stats():
    """Kanal istatistiklerini göster."""
    from src.youtube_uploader import YouTubeUploader
    try:
        uploader = YouTubeUploader()
        stats = uploader.get_channel_stats()
        table = Table(title="Kanal İstatistikleri", border_style="blue")
        table.add_column("Metrik", style="cyan")
        table.add_column("Değer", style="green")
        for k, v in stats.items():
            table.add_row(k.replace("_", " ").title(), str(v))
        console.print(table)
    except Exception as e:
        console.print(f"[red]İstatistikler alınamadı: {e}[/red]")


def _check_config(config):
    """Yapılandırma ve API doğrulama."""
    console.print("[bold]Yapılandırma Kontrolü[/bold]\n")
    missing = config.validate()

    items = [
        ("ANTHROPIC_API_KEY", bool(config.anthropic_api_key)),
        ("YOUTUBE_CLIENT_ID", bool(config.youtube_client_id)),
        ("YOUTUBE_CLIENT_SECRET", bool(config.youtube_client_secret)),
        ("ELEVENLABS_API_KEY (opsiyonel)", bool(config.elevenlabs_api_key)),
        ("Niş", bool(config.channel_niche)),
        ("Dil", bool(config.channel_language)),
    ]

    for name, ok in items:
        icon = "✅" if ok else "❌"
        console.print(f"  {icon} {name}")

    if not missing:
        console.print("\n[green]Tüm zorunlu yapılandırmalar mevcut![/green]")
    else:
        console.print(f"\n[red]Eksik: {', '.join(missing)}[/red]")


if __name__ == "__main__":
    main()
