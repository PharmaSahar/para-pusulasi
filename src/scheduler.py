"""
Otomasyon Zamanlayicisi
"""
import logging
import os
from datetime import datetime

import schedule
import time

from .config import config
from .pipeline import run_full_pipeline

logger = logging.getLogger(__name__)

DAY_MAP = {
    "Monday": schedule.every().monday,
    "Tuesday": schedule.every().tuesday,
    "Wednesday": schedule.every().wednesday,
    "Thursday": schedule.every().thursday,
    "Friday": schedule.every().friday,
    "Saturday": schedule.every().saturday,
    "Sunday": schedule.every().sunday,
}


def setup_schedule():
    """Yapilandirmaya gore yukleme zamanlarini ayarla."""
    upload_times_raw = os.getenv("UPLOAD_TIME", "10:00")
    upload_times = [t.strip() for t in upload_times_raw.split(",")]
    days = config.upload_days

    for day in days:
        if day in DAY_MAP:
            for t in upload_times:
                DAY_MAP[day].at(t).do(_scheduled_run)
                logger.info(f"Zamanlama ayarlandi: Her {day} saat {t}")
        else:
            logger.warning(f"Geçersiz gün: {day}")

    logger.info(f"Toplam {len(schedule.jobs)} zamanlama aktif.")


def _scheduled_run():
    """Zamanlayıcı tarafından çağrılan pipeline çalıştırıcı."""
    logger.info(f"Zamanlanmış çalışma başlıyor: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    try:
        run_full_pipeline()
    except Exception as e:
        logger.error(f"Zamanlanmış çalışmada hata: {e}", exc_info=True)


def start_scheduler():
    """Zamanlayıcıyı başlat ve çalıştırmaya devam et."""
    setup_schedule()
    logger.info("Zamanlayıcı çalışıyor. Durdurmak için Ctrl+C.")

    while True:
        schedule.run_pending()
        next_job = schedule.next_run()
        if next_job:
            logger.debug(f"Bir sonraki çalışma: {next_job}")
        time.sleep(60)  # Her dakika kontrol et
