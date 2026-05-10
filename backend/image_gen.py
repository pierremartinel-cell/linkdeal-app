import asyncio
import io
import os
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFont

ASSETS_DIR = Path(__file__).parent.parent / "assets"
GENERATED_DIR = Path(__file__).parent.parent / "generated"
GENERATED_DIR.mkdir(exist_ok=True)

CARD_W = 1080
CARD_H = 1350

BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
GRAY = (110, 118, 125)
BLUE = (29, 155, 240)
GREEN = (27, 120, 82)


def _find_font() -> str | None:
    candidates = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/SFNS.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


FONT_PATH = _find_font()


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if FONT_PATH:
        try:
            return ImageFont.truetype(FONT_PATH, size)
        except Exception:
            pass
    return ImageFont.load_default()


async def _download_image(url: str) -> Image.Image | None:
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            return Image.open(io.BytesIO(resp.content)).convert("RGBA")
    except Exception:
        return None


def _circle_crop(img: Image.Image, size: int) -> Image.Image:
    img = img.resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
    result = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    result.paste(img, (0, 0), mask)
    return result


def _make_avatar(size: int) -> Image.Image:
    logo_path = ASSETS_DIR / "logo.png"
    if logo_path.exists():
        try:
            return _circle_crop(Image.open(logo_path).convert("RGBA"), size)
        except Exception:
            pass
    # Fallback: green circle with "LD"
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse((0, 0, size, size), fill=GREEN)
    f = _font(size // 3)
    draw.text((size // 2, size // 2), "LD", fill=WHITE, font=f, anchor="mm")
    return img


def _tweet_html(
    phrase: str,
    current_price: str,
    original_price: str,
    awin_link: str,
    avatar_b64: str,
    img1_b64: str,
    img2_b64: str,
) -> str:
    short_link = awin_link if len(awin_link) <= 42 else awin_link[:39] + "…"
    tweet_body = f"{phrase}\n\n{current_price}€ au lieu de {original_price}€\n\nLien : {short_link}"
    lines_html = "".join(
        f'<div class="tline">{line if line else "&nbsp;"}</div>'
        for line in tweet_body.split("\n")
    )
    img_section = ""
    if img1_b64 and img2_b64:
        img_section = f'''<div class="imgs two">
  <img src="data:image/jpeg;base64,{img1_b64}">
  <img src="data:image/jpeg;base64,{img2_b64}">
</div>'''
    elif img1_b64:
        img_section = f'<div class="imgs one"><img src="data:image/jpeg;base64,{img1_b64}"></div>'

    avatar_src = f"data:image/png;base64,{avatar_b64}" if avatar_b64 else ""
    avatar_html = f'<img class="ava" src="{avatar_src}">' if avatar_src else '<div class="ava ava-fallback">LD</div>'

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  background: #000;
  font-family: -apple-system, "Helvetica Neue", Arial, sans-serif;
  width: 540px;
  padding: 0;
}}
.tweet {{
  background: #000;
  border: 1px solid #2f3336;
  border-radius: 16px;
  padding: 16px 16px 0;
  overflow: hidden;
}}
.header {{
  display: flex;
  align-items: flex-start;
  margin-bottom: 12px;
}}
.ava {{
  width: 48px; height: 48px;
  border-radius: 50%;
  object-fit: cover;
  flex-shrink: 0;
  background: #1b7852;
}}
.ava-fallback {{
  width: 48px; height: 48px;
  border-radius: 50%;
  background: #1b7852;
  color: #fff;
  font-size: 16px;
  font-weight: 700;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
}}
.userinfo {{ flex: 1; margin-left: 10px; line-height: 1.3; }}
.name-row {{ display: flex; align-items: center; gap: 4px; }}
.name {{ font-size: 15px; font-weight: 700; color: #fff; }}
.badge {{
  width: 18px; height: 18px;
  background: #1d9bf0;
  border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  font-size: 10px; color: #fff; font-weight: 700;
}}
.handle {{ font-size: 14px; color: #71767b; }}
.x-logo {{
  margin-left: auto;
  font-size: 22px;
  color: #fff;
  font-weight: 900;
  letter-spacing: -1px;
  line-height: 1;
  padding-top: 2px;
}}
.body {{ font-size: 17px; color: #e7e9ea; line-height: 1.5; margin-bottom: 12px; }}
.tline {{ min-height: 1.5em; }}
.body a, .link {{ color: #1d9bf0; text-decoration: none; }}
.imgs {{ border-radius: 14px; overflow: hidden; margin-bottom: 12px; }}
.imgs.two {{ display: grid; grid-template-columns: 1fr 1fr; gap: 3px; height: 280px; }}
.imgs.two img {{ width: 100%; height: 100%; object-fit: cover; }}
.imgs.one {{ height: 300px; }}
.imgs.one img {{ width: 100%; height: 100%; object-fit: cover; }}
.meta {{ font-size: 14px; color: #71767b; padding: 12px 0 10px; border-top: 1px solid #2f3336; }}
.meta span {{ color: #e7e9ea; }}
.sep {{ height: 1px; background: #2f3336; margin: 0 -16px; }}
.stats {{ display: flex; gap: 20px; padding: 10px 0; font-size: 14px; color: #71767b; }}
.stats b {{ color: #e7e9ea; }}
.sep2 {{ height: 1px; background: #2f3336; margin: 0 -16px; }}
.actions {{
  display: flex; justify-content: space-around;
  padding: 12px 0 14px;
  color: #71767b; font-size: 22px;
}}
</style>
</head>
<body>
<div class="tweet">
  <div class="header">
    {avatar_html}
    <div class="userinfo">
      <div class="name-row">
        <span class="name">LinkDeal</span>
        <div class="badge">✓</div>
      </div>
      <div class="handle">@LinkDeal_</div>
    </div>
    <div class="x-logo">𝕏</div>
  </div>
  <div class="body">{lines_html}</div>
  {img_section}
  <div class="meta">10:28 · 7 mai 2025 · <span>12,4K</span> vues</div>
  <div class="sep"></div>
  <div class="stats">
    <span><b>247</b> Retweets</span>
    <span><b>18</b> Citations</span>
    <span><b>1 842</b> J'aime</span>
    <span><b>312</b> Signets</span>
  </div>
  <div class="sep2"></div>
  <div class="actions">
    <span>💬</span><span>🔁</span><span>🤍</span><span>🔖</span><span>⬆️</span>
  </div>
</div>
</body>
</html>"""


async def _screenshot_tweet(html: str, out_path: str):
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 540, "height": 800})
        await page.set_content(html, wait_until="networkidle")
        elem = await page.query_selector(".tweet")
        await elem.screenshot(path=out_path, type="jpeg", quality=95)
        await browser.close()


async def generate_carousel(
    product: dict,
    phrase: str,
    current_price: str,
    original_price: str,
    awin_link: str,
    job_id: str,
) -> list[str]:
    import base64

    job_dir = GENERATED_DIR / job_id
    job_dir.mkdir(exist_ok=True)

    # Download product images in parallel
    image_urls = product.get("image_urls", [])[:4]
    tasks = [_download_image(u) for u in image_urls]
    product_images = [img for img in await asyncio.gather(*tasks) if img]

    paths = []

    # Encode first 2 product images as base64 for HTML embedding
    def _to_b64(img: Image.Image | None) -> str:
        if not img:
            return ""
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=85)
        return base64.b64encode(buf.getvalue()).decode()

    img1_b64 = _to_b64(product_images[0] if len(product_images) > 0 else None)
    img2_b64 = _to_b64(product_images[1] if len(product_images) > 1 else None)

    # Avatar as base64
    avatar_b64 = ""
    logo_path = ASSETS_DIR / "logo.png"
    if logo_path.exists():
        try:
            buf = io.BytesIO()
            Image.open(logo_path).convert("RGB").save(buf, "PNG")
            avatar_b64 = base64.b64encode(buf.getvalue()).decode()
        except Exception:
            pass

    # Slide 1: tweet card via Playwright screenshot
    tweet_path = str(job_dir / "01_tweet.jpg")
    html = _tweet_html(phrase, current_price, original_price, awin_link, avatar_b64, img1_b64, img2_b64)
    await _screenshot_tweet(html, tweet_path)

    # Crop/resize to 1080x1350 (TikTok format)
    raw = Image.open(tweet_path)
    slide1 = Image.new("RGB", (CARD_W, CARD_H), BLACK)
    raw_rgb = raw.convert("RGB")
    ratio = CARD_W / raw_rgb.width
    resized = raw_rgb.resize((CARD_W, int(raw_rgb.height * ratio)), Image.LANCZOS)
    y_off = (CARD_H - resized.height) // 2
    slide1.paste(resized, (0, max(0, y_off)))
    slide1.save(tweet_path, "JPEG", quality=95)
    paths.append(tweet_path)

    # Slides 2-4: individual product images on black background
    for idx, img in enumerate(product_images[:3], start=2):
        slide = Image.new("RGB", (CARD_W, CARD_H), BLACK)
        im = img.convert("RGB")
        im.thumbnail((CARD_W, CARD_H), Image.LANCZOS)
        x_off = (CARD_W - im.width) // 2
        y_off = (CARD_H - im.height) // 2
        slide.paste(im, (x_off, y_off))
        p = str(job_dir / f"0{idx}_product.jpg")
        slide.save(p, "JPEG", quality=95)
        paths.append(p)

    return paths
