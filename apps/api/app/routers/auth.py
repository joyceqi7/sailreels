from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, StringConstraints
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.core.security import current_open_id, issue_session
from app.models import User
from app.routers.auth_errors import AUTH_RESPONSES, auth_failure
from app.routers.deps import get_tiktok
from app.services.auth import LoginRequired, ensure_fresh_token, fetch_profile, login_with_code
from app.tiktok.client import TikTokAPIError, TikTokClient

router = APIRouter(prefix="/auth", tags=["auth"], responses=AUTH_RESPONSES)


class LoginIn(BaseModel):
    code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2048, strict=True)]


class LoginOut(BaseModel):
    token: str
    open_id: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_in: int


class ProfileOut(BaseModel):
    open_id: str
    nickname: str | None
    avatar_url: str | None


@router.post("/login", response_model=LoginOut)
async def login(body: LoginIn, response: Response, session: AsyncSession = Depends(get_session),
                tiktok: TikTokClient = Depends(get_tiktok), settings: Settings = Depends(get_settings)):
    try:
        user = await login_with_code(session, tiktok, body.code)
    except (TikTokAPIError, httpx.HTTPError) as e:
        raise auth_failure(e, login=True) from e
    response.headers["Cache-Control"] = "no-store"
    return LoginOut(token=issue_session(user.open_id, settings), open_id=user.open_id,
                    expires_in=settings.session_ttl_seconds)


@router.post("/authorize", response_model=ProfileOut)
async def authorize(open_id: str = Depends(current_open_id), session: AsyncSession = Depends(get_session),
                    tiktok: TikTokClient = Depends(get_tiktok)):
    """Call after TTMinis.authorize() succeeds. Uses the stored access_token to fetch nickname/avatar."""
    user = await session.get(User, open_id)
    if user is None:
        raise HTTPException(401, "login_required")
    try:
        info = await fetch_profile(session, tiktok, user)
    except (LoginRequired, TikTokAPIError, httpx.HTTPError) as e:
        raise auth_failure(e) from e
    user.nickname, user.avatar_url = info.get("display_name"), info.get("avatar_url")
    await session.commit()
    return ProfileOut(open_id=open_id, nickname=user.nickname, avatar_url=user.avatar_url)


@router.get("/me", response_model=ProfileOut)
async def me(open_id: str = Depends(current_open_id), session: AsyncSession = Depends(get_session),
             tiktok: TikTokClient = Depends(get_tiktok)):
    user = await session.get(User, open_id)
    if user is None:
        raise HTTPException(401, "login_required")
    try:
        await ensure_fresh_token(session, tiktok, user)
    except (LoginRequired, TikTokAPIError, httpx.HTTPError) as e:
        raise auth_failure(e) from e
    return ProfileOut(open_id=open_id, nickname=user.nickname, avatar_url=user.avatar_url)
