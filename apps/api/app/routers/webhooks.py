import json
import logging
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.core.security import verify_tiktok_signature
from app.models import WebhookEvent
from app.routers.auth_errors import AuthErrorOut
from app.services.webhooks import handle_event, record_event

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
log = logging.getLogger(__name__)


class WebhookOut(BaseModel):
    ok: Literal[True]
    duplicate: bool = False


@router.post("/tiktok", response_model=WebhookOut, responses={
    400: {"model": AuthErrorOut, "description": "invalid_webhook_payload"},
    401: {"model": AuthErrorOut, "description": "bad_signature"},
    503: {"model": AuthErrorOut, "description": "webhook_not_configured"},
})
async def tiktok_webhook(request: Request, tiktok_signature: str = Header(default=""),
                         session: AsyncSession = Depends(get_session),
                         settings: Settings = Depends(get_settings)):
    """Single endpoint for payment + subscription events. Configure this URL in the Dev Portal."""
    raw = await request.body()
    if not settings.tiktok_client_secret.strip():
        raise HTTPException(503, "webhook_not_configured")
    if not verify_tiktok_signature(raw, tiktok_signature, settings.tiktok_client_secret,
                                   settings.webhook_tolerance_seconds):
        raise HTTPException(401, "bad_signature")
    try:
        envelope = json.loads(raw)
        if not isinstance(envelope, dict) or not isinstance(envelope.get("event"), str) or not envelope["event"]:
            raise ValueError("missing event")
        content = envelope.get("content", {})
        if isinstance(content, str):
            content = json.loads(content)
        if not isinstance(content, dict):
            raise ValueError("invalid content")
    except (ValueError, UnicodeError):
        raise HTTPException(400, "invalid_webhook_payload") from None
    row, content = await record_event(session, envelope)
    if row is None:
        return {"ok": True, "duplicate": True}
    event_id = row.id
    try:
        await handle_event(session, row, content)
    except Exception as e:  # keep 200 so TikTok doesn't hammer; row stays unprocessed for the retry job
        await session.rollback()
        row = await session.scalar(select(WebhookEvent).where(WebhookEvent.id == event_id).with_for_update()
                                   .execution_options(populate_existing=True))
        if row is not None and row.processed_at is None:
            row.error = type(e).__name__
            await session.commit()
            log.warning("webhook %s failed: %s", row.event, row.error)
    return {"ok": True}
