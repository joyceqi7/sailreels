# SailReels — TikTok Minis 短剧小程序

计划、分工、排期：`docs/PLAN.md`。官方文档原文：`docs/official/`。

## 动手前必读

**写某条链路前，先读对应的官方文档。不要凭对微信、抖音小程序的经验猜。**

| 要做的事 | 读这份 |
|-|-|
| 整体技术形态 | `docs/official/10-tech-overview.md` |
| 本地调试、真机、CLI、账号与地区 | `docs/official/14-dev-debugging.md` |
| 播放器 VePlayer、切集、预加载、错误码 | `docs/official/13-player-integration.md`（中文从约 3110 行开始）、`15-player-best-practice.md` |
| 媒资上传、建剧、送审、上架 | `docs/official/12-media-library-api.md`、`11-media-player-overview.md` |
| 登录 / 授权 | `20-login.md` / `21-authorize.md` |
| Beans 支付 | `30-iap-beans.md` |
| 订阅 | `31-subscription.md`（8 类 Webhook 在 §8.3） |
| 激励广告 | `40-iaa-rewarded-ad.md`，广告时机规则在 `01-onboarding-one-page.md` |
| 中间事件回传 | `41-event-postback.md` |
| 业务规则、上线清单、驳回原因 | `00-closed-loop-all-in-one.md`、`01-onboarding-one-page.md` |

官方文档之间有不少矛盾，见 `docs/PLAN.md §8`。遇到矛盾时，**以真实接口的返回为准**，并在代码里写 `TODO(confirm)` 注释说明。

## 仓库结构

```
apps/web     Minis H5 (React 19 + Vite)，基于官方 tiktok-minis-drama-demo
  src/plugins/minis-player/   官方播放器插件，尽量不改，方便以后同步官方更新
  src/minis/                  唯一允许访问 window.TTMinis 的地方（播放器除外）
apps/api     FastAPI + SQLAlchemy 2 (async) + Alembic，Python 3.12，用 uv 管理
  app/tiktok/client.py        TikTok OpenAPI 薄封装：一个函数对应一个接口，不写业务逻辑
  app/services/               业务逻辑（auth / entitlement / webhooks）
  app/routers/                HTTP 层
apps/admin   运营后台（W4 搭建）
packages/api-types           由 OpenAPI 生成，禁止手改
```

## 常用命令

```bash
docker compose -p sailreels up -d db redis            # PG 映射到 55440，Redis 映射到 56390
cd apps/api && cp .env.example .env                    # 第一次运行时
cd apps/api && uv run alembic upgrade head
cd apps/api && uv run python -m scripts.seed_test_drama   # 写入官方测试剧
cd apps/api && uv run uvicorn app.main:app --reload --port 18800
cd apps/api && uv run pytest -q && uv run ruff check .
cd apps/web && npm run dev                             # 端口 5177，/api 代理到 18800
cd apps/web && npx ttdx minis debug                    # 另开一个终端，扫码连接手机
cd apps/web && npm run build && npx ttdx minis check --output
cd apps/web && npm run gen:api                         # 后端接口变了以后重新生成类型
```

## 媒资流水线（Wayne）

```bash
cd apps/api
uv run python -m scripts.media list                          # 看所有剧的状态
uv run python -m scripts.media add-drama --title "X" --source-dir ./eps --url-prefix https://oss.../
uv run python -m scripts.media upload-covers <id> --url https://.../cover.jpg
uv run python -m scripts.media upload-episode-covers <id> --cover-dir ./covers   # 每集封面，提审必需
uv run python -m scripts.media upload-videos <id>            # 批量上传并轮询到出 vid
uv run python -m scripts.media push <id>                     # 生成新版本，回写 episode_id
uv run python -m scripts.media submit <id>                   # 送审，落库 review_id
uv run python -m scripts.media status <id>                   # 查审核/上架状态（含被拒剧集明细）
uv run python -m scripts.media go-live <id>                  # 设线上版本并上架
uv run python -m scripts.media authorize <id> --client-key mnXXXX   # 授权给其他小程序播放
uv run python -m scripts.media appeal <id> --reason "..." [--seq 3] # 申诉被拒的剧目/剧集
```

顺序不能乱：**covers → uploads → push → submit → (等审核) → go-live**。`go-live` 会先查审核状态，没过审直接拒绝。

