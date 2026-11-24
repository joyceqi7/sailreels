"""Public legal pages (no auth). Served at the site root, not under /api/v1, and kept out of the OpenAPI
contract: they are documents for people and for TikTok's reviewers, not API endpoints."""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.legal import PRIVACY_HTML, TERMS_HTML

router = APIRouter(include_in_schema=False)

# Static content; let Caddy/clients cache briefly so a policy edit shows up within the hour.
_HEADERS = {"Cache-Control": "public, max-age=3600"}


@router.get("/privacy", response_class=HTMLResponse)
async def privacy() -> HTMLResponse:
    return HTMLResponse(PRIVACY_HTML, headers=_HEADERS)


@router.get("/terms", response_class=HTMLResponse)
async def terms() -> HTMLResponse:
    return HTMLResponse(TERMS_HTML, headers=_HEADERS)
