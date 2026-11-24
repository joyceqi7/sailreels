# OpenAPI 契约 v1

`v1.json` 是 FastAPI 实际路由生成的 v1 基线（`info.version=1.0.0`）。
`packages/api-types/schema.d.ts` 从这份文件生成，禁止手改。
生成过程不需要 TikTok 凭证、运行中的 API 或数据库连接。

## 更新与检查

```sh
cd apps/api
uv run python -m scripts.export_openapi
uv run python -m scripts.export_openapi --check
cd ../web
npm run gen:api
npm run check:api
```

修改 API 时，在同一个 PR 中提交实现、JSON 契约和生成类型。CI 分别检查
实现与 JSON、JSON 与 TS 类型是否一致。涉及字段删除、类型变化、状态含义改变等
不兼容变更，必须先与 FE 确认，并记录迁移方案；不能只重新生成文件就视为确认完成。

## v1 范围

除 `/healthz` 外，业务 API 都以 `/api/v1` 为前缀。

| 方法 | 路径 | 认证 | 含义 |
|---|---|---|---|
| POST | `/auth/login` | 无 | 一次性 code 换后端 session |
| GET | `/auth/me` | SessionBearer | 返回本地资料，检查/刷新 TikTok token |
| POST | `/auth/authorize` | SessionBearer | 用户主动授权后获取、保存头像昵称 |
| GET | `/dramas` | 无 | 已上线剧目数组 |
| GET | `/dramas/{drama_id}` | 无 | 单部剧目摘要 |
| GET | `/dramas/{drama_id}/episodes` | SessionBearer | 剧集列表、逐集锁定状态及下一锁定集 |
| GET | `/dramas/{drama_id}/episodes/{seq}/access` | SessionBearer | 权益及有权限时的播放身份 |
| POST | `/orders/beans` | SessionBearer | 创建 Beans 解锁订单 |
| GET | `/orders/beans/{order_id}` | SessionBearer | 查询本人的订单状态 |
| POST | `/ads/rewarded/nonce` | SessionBearer | 获取一次性广告领奖凭证 |
| POST | `/ads/rewarded/claim` | SessionBearer | 使用 nonce 领奖 |
| POST | `/subscriptions` | SessionBearer | 创建订阅订单 |
| POST | `/subscriptions/{subscription_id}/reactivate` | SessionBearer | 恢复本人的订阅续费 |
| GET | `/subscriptions/me` | SessionBearer | 查询本地订阅状态 |
| POST | `/webhooks/tiktok` | TikTok-Signature | 支付、订阅回调 |

JSON 字段为 snake_case。`album_id`、`episode_id`、平台订单/订阅 ID 是字符串；
本地 `drama_id` 和集序 `seq` 是整数。状态枚举、可空字段和请求/响应的完整定义以 JSON 为准。
支付和订阅最终结果依赖服务端 Webhook；Mock 测试通过不能代替平台联调。
历史、观看进度、运营后台和对账任务尚未纳入此基线。

**前端目录适配边界：** 现有页面仍使用 `Demo*Response` 的 `{data:{dramas}}`、
`drama_id`、`episode_count` 等演示形状；真实 `/dramas` 返回 `DramaOut[]`，
`/dramas/{id}` 返回 `DramaOut` 摘要；全量剧集通过已认证的 `/dramas/{id}/episodes` 获取。
锁定集不返回 vid、episode_id 等播放身份，解锁或订阅后才返回。
W1 的 `src/api/catalog.ts`、`catalog-adapters.ts` 和 `access.ts` 已使用生成类型，
提供同格式 Mock、元信息适配与逐集权限响应校验，并由 `npm run test:api` 验证。
当前页面仍走旧演示目录；live 登录入口已接入，播放器与目录页面接入另行交付。模拟测试不代表真机验收完成。

## 登录与 401 重登

```json
POST /api/v1/auth/login
{"code":"one-time-code-from-TTMinis.login"}

200
{"token":"backend-session-token","open_id":"user-id","token_type":"Bearer","expires_in":604800}
```

`token` 是我们自己的 session，不能当作 TikTok `access_token`。平台 access/refresh token
只保存在后端，前端只保存 session；code 不缓存，不自动重放。登录响应设为 `Cache-Control: no-store`。

后端在用户请求需要 token 时提前 30 分钟刷新，保存平台返回的两枚新 token 和有效期。
PostgreSQL 用用户行锁并重新读取当前值，避免多个 API worker 同时轮换同一 refresh token。
refresh 已过期或平台返回 `invalid_grant` 等凭证失效错误时，返回 401。
资料读取遇到平台 401 时允许一次强制刷新和只读重试；不自动重放支付请求。
定时刷新（Celery/beat）已提供骨架，默认暂停；启动及配置见 `docs/worker-and-platform-handoff.md`。

`src/minis/session.ts` 提供 `ensureSession()`、`apiFetch()`、`getSessionProfile()`：

1. 调用 `TTMinis.login()`，立即将 code 发送至后端。
2. API 请求携带 `Authorization: Bearer <token>`。
3. 401 时只重新登录一次，再重试原请求一次。
4. 同时到达的 401 共享登录 Promise；晚到的旧 session 401 复用已更新的 session。
5. 第二次仍为 401 时清除被拒绝的 session 并抛错，停止循环。
6. 403、429、502、503、504 不触发重登；登录 SDK 没有回调时 15 秒超时，code 交换请求 20 秒超时。

页面入口已接入 `SessionGate`：live 模式启动时先登录并通过 `/auth/me` 确认会话，再显示页面；mock 模式跳过登录且不伪造 token。失败只显示通用提示，可主动重试；真实目录页面迁移与真机验收另行验证。

## 登录错误约定

响应为 `{"detail":"<code>"}`；请求格式校验失败的 422 使用 FastAPI 的标准校验数组。

| HTTP | detail | 调用方处理 |
|---|---|---|
| 400 | `invalid_login_code` | 重新获取 code，禁止重放原 code |
| 401 | `login_required` | 经 SDK 建立新 session；最多重试一次 |
| 502 | `tiktok_unavailable` | 显示暂时不可用；不主动注销 |
| 503 | `auth_not_configured` | Wayne 检查应用凭证和权限 |
| 504 | `tiktok_timeout` | 稍后重新发起；code 交换结果不确定时获取新 code |

日志/响应不得包含平台凭证或原始 OAuth 错误 payload。
其他业务错误仍沿用既有 detail 值/对象，不应只按所有 4xx 自动重新登录。

## 验收与 Wayne 交付项

自动化验收：SQLite + httpx/respx 覆盖后端 OAuth/刷新/失效/平台故障；
Vitest 模拟 SDK 和 HTTP，覆盖首次登录、并发/晚到 401、一次重试、失败恢复和 SDK 超时。
这些测试未验证 PostgreSQL 的真实多进程锁行为，也未验证 TikTok 真机接口。

真实联调需要 Wayne 在后端环境安全配置应用凭证、随机 SESSION_SECRET（staging/prod 至少 32 字符）、
staging HTTPS API、白名单、数据库及美区测试账号/真机。不要将真实 .env 或凭证提交到 Git。

联调顺序：真机获取 code → 登录后检查 user/token 落库 → 调 `/auth/me` →
在 staging 验证过期前刷新及双 token 更新 → 验证失效返回 401 和前端单次重登。
最后在 PostgreSQL staging 并发触发同一用户刷新，确认只使用一次旧 refresh token。
安全相关改动须由同事按 `CLAUDE.md` 人工 review 后合并。
