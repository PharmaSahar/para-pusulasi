"""
Premium Görsel Servisler Entegrasyonu
- DALL-E 3: AI thumbnail arka planı
- Storyblocks: Premium stok video
- HeyGen: AI avatar presenter
"""
import logging
import os
import requests
import base64
from pathlib import Path

logger = logging.getLogger(__name__)

# .env'den değerleri yükle (import zamanında değil, çağrı zamanında)
def _get_env(key: str) -> str:
    """Her çağrıda .env'den oku — modül import zamanı yerine çağrı zamanı."""
    # Önce os.environ dene (systemd/shell'de set edilmiş olabilir)
    val = os.environ.get(key, "")
    if val:
        return val
    # .env dosyasından oku
    for env_path in [".env", "/opt/parapusulasi/.env"]:
        if Path(env_path).exists():
            try:
                from dotenv import dotenv_values
                vals = dotenv_values(env_path)
                val = vals.get(key, "")
                if val:
                    return val
            except Exception:
                pass
    return ""


# ══════════════════════════════════════════════════════════════
# DALL-E 3 — AI Thumbnail Görseli
# ══════════════════════════════════════════════════════════════

def generate_dalle_thumbnail(prompt: str, output_path: str) -> str | None:
    api_key = _get_env("OPENAI_API_KEY")
    if not api_key or not has_dalle():
        return None
    try:
        enhanced_prompt = (
            f"Professional YouTube finance channel thumbnail background. "
            f"{prompt}. "
            f"Ultra HD, dramatic lighting, vibrant colors, cinematic quality. "
            f"NO TEXT, NO WORDS, NO LETTERS in the image. "
            f"Turkish finance YouTube aesthetic."
        )
        resp = requests.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": "dall-e-3",
                "prompt": enhanced_prompt,
                "size": "1792x1024",  # 16:9 yakın
                "quality": "hd",
                "n": 1,
            },
            timeout=60,
        )
        resp.raise_for_status()
        img_url = resp.json()["data"][0]["url"]
        # İndir
        img_resp = requests.get(img_url, timeout=30)
        img_resp.raise_for_status()
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(img_resp.content)
        logger.info(f"DALL-E 3 thumbnail: {output_path}")
        return output_path
    except Exception as e:
        logger.warning(f"DALL-E 3 başarısız: {e}")
        return None


# ══════════════════════════════════════════════════════════════
# STORYBLOCKS — Premium Stok Video
# ══════════════════════════════════════════════════════════════

