import httpx
import json
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from playwright.async_api import async_playwright


HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
}

SKIP_IMAGE_PATTERNS = [
    "logo", "icon", "avatar", "badge", "sprite", "pixel",
    "tracking", "banner", "header", "footer", "nav", "social", "flag",
]


# ── Price helpers ─────────────────────────────────────────────────────────────

def _clean_price(value: str) -> str:
    if not value:
        return ""
    cleaned = re.sub(r"[^\d.,]", "", str(value))
    cleaned = cleaned.replace(",", ".")
    parts = cleaned.split(".")
    if len(parts) > 2:
        cleaned = parts[0] + "." + "".join(parts[1:])
    if cleaned.endswith(".0") or cleaned.endswith(".00"):
        cleaned = cleaned.split(".")[0]
    return cleaned


def _best_price(candidates: list[str]) -> str:
    """Return the first non-empty, plausible price."""
    for c in candidates:
        p = _clean_price(str(c))
        if p and 1 <= float(p.replace(",", ".")) <= 10000:
            return p
    return ""


def _extract_prices_from_scripts(soup: BeautifulSoup) -> dict:
    """Scan embedded JSON/JS for price values."""
    current_keys = [
        "currentPrice", "salePrice", "sale_price", "sellingPrice",
        "finalPrice", "priceValue", "discountedPrice",
    ]
    original_keys = [
        "compareAtPrice", "regularPrice", "basePrice", "originalPrice",
        "original_price", "wasPrice", "listPrice", "strikethroughPrice",
        "fullPrice", "rrp",
    ]

    best_current = ""
    best_original = ""

    for script in soup.find_all("script"):
        text = script.string or ""
        if len(text) < 10:
            continue

        if not best_current:
            for key in current_keys:
                m = re.search(rf'["\']?{key}["\']?\s*[=:]\s*["\']?(\d+[.,]?\d*)["\'€]?', text, re.I)
                if m:
                    best_current = _clean_price(m.group(1))
                    break

        if not best_original:
            for key in original_keys:
                m = re.search(rf'["\']?{key}["\']?\s*[=:]\s*["\']?(\d+[.,]?\d*)["\'€]?', text, re.I)
                if m:
                    best_original = _clean_price(m.group(1))
                    break

        if best_current and best_original:
            break

    return {"current_price": best_current, "original_price": best_original}


# ── Image helpers ─────────────────────────────────────────────────────────────

def _is_product_image(url: str) -> bool:
    low = url.lower()
    return (
        url.startswith("http")
        and any(ext in low for ext in (".jpg", ".jpeg", ".png", ".webp"))
        and not any(pat in low for pat in SKIP_IMAGE_PATTERNS)
        and len(url) > 20
    )


def _dedupe(urls: list[str]) -> list[str]:
    seen, out = set(), []
    for u in urls:
        key = re.sub(r"[?#].*", "", u)
        if key not in seen:
            seen.add(key)
            out.append(u)
    return out


# ── Parsers ───────────────────────────────────────────────────────────────────

def _parse_jsonld(soup: BeautifulSoup) -> dict:
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            raw = script.string or script.get_text()
            data = json.loads(raw)
            if isinstance(data, list):
                data = next((d for d in data if d.get("@type") == "Product"), None)
                if not data:
                    continue
            if data.get("@type") != "Product":
                continue

            title = data.get("name", "")
            brand = ""
            if isinstance(data.get("brand"), dict):
                brand = data["brand"].get("name", "")
            elif isinstance(data.get("brand"), str):
                brand = data["brand"]

            images = []
            if "image" in data:
                imgs = data["image"]
                if isinstance(imgs, str):
                    imgs = [imgs]
                elif isinstance(imgs, dict):
                    imgs = [imgs.get("url", "")]
                images = [i for i in imgs if i and _is_product_image(i)][:6]

            current_price = ""
            original_price = ""
            if "offers" in data:
                offers = data["offers"]
                if isinstance(offers, list):
                    prices = sorted(
                        [float(o.get("price", 0) or 0) for o in offers if o.get("price")],
                    )
                    if prices:
                        current_price = _clean_price(str(prices[0]))
                    if len(prices) > 1:
                        original_price = _clean_price(str(prices[-1]))
                else:
                    current_price = _clean_price(str(offers.get("price", "")))
                    original_price = _clean_price(str(
                        data.get("highPrice", offers.get("highPrice", ""))
                    ))

            if title:
                return {
                    "title": title, "brand": brand,
                    "current_price": current_price, "original_price": original_price,
                    "image_urls": images,
                }
        except (json.JSONDecodeError, AttributeError, KeyError):
            continue
    return {}


