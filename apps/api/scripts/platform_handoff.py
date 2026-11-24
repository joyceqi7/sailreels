"""Generate portal handoff values locally. Does not contact TikTok or change any account."""

import argparse
import ipaddress
import json
from urllib.parse import urlsplit

from app.core.config import get_settings
from app.services.webhooks import HANDLERS, SUBSCRIPTION_EVENTS


def portal_values(origin: str) -> dict:
    url = urlsplit(origin.strip())
    # Accessing port also rejects malformed and out-of-range port numbers.
    try:
        port = url.port
    except ValueError:
        raise ValueError("Invalid HTTPS port") from None
    if port is not None and not 1 <= port <= 65535:
        raise ValueError("Invalid HTTPS port")
    if (url.scheme != "https" or not url.hostname or url.username or url.password
            or url.query or url.fragment or url.path not in ("", "/")):
        raise ValueError("Use a public HTTPS origin, e.g. https://api-staging.example.com (without API path)")
    if url.hostname.lower() == "localhost" or url.hostname.lower().endswith(".localhost"):
        raise ValueError("Localhost cannot receive platform webhooks")
    try:
        address = ipaddress.ip_address(url.hostname)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("A public HTTPS origin is required")
    callback = origin.strip().rstrip("/") + "/api/v1/webhooks/tiktok"
    return {
        "application": "SailReels", "live_integration": "paused",
        "payment_webhook_url": callback, "subscription_webhook_url": callback,
        "health_url": origin.strip().rstrip("/") + "/healthz",
        "webhook_events": sorted(set(HANDLERS) | SUBSCRIPTION_EVENTS),
        "external_owner": "Wayne", "portal_configuration_verified": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-origin", default=get_settings().public_api_origin,
                        help="Actual deployed public HTTPS origin; examples do not indicate deployment")
    args = parser.parse_args()
    try:
        values = portal_values(args.api_origin)
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(values, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
