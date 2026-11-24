"""Verify TikTok credentials and print what the app can currently do.

Run this first when setting up a machine, or when an OpenAPI call starts failing with auth errors:
  cd apps/api && uv run python -m scripts.check_credentials

It never prints the secret — only its length and the token's prefix.
"""

import asyncio

from app.core.config import get_settings
from app.tiktok.client import TikTokAPIError, TikTokClient


async def main() -> None:
    s = get_settings()
    secret_state = f"set, {len(s.tiktok_client_secret)} chars" if s.tiktok_client_secret else "(missing)"
    print(f"env                 : {s.env}")
    print(f"tiktok_client_key   : {s.tiktok_client_key or '(missing)'}")
    print(f"tiktok_client_secret: {secret_state}")
    print(f"byteplus_account_id : {s.byteplus_account_id or '(missing)'}")
    print(f"byteplus_space_name : {s.byteplus_space_name or '(missing)'}")

    if not s.tiktok_client_key or not s.tiktok_client_secret:
        print("\nFAIL: fill TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET in apps/api/.env")
        return

    client = TikTokClient(s)
    # 1) App token (client_credentials) — required by every media library call.
    try:
        token = await client.app_token()
        print(f"\napp token (client_credentials): OK, {len(token)} chars, {token[:6]}...")
    except TikTokAPIError as e:
        print(f"\napp token FAILED: {e.status} {str(e.body)[:400]}")
        print("  invalid_client -> client_key and client_secret are not from the same TikTok app")
        return
    except Exception as e:
        print(f"\napp token ERROR: {type(e).__name__}: {e}")
        return

    # 2) Media library reachability — a read-only call that also proves the account binding.
    if not s.byteplus_account_id:
        print("\nSKIP media API: BYTEPLUS_ACCOUNT_ID not set (BytePlus account not bound yet)")
        return
    try:
        await client.media_info_query(["nonexistent-vid-probe"])
        print("media info query: OK (unexpected for a fake vid)")
    except TikTokAPIError as e:
        # An auth/param error is informative; a network error is not.
        print(f"media info query: reachable (responded {e.status}: {str(e.body)[:200]})")
    except Exception as e:
        print(f"media info query ERROR: {type(e).__name__}: {e}")


if __name__ == "__main__":
    asyncio.run(main())