def _parse_og(soup: BeautifulSoup) -> dict:
    def meta(prop):
        tag = soup.find("meta", property=prop) or soup.find("meta", attrs={"name": prop})
        return tag.get("content", "").strip() if tag else ""

    og_imgs = [
        t.get("content", "").strip()
        for t in soup.find_all("meta", property="og:image")
        if t.get("content")
    ]
    tw_img = meta("twitter:image")
    if tw_img and tw_img not in og_imgs:
        og_imgs.append(tw_img)

    return {
        "title": meta("og:title") or meta("twitter:title"),
        "brand": "",
        "current_price": _clean_price(meta("product:price:amount") or meta("og:price:amount")),
        "original_price": _clean_price(meta("product:original_price:amount")),
        "image_urls": [u for u in og_imgs if _is_product_image(u)],
    }


def _parse_microdata(soup: BeautifulSoup) -> dict:
    price_el = soup.find(attrs={"itemprop": "price"})
    current = ""
    if price_el:
        current = _clean_price(price_el.get("content") or price_el.get_text())
    return {"current_price": current, "original_price": ""}


def _extract_gallery_images(soup: BeautifulSoup, base_url: str) -> list[str]:
    found = []
    selectors = [
        "[class*='gallery'] img", "[class*='product-image'] img",
        "[class*='product-photo'] img", "[class*='product-media'] img",
        "[class*='pdp'] img", "[data-zoom-image]", "[data-large-image]",
        "img[data-src*='product']", "img[data-src*='goods']",
        "img[src*='product']", "img[src*='goods']",
    ]
    for sel in selectors:
        try:
            for tag in soup.select(sel)[:8]:
                for attr in ("data-zoom-image", "data-large-image", "data-src", "src"):
                    val = tag.get(attr, "")
                    if val and _is_product_image(val):
                        found.append(urljoin(base_url, val))
                        break
        except Exception:
            continue
    return found


# ── Playwright fallback ───────────────────────────────────────────────────────

async def _playwright_prices(url: str) -> dict:
    """Render page with JS and extract prices from DOM."""
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(
                viewport={"width": 390, "height": 844},
                user_agent=HEADERS["User-Agent"],
            )
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_timeout(3000)

            prices = await page.evaluate("""() => {
                const txt = el => (el?.textContent || el?.getAttribute('content') || '').trim();
                const num = s => { const m = s.replace(',','.').match(/(\\d+\\.?\\d*)/); return m ? m[1] : ''; };

                // Original / crossed-out price selectors
                const originalSels = [
                    '[class*="original-price"]','[class*="__original"]',
                    '[class*="was-price"]','[class*="compare-at"]',
                    '[class*="strike"]','[class*="crossed"]',
                    '[class*="regular-price"]','[class*="before-price"]',
                    '[class*="prix-barre"]','[class*="price--compare"]',
                    '[class*="price-before"]','[class*="price_before"]',
                    'del','s.price','s[class*="price"]',
                ];
                // Current / sale price selectors
                const currentSels = [
                    '[class*="sale-price"]','[class*="selling-price"]',
                    '[class*="current-price"]','[class*="price-sale"]',
                    '[class*="promo-price"]','[class*="prix-promo"]',
                    '[class*="price--sale"]','[class*="price-reduced"]',
                    '[class*="special-price"]','[class*="price_sale"]',
                    '[class*="price-text--large"]','[class*="price--current"]',
                    '[class*="price-text--c"]',
                    '[data-testid*="price"]','[itemprop="price"]',
                ];

                let current = '', original = '';

                for (const s of originalSels) {
                    const el = document.querySelector(s);
                    if (el) { original = num(txt(el)); if (original) break; }
                }
                for (const s of currentSels) {
                    const el = document.querySelector(s);
                    if (el) { current = num(txt(el)); if (current) break; }
                }

                // Fallback: collect all price-like elements and pick lowest as current
                if (!current) {
                    const allPriceEls = [...document.querySelectorAll('[class*="price"]')]
                        .filter(el => el.children.length === 0)  // leaf nodes only
                        .map(el => ({ val: parseFloat(num(txt(el))), text: txt(el) }))
                        .filter(p => p.val > 0 && p.val < 5000)
                        .sort((a, b) => a.val - b.val);

                    if (allPriceEls.length > 0) current = String(allPriceEls[0].val);
                    if (allPriceEls.length > 1 && !original) original = String(allPriceEls[allPriceEls.length - 1].val);
                }

                return { current, original };
            }""")

            await browser.close()
            return {
                "current_price": _clean_price(prices.get("current", "")),
                "original_price": _clean_price(prices.get("original", "")),
            }
    except Exception as e:
        print(f"[scraper] Playwright prices failed: {e}")
        return {}


