from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import httpx
import pytest
from celery.contrib.testing.worker import start_worker
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings, get_settings
from app.core.db import Base
from app.models import User
from app.tiktok.client import TikTokClient
from app.worker import tasks
from app.worker.celery_app import create_celery_app
from app.worker.tasks import refresh_user_token, scan_due_tokens
from app.worker.token_refresh import TokenRefreshTemporaryError, due_user_ids, refresh_one_user
from scripts.platform_handoff import portal_values
from tests.test_core_flows import sign

TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"


@pytest.fixture
def enabled(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "token_refresh_enabled", True)
    return settings


@pytest.fixture
async def tiktok():
    client = TikTokClient(get_settings())
    yield client
    await client.http.aclose()


async def add_user(sessions, open_id="u1", access_seconds=60, refresh_seconds=86400):
    async with sessions() as session:
        now = datetime.now(UTC)
        session.add(User(open_id=open_id, access_token="old-access", refresh_token="old-refresh",
                         access_expires_at=now + timedelta(seconds=access_seconds),
                         refresh_expires_at=now + timedelta(seconds=refresh_seconds)))
        await session.commit()


def token_response():
    return {"open_id": "u1", "access_token": "new-private-access", "refresh_token": "new-private-refresh",
            "expires_in": 86400, "refresh_expires_in": 31536000, "scope": "user.info.basic"}


async def test_scan_projects_only_due_users_and_respects_batch(sessionmaker, enabled, monkeypatch):
    await add_user(sessionmaker, "earliest", access_seconds=-60)
    await add_user(sessionmaker, "later", access_seconds=600)
    await add_user(sessionmaker, "fresh", access_seconds=86400)
    await add_user(sessionmaker, "expired-refresh", refresh_seconds=-60)
    monkeypatch.setattr(enabled, "token_refresh_batch_size", 1)
    assert await due_user_ids(sessionmaker, enabled) == ["earliest"]
    monkeypatch.setattr(enabled, "token_refresh_batch_size", 10)
    assert await due_user_ids(sessionmaker, enabled) == ["earliest", "later"]


async def test_paused_or_unconfigured_jobs_never_touch_resources(tiktok, enabled, monkeypatch):
    sessions = Mock(side_effect=AssertionError("Database must not be opened"))
    monkeypatch.setattr(enabled, "token_refresh_enabled", False)
    assert await due_user_ids(sessions, enabled) == []
    assert await refresh_one_user("u1", sessions, tiktok, enabled) == {"status": "skipped", "reason": "paused"}
    monkeypatch.setattr(enabled, "token_refresh_enabled", True)
    monkeypatch.setattr(enabled, "tiktok_client_secret", "")
    assert await due_user_ids(sessions, enabled) == []
    assert (await refresh_one_user("u1", sessions, tiktok, enabled))["reason"] == "credentials_missing"


async def test_worker_rotates_credentials_without_returning_them(sessionmaker, tiktok, enabled, respx_mock):
    await add_user(sessionmaker)
    route = respx_mock.post(TOKEN_URL).respond(200, json=token_response())
    result = await refresh_one_user("u1", sessionmaker, tiktok, enabled)
    assert result == {"status": "refreshed"}
    assert "private" not in str(result) and "refresh_token" not in str(result)
    async with sessionmaker() as session:
        user = await session.get(User, "u1")
        assert (user.access_token, user.refresh_token) == ("new-private-access", "new-private-refresh")
    # Redelivery / an overlapping beat scan must not rotate an already fresh token again.
    assert await refresh_one_user("u1", sessionmaker, tiktok, enabled) == {"status": "already_fresh"}
    assert route.call_count == 1


async def test_rejected_refresh_is_removed_from_future_scans(sessionmaker, tiktok, enabled, respx_mock):
    await add_user(sessionmaker)
    route = respx_mock.post(TOKEN_URL).respond(400, json={"error": "invalid_grant"})
    assert await refresh_one_user("u1", sessionmaker, tiktok, enabled) == {"status": "login_required"}
    assert await due_user_ids(sessionmaker, enabled) == []
    assert (await refresh_one_user("u1", sessionmaker, tiktok, enabled))["status"] == "login_required"
    assert route.call_count == 1


