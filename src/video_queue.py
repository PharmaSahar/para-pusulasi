"""
Akıllı Video Kuyruğu Sistemi
- Yükleme sonrası hemen sonraki video renderlanır
- Saat geldiğinde video hazır bekler, anında yüklenir
"""
import json
import logging
import os
import pickle
import time
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)

QUEUE_DIR = "output/queue"


def get_queue_path(channel_id: str) -> str:
    return f"{QUEUE_DIR}/{channel_id}_queue.json"


def save_to_queue(channel_id: str, rendered_video: dict):
    """Renderlanmış videoyu kuyruğa ekle."""
    Path(QUEUE_DIR).mkdir(parents=True, exist_ok=True)
    queue_path = get_queue_path(channel_id)
    queue = load_queue(channel_id)
    queue.append(rendered_video)
    with open(queue_path, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)
    logger.info(f"[{channel_id}] Kuyruga eklendi. Kuyruk boyutu: {len(queue)}")


def load_queue(channel_id: str) -> list:
    queue_path = get_queue_path(channel_id)
    if not Path(queue_path).exists():
        return []
    with open(queue_path, encoding="utf-8") as f:
        return json.load(f)


def pop_from_queue(channel_id: str) -> dict | None:
    """Kuyruktan bir sonraki hazır videoyu al."""
    queue = load_queue(channel_id)
    if not queue:
        return None
    item = queue.pop(0)
    queue_path = get_queue_path(channel_id)
    with open(queue_path, "w", encoding="utf-8") as f:
        json.dump(queue, f, ensure_ascii=False, indent=2)
    return item


def queue_size(channel_id: str) -> int:
    return len(load_queue(channel_id))
