from __future__ import annotations

import hashlib
import io
import logging
import os
import tempfile
from pathlib import Path

import requests
from PIL import Image, ImageOps, UnidentifiedImageError

LOGGER = logging.getLogger(__name__)
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024


def _download(url: str, timeout: int = 45) -> bytes:
    headers = {
        "user-agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 Chrome/136 Safari/537.36"
        )
    }
    with requests.get(url, headers=headers, timeout=timeout, stream=True) as response:
        response.raise_for_status()
        content_length = int(response.headers.get("content-length") or 0)
        if content_length > MAX_DOWNLOAD_BYTES:
            raise ValueError("Instagram preview exceeds download limit")
        chunks: list[bytes] = []
        total = 0
        for chunk in response.iter_content(64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_DOWNLOAD_BYTES:
                raise ValueError("Instagram preview exceeds download limit")
            chunks.append(chunk)
        return b"".join(chunks)


def prepare_preview(event_key: str, url: str | None, media_dir: Path) -> Path | None:
    if not url:
        return None
    media_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(event_key.encode("utf-8")).hexdigest()
    destination = media_dir / f"{digest}.jpg"
    if destination.exists() and destination.stat().st_size > 0:
        return destination

    raw = _download(url)
    try:
        with tempfile.NamedTemporaryFile(
            dir=media_dir, suffix=".jpg", delete=False
        ) as handle:
            temporary = Path(handle.name)
        with Image.open(io.BytesIO(raw)) as source:
            image = ImageOps.exif_transpose(source)
            if image.mode not in {"RGB", "L"}:
                background = Image.new("RGB", image.size, "white")
                if "A" in image.getbands():
                    background.paste(image, mask=image.getchannel("A"))
                else:
                    background.paste(image)
                image = background
            elif image.mode == "L":
                image = image.convert("RGB")
            image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
            image.save(temporary, format="JPEG", quality=85, optimize=True)
        os.replace(temporary, destination)
        return destination
    except (OSError, UnidentifiedImageError):
        LOGGER.exception("Instagram preview could not be prepared")
        if "temporary" in locals():
            temporary.unlink(missing_ok=True)
        return None
