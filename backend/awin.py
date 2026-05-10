import httpx
import json
import os
from pathlib import Path
from urllib.parse import urlparse, quote

AWIN_API_KEY = os.getenv("AWIN_API_KEY", "")
AWIN_PUBLISHER_ID = os.getenv("AWIN_PUBLISHER_ID", "1625265")
CACHE_FILE = Path(__file__).parent / "awin_merchants_cache.json"


async def _load_cache() -> dict:
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text())
    return {}


async def _fetch_merchants() -> dict:
    if not AWIN_API_KEY:
        return {}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"https://api.awin.com/publishers/{AWIN_PUBLISHER_ID}/programmes",
            params={"relationship": "joined"},
            headers={"Authorization": f"Bearer {AWIN_API_KEY}"},
        )
        resp.raise_for_status()
        programmes = resp.json()

    cache = {}
    for prog in programmes:
        display_url = prog.get("displayUrl", "").lower().strip()
        if display_url:
            # Normalize: remove www. and trailing slash/path
            domain = display_url.replace("https://", "").replace("http://", "").replace("www.", "")
            domain = domain.split("/")[0]
            cache[domain] = prog["id"]

    CACHE_FILE.write_text(json.dumps(cache, indent=2))
    return cache


async def refresh_merchants() -> dict:
    if CACHE_FILE.exists():
        CACHE_FILE.unlink()
    return await _fetch_merchants()


async def get_merchant_id(product_url: str) -> str | None:
    domain = urlparse(product_url).netloc.lower().replace("www.", "")

    cache = await _load_cache()
    if not cache:
        cache = await _fetch_merchants()

    # Exact match first
    if domain in cache:
        return str(cache[domain])

    # Partial match (e.g. fr.zalando.com → zalando.com)
    for cached_domain, mid in cache.items():
        if domain.endswith(cached_domain) or cached_domain.endswith(domain):
            return str(mid)

    return None


async def _shorten(long_url: str) -> str:
    """Shorten via TinyURL — free, no auth."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://tinyurl.com/api-create.php",
                params={"url": long_url},
            )
            short = resp.text.strip()
            if short.startswith("http"):
                return short
    except Exception:
        pass
    return long_url  # fallback to long URL if TinyURL is down


async def generate_awin_link(product_url: str) -> str:
    merchant_id = await get_merchant_id(product_url)
    encoded_url = quote(product_url, safe="")

    if merchant_id:
        long = f"https://www.awin1.com/cread.php?awinmid={merchant_id}&awinaffid={AWIN_PUBLISHER_ID}&p={encoded_url}"
    else:
        long = f"https://www.awin1.com/cread.php?awinaffid={AWIN_PUBLISHER_ID}&p={encoded_url}"

    return await _shorten(long)