def fetch_storyblocks_clips(query: str, count: int = 4, output_dir: str = "") -> list:
    """
    Storyblocks API ile premium stok video indir.
    Gereksinim: STORYBLOCKS_API_KEY .env'de
    Docs: https://www.storyblocks.com/api/docs
    """
    api_key = _get_env("STORYBLOCKS_API_KEY")
    public_key = _get_env("STORYBLOCKS_PUBLIC_KEY")
    private_key = _get_env("STORYBLOCKS_PRIVATE_KEY")
    user_id = _get_env("STORYBLOCKS_USER_ID")
    project_id = _get_env("STORYBLOCKS_PROJECT_ID")
    search_url = _get_env("STORYBLOCKS_SEARCH_URL") or "https://api.storyblocks.com/api/v2/videos/search"
    if not (api_key or (public_key and private_key)):
        return []
    try:
        headers = {"Accept": "application/json"}
        if public_key and private_key:
            token = base64.b64encode(f"{public_key}:{private_key}".encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"Basic {token}"
        elif api_key:
            headers["APIKEY"] = api_key

        # Storyblocks arama
        resp = requests.get(
            search_url,
            params={
                "keyword": query,
                "num_results": count,
                "content_type": "footage",
                **({"user_id": user_id} if user_id else {}),
                **({"project_id": project_id} if project_id else {}),
            },
            headers=headers,
            timeout=15,
        )
        resp.raise_for_status()
        payload = resp.json() if resp.content else {}
        results = (
            payload.get("results")
            or payload.get("data", {}).get("results")
            or payload.get("data")
            or []
        )
        if not isinstance(results, list):
            logger.warning("Storyblocks: beklenmeyen response formatı")
            return []
        
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        paths = []
        for i, item in enumerate(results[:count]):
            preview_url = (
                item.get("preview_url")
                or item.get("thumbnail_url")
                or item.get("mp4_url")
                or item.get("url")
            )
            if not preview_url:
                continue
            clip_resp = requests.get(preview_url, timeout=30, stream=True)
            clip_resp.raise_for_status()
            content_type = (clip_resp.headers.get("Content-Type") or "").lower()
            if "video" in content_type:
                ext = ".mp4"
            elif "png" in content_type:
                ext = ".png"
            else:
                ext = ".jpg"
            clip_path = f"{output_dir}/sb_clip_{i:02d}{ext}"
            with open(clip_path, "wb") as f:
                for chunk in clip_resp.iter_content(chunk_size=65536):
                    f.write(chunk)
            paths.append(clip_path)
            logger.info(f"Storyblocks klip: {clip_path}")
        
        return paths
    except Exception as e:
        logger.warning(f"Storyblocks başarısız: {e}")
        return []


def has_storyblocks() -> bool:
    return bool(_get_env("STORYBLOCKS_API_KEY")) or (
        bool(_get_env("STORYBLOCKS_PUBLIC_KEY")) and bool(_get_env("STORYBLOCKS_PRIVATE_KEY"))
    )


def test_storyblocks_connection(query: str = "stock market", count: int = 1) -> tuple[bool, str]:
    """Storyblocks kimlik doğrulama ve arama endpoint'ini hızlıca test et."""
    api_key = _get_env("STORYBLOCKS_API_KEY")
    public_key = _get_env("STORYBLOCKS_PUBLIC_KEY")
    private_key = _get_env("STORYBLOCKS_PRIVATE_KEY")
    user_id = _get_env("STORYBLOCKS_USER_ID")
    project_id = _get_env("STORYBLOCKS_PROJECT_ID")
    search_url = _get_env("STORYBLOCKS_SEARCH_URL") or "https://api.storyblocks.com/api/v2/videos/search"
    if not (api_key or (public_key and private_key)):
        return False, "Storyblocks anahtarları boş (API key veya public+private gerekli)"

    try:
        headers = {"Accept": "application/json"}
        if public_key and private_key:
            token = base64.b64encode(f"{public_key}:{private_key}".encode("utf-8")).decode("ascii")
            headers["Authorization"] = f"Basic {token}"
        elif api_key:
            headers["APIKEY"] = api_key

        resp = requests.get(
            search_url,
            params={
                "keyword": query,
                "num_results": count,
                "content_type": "footage",
                **({"user_id": user_id} if user_id else {}),
                **({"project_id": project_id} if project_id else {}),
            },
            headers=headers,
            timeout=20,
        )
        if resp.status_code >= 400:
            snippet = (resp.text or "")[:220]
            return False, f"HTTP {resp.status_code}: {snippet}"

        payload = resp.json() if resp.content else {}
        results = (
            payload.get("results")
            or payload.get("data", {}).get("results")
            or payload.get("data")
            or []
        )
        size = len(results) if isinstance(results, list) else 0
        return True, f"Bağlantı başarılı. Sonuç sayısı: {size}"
    except Exception as e:
        return False, f"Bağlantı hatası: {e}"


# ══════════════════════════════════════════════════════════════
# HEYGEN — AI Avatar Presenter Video
# ══════════════════════════════════════════════════════════════

def generate_heygen_video(
    script: str,
    avatar_id: str,
    voice_id: str,
    output_path: str,
    title: str = "",
) -> str | None:
    """
    HeyGen ile AI avatar video üret.
    Gereksinim: HEYGEN_API_KEY .env'de, HEYGEN_AVATAR_ID .env'de
    
    Adımlar:
    1. Video oluşturma isteği gönder
    2. İşlem tamamlanana kadar bekle (genellikle 2-5 dakika)
    3. İndir
    """
    api_key = _get_env("HEYGEN_API_KEY")
    avatar_id = avatar_id or _get_env("HEYGEN_AVATAR_ID")
    if not api_key or not avatar_id:
        return None

    try:
        # Script çok uzunsa ilk 2000 karakter (HeyGen limiti)
        script_trimmed = script[:2000] if len(script) > 2000 else script

        # Video oluştur
        create_resp = requests.post(
            "https://api.heygen.com/v2/video/generate",
            headers={
                "X-Api-Key": api_key,
                "Content-Type": "application/json",
            },
            json={
                "video_inputs": [{
                    "character": {
                        "type": "avatar",
                        "avatar_id": avatar_id,
                        "avatar_style": "normal",
                    },
                    "voice": {
                        "type": "text",
                        "input_text": script_trimmed,
                        "voice_id": voice_id or "tr-TR-AhmetNeural",
                        "speed": 1.0,
                    },
                    "background": {
                        "type": "color",
                        "value": "#0A1228",  # Kanal rengi
                    }
                }],
                "dimension": {"width": 1920, "height": 1080},
                "title": title or "Para Pusulası Video",
            },
            timeout=30,
        )
        create_resp.raise_for_status()
        video_id = create_resp.json().get("data", {}).get("video_id")
        if not video_id:
            logger.warning("HeyGen video ID alınamadı")
            return None

        logger.info(f"HeyGen video oluşturuluyor: {video_id}")

        # Tamamlanmasını bekle (max 10 dakika)
        import time
        for attempt in range(40):  # 40 × 15sn = 10dk
            time.sleep(15)
            status_resp = requests.get(
                f"https://api.heygen.com/v1/video_status.get?video_id={video_id}",
                headers={"X-Api-Key": api_key},
                timeout=15,
            )
            status_data = status_resp.json().get("data", {})
            status = status_data.get("status")
            
            if status == "completed":
                video_url = status_data.get("video_url")
                if video_url:
                    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                    dl = requests.get(video_url, timeout=120, stream=True)
                    with open(output_path, "wb") as f:
                        for chunk in dl.iter_content(chunk_size=65536):
                            f.write(chunk)
                    logger.info(f"HeyGen video hazır: {output_path}")
                    return output_path
                break
            elif status == "failed":
                logger.error(f"HeyGen video başarısız: {status_data}")
                break
            else:
                logger.info(f"HeyGen bekleniyor... ({attempt+1}/40) status: {status}")

        return None
    except Exception as e:
        logger.warning(f"HeyGen başarısız: {e}")
        return None


def has_heygen() -> bool:
    return bool(_get_env("HEYGEN_API_KEY")) and bool(_get_env("HEYGEN_AVATAR_ID"))


def has_dalle() -> bool:
    enabled = (_get_env("OPENAI_IMAGE_ENABLED") or "").strip().lower()
    return bool(_get_env("OPENAI_API_KEY")) and enabled in {"1", "true", "yes", "on"}
