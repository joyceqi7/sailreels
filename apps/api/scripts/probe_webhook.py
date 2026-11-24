#!/usr/bin/env python3
"""Send a correctly signed webhook to a SailReels endpoint, to verify the whole receive path.

Why a script: signing depends on the *exact* bytes of the body. Building the payload in shell and
signing it in a nested quoting context silently changes escaping, so the signature no longer matches
the body that gets sent — the request then fails verification and looks like a server bug.

  uv run python -m scripts.probe_webhook                      # defaults to staging
  uv run python -m scripts.probe_webhook --url http://localhost:18800/api/v1/webhooks/tiktok
  uv run python -m scripts.probe_webhook --event minis.subscription.onhold

A 200 means the signature was accepted. It also writes a webhook_events row, so use an obviously
fake trade_order_id (the default) unless you mean to exercise real order logic.
"""

import argparse
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request

from app.core.config import get_settings

DEFAULT_URL = "https://sailreels.sailson.com/api/v1/webhooks/tiktok"

PAYLOADS = {
    "minis.trade_order.redeem.success": {"trade_order_id": "VERIFY_PROBE", "order_id": "VERIFY_PROBE"},
    "minis.subscription.onhold": {"subscription_id": "VERIFY_PROBE", "is_sandbox": True},
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--event", default="minis.trade_order.redeem.success", choices=sorted(PAYLOADS))
    args = parser.parse_args()

    settings = get_settings()
    if not settings.tiktok_client_secret:
        raise SystemExit("TIKTOK_CLIENT_SECRET is not set; run this from apps/api with .env present")

    body = json.dumps({
        "client_key": settings.tiktok_client_key,
        "event": args.event,
        "create_time": int(time.time()),
        "user_openid": "",
        "content": json.dumps(PAYLOADS[args.event]),  # content is a JSON *string*
    }).encode()
    t = str(int(time.time()))
    signature = hmac.new(settings.tiktok_client_secret.encode(), t.encode() + b"." + body, hashlib.sha256)
    header = f"t={t},s={signature.hexdigest()}"

    request = urllib.request.Request(
        args.url, data=body, method="POST",
        headers={"Content-Type": "application/json", "TikTok-Signature": header},
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            print(f"HTTP {response.status}: {response.read().decode()}")
            print("signature accepted")
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode()}")
        if e.code == 401:
            print("signature rejected — the secret on the server may differ from the local one")
        raise SystemExit(1) from e


if __name__ == "__main__":
    main()
