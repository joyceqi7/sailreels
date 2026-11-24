"""CORS regression tests.

The mini page is served by TikTok, not by us, so every API call the page makes is cross-origin.
A wrong allowlist fails only on a real device (local dev goes through the Vite proxy, same-origin),
which is exactly the kind of bug that survives all the way to the device test. These tests pin the
allowed origins and, just as importantly, that lookalike domains are rejected.
"""

import pytest

from app.core.config import get_settings

ALLOWED = [
    "https://tiktok-minis.us",
    "https://tiktok-minis.com",
    "https://tiktok-minis.eu",
    "https://tiktokminis.us",
    "https://app.tiktok-minis.com",  # the page may sit on a subdomain
    "https://sailreels.sailson.com",
    "https://api-staging.sailson.com",
    "http://localhost:5177",
]

# Suffix tricks must not slip through the subdomain wildcard.
DENIED = [
    "https://evil-tiktok-minis.com.attacker.io",
    "https://tiktok-minis.com.evil.io",
    "https://sailson.com.evil.io",
    "https://nottiktokminis.us",
    "https://evil.com",
    "http://tiktok-minis.com",  # platform is HTTPS only
    "null",
]


@pytest.mark.parametrize("origin", ALLOWED)
def test_platform_and_own_origins_are_allowed(origin):
    import re
    assert re.fullmatch(get_settings().cors_origin_regex, origin), f"{origin} must be allowed"


@pytest.mark.parametrize("origin", DENIED)
def test_lookalike_origins_are_rejected(origin):
    import re
    assert not re.fullmatch(get_settings().cors_origin_regex, origin), f"{origin} must be rejected"


async def test_preflight_from_platform_origin_succeeds(client):
    """The device sends an OPTIONS preflight because we attach an Authorization header."""
    r = await client.options(
        "/api/v1/dramas/1/episodes",
        headers={"Origin": "https://tiktok-minis.com",
                 "Access-Control-Request-Method": "GET",
                 "Access-Control-Request-Headers": "authorization"},
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "https://tiktok-minis.com"
    assert "authorization" in r.headers["access-control-allow-headers"].lower()


async def test_preflight_from_unknown_origin_is_refused(client):
    r = await client.options(
        "/api/v1/dramas/1/episodes",
        headers={"Origin": "https://attacker.example",
                 "Access-Control-Request-Method": "GET"},
    )
    assert r.status_code == 400
    assert "access-control-allow-origin" not in r.headers