2026-10-22 实调修正的三处（文档示例是错的，以真实返回为准）：
- `push` 之后 `episode_id_map` 里**新剧集的 key 是 `seq:3`（冒号），不是文档写的 `seq_3`**。代码两种都接受。
- **每一集都必须带 `cover_list`**，包括从上一版本沿用下来的老集；漏了报 `4001 episode cover_list is required`。所以 `upload-episode-covers` 是 `push` 之前必须做的一步。
- `album/review/submit` 返回的 `review_id` 必须存下来——`album/review/appeal` 要用它，且只有被拒时才能申诉，错过就补不回来。现已落库到 `dramas.review_id`。

改了模型就要生成迁移：`uv run alembic revision --autogenerate -m "..."`，然后人工检查生成的迁移文件。

## 硬性约束（违反会导致审核被拒、资损或线上事故）

1. **`client_secret` 只能出现在后端。** 前端只能拿到 `clientKey`。
2. **`index.html` 中 `<head>` 的第一个 `<script>` 必须是 Minis SDK**，紧接着执行 `TTMinis.init({ clientKey })`。`clientKey` 必须和 `minis.config.json` 里的一致。
3. **视频只能通过 `TTMinis.getPlayer()` 拿到的 VePlayer 播放。** 禁止另外引入 `@byteplus/veplayer` 或 `@volcengine/veplayer`，禁止用 `<video>` 直接播放，禁止传 `url`/`playList` 参数（会报 9301）。
4. **能否观看由后端判断**（`GET /dramas/{id}/episodes/{seq}/access`）。前端不能自己判断是否已解锁；后端只在有权限时才返回 `vid`/`episode_id`。
5. **支付和订阅以 Webhook 为准。** `TTMinis.pay()` / `createSubscription()` 的回调成功只代表面板关闭了。之后前端轮询后端的订单状态。
6. **Webhook 处理顺序**：用原始 body 验签（`TikTok-Signature: t=..,s=..`，HMAC-SHA256，密钥是 client_secret）→ 按 dedup_key 存入 `webhook_events` → 处理业务。`content` 字段是 JSON 字符串，需要再解析一次。
7. **订阅**：
   - cancel 和 renew 都会生成新的 `trade_order_id`，所以幂等不能只靠它。
   - onhold 和 expire 事件只带 `subscription_id`，要靠 `subscriptions` 表找到对应用户。
   - 是否有权益只看 `rights_valid` 和 `benefit_end_time`，`state` 字段只用于展示。
8. **`is_sandbox=true` 的订单**在生产环境（`ALLOW_SANDBOX_ENTITLEMENTS=false`）不发放权益，也不计入 GMV。
9. **激励广告没有服务端回调。** 流程是：先取 nonce，再 `show()`，只有 `isEnded === true` 才调 claim。每次展示都要新建 ad 实例。展示前先 `canIUse('createRewardedVideoAd')`，不支持时提示用户升级 TikTok（需要 44.2.0 以上）。
10. **广告时机**：只允许在两种情况弹广告：本集正常播完、进入下一集之前；或用户主动跳集/拖动进度条进入未解锁的集。**禁止在剧集中途无用户操作时弹，也禁止在自动连播时自动弹。**
11. **商品价格只以后端为准**，不信任前端传来的金额。
12. **`album_id`、`episode_id` 这类 int64 一律当字符串处理**，否则 JS 会丢精度。
13. 每次 `album/update` 都会生成新版本，`episode_id` 可能变化，**必须用 `episode_id_map` 回写数据库**。
14. 中间事件的名称和参数名是 TikTok 定死的（`src/minis/events.ts`），不要改名。
15. 不要在页面一打开就调 `TTMinis.authorize()`，只在用户主动操作时调用（例如进入"我的"页面）。
16. **跨 App 复用剧集只能走 `album/authorize`，不要重复上传+重复送审。** 同主体下 App A 上传送审过的剧目，可以授权给 App B 播放（见下方「两个小程序共用一套媒资」）。前提是内容一致、归属校验通过；内容变更或归属对不上，仍要走正常送审。
17. **一个剧目只能绑定同一个 BytePlus 账号的同一个空间**，该剧目下所有剧集视频都必须属于该空间。同一个 BytePlus 账号可以被多个 App 共用（App ↔ 账号是多对多）。

## 本仓库的三个部署（SailReels / SailTale / SailShort）

同一套代码，每个 App 独立部署。身份由后端 `APP_NAME` + `LEGAL_ENTITY` 和前端 Vite mode
（`apps/web/.env.<app>`，`npm run build:<app>`）决定。剧目目录不能跨 client key 复用：各传各的、各审各的、各绑自己的 BytePlus 空间。不要把 `TIKTOK_CLIENT_KEY` 改成多值。

