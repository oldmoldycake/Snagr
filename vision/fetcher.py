"""Image download from marketplace CDNs — hostile territory (risk 2):
hotlink protection and fingerprinting are normal there, so requests carry
realistic browser headers and the listing page as Referer. A failed fetch
skips that image (logged), never fails the check — if failure rates prove
high, the named fallback is the agent posting bytes it captured via
Playwright (future work)."""

import logging
from io import BytesIO

import httpx
from PIL import Image

log = logging.getLogger(__name__)

FETCH_TIMEOUT_SECONDS = 20
# Sanity bound: a listing photo is not 50 MB; anything past this is skipped.
MAX_IMAGE_BYTES = 20 * 1024 * 1024

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def fetch_image(url: str, referer: str | None = None) -> tuple[bytes, str] | None:
    """Download one listing photo; (bytes, content_type), or None to skip it.

    Pillow verifies the payload is actually an image — CDNs answer blocked
    requests with HTML error pages at HTTP 200.
    """
    headers = dict(BROWSER_HEADERS)
    if referer:
        headers["Referer"] = referer
    try:
        response = httpx.get(
            url, headers=headers, timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=True
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning(f"Skipping image {url}: fetch failed ({exc})")
        return None

    data = response.content
    if len(data) > MAX_IMAGE_BYTES:
        log.warning(f"Skipping image {url}: {len(data)} bytes exceeds the sanity bound")
        return None
    try:
        with Image.open(BytesIO(data)) as image:
            image.verify()
            content_type = Image.MIME.get(image.format, "application/octet-stream")
    except Exception as exc:
        log.warning(f"Skipping image {url}: not a decodable image ({exc})")
        return None
    return data, content_type
