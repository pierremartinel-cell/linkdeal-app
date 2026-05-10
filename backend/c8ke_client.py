"""
C8KE client — uses API calls directly after Playwright login (Cognito OAuth).
Playwright is only used once to handle the login flow and extract session cookies.
"""

import os
import json
import asyncio
from pathlib import Path

import httpx
from playwright.async_api import async_playwright

C8KE_EMAIL = os.getenv("C8KE_EMAIL", "")
C8KE_PASSWORD = os.getenv("C8KE_PASSWORD", "")
SESSION_FILE = Path(__file__).parent / "c8ke_session.json"
CONFIG_FILE = Path(__file__).parent / "c8ke_config.json"

BASE = "https://www.c8ke.co"


# ── Session management ────────────────────────────────────────────────────────

async def _login_and_save_session() -> list[dict]:
    """Log in via Playwright (handles Cognito) and save cookies."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 390, "height": 844})
        page = await context.new_page()

        await page.goto(f"{BASE}/auth/index/login.html", wait_until="load")
        await page.fill('input[name="username"]', C8KE_EMAIL)
        await page.fill('input[name="password"]', C8KE_PASSWORD)
        await page.click('input[name="signInSubmitButton"]')
        await page.wait_for_load_state("load")
        await page.wait_for_timeout(2000)

        cookies = await context.cookies()
        SESSION_FILE.write_text(json.dumps(cookies))
        await browser.close()
        return cookies


def _load_cookies() -> list[dict]:
    if SESSION_FILE.exists():
        return json.loads(SESSION_FILE.read_text())
    return []


def _cookies_to_jar(cookies: list[dict]) -> dict[str, str]:
    return {c["name"]: c["value"] for c in cookies if "c8ke.co" in c.get("domain", "")}


# ── Config: block_id ──────────────────────────────────────────────────────────

def _load_config() -> dict:
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return {}


def _save_config(cfg: dict):
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))


async def _fetch_block_id(cookies_jar: dict[str, str]) -> str | None:
    """Fetch the Links Group block_id from the page config."""
    async with httpx.AsyncClient(base_url=BASE, cookies=cookies_jar, timeout=20) as client:
        resp = await client.post("/influencer//web_app/page", data={"page": "home"})
        data = resp.json()

    blocks = data.get("result", {}).get("blocks", []) or data.get("blocks", [])
    for block in blocks:
        if block.get("type") == "links" or block.get("blockType") == "links":
            return str(block.get("id") or block.get("blockId"))

    # Fallback: search in the full response for the links block
    text = resp.text
    import re
    match = re.search(r'"id"\s*:\s*(\d+).*?"type"\s*:\s*"links"', text)
    if match:
        return match.group(1)
    # Known fallback from discovery
    return "434598"


# ── Main function ─────────────────────────────────────────────────────────────

async def add_to_c8ke(title: str, url: str, image_url: str | None = None) -> bool:
    if not C8KE_EMAIL or not C8KE_PASSWORD:
        print("[c8ke] Credentials not configured")
        return False

    cfg = _load_config()
    block_id = cfg.get("block_id")

    # Try with existing session first
    cookies = _load_cookies()
    if not cookies:
        cookies = await _login_and_save_session()

    for attempt in range(2):
        try:
            jar = _cookies_to_jar(cookies)

            # Fetch block_id if not cached
            if not block_id:
                block_id = await _fetch_block_id(jar)
                if block_id:
                    cfg["block_id"] = block_id
                    _save_config(cfg)

            async with httpx.AsyncClient(base_url=BASE, cookies=jar, timeout=20) as client:
                resp = await client.post(
                    "/influencer/linktrees_v1/save",
                    data={"title": title, "url": url, "block_id": block_id, "sort": "top"},
                )

            try:
                result = resp.json()
            except Exception:
                result = {}

            code = result.get("code") or resp.status_code
            if code == 200 or resp.status_code == 200:
                link_id = result.get("result", {}).get("id")
                print(f"[c8ke] Link added (id={link_id}): {title}")

                # Upload image if provided
                if image_url and link_id:
                    asyncio.create_task(_upload_image(jar, link_id, image_url))

                return True

            if code in (301, 302, 401, 403) or "login" in str(result).lower():
                raise PermissionError("Session expired")

            print(f"[c8ke] Unexpected response ({resp.status_code}): {result}")
            return False

        except PermissionError:
            if attempt == 0:
                print("[c8ke] Session expired, re-logging in…")
                cookies = await _login_and_save_session()
            else:
                print("[c8ke] Login failed")
                return False
        except Exception as e:
            print(f"[c8ke] Error: {e}")
            return False

    return False


async def _upload_image(jar: dict, link_id: str, image_url: str):
    """Download the product image and upload it to the c8ke link."""
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            img_resp = await client.get(image_url, headers={"User-Agent": "Mozilla/5.0"})
            img_resp.raise_for_status()
            img_bytes = img_resp.content

        async with httpx.AsyncClient(base_url=BASE, cookies=jar, timeout=20) as client:
            resp = await client.post(
                "/influencer/linktrees_v1/uploadImg",
                files={"file": ("product.jpg", img_bytes, "image/jpeg")},
                data={"id": link_id},
            )
            try:
                img_result = resp.json()
            except Exception:
                img_result = {}
            if img_result.get("code") == 200 or resp.status_code == 200:
                print(f"[c8ke] Image uploaded for link {link_id}")
    except Exception as e:
        print(f"[c8ke] Image upload error: {e}")
