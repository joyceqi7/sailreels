import base64
import hashlib
import hmac
import json
import time
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.core.security import issue_session, read_session
from app.main import app
from app.models import User
from app.routers.deps import get_tiktok
from app.services.auth import ensure_fresh_token
from app.tiktok.client import TikTokClient

TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
PROFILE_URL = "https://open.tiktokapis.com/v2/user/info/"


def tokens(**overrides):
    return {"open_id": "u1", "access_token": "private-access", "refresh_token": "private-refresh",
            "expires_in": 86400, "refresh_expires_in": 31536000, "scope": "user.info.basic", **overrides}


@pytest.fixture
async def tiktok(client):
    t = TikTokClient(get_settings())
    app.dependency_overrides[get_tiktok] = lambda: t
    yield t
    await t.http.aclose()


async def seed_user(sessionmaker, *, access_seconds=86400, refresh_seconds=31536000):
    async with sessionmaker() as session:
        now = datetime.now(UTC)
        session.add(User(open_id="u1", access_token="old-access", refresh_token="old-refresh",
                         access_expires_at=now + timedelta(seconds=access_seconds),
                         refresh_expires_at=now + timedelta(seconds=refresh_seconds)))
        await session.commit()


def auth():
    return {"Authorization": f"Bearer {issue_session('u1', get_settings())}"}


