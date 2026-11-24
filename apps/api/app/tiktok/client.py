"""Thin wrappers over TikTok OpenAPI. One function per documented endpoint; no business logic here.

Docs: docs/official/20-login.md, 21-authorize.md, 30-iap-beans.md, 31-subscription.md, 12-media-library-api.md
"""

import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import Settings


class TikTokAPIError(Exception):
    def __init__(self, path: str, status: int, body: Any):
        # Provider payloads can contain credentials; never include them in exception text/logs.
        super().__init__(f"TikTok request failed: {path} (HTTP {status})")
        self.path, self.status, self.body = path, status, body

    @property
    def code(self) -> str:
        if not isinstance(self.body, dict):
            return ""
        error = self.body.get("error")
        if isinstance(error, dict):
            return str(error.get("code", ""))
        return str(error or self.body.get("error_code", ""))


@dataclass
class TokenResult:
    open_id: str
    access_token: str
    refresh_token: str
    expires_in: int
    refresh_expires_in: int
    scope: str


class TikTokClient:
    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None):
        self.s = settings
        self.http = http or httpx.AsyncClient(base_url=settings.tiktok_open_api, timeout=15)
        self._app_token: tuple[str, float] | None = None

    # ---------- OAuth (user) ----------

    async def _oauth(self, data: dict[str, str]) -> dict:
        resp = await self.http.post(
            "/v2/oauth/token/",
            data={"client_key": self.s.tiktok_client_key, "client_secret": self.s.tiktok_client_secret, **data},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            body = resp.json()
        except ValueError as e:
            raise TikTokAPIError("/v2/oauth/token/", resp.status_code, None) from e
        if resp.status_code != 200 or not isinstance(body, dict) or body.get("error"):
            raise TikTokAPIError("/v2/oauth/token/", resp.status_code, body)
        return body

    @staticmethod
    def _token(body: dict) -> TokenResult:
        try:
            result = TokenResult(
                open_id=body["open_id"], access_token=body["access_token"], refresh_token=body["refresh_token"],
                expires_in=int(body["expires_in"]), refresh_expires_in=int(body["refresh_expires_in"]),
                scope=body.get("scope", ""),
            )
            if any(not isinstance(v, str) or not v for v in
                   (result.open_id, result.access_token, result.refresh_token)):
                raise ValueError("missing identity or token")
            if len(result.open_id) > 128 or result.expires_in <= 0 or result.refresh_expires_in <= 0:
                raise ValueError("invalid token lifetime or identity")
            if not isinstance(result.scope, str):
                raise ValueError("invalid scope")
            return result
        except (KeyError, TypeError, ValueError) as e:
            raise TikTokAPIError("/v2/oauth/token/", 502, None) from e

    async def exchange_code(self, code: str) -> TokenResult:
        return self._token(await self._oauth({"code": code, "grant_type": "authorization_code"}))

    async def refresh(self, refresh_token: str) -> TokenResult:
        return self._token(await self._oauth({"refresh_token": refresh_token, "grant_type": "refresh_token"}))

    async def user_info(self, access_token: str) -> dict:
        body = await self._json("GET", "/v2/user/info/", access_token,
            params={"fields": "open_id,avatar_url,display_name"},
        )
        try:
            user = body["data"]["user"]
            if not isinstance(user, dict):
                raise ValueError("invalid user")
            return user
        except (KeyError, TypeError, ValueError) as e:
            raise TikTokAPIError("/v2/user/info/", 502, None) from e

    # ---------- OAuth (app, client_credentials) — used by media library ----------

    async def app_token(self) -> str:
        if self._app_token and self._app_token[1] > time.time() + 60:
            return self._app_token[0]
        body = await self._oauth({"grant_type": "client_credentials"})
        self._app_token = (body["access_token"], time.time() + int(body.get("expires_in", 7200)))
        return self._app_token[0]

    # ---------- generic JSON call ----------

    async def _json(self, method: str, path: str, bearer: str, json: dict | None = None,
                    params: dict | None = None, headers: dict | None = None) -> dict:
        resp = await self.http.request(
            method, path, json=json, params=params,
            headers={"Authorization": f"Bearer {bearer}", "Content-Type": "application/json", **(headers or {})},
        )
        try:
            body = resp.json()
        except ValueError:
            body = resp.text
        err = body.get("error") if isinstance(body, dict) else None
        if resp.status_code != 200 or (isinstance(err, dict) and err.get("code") not in (None, "ok", 0, "0")):
            raise TikTokAPIError(path, resp.status_code, body)
        return body

    # ---------- IAP Beans (30-iap-beans.md) ----------

    async def check_redeem_amount(self, access_token: str, token_amount: int) -> bool:
        path = "/v2/minis/utility/check_redeem_amounts/"
        body = await self._json("POST", path, access_token,
                                json={"token_type": "BEANS", "token_amounts": [token_amount]})
        try:
            valid = body["data"]["valid"]
            if not isinstance(valid, bool):
                raise ValueError("invalid price validation result")
            return valid
        except (KeyError, TypeError, ValueError) as e:
            raise TikTokAPIError(path, 502, None) from e

    async def create_trade_order(self, access_token: str, *, order_id: str, token_amount: int,
                                 product_name: str, quantity: int = 1, quantity_unit: str = "episode") -> str:
        # Official Payment APIs: token_type + token_amount + nested order_info.
        # https://developers.tiktok.com/docs/en/minis-payment-apis
        path = "/v2/minis/trade_order/create/"
        body = await self._json("POST", path, access_token, json={
            "token_type": "BEANS",
            "token_amount": token_amount,
            "order_info": {"order_id": order_id, "product_name": product_name,
                           "quantity": quantity, "quantity_unit": quantity_unit},
        })
        try:
            trade_id = body["data"]["trade_order_id"]
            if not isinstance(trade_id, str) or not trade_id.strip() or len(trade_id) > 64:
                raise ValueError("invalid trade order ID")
            return trade_id
        except (KeyError, TypeError, ValueError) as e:
            raise TikTokAPIError(path, 502, None) from e

    # ---------- Subscription (31-subscription.md §7) ----------

    async def create_subscription(self, access_token: str, *, tier_id: str, order_id: str,
                                  product_name: str) -> str:
        body = await self._json("POST", "/v2/minis/subscription/create/", access_token, json={
            "tier_id": tier_id,
            "order_info": {"order_id": order_id, "product_name": product_name},
        })
        return self._subscription_trade_id(body)

    async def reactivate_subscription(self, access_token: str, *, subscription_id: str, order_id: str,
                                      product_name: str) -> str:
        body = await self._json("POST", "/v2/minis/subscription/reactivate/", access_token, json={
            "subscription_id": subscription_id,
            "order_info": {"order_id": order_id, "product_name": product_name},
        })
        return self._subscription_trade_id(body)

    @staticmethod
    def _subscription_trade_id(body: dict) -> str:
        try:
            trade = body["data"]["trade_order_id"]
            if not isinstance(trade, str) or not trade.strip() or len(trade) > 64:
                raise ValueError("invalid trade ID")
            return trade
        except (KeyError, TypeError, ValueError) as e:
            raise TikTokAPIError("subscription/create-or-reactivate", 502, None) from e

    async def get_active_subscriptions(self, access_token: str) -> list[dict]:
        path = "/v2/minis/subscription/get_active_list/"
        body = await self._json("POST", path, access_token, json={})
        try:
            rows = body["data"]["subscriptions"]
            if not isinstance(rows, list):
                raise ValueError("invalid subscriptions")
            for item in rows:
                for key in ("subscription_id", "tier_id"):
                    if not isinstance(item[key], str) or not 1 <= len(item[key]) <= 128:
                        raise ValueError("invalid subscription identity")
                # Fail closed on missing sandbox classification, rather than calling test rights real.
                for key in ("is_subscription_rights_valid", "is_renewal_normal", "is_sandbox"):
                    if type(item[key]) is not bool:
                        raise ValueError("invalid subscription flags")
                for key in ("end_time", "next_duduct_time"):
                    value = item.get(key)
                    if value is not None and (isinstance(value, bool) or not str(value).isdigit()
                                              or not 0 <= int(value) <= 253402300799):
                        raise ValueError("invalid subscription time")
            return rows
        except (KeyError, TypeError, ValueError, OverflowError) as e:
            raise TikTokAPIError(path, 502, None) from e

    async def get_subscription_trade_order(self, access_token: str, trade_order_id: str) -> dict:
        body = await self._json("POST", "/v2/minis/subscription/get_trade_order_info/", access_token,
                                json={"trade_order_id": trade_order_id})
        try:
            data = body["data"]
            if (data["trade_order_id"] != trade_order_id or not isinstance(data["trade_order_status"], str)
                    or type(data["is_sandbox"]) is not bool):
                raise ValueError("invalid subscription trade order")
            return data
        except (KeyError, TypeError, ValueError) as e:
            raise TikTokAPIError("subscription/get_trade_order_info", 502, None) from e

    async def get_subscription_info(self, access_token: str, trade_order_id: str) -> dict:
        body = await self._json("POST", "/v2/minis/subscription/get_subscription_info/", access_token,
                                json={"trade_order_id": trade_order_id})
        try:
            result = body["data"]["subscription"]
            if not isinstance(result, dict):
                raise ValueError("invalid subscription info")
            return result
        except (KeyError, TypeError, ValueError) as e:
            raise TikTokAPIError("subscription/get_subscription_info", 502, None) from e

    async def get_subscription_tiers(self, access_token: str, tier_ids: list[str], platform: str) -> dict:
        path = "/v2/minis/subscription/get_subscription_tier_info/"
        body = await self._json("POST", path, access_token,
                                json={"tier_ids": tier_ids, "device_platform": platform})
        try:
            tiers = body["data"]["subscription_tiers_info"]
            if not isinstance(tiers, dict):
                raise ValueError("invalid tiers")
            for key, item in tiers.items():
                if key not in tier_ids or not isinstance(item, dict):
                    raise ValueError("unexpected tier")
                for field in ("price", "currency", "deduct_cycle"):
                    if not isinstance(item[field], str) or not item[field]:
                        raise ValueError("invalid tier field")
            return tiers
        except (KeyError, TypeError, ValueError) as e:
            raise TikTokAPIError(path, 502, None) from e

    # ---------- Media library (12-media-library-api.md) ----------
    # All calls use the app token (client_credentials). Several endpoints additionally require the
    # client_key in the body / query string / `client-key` header — the docs' working curl examples
    # are the source of truth for which, so follow them exactly.

    MEDIA = "/v2/sg/shortdrama"

    async def media_upload_image(self, image_url: str) -> str:
        body = await self._json("POST", f"{self.MEDIA}/image", await self.app_token(),
                                json={"client_key": self.s.tiktok_client_key, "image_url": image_url})
        return body["data"]["open_pic_id"]

    async def media_upload_video(self, url: str, title: str, *, vid: str | None = None) -> dict:
        """Async by design: poll media_query_video() with the returned job_id until upload_status == 2."""
        payload: dict[str, Any] = {
            "client_key": self.s.tiktok_client_key,
            "title": title,
            "space_name": self.s.byteplus_space_name,
            "byteplus_account_id": self.s.byteplus_account_id,
            "byteplus_region": self.s.byteplus_region,
        }
        if vid:
            payload["vid"] = vid  # reuse an existing BytePlus VID; `url` must be omitted
        else:
            payload["url"] = url
        return (await self._json("POST", f"{self.MEDIA}/video", await self.app_token(), json=payload))["data"]

    async def media_query_video(self, *, job_id: str | None = None, vid: str | None = None) -> dict:
        if not job_id and not vid:
            raise ValueError("job_id or vid is required")
        params = {
            "client_key": self.s.tiktok_client_key,
            "byteplus_account_id": self.s.byteplus_account_id,
            **({"job_id": job_id} if job_id else {"vid": vid}),
        }
        return (await self._json("GET", f"{self.MEDIA}/video", await self.app_token(), params=params))["data"]

    async def media_delete_videos(self, vids: list[str]) -> dict:
        """1–20 vids, same account and space. A vid referenced by an online version fails with 22101.

        The body field is `vid_list`, not `vids` — the other two vid endpoints use `vids`, this one
        doesn't. Verified against docs/official/12-media-library-api.md §批量删除视频.
        """
        if not 1 <= len(vids) <= 20:
            raise ValueError("vids must contain 1 to 20 items")
        return (await self._json(
            "POST", f"{self.MEDIA}/video/delete/", await self.app_token(),
            json={"vid_list": vids, "space_name": self.s.byteplus_space_name,
                  "byteplus_account_id": self.s.byteplus_account_id},
            headers={"client-key": self.s.tiktok_client_key},
        ))["data"]

    async def album_create(self) -> str:
        # Doc's request-parameter table for this endpoint is empty; the example posts an empty body.
        body = await self._json("POST", f"{self.MEDIA}/album/create/", await self.app_token(), json={})
        return str(body["data"]["album_id"])

    async def album_update(self, album_id: str, album_info: dict, episodes: list[dict],
                           version: str | None = None) -> dict:
        """Always produces a NEW version (history is never overwritten). Returns version + episode_id_map."""
        payload: dict[str, Any] = {
            "client_key": self.s.tiktok_client_key,
            "album_id": album_id, "operation_type": 1,
            "album_info": album_info, "episode_info_list": episodes,
        }
        if version:
            payload["version"] = version
        return (await self._json("POST", f"{self.MEDIA}/album/update/", await self.app_token(), json=payload))["data"]

    async def album_set_edit_status(self, album_id: str, album_status: int = 3) -> dict:
        """operation_type=2: only flips the album edit status (1 not published, 2 updating, 3 finished)."""
        return (await self._json("POST", f"{self.MEDIA}/album/update/", await self.app_token(), json={
            "client_key": self.s.tiktok_client_key, "album_id": album_id,
            "operation_type": 2, "album_status": album_status,
        }))["data"]

    async def album_query(self, album_id: str, version: str | None = None) -> dict:
        params = {"client_key": self.s.tiktok_client_key, "album_id": album_id,
                  **({"version": version} if version else {})}
        return (await self._json("GET", f"{self.MEDIA}/album/query/", await self.app_token(), params=params))["data"]

    async def album_review_submit(self, album_id: str, version: str) -> dict:
        """`version` is sent as a string: the live API accepted it on 2026-10-22 (returned version 3)."""
        return (await self._json("POST", f"{self.MEDIA}/album/review/submit/", await self.app_token(),
                                 json={"album_id": album_id, "version": version}))["data"]

    async def album_review_withdraw(self, album_id: str, version: str) -> dict:
        return (await self._json("POST", f"{self.MEDIA}/album/review/withdraw/", await self.app_token(),
                                 json={"album_id": album_id, "version": version}))["data"]

    async def album_review_appeal(self, *, album_id: str, review_id: str, appeal_item_type: int,
                                  item_id: str, appeal_reason: str,
                                  attachment_urls: list[str] | None = None) -> dict:
        """Only for already-rejected items. appeal_item_type: 1 album, 2 episode.

        album_id and review_id are required by the doc; review_id is the one album/review/submit
        returned. The attachment field is `attachment_urls` (max 10, 200 MB each).
        """
        if appeal_item_type not in (1, 2):
            raise ValueError("appeal_item_type must be 1 (album) or 2 (episode)")
        if len(attachment_urls or []) > 10:
            raise ValueError("appeal supports at most 10 attachments")
        return (await self._json("POST", f"{self.MEDIA}/album/review/appeal/", await self.app_token(), json={
            "client_key": self.s.tiktok_client_key, "album_id": album_id, "review_id": review_id,
            "appeal_item_type": appeal_item_type, "item_id": item_id,
            "appeal_reason": appeal_reason, "attachment_urls": attachment_urls or [],
        }))["data"]

    async def album_online_version(self, album_id: str, version: str) -> dict:
        """The version must already have passed review."""
        return (await self._json("POST", f"{self.MEDIA}/album/online_version/", await self.app_token(),
                                 json={"album_id": album_id, "version": version}))["data"]

    async def album_set_status(self, album_id: str, online: bool) -> dict:
        return (await self._json("POST", f"{self.MEDIA}/album/status/", await self.app_token(), json={
            "client_key": self.s.tiktok_client_key, "album_id": album_id,
            "status": 1 if online else 2,
        }))["data"]

    async def album_authorize(self, album_id: str, operate_type: int,
                              target_client_keys: list[str]) -> dict:
        """Lend one album to other Minis apps under the same entity (operate_type 1 adds, 2 removes).

        This is the endpoint that lets a supplier-built app and our own app share one reviewed album
        instead of uploading and reviewing the same episodes twice. Batch: check every entry in
        client_key_result_list — a 200 response does not mean every target was authorised.
        """
        if not target_client_keys:
            raise ValueError("target_client_key_list cannot be empty")
        data = (await self._json("POST", f"{self.MEDIA}/album/authorize/", await self.app_token(), json={
            "client_key": self.s.tiktok_client_key, "album_id": album_id,
            "operate_type": operate_type, "target_client_key_list": target_client_keys,
        }))["data"]
        failed = [r for r in data.get("client_key_result_list", []) if r.get("error_code")]
        if failed:
            raise TikTokAPIError("/v2/sg/shortdrama/album/authorize/", 200, {
                "error": {"code": str(failed[0].get("error_code")),
                          "message": failed[0].get("error_message", "")},
                "client_key_result_list": data.get("client_key_result_list"),
            })
        return data

    async def media_transcode_batch(self, vids: list[str], *, idempotency_key: str,
                                    template_id: str = "default_0", template_type: int = 0) -> dict:
        return (await self._json(
            "POST", f"{self.MEDIA}/video/transcode/batch/", await self.app_token(),
            json={"vids": vids[:1000], "template_id": template_id, "template_type": template_type,
                  "space_name": self.s.byteplus_space_name,
                  "byteplus_account_id": self.s.byteplus_account_id},
            headers={"Idempotency-Key": idempotency_key},
        ))["data"]

    async def media_transcode_query(self, task_id: str) -> dict:
        return (await self._json("GET", f"{self.MEDIA}/video/transcode/batch/", await self.app_token(),
                                 params={"task_id": task_id,
                                         "byteplus_account_id": self.s.byteplus_account_id},
                                 headers={"client-key": self.s.tiktok_client_key}))["data"]

    async def media_info_query(self, vids: list[str]) -> dict:
        return (await self._json("POST", f"{self.MEDIA}/video/media-info/query/", await self.app_token(),
                                 json={"vids": vids[:20],
                                       "byteplus_account_id": self.s.byteplus_account_id}))["data"]

    async def media_upload_subtitle(self, vid: str, subtitle_url: str, *, title: str,
                                    format: str = "srt", language: str | None = None) -> str:
        """Attach a subtitle track to an already-uploaded vid. Returns the BytePlus material id.

        Review-time only: per docs/official/11-media-player-overview.md the review team reads the
        subtitle pack but does not process it. Multi-language albums must include an English track.
        Requires the `client-key` header as well as the body field.
        """
        payload: dict[str, Any] = {
            "client_key": self.s.tiktok_client_key, "subtitle_url": subtitle_url, "title": title,
            "format": format, "vid": vid, "space_name": self.s.byteplus_space_name,
            "byteplus_account_id": self.s.byteplus_account_id,
        }
        if language:
            payload["language"] = language
        return (await self._json("POST", f"{self.MEDIA}/subtitle/", await self.app_token(), json=payload,
                                 headers={"client-key": self.s.tiktok_client_key}))["data"]["mid"]

    async def play_token(self, episode_id: str) -> str:
        """Only needed for TikTok clients below 44.5.0 (<1% of traffic). We target a higher minimum."""
        body = await self._json("GET", f"{self.MEDIA}/play_token/", await self.app_token(), params={
            "client_key": self.s.tiktok_client_key, "episode_id": episode_id,
        })
        return body["data"]["play_auth_token"]
