"""Stable, sanitized errors for user authentication and token refresh."""

import httpx
from fastapi import HTTPException
from pydantic import BaseModel

from app.services.auth import LoginRequired
from app.tiktok.client import TikTokAPIError


class AuthErrorOut(BaseModel):
    detail: str


AUTH_RESPONSES = {
    code: {"model": AuthErrorOut, "description": description}
    for code, description in {
        400: "invalid_login_code: obtain a fresh one-time code; do not reuse it",
        401: "login_required: obtain a new Minis code and establish a new session",
        502: "tiktok_unavailable: upstream failure; do not trigger automatic re-login",
        503: "auth_not_configured: operator must check application credentials",
        504: "tiktok_timeout: upstream timeout; do not replay the same login code",
    }.items()
}


def auth_failure(error: Exception, *, login: bool = False) -> HTTPException:
    if isinstance(error, LoginRequired):
        return HTTPException(401, "login_required", headers={"WWW-Authenticate": "Bearer"})
    if isinstance(error, httpx.TimeoutException):
        return HTTPException(504, "tiktok_timeout")
    if isinstance(error, TikTokAPIError):
        if error.code in {"invalid_client", "unauthorized_client"}:
            return HTTPException(503, "auth_not_configured")
        if login and error.code in {"invalid_grant", "invalid_request"}:
            return HTTPException(400, "invalid_login_code")
    return HTTPException(502, "tiktok_unavailable")