async def test_expired_refresh_and_missing_user_make_no_api_calls(sessionmaker, tiktok, enabled, respx_mock):
    await add_user(sessionmaker, refresh_seconds=-1)
    route = respx_mock.post(TOKEN_URL).respond(200, json=token_response())
    assert (await refresh_one_user("u1", sessionmaker, tiktok, enabled))["status"] == "login_required"
    assert (await refresh_one_user("missing", sessionmaker, tiktok, enabled))["reason"] == "user_missing"
    assert not route.called


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_temporary_provider_failure_preserves_tokens(sessionmaker, tiktok, enabled, respx_mock, status):
    await add_user(sessionmaker)
    respx_mock.post(TOKEN_URL).respond(status, json={"error": "server_error", "secret": "never-log-me"})
    with pytest.raises(TokenRefreshTemporaryError) as error:
        await refresh_one_user("u1", sessionmaker, tiktok, enabled)
    assert "never-log-me" not in str(error.value)
    async with sessionmaker() as session:
        assert (await session.get(User, "u1")).refresh_token == "old-refresh"


async def test_network_failure_is_retryable_and_sanitized(sessionmaker, tiktok, enabled, respx_mock):
    await add_user(sessionmaker)
    respx_mock.post(TOKEN_URL).mock(side_effect=httpx.ReadTimeout("may-contain-secret"))
    with pytest.raises(TokenRefreshTemporaryError, match="network failure") as error:
        await refresh_one_user("u1", sessionmaker, tiktok, enabled)
    assert "may-contain-secret" not in str(error.value)


async def test_bad_application_credentials_do_not_force_user_logout(sessionmaker, tiktok, enabled, respx_mock):
    await add_user(sessionmaker)
    respx_mock.post(TOKEN_URL).respond(400, json={"error": "invalid_client"})
    assert (await refresh_one_user("u1", sessionmaker, tiktok, enabled))["status"] == "configuration_error"
    assert await due_user_ids(sessionmaker, enabled) == ["u1"]


def test_celery_retries_temporary_failure_at_most_three_times(enabled, monkeypatch):
    attempts = 0

    async def fail(_operation):
        nonlocal attempts
        attempts += 1
        raise TokenRefreshTemporaryError("sanitized failure")

    monkeypatch.setattr(tasks, "_with_resources", fail)
    result = refresh_user_token.apply(args=("u1",), throw=False)
    assert result.failed() and attempts == 4  # Initial attempt plus three retries.
    assert isinstance(result.get(propagate=False), TokenRefreshTemporaryError)


def test_scanner_queues_only_user_ids_with_redacted_args(enabled, monkeypatch):
    async def users(_operation):
        return ["u1", "u2"]

    publish = Mock()
    monkeypatch.setattr(tasks, "_with_resources", users)
    monkeypatch.setattr(refresh_user_token, "apply_async", publish)
    assert scan_due_tokens.apply().get() == {"status": "queued", "queued": 2}
    assert publish.call_count == 2
    assert publish.call_args_list[0].kwargs == {"args": ("u1",), "argsrepr": "(<user>,)", "queue": "auth"}


def test_disabled_token_refresh_schedules_only_the_webhook_retry(monkeypatch):
    """With token refresh off, only the webhook retry sweep is scheduled.

    The retry sweep is unconditional on purpose: the webhook handler answers 200 even when applying
    an event fails, so a paid order would never be fulfilled without it. It performs no TikTok calls
    (app/services/webhooks.py is pure database work), so the paused period stays network-silent;
    token refresh itself remains off.
    """
    settings = get_settings()
    monkeypatch.setattr(settings, "token_refresh_enabled", False)
    app = create_celery_app(settings)
    assert set(app.conf.beat_schedule) == {"retry-unprocessed-webhooks"}
    assert scan_due_tokens.apply().get()["reason"] == "paused"
    assert refresh_user_token.apply(args=("u1",)).get()["reason"] == "paused"