async def test_login_exchanges_code_and_persists_private_credentials(client, tiktok, sessionmaker, respx_mock):
    route = respx_mock.post(TOKEN_URL).respond(200, json=tokens())
    before = datetime.now(UTC)
    response = await client.post("/api/v1/auth/login", json={"code": "one-time-code"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["open_id"] == "u1" and body["token_type"] == "Bearer"
    assert body["expires_in"] == get_settings().session_ttl_seconds
    assert read_session(body["token"], get_settings()) == "u1"
    assert "private-access" not in response.text and "private-refresh" not in response.text
    request = route.calls[0].request
    form = dict(httpx.QueryParams(request.content.decode()))
    assert request.headers["content-type"].startswith("application/x-www-form-urlencoded")
    assert form == {"code": "one-time-code", "grant_type": "authorization_code",
                    "client_key": "test_key", "client_secret": "test_secret"}
    async with sessionmaker() as session:
        user = await session.get(User, "u1")
        assert (user.access_token, user.refresh_token) == ("private-access", "private-refresh")
        assert user.access_expires_at.replace(tzinfo=UTC) >= before + timedelta(seconds=86400)
        assert user.refresh_expires_at.replace(tzinfo=UTC) >= before + timedelta(seconds=31536000)


async def test_relogin_updates_existing_user(client, tiktok, sessionmaker, respx_mock):
    await seed_user(sessionmaker)
    respx_mock.post(TOKEN_URL).respond(200, json=tokens())
    assert (await client.post("/api/v1/auth/login", json={"code": "new-code"})).status_code == 200
    async with sessionmaker() as session:
        assert (await session.get(User, "u1")).access_token == "private-access"


@pytest.mark.parametrize("code", ["", "  ", 123, None, "x" * 2049])
async def test_invalid_code_is_rejected_before_provider(client, tiktok, respx_mock, code):
    route = respx_mock.post(TOKEN_URL).respond(200, json=tokens())
    assert (await client.post("/api/v1/auth/login", json={"code": code})).status_code == 422
    assert not route.called


@pytest.mark.parametrize("error,status,detail", [
    ("invalid_grant", 400, "invalid_login_code"),
    ("invalid_client", 503, "auth_not_configured"),
    ("server_error", 502, "tiktok_unavailable"),
])
async def test_login_provider_errors_are_sanitized(client, tiktok, respx_mock, error, status, detail):
    route = respx_mock.post(TOKEN_URL).respond(400, json={"error": error, "access_token": "do-not-expose"})
    response = await client.post("/api/v1/auth/login", json={"code": "code"})
    assert response.status_code == status and response.json() == {"detail": detail}
    assert "do-not-expose" not in response.text
    assert route.call_count == 1  # Never replay a one-time authorization code.


async def test_code_replay_does_not_issue_another_session(client, tiktok, respx_mock):
    route = respx_mock.post(TOKEN_URL).mock(side_effect=[
        httpx.Response(200, json=tokens()), httpx.Response(400, json={"error": "invalid_grant"}),
    ])
    assert (await client.post("/api/v1/auth/login", json={"code": "same-code"})).status_code == 200
    response = await client.post("/api/v1/auth/login", json={"code": "same-code"})
    assert response.status_code == 400 and "token" not in response.json()
    assert route.call_count == 2


@pytest.mark.parametrize("failure,status", [(httpx.ReadTimeout, 504), (httpx.ConnectError, 502)])
async def test_network_failure_does_not_retry_login(client, tiktok, respx_mock, failure, status):
    route = respx_mock.post(TOKEN_URL).mock(side_effect=failure("provider failure"))
    assert (await client.post("/api/v1/auth/login", json={"code": "code"})).status_code == status
    assert route.call_count == 1


@pytest.mark.parametrize("body", [{}, {"open_id": "u1"}, tokens(open_id=""), tokens(expires_in=0)])
async def test_malformed_provider_token_is_not_persisted(client, tiktok, sessionmaker, respx_mock, body):
    respx_mock.post(TOKEN_URL).respond(200, json=body)
    assert (await client.post("/api/v1/auth/login", json={"code": "code"})).status_code == 502
    async with sessionmaker() as session:
        assert await session.get(User, "u1") is None


async def test_valid_token_needs_no_refresh(client, tiktok, sessionmaker, respx_mock):
    await seed_user(sessionmaker)
    route = respx_mock.post(TOKEN_URL).respond(200, json=tokens())
    assert (await client.get("/api/v1/auth/me", headers=auth())).status_code == 200
    assert not route.called


async def test_near_expiry_rotates_both_tokens(client, tiktok, sessionmaker, respx_mock):
    await seed_user(sessionmaker, access_seconds=60)
    route = respx_mock.post(TOKEN_URL).respond(200, json=tokens())
    assert (await client.get("/api/v1/auth/me", headers=auth())).status_code == 200
    assert dict(httpx.QueryParams(route.calls[0].request.content.decode()))["refresh_token"] == "old-refresh"
    async with sessionmaker() as session:
        user = await session.get(User, "u1")
        assert (user.access_token, user.refresh_token) == ("private-access", "private-refresh")


@pytest.mark.parametrize("stale_refresh_seconds", [-60, 86400])
async def test_stale_worker_reloads_tokens_before_refresh(tiktok, sessionmaker, respx_mock, stale_refresh_seconds):
    await seed_user(sessionmaker)  # Represents credentials already rotated by another worker.
    route = respx_mock.post(TOKEN_URL).respond(200, json=tokens())
    stale = User(open_id="u1", access_token="stale-access", refresh_token="stale-refresh",
                 access_expires_at=datetime.now(UTC),
                 refresh_expires_at=datetime.now(UTC) + timedelta(seconds=stale_refresh_seconds))
    async with sessionmaker() as session:
        assert await ensure_fresh_token(session, tiktok, stale) == "old-access"
    assert not route.called


async def test_expired_refresh_returns_401_without_provider(client, tiktok, sessionmaker, respx_mock):
    await seed_user(sessionmaker, refresh_seconds=-1)
    route = respx_mock.post(TOKEN_URL).respond(200, json=tokens())
    response = await client.get("/api/v1/auth/me", headers=auth())
    assert response.status_code == 401 and response.json() == {"detail": "login_required"}
    assert response.headers["www-authenticate"] == "Bearer"
    assert not route.called


@pytest.mark.parametrize("error,status", [("invalid_grant", 401), ("server_error", 502), ("invalid_client", 503)])
async def test_refresh_failure_preserves_credentials(client, tiktok, sessionmaker, respx_mock, error, status):
    await seed_user(sessionmaker, access_seconds=60)
    respx_mock.post(TOKEN_URL).respond(400, json={"error": error})
    response = await client.get("/api/v1/auth/me", headers=auth())
    assert response.status_code == status
    async with sessionmaker() as session:
        assert (await session.get(User, "u1")).refresh_token == "old-refresh"


async def test_refresh_cannot_change_identity(client, tiktok, sessionmaker, respx_mock):
    await seed_user(sessionmaker, access_seconds=60)
    respx_mock.post(TOKEN_URL).respond(200, json=tokens(open_id="other-user"))
    assert (await client.get("/api/v1/auth/me", headers=auth())).status_code == 502
    async with sessionmaker() as session:
        assert (await session.get(User, "u1")).access_token == "old-access"


async def test_authorize_retries_read_once_after_platform_401(client, tiktok, sessionmaker, respx_mock):
    await seed_user(sessionmaker)
    profile = respx_mock.get(PROFILE_URL).mock(side_effect=[
        httpx.Response(401, json={"error": {"code": "access_token_invalid"}}),
        httpx.Response(200, json={"data": {"user": {"open_id": "u1", "display_name": "Joyce"}},
                                 "error": {"code": "ok"}}),
    ])
    refresh = respx_mock.post(TOKEN_URL).respond(200, json=tokens())
    response = await client.post("/api/v1/auth/authorize", headers=auth())
    assert response.status_code == 200 and response.json()["nickname"] == "Joyce"
    assert profile.call_count == 2 and refresh.call_count == 1
    assert profile.calls[1].request.headers["authorization"] == "Bearer private-access"


async def test_platform_401_after_refresh_does_not_loop(client, tiktok, sessionmaker, respx_mock):
    await seed_user(sessionmaker)
    profile = respx_mock.get(PROFILE_URL).respond(401, json={"error": {"code": "access_token_invalid"}})
    refresh = respx_mock.post(TOKEN_URL).respond(200, json=tokens())
    assert (await client.post("/api/v1/auth/authorize", headers=auth())).status_code == 401
    assert profile.call_count == 2 and refresh.call_count == 1


@pytest.mark.parametrize("authorization", ["", "Basic abc", "Bearer broken", "Bearer a.b", "Bearer " + "x" * 5000])
async def test_invalid_session_is_401(client, authorization):
    response = await client.get("/api/v1/auth/me", headers={"Authorization": authorization})
    assert response.status_code == 401


@pytest.mark.parametrize("payload", [[], {}, {"sub": "u1", "exp": "tomorrow"},
                                   {"sub": "u1", "exp": True}, {"sub": 1, "exp": int(time.time()) + 60},
                                   {"sub": "u1", "exp": int(time.time())}])
async def test_signed_malformed_session_is_401(client, payload):
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    signature = hmac.new(get_settings().session_secret.encode(), encoded.encode(), hashlib.sha256).digest()
    token = encoded + "." + base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    assert (await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})).status_code == 401


def test_openapi_auth_contract_has_bearer_and_no_private_token_fields():
    schema = app.openapi()
    assert schema["info"]["version"] == "1.0.0"
    assert schema["components"]["securitySchemes"]["SessionBearer"]["scheme"] == "bearer"
    me = schema["paths"]["/api/v1/auth/me"]["get"]
    assert me["security"] == [{"SessionBearer": []}]
    assert "401" in me["responses"] and "504" in me["responses"]
    login = schema["paths"]["/api/v1/auth/login"]["post"]
    assert "security" not in login
    fields = schema["components"]["schemas"]["LoginOut"]["properties"]
    assert set(fields) == {"token", "open_id", "token_type", "expires_in"}


def test_staging_requires_a_private_signing_secret():
    with pytest.raises(ValidationError, match="SESSION_SECRET"):
        Settings(_env_file=None, env="staging", session_secret="change-me")
    assert Settings(_env_file=None, env="staging", session_secret="x" * 32).env == "staging"