| App | `LEGAL_ENTITY` | 主体 | client key | 激励广告位 | 域名 |
|-|-|-|-|-|-|
| SailReels | `sailson_sg` | SAILSON PTE LTD | `mn_example_client_key` | `ad7000000000000000001` | `https://sailreels.sailson.com` |
| SailTale | `sailson_hk` | Sailson HK Limited | `mn_example_client_key` | `ad7000000000000000002` | `https://sailtale.sailson.com` |
| SailShort | `bang_us` | BANG ENTERTAINMENT INC. | `mn_example_client_key` | `ad7000000000000000003` | `https://sailshort.sailson.com` |

SailShort 公司登记号 `82-5480616`，地址 100 S. Birch Rd., Suite 901, Jackson Tower, Fort Lauderdale, FL 33316, US。三个 App 的公开联系邮箱都是 `user1@example.com`。SailShort 的 TikTok App ID 未提供，不要编。Webhook 都是 `https://<域名>/api/v1/webhooks/tiktok`。栈目录 `/opt/<app>`，compose 项目名 `<app>`，API 别名 `<app>-api`（SailShort 为 `sailshort-api`，Caddy 片段 `deploy/caddy-snippet-sailshort.conf`）。`client_secret` 只放该栈服务器上的 `apps/api/.env`。

## 两个 App 的关系（2026-10-29 起）

- **SailReels**：自研 App，用本仓库的代码 + 我们自己的 BytePlus 账号。`TIKTOK_CLIENT_KEY=mn_example_client_key`，App ID `7000000000000000004`，激励广告位 `ad7000000000000000001`。
- **ZorvTales**：归供应商，他们有**自己的代码和自己的 BytePlus 账号**，不再与本仓库共用任何东西。

所以两者**不共享媒资**：各传各的剧、各走各的审核、各绑自己的 BytePlus 空间。
早前规划的「同主体两个 App 共用一套媒资 + 后端按 client_key 路由」**已取消**——
不要把 `TIKTOK_CLIENT_KEY` 改成多值，那是不必要的重构。

`album/authorize`（`media.authorize_to_apps()` / `scripts.media authorize <drama_id> --client-key mnXXXX`）
代码仍然保留：平台确实支持同主体小程序之间复用已送审剧目，将来真要共享可以再启用。
注意它是批量接口，**返回 200 不代表每个目标都授权成功**——必须逐项看
`client_key_result_list[].error_code`，代码里对任一失败都会抛错。

反之，一旦真要共享，这些仍然必须各自独立：
- **广告位 ID**（按 App 创建，`ad-config.ts` 里的 ID 只属于 SailReels）
- **订阅 SKU / tier_id**（按 App 线下申请）
- **应用级 Webhook 地址**（按 App 配置）
- **登录用的 clientKey**（`index.html` 与 `minis.config.json` 必须同时改）

## 变现模式开关（2026-11-05 起三个 App 都是纯 IAA）

后端 `MONETIZATION_MODE`（服务器 `apps/api/.env`）和前端 `VITE_MONETIZATION`（`apps/web/.env.<app>`）必须一致：
- `iaa`：只能看激励广告解锁。前端隐藏 Beans、VIP、钱包页；后端对 Beans/订阅下单返回 `403 iap_disabled`，
  `unlock-options` 的 `offers` 为空。直接打开锁定集（`reason='entry'`）也可以看广告解锁（用户决定）。
- `hybrid`：Beans + 订阅 + 广告，原有全部流程。
- 后端不配默认 `iaa`（防止漏配就开始收钱）；前端不配默认 `hybrid`（本地开发和测试要覆盖全部流程）。
- 已下的订单、webhook、已发放的权益不受开关影响。Beans/订阅代码全部保留，恢复只改这两个变量。

## 必须人工逐行 review 的代码

`app/core/security.py`（验签）、`app/services/webhooks.py`、`app/services/entitlement.py`、`app/routers/monetization.py`。
改这几个文件的 PR 必须附上相关测试。现有测试在 `apps/api/tests/test_core_flows.py`。

## 约定

- 后端返回的 JSON 字段用 snake_case；前端在 `src/api/adapters.ts` 统一转换。
- 面向用户的文案用英文（首发美国）。
- 提交信息格式：`<area>: <what>`，例如 `api: subscription renew webhook`。area 取 web / api / admin / infra / docs。
