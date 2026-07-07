"""
Finansal Grafik Üretici
- Matplotlib ile gerçekçi finans grafikleri
- Video içine embed edilecek PNG formatında
"""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def generate_chart(chart_data: dict, output_path: str) -> str | None:
    """
    chart_data formatı:
    {
      "type": "bar" | "line" | "pie",
      "title": "Grafik Başlığı",
      "data": {"labels": [...], "values": [...]}
    }
    Döner: output_path (başarılıysa) veya None
    """
    if not chart_data or not isinstance(chart_data, dict):
        return None
    try:
        import matplotlib
        matplotlib.use("Agg")  # GUI yok
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
        import numpy as np

        chart_type = chart_data.get("type", "bar")
        title = chart_data.get("title", "")
        data = chart_data.get("data", {})
        labels = data.get("labels", [])
        values = data.get("values", [])

        if not labels or not values:
            return None

        # Türk finans kanalı tema renkleri
        PRIMARY = "#D4AF37"   # Altın sarısı
        BG = "#0A1228"        # Lacivert
        GRID = "#1a2a4a"
        TEXT = "#FFFFFF"
        ACCENT = "#00D4AA"    # Yeşil vurgu

        fig, ax = plt.subplots(figsize=(12, 6.75))  # 16:9 oran
        fig.patch.set_facecolor(BG)
        ax.set_facecolor(BG)

        values_num = [float(v) for v in values]

        if chart_type == "bar":
            colors = [PRIMARY if v >= 0 else "#FF4757" for v in values_num]
            bars = ax.bar(labels, values_num, color=colors, width=0.6, zorder=3)
            # Değer etiketleri
            for bar, val in zip(bars, values_num):
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + max(values_num) * 0.02,
                    f"{val:,.0f}" if abs(val) > 100 else f"{val:.1f}%",
                    ha="center", va="bottom", color=TEXT, fontsize=11, fontweight="bold"
                )

        elif chart_type == "line":
            ax.plot(labels, values_num, color=PRIMARY, linewidth=3, marker="o",
                    markersize=8, markerfacecolor=ACCENT, zorder=3)
            ax.fill_between(range(len(labels)), values_num,
                           alpha=0.15, color=PRIMARY)
            for i, (l, v) in enumerate(zip(labels, values_num)):
                ax.text(i, v + max(values_num) * 0.02, f"{v:.1f}",
                       ha="center", color=TEXT, fontsize=10)

        elif chart_type == "pie":
            pie_colors = [PRIMARY, ACCENT, "#FF6B6B", "#4ECDC4", "#45B7D1", "#FFA07A"]
            wedges, texts, autotexts = ax.pie(
                values_num, labels=labels, colors=pie_colors[:len(values_num)],
                autopct="%1.1f%%", startangle=90,
                textprops={"color": TEXT, "fontsize": 11}
            )
            for at in autotexts:
                at.set_color(BG)
                at.set_fontweight("bold")

        # Genel stil
        ax.set_title(title, color=TEXT, fontsize=16, fontweight="bold", pad=20)
        ax.tick_params(colors=TEXT)
        for spine in ax.spines.values():
            spine.set_edgecolor(GRID)
        ax.grid(axis="y", color=GRID, alpha=0.5, zorder=0)

        if chart_type != "pie":
            ax.set_xticks(range(len(labels)) if chart_type == "line" else range(len(labels)))
            ax.set_xticklabels(labels, color=TEXT, fontsize=11)
            ax.yaxis.label.set_color(TEXT)

        # Kanal watermark
        fig.text(0.99, 0.01, "Para Pusulası", ha="right", va="bottom",
                 color=PRIMARY, fontsize=10, alpha=0.7)

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        plt.tight_layout()
        plt.savefig(output_path, dpi=150, bbox_inches="tight",
                    facecolor=BG, edgecolor="none")
        plt.close()
        logger.info(f"Grafik üretildi: {output_path}")
        return output_path

    except Exception as e:
        logger.warning(f"Grafik üretilemedi: {e}")
        return None


def generate_placeholder_chart(topic: str, output_path: str) -> str | None:
    """Konu bazlı örnek grafik — chart_data yoksa kullan."""
    import random

    # Konuya göre anlamlı örnek veri
    topic_lower = topic.lower()
    if "enflasyon" in topic_lower or "fiyat" in topic_lower:
        chart = {
            "type": "line",
            "title": "Türkiye Yıllık Enflasyon (2020-2026)",
            "data": {
                "labels": ["2020", "2021", "2022", "2023", "2024", "2025", "2026"],
                "values": [14.6, 19.6, 64.3, 67.1, 44.4, 38.2, 28.5]
            }
        }
    elif "borsa" in topic_lower or "bist" in topic_lower or "hisse" in topic_lower:
        chart = {
            "type": "line",
            "title": "BIST 100 Endeksi (Son 6 Ay)",
            "data": {
                "labels": ["Oca", "Şub", "Mar", "Nis", "May", "Haz"],
                "values": [8200, 8750, 9100, 8800, 9400, 9850]
            }
        }
    elif "kripto" in topic_lower or "bitcoin" in topic_lower:
        chart = {
            "type": "bar",
            "title": "Bitcoin Yıllık Getirileri (%)",
            "data": {
                "labels": ["2020", "2021", "2022", "2023", "2024", "2025"],
                "values": [302, 59.8, -65.2, 154, 122, 67]
            }
        }
    elif "faiz" in topic_lower or "mevduat" in topic_lower:
        chart = {
            "type": "bar",
            "title": "Yatırım Araçları Yıllık Getiri Karşılaştırması (2025)",
            "data": {
                "labels": ["Mevduat", "Döviz", "Altın", "BIST", "BTC"],
                "values": [42, 18, 35, 88, 67]
            }
        }
    elif "gayrimenkul" in topic_lower or "konut" in topic_lower:
        chart = {
            "type": "line",
            "title": "Türkiye Konut Fiyat Artışı (2020-2026, %)",
            "data": {
                "labels": ["2020", "2021", "2022", "2023", "2024", "2025", "2026"],
                "values": [30, 59, 198, 120, 68, 45, 32]
            }
        }
    else:
        # Genel tasarruf/yatırım grafiği
        chart = {
            "type": "bar",
            "title": "Aylık 5.000 TL Yatırımın 10 Yıllık Büyümesi",
            "data": {
                "labels": ["1. Yıl", "3. Yıl", "5. Yıl", "7. Yıl", "10. Yıl"],
                "values": [65000, 215000, 420000, 720000, 1250000]
            }
        }

    return generate_chart(chart, output_path)
