# apps/web — SailReels Minis H5

Based on the official `tiktok-minis-drama-demo` (player plugin in `src/plugins/minis-player/`, see its README).

- `src/minis/` — typed wrappers for login / pay / subscription / rewarded ads / funnel events, plus backend session + unlock flows.
- `src/api/catalog.ts` — generated v1 catalog/detail/access responses with matching Mock fixtures. `catalog-adapters.ts` maps metadata; `access.ts` rejects locked or invalid grants.
- 首页、详情和剧场均使用 v1 `src/api/catalog.ts`；播放及预加载的媒资只能从 access 响应取得。旧 `client.ts` / `adapters.ts` 仅保留 demo 兼容代码，不再被页面使用。

Before first real-device run: confirm the matching public clientKey in `index.html` and `minis.config.json` belongs to the test application, and fill `iconUrl` / `ppLink` / `tosLink`.

```bash
npm run dev                     # :5177, /api proxied to :18800
npx ttdx minis debug            # bridge to TikTok (Android test build)
npm run build && npx ttdx minis check --output   # produces dist/ for upload
```

## W1 API types and Mock verification

`src/api/types.ts` derives `DramaListResponse`, `DramaDetailResponse` and
`EpisodeAccessResponse` from the generated v1 schema. `Demo*Response` types
keep the existing demo pages compatible; they are not backend wire formats.

```bash
npm run gen:api       # offline, from docs/openapi/v1.json; no server required
npm run check:api     # detects generated-type drift
npm run test:api      # actual v1 client, adapters and permission validation with Mock
npm test             # existing SDK/session tests plus the API/Mock suite
```

The v1 catalog client defaults to Mock. Catalog and detail expose metadata
only; detail adapters create episode numbers without media IDs. Mock starts with
episode 1 free and episodes 2/3 locked, matching the backend seed. Explicit preview
payment/ad completion grants page-local preview rights; this never changes backend rights.
A valid grant requires a permitted access state, matching sequence, no explicit
lock and complete string media IDs. Returned fixtures are cloned; an unknown
ID fails rather than falling back to another drama.

Mock business IDs are local only (official three-episode fixture: `1`). Obtain
the actual business ID from BE for a deployed test environment. The generated
schema is never edited manually; `.gitattributes` preserves LF for its check.

`VITE_API_MODE=live` selects real endpoints in the v1 catalog client. It uses
`VITE_API_BASE` (including `/api/v1`, without a trailing slash) and the existing
session wrapper for authenticated access. Live also enables the login gate described below and all page
routes use v1 data. No device-login or platform payment acceptance
is claimed by the simulated tests.

## W1 page login

`SessionGate` wraps the routes. With `VITE_API_MODE=live`, it shows a sign-in
status, obtains a one-time code from `TTMinis.login()`, exchanges it through
`POST /auth/login`, and calls `/auth/me` before mounting pages. A persisted
session is checked first. Failures show a generic message and **Try again**;
backend diagnostics never appear in this UI. A retry obtains a fresh code
when a new login is needed. It never calls `authorize()` automatically.

Only the application's session token is stored; restricted storage falls
back to memory. Login responses are validated against required v1 fields.
Concurrent logins share one request; concurrent or delayed 401s reuse the
same refresh, and a second 401 clears the rejected session without looping.
SDK login has a 15-second timeout, login HTTP has 20 seconds, and other
session HTTP requests have 15 seconds including the response body.

In mock mode the gate is skipped without a fake login or token. For future
real-environment verification, set `.env` from `.env.example` to live and the
confirmed API base, then restart Vite. The matching clientKey in `index.html`
and `minis.config.json` is already filled; this does not verify platform
permissions. A real environment and Test User are required for device proof.

`npm run test:session` covers startup, invalid payloads, concurrent/late 401s,
failure recovery, unavailable storage and SDK/network/body timeouts with
simulated SDK/HTTP. `npm test` also retains existing SDK/session and API tests.

## 广告位

`src/minis/ad-config.ts` 导出 `AD_UNIT_IDS` 和 `REWARDED_AD_CONFIGURED`。**广告位是按 App 创建的**，
SailReels 的默认值：

| 类型 | 默认值 |
|---|---|
| 激励视频 | `ad7000000000000000001`（SailReels 已激活） |
| 插屏 | `''`（SailReels 尚未创建） |

插屏为空时不展示插屏；若激励视频 ID 也为空（例如某个部署用 env 显式清空），解锁面板会**不显示**
"看广告解锁"按钮——不是显示一个禁用按钮。`showRewardedAd()` 收到空 ID 会直接以
`rewarded_ad_not_configured` 拒绝，避免用户点下去之后才报一个看不懂的 SDK 错误。

**不要把别的小程序（例如旧的 ZorvTales）的广告位 ID 填进来**：广告曝光会记到错误的 App 名下，
平台也会拒绝。`VITE_REWARDED_AD_UNIT_ID` / `VITE_INTERSTITIAL_AD_UNIT_ID` 可在构建时覆盖默认值，
改后需要重新构建。

相关测试：`UnlockSheet.noads.test.tsx` mock 成"未配置"验证隐藏广告的分支；
`UnlockSheet.live.test.tsx` mock 成"已配置"验证解锁流程本身。
