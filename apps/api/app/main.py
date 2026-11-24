import logging
from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.core.config import get_settings
from app.routers import account, auth, catalog, legal, monetization, subscriptions, webhooks

logging.basicConfig(level=logging.INFO)
settings = get_settings()

app = FastAPI(title="SailReels API", version="1.0.0", description=(
    "OpenAPI contract v1. User APIs use the backend SessionBearer token; TikTok credentials stay server-side. "
    "Payment and subscription results are confirmed by verified webhooks, never client callbacks."
))
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    # The mini page is served by TikTok, not by us, so its origin must be allowed for our API calls
    # to pass the browser's CORS check. Starlette regex-matches the origin with re.fullmatch.
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

API = "/api/v1"
app.include_router(auth.router, prefix=API)
app.include_router(catalog.router, prefix=API)
app.include_router(monetization.router, prefix=API)
app.include_router(subscriptions.router, prefix=API)
app.include_router(account.router, prefix=API)
app.include_router(webhooks.router, prefix=API)
app.include_router(legal.router)  # /privacy, /terms — ppLink/tosLink in minis.config.json


class HealthOut(BaseModel):
    ok: Literal[True]
    env: str


@app.get("/healthz", response_model=HealthOut)
async def healthz():
    return {"ok": True, "env": settings.env}
