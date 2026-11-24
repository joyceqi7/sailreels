"""Session tokens between our frontend and our API, plus TikTok webhook verification."""

import base64
import binascii
import hashlib
import hmac
import json
import time

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.config import Settings, get_settings

bearer = HTTPBearer(auto_error=False, scheme_name="SessionBearer",
                    description="Session token from POST /api/v1/auth/login")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def issue_session(open_id: str, settings: Settings) -> str:
    payload = _b64(json.dumps({"sub": open_id, "exp": int(time.time()) + settings.session_ttl_seconds}).encode())
    sig = _b64(hmac.new(settings.session_secret.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{sig}"


def read_session(token: str, settings: Settings) -> str | None:
    if len(token) > 4096:
        return None
    try:
        payload, sig = token.split(".", 1)
    except ValueError:
        return None
    expected = _b64(hmac.new(settings.session_secret.encode(), payload.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(expected, sig):
        return None
    try:
        data = json.loads(_unb64(payload))
    except (ValueError, UnicodeError, binascii.Error):
        return None
    if not isinstance(data, dict):
        return None
    expires = data.get("exp")
    subject = data.get("sub")
    if not isinstance(expires, int) or isinstance(expires, bool) or expires <= time.time():
        return None
    if not isinstance(subject, str) or not subject.strip() or len(subject) > 128:
        return None
    return subject


async def current_open_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer), settings: Settings = Depends(get_settings)
) -> str:
    token = credentials.credentials if credentials else ""
    open_id = read_session(token, settings) if token else None
    if not open_id:
        # Frontend reacts to 401 by re-running TTMinis.login().
        raise HTTPException(status_code=401, detail="login_required", headers={"WWW-Authenticate": "Bearer"})
    return open_id


def verify_tiktok_signature(raw_body: bytes, header: str, client_secret: str, tolerance: int) -> bool:
    """TikTok-Signature: t=<unix>,s=<hex hmac_sha256(client_secret, f"{t}.{body}")>.

    Ref: https://developers.tiktok.com/doc/webhooks-verification
    """
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    t, s = parts.get("t", "").strip(), parts.get("s", "").strip()
    if not t.isdigit() or not s:
        return False
    if abs(time.time() - int(t)) > tolerance:
        return False
    signed = t.encode() + b"." + raw_body
    expected = hmac.new(client_secret.encode(), signed, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, s)
