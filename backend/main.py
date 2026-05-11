import asyncio
import os
import uuid
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from awin import generate_awin_link, refresh_merchants
from c8ke_client import add_to_c8ke
from image_gen import generate_carousel
from scraper import scrape_product

app = FastAPI(title="LinkDeal")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

JOBS: dict = {}
GENERATED_DIR = Path(__file__).parent.parent / "generated"


# ── Models ────────────────────────────────────────────────────────────────────

class ScrapeRequest(BaseModel):
    url: str


class ProcessRequest(BaseModel):
    url: str
    phrase: str
    current_price: str
    original_price: str
    image_urls: list[str] = []


# ── Routes ────────────────────────────────────────────────────────────────────

@app.post("/api/scrape")
async def scrape(req: ScrapeRequest):
    try:
        return await scrape_product(req.url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/process")
async def process(req: ProcessRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())[:8]
    JOBS[job_id] = {"status": "processing"}

    awin_link = await generate_awin_link(req.url)
    tweet_text = f"{req.phrase}\n\n{req.current_price}€ au lieu de {req.original_price}€\n\nLien : {awin_link}"
    twitter_url = f"https://twitter.com/intent/tweet?text={quote(tweet_text)}"

    background_tasks.add_task(_bg_process, job_id, req, awin_link)

    return {
        "job_id": job_id,
        "awin_link": awin_link,
        "tweet_text": tweet_text,
        "twitter_url": twitter_url,
    }


@app.get("/api/job/{job_id}")
async def get_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/api/image/{job_id}/{filename}")
async def get_image(job_id: str, filename: str):
    path = GENERATED_DIR / job_id / filename
    if not path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(str(path), media_type="image/jpeg")


@app.get("/api/refresh-merchants")
async def api_refresh_merchants():
    try:
        cache = await refresh_merchants()
        return {"ok": True, "count": len(cache)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Background task ───────────────────────────────────────────────────────────

async def _bg_process(job_id: str, req: ProcessRequest, awin_link: str):
    try:
        product = await scrape_product(req.url)
        # Use manually provided images if scraping returned none
        if req.image_urls:
            product["image_urls"] = req.image_urls

        cover_image = product["image_urls"][0] if product.get("image_urls") else None

        c8ke_title = f"{req.phrase} — {req.current_price}€ au lieu de {req.original_price}€"
        print(f"[c8ke] Sending title={c8ke_title!r} url={awin_link!r}")
        c8ke_task = asyncio.create_task(add_to_c8ke(c8ke_title, awin_link, cover_image))
        carousel_task = asyncio.create_task(
            generate_carousel(product, req.phrase, req.current_price, req.original_price, awin_link, job_id)
        )

        c8ke_ok, image_paths = await asyncio.gather(c8ke_task, carousel_task)

        JOBS[job_id] = {
            "status": "done",
            "images": [f"/api/image/{job_id}/{Path(p).name}" for p in image_paths],
            "c8ke_ok": c8ke_ok,
            "awin_link": awin_link,
        }

    except Exception as e:
        JOBS[job_id] = {"status": "error", "error": str(e)}


# ── Static frontend ───────────────────────────────────────────────────────────

frontend_dir = Path(__file__).parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
