# Worker、定时 token 刷新与平台开通交接

真实业务联调当前暂停，worker/beat 骨架已交付，token 定时刷新默认保持关闭。
截至 2026-10-13，测试服务已部署，IAP/IAA 已核验开启，两个广告位均已启用，
请求域名和统一 Webhook 已保存，平台测试回调返回 200；详细证据边界见
[平台配置记录](platform-configuration-status.md)。本次没有重新签署合同。
Wayne 负责外部依赖；Joyce 已协助完成上述 Dev Portal 配置，后续继续负责后端技术联调。

## Worker 与 beat

- 入口：`app.worker.celery_app:celery_app`，任务实现：`app/worker/tasks.py`。
- `TOKEN_REFRESH_ENABLED=false` 是默认值：beat 没有刷新调度，直接调用刷新任务也会跳过。
  缺少应用凭证时任务同样跳过，不连接数据库或调用 TikTok。
- 开启后，beat 默认每 300 秒扫描一次 access token 将在 1800 秒内过期的用户。
  排除已过期的 refresh token，每轮最多 200 人，先处理最早过期的用户。
- scanner 向 `auth` 队列逐人发任务。消息只有用户 ID，使用脱敏 argsrepr；不发送 token。
  结果只有 status/reason，不包含凭证；默认不保存任务结果。
- worker 复用登录链路的 PostgreSQL 行锁及锁后重读。重复任务遇到新 token 时不再刷新。
- access/refresh token 与过期时间一起更新。平台拒绝 refresh 后，将本地 refresh 有效期置为失效，
  让后续 API 返回 401，并停止 beat 反复扫描此凭证；用户重新登录后恢复正常。
- HTTP 网络错误、429、5xx 最多额外重试 3 次，指数退避（30 秒起步，带 jitter）。
  `invalid_client` 等配置错误不强制用户注销；日志/重试异常不携带原始平台 payload。
- 每次任务在自己的 asyncio loop 中创建并关闭数据库 engine 和 HTTP client，不复用 API 的资源。
  PostgreSQL 设置锁等待/语句超时；worker 预取为 1，单任务软/硬时限为 60/90 秒。
- broker 至少一次投递可能产生重复消息，数据库状态负责避免重复实际刷新。
  任务被强制中断后，仍到期的用户由后续扫描再次检查。