# ── Main ──────────────────────────────────────────────────────────────────────

async def scrape_product(url: str) -> dict:
    # 1. Fetch raw HTML
    async with httpx.AsyncClient(follow_redirects=True, timeout=30, headers=HEADERS) as client:
        resp = await client.get(url)
        resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "lxml")

    # 2. JSON-LD (most reliable)
    data = _parse_jsonld(soup)

    # 3. Fill gaps from OG tags
    og = _parse_og(soup)
    if not data.get("title"):
        data["title"] = og["title"]
    if not data.get("current_price"):
        data["current_price"] = og["current_price"]
    if not data.get("original_price"):
        data["original_price"] = og["original_price"]
    if not data.get("brand"):
        data["brand"] = og.get("brand", "")

    # 4. Microdata fallback for price
    if not data.get("current_price"):
        md = _parse_microdata(soup)
        data["current_price"] = md["current_price"]

    # 5. Script tag JSON extraction
    if not data.get("current_price"):
        sc = _extract_prices_from_scripts(soup)
        if sc.get("current_price"):
            data["current_price"] = sc["current_price"]
        if not data.get("original_price") and sc.get("original_price"):
            data["original_price"] = sc["original_price"]

    # 6. Playwright JS rendering (last resort — handles most JS-heavy sites)
    if not data.get("current_price"):
        print(f"[scraper] No price found via static scraping, trying Playwright…")
        pw = await _playwright_prices(url)
        if pw.get("current_price"):
            data["current_price"] = pw["current_price"]
        if not data.get("original_price") and pw.get("original_price"):
            data["original_price"] = pw["original_price"]

    # 7. Merge images from all sources
    all_images = list(data.get("image_urls") or [])
    for img in og.get("image_urls", []):
        if img not in all_images:
            all_images.append(img)
    if len(all_images) < 3:
        gallery = _extract_gallery_images(soup, url)
        for img in gallery:
            if img not in all_images:
                all_images.append(img)
    data["image_urls"] = _dedupe(all_images)[:6]

    # 8. Brand fallback: extract from domain if not found elsewhere
    brand = data.get("brand", "").strip()
    if not brand:
        from urllib.parse import urlparse
        domain = urlparse(url).netloc.lower()
        domain = re.sub(r"^www\.", "", domain)
        domain = re.sub(r"\.(com|fr|co\.uk|de|es|it|nl|be|ch|ca|au|us).*$", "", domain)
        # Known multi-word brands
        KNOWN_BRANDS = {
            "thenorthface": "The North Face",
            "newbalance": "New Balance",
            "underarmour": "Under Armour",
            "calvinklein": "Calvin Klein",
            "tommyhilfiger": "Tommy Hilfiger",
            "ralphlauren": "Ralph Lauren",
        }
        brand = KNOWN_BRANDS.get(domain.replace("-", "").replace(".", ""), domain.title())

    # 9. Clean title and always include brand
    title = data.get("title", "")
    for sep in [" | ", " — ", " - "]:
        if sep in title:
            title = title.split(sep)[0].strip()
    if brand and brand.lower() not in title.lower():
        title = f"{title} {brand}"
    data["title"] = title.strip()
    data["brand"] = brand
    data["url"] = url
    return data