def test_enabled_schedule_routes_to_auth_queue(enabled):
    app = create_celery_app(enabled)
    entry = app.conf.beat_schedule["scan-due-user-tokens"]
    assert entry["schedule"] == 300 and entry["options"]["queue"] == "auth"
    assert app.conf.accept_content == ["json"]
    assert app.conf.task_routes["sailreels.auth.*"]["queue"] == "auth"


@pytest.mark.parametrize("field,value", [("token_refresh_batch_size", 0), ("token_refresh_interval_seconds", 0),
                                      ("token_refresh_window_seconds", 4000)])
def test_invalid_worker_configuration_is_rejected(field, value):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{field: value})


def test_handoff_has_shared_https_callback_and_exact_event_set():
    values = portal_values("https://api-staging.example.com/")
    expected = "https://api-staging.example.com/api/v1/webhooks/tiktok"
    assert values["payment_webhook_url"] == values["subscription_webhook_url"] == expected
    assert len(values["webhook_events"]) == 10
    assert values["live_integration"] == "paused" and values["portal_configuration_verified"] is False
    assert "client_secret" not in str(values)


@pytest.mark.parametrize("origin", ["", "http://example.com", "https://user:password@example.com",
                                    "https://example.com/api/v1", "https://example.com?q=x",
                                    "https://localhost", "https://127.0.0.1", "https://10.0.0.1"])
def test_handoff_rejects_nonpublic_or_ambiguous_origins(origin):
    with pytest.raises(ValueError):
        portal_values(origin)


@pytest.mark.parametrize("origin", ["https://example.com:invalid", "https://example.com:0", "https://example.com:99999"])
def test_handoff_rejects_invalid_ports(origin):
    with pytest.raises(ValueError):
        portal_values(origin)


async def test_real_celery_worker_uses_its_own_async_resources(tmp_path, enabled, monkeypatch, respx_mock):
    database_url = "sqlite+aiosqlite:///" + (tmp_path / "worker.sqlite").as_posix()
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        await add_user(async_sessionmaker(engine, expire_on_commit=False))
    finally:
        await engine.dispose()
    monkeypatch.setattr(enabled, "database_url", database_url)
    route = respx_mock.post(TOKEN_URL).respond(200, json=token_response())
    app = create_celery_app(enabled)
    app.conf.update(broker_url="memory://", result_backend="cache+memory://", task_ignore_result=False)

    @app.task(name="test.refresh_user", ignore_result=False)
    def worker_job(open_id):
        return refresh_user_token.run(open_id)

    with start_worker(app, pool="solo", concurrency=1, queues=["auth", "default"],
                      perform_ping_check=False, shutdown_timeout=10):
        # Two separate task invocations also verify resources are not reused across closed loops.
        assert worker_job.apply_async(args=("u1",), queue="auth").get(timeout=10) == {"status": "refreshed"}
        assert worker_job.apply_async(args=("u1",), queue="auth").get(timeout=10) == {"status": "already_fresh"}
    assert route.call_count == 1


async def test_webhook_without_credentials_is_unavailable(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "tiktok_client_secret", "")
    result = await client.post("/api/v1/webhooks/tiktok", content=b"{}")
    assert result.status_code == 503 and result.json() == {"detail": "webhook_not_configured"}


@pytest.mark.parametrize("body", [b"not-json", b"[]", b"{}", b'{"event":"test","content":"invalid-json"}',
                                  b'{"event":"test","content":[]}'])
async def test_signed_malformed_webhook_is_rejected(client, body):
    result = await client.post("/api/v1/webhooks/tiktok", content=body, headers={"TikTok-Signature": sign(body)})
    assert result.status_code == 400 and result.json() == {"detail": "invalid_webhook_payload"}