Celery 官方要求同一 schedule 只有一个 beat，且周期任务可能重叠：
[Periodic Tasks](https://docs.celeryq.dev/en/stable/userguide/periodic-tasks.html)。
关闭服务时先停止 beat，再让 worker 完成在途任务，参考
[Workers Guide](https://docs.celeryq.dev/en/stable/userguide/workers.html)。

## 启动命令

先复制 `apps/api/.env.example` 为本地 `.env`，保持 `TOKEN_REFRESH_ENABLED=false`。
数据库迁移完成后才启动 worker/beat。Compose 用 API 健康检查等待迁移/启动结束：

```sh
docker compose -p sailreels up -d --build
docker compose -p sailreels logs --tail=100 worker beat
docker compose -p sailreels stop beat
docker compose -p sailreels stop worker
```

Compose 将 API/worker/beat 的数据库和 Redis 指向内部服务，beat 状态保存在独立 volume。
`.dockerignore` 排除真实 .env、Windows .venv 和运行时文件。
生产 ECS/RDS/Redis、证书和网络访问由 Wayne 配置，不直接沿用示例数据库账号密码。
staging/prod 的 SESSION_SECRET 至少 32 个随机字符。

不用 Docker 时（在 apps/api）：

```sh
uv run celery -A app.worker.celery_app:celery_app worker --loglevel=INFO --queues=auth,default --concurrency=2
uv run celery -A app.worker.celery_app:celery_app beat --loglevel=INFO --schedule=celerybeat-schedule
```

Windows 本地 smoke 使用 `worker --pool=solo --concurrency=1`；正式部署使用 Linux。
真实联调恢复后再设置 TOKEN_REFRESH_ENABLED=true，并重启 worker 和唯一的 beat。
未启用时 API 的按需 token 刷新仍可在登录联调中单独验证。

## Wayne 的平台交接清单

以下为平台交接验收口径，已完成状态以 [2026-10-13 配置记录](platform-configuration-status.md) 为准。
合同文件/版本归档、所有业务事件订阅和真实业务联调仍需后续核验。当前签署入口以实际 Dev Portal 为准。
资料依据：`docs/official/01-onboarding-one-page.md` 的 Contract Signing，
`30-iap-beans.md` 的接入前置，`40-iaa-rewarded-ad.md` 的前置条件和广告位步骤。

| 项目 | Wayne 的操作/交付 | 验收记录 |
|---|---|---|
| 应用身份 | 确认组织、已认证主体和 SailReels App，避免在其他 App 下配置 | App ID/clientKey、主体与访问权限 |
| IAP | 打开 Monetization，阅读并由有权签署人提交 IAP 合同，确认能力启用 | 签署状态、合同版本和启用状态 |
| IAA | 资料还要求 Drama IAA 合同；核对 IAA 的合同及启用状态 | IAA 签署/启用状态 |
| 激励广告位 | 创建 rewarded 广告位，记录 adUnitId，手动激活 | ID、类型、激活状态 |
| 插屏广告位 | 按项目计划创建 interstitial 位并激活 | ID、类型、激活状态；展示规则/SDK 文档确认 |
| 支付 Webhook | 填实际部署的 HTTPS 回调 URL，启用两类 Beans 事件 | 保存结果和事件选项 |
| 订阅 Webhook | 填同一 HTTPS 回调 URL，启用八类订阅事件 | 保存结果和事件选项 |
| 对接配置 | 仅在后端保存 client_secret；提供 API origin 和公开广告位 ID | 后端环境配置、前端公开 ID |

两个公开广告位 ID 已写入前端 `src/minis/ad-config.ts` 和 `.env.example`，
可由 VITE_REWARDED_AD_UNIT_ID/VITE_INTERSTITIAL_AD_UNIT_ID 在构建时覆盖。
现有激励广告辅助函数默认读取该配置，页面激励广告已于 10/23 接入；插屏展示仍待后续开发，不将插屏回调当作解锁奖励。
激励广告没有服务端 Webhook，继续使用 isEnded + 后端 nonce 的领奖链路。

## Webhook 地址与事件

部署实际域名后，在 apps/api 本地运行：

```sh
uv run python -m scripts.platform_handoff --api-origin https://api-staging.example.com
```

**example.com 仅为示例，不能填进实际控制台。** 也可由 PUBLIC_API_ORIGIN 提供真实 origin。
脚本只生成交接 JSON；输出始终标记 `portal_configuration_verified=false` 和 `live_integration=paused`，
不发网络请求、不读取/输出凭证、不办理签约或激活。

当前控制台使用一个统一的应用级 Webhook 地址，支付和订阅共用：
`https://sailreels.sailson.com/api/v1/webhooks/tiktok`。

Beans 事件：
- `minis.trade_order.redeem.success`
- `minis.trade_order.redeem.refund_success`

订阅事件：
- `minis.subscription.create`
- `minis.subscription.renew`
- `minis.subscription.reactivate`
- `minis.subscription.cancel`
- `minis.subscription.onhold`
- `minis.subscription.expire`
- `minis.subscription.refund`
- `minis.subscription.revoke`

Webhook 必须通过 HTTPS POST，保持 body 原文与 TikTok-Signature header。
部署模板：`infra/nginx/api.conf.example`，替换域名和证书路径后再配置 Nginx。
不要给 Webhook 加浏览器登录页、Basic Auth 或跳转；用平台签名认证。
缺少 client_secret 返回 503；签名错误返回 401；签名有效但 JSON 格式错误返回 400。
正确事件落库后返回 200，重复事件由幂等键去重。
官方说明：[Webhook Overview](https://developers.tiktok.com/docs/en/webhooks-overview)、
[Webhook Verification](https://developers.tiktok.com/docs/en/webhooks-verification)。

## 验证边界与后续验收

worker 骨架初次交付的自动测试使用 SQLite、mock TikTok、内存 broker 的真实 Celery worker。
覆盖到期筛选、分批、重复任务、凭证轮换/失效、限次重试、暂停门禁、独立异步资源和 Webhook 配置校验。
该批测试没有进行真实 TikTok、ECS/RDS/Redis 或平台回调联调。
后续部署与平台测试回调的已完成状态见上方配置记录；真实业务联调仍未验收。

条件就绪后：验证 Linux Docker 启动、真实 Redis 投递、单 beat 调度、PostgreSQL 并发锁、
SIGTERM 下 worker 优雅退出，然后再验证 TikTok token 刷新和平台 sandbox 支付/订阅回调。
Webhook 失败记录的后台重试、订阅对账、支付退款业务规则和完整广告页面接入仍是后续任务。
Webhook 入口中的「落库后业务失败返回 200」所需的重试任务已补齐（2026-10-12）：`sailreels.webhooks.retry_unprocessed` 每 60 秒扫描未成功处理的事件，最多重试 5 次，超过后保留 `processed_at` 为空并打 error 日志等人工介入；该调度不依赖 TOKEN_REFRESH_ENABLED，因为支付/订阅事件必须被应用。重试是幂等的（权益按 open_id+drama_id+seq 唯一）。
安全相关改动按 CLAUDE.md 由同事人工 review 后合并。
