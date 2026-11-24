# Beans 与广告领奖自动化联调（2026-10-19）

> 2026-10-23 已继续交付页面接入、三档套餐及订单确认超时后的查询入口；最新范围见
> [10/23 交付清单](w2-2026-10-23-handoff.md)。本文保留 10/19 的实现背景与真机步骤。

本轮交付后端 Beans 下单、Webhook、轮询、权益判断及广告 nonce 领奖的闭环校验，
以及前端 SDK 辅助函数的协作测试。美国 Test User 账号和 Android 测试设备尚未就绪，
用户确认本轮先完成代码和自动化联调；未执行 TikTok 真机支付或广告展示，也未改动线上数据库。

## Beans 链路

1. 前端请求 `POST /api/v1/orders/beans`，只提交正整数 `drama_id`、`seq`。
2. 后端确认剧已上架、剧集存在且可付费解锁；免费集、不存在的集及已拥有权益的集拒绝下单。
3. 价格只取数据库，先调用 TikTok `check_redeem_amounts` 确认档位有效。
4. 先提交本地 `BeansOrder`，再发起一次 TikTok 下单请求；结构是 `token_type: BEANS`、
   `token_amount` 和嵌套的 `order_info`。成功后保存 `trade_order_id` 再返回前端。
5. 前端拉起 `TTMinis.pay()`；面板回调不发权益。回调等待上限为 120 秒。
6. 支付 Webhook 用原始 body 验签并先落库；校验订单映射后，在同一事务更新状态并发放权益。
   相同投递去重；不同投递指向同一订单时由 PostgreSQL 行锁串行处理。
7. 前端每 1.5 秒轮询自己的订单，`paid` 后仍查询 `/dramas/{id}/episodes/{seq}/access`，
   确认服务端已允许访问后才返回解锁成功；`refunded`、`failed` 立即停止，超时保留“处理中”语义。

`pollBeansOrder(orderId, timeoutMs)` 已导出，调用方持有订单 ID 时可继续查询原订单，
不需要再次创建或支付。调用方要保存成功下单返回的业务 ID，超时后先查原订单再决定下一步。
现有 `unlockWithBeans` 便利函数仍返回布尔值；正式订单历史/恢复 UI 留给页面开发接入。

上游超时或异常不自动重放下单，也不把未知结果强制写成失败。本地订单保留为 `created`，
签名有效的迟到回调可以通过业务 `order_id` 找到记录并补齐映射。
2026-10-23 更新：后端下单已落库但上游异常时返回业务 `order_id`，前端保留原订单查询入口；
关闭重开面板也会在当前页面生命周期内恢复该引用。完全断网导致响应未收到、完整刷新后的历史订单
恢复以及主动对账任务仍需后续处理，不能把请求超时直接解释为“没有创建订单”。

退款沿用现有产品口径：支付成功后退款，保留已解锁权益；退款先到、成功通知后到时，
订单保持 `refunded`，不因乱序成功通知重新发放。退款撤权与部分退款追偿规则需产品另行确定。

## 权益和 sandbox 隔离

- `ENV=prod` 时，即使误设 `ALLOW_SANDBOX_ENTITLEMENTS=true`，也禁止 sandbox 权益。
- sandbox 识别来自平台 Webhook 的布尔 `is_sandbox`；Beans 回调中的字符串等错误类型不发货，
  保留未处理事件供检查。官方历史通知缺少该字段时沿用非 sandbox 兼容口径，真机需核验实际载荷。
- 测试订单仍记录真实支付状态和 sandbox 标识；`paid` 不等于允许解锁。
- 关闭 sandbox 权益后，已存在的测试购买也会从单集 access 和剧集列表中隐藏。
- 相同用户、剧、集的权益通过数据库唯一约束及原子 upsert 去重；正式购买或广告领奖可替换旧测试权益。
- 没有新增 GMV/财务统计；后续统计仍必须排除 `BeansOrder.is_sandbox=true`。

## 广告 nonce 链路

1. `POST /ads/rewarded/nonce` 验证登录用户和可解锁目标；nonce 绑定用户、剧、集，10 分钟有效。
2. 前端检查 `canIUse`，每次新建广告实例，仅完整观看（`isEnded === true`）才请求 claim。
   中途关闭、未提供完成标识、拉取或展示错误均不领奖。
3. `POST /ads/rewarded/claim` 锁定用户及 nonce，检查归属、单次使用、有效期、目标和滚动 24 小时限额。
   同一用户不同 nonce 也串行计数，防止提前囤积 nonce 后并发超过 50 次限额。
4. 消费 nonce 和发放权益在同一事务提交；前端再查询 access 确认结果。

nonce 只能限制重放、越权和领奖频率，不是平台提供的服务端完播证明；IAA 目前没有服务端完播 Webhook。
10/19 未新增解锁面板；10/23 已完成面板及用户主动触发的激励广告，插屏展示与冷却仍属后续任务。

## 自动化运行与验证范围

在 `apps/api`：

```sh
uv run ruff check .
uv run pytest -q
uv run python -m scripts.export_openapi --check
```

`tests/test_monetization_integration.py` 经真实 FastAPI HTTP 路由、签名校验、数据库事务和权益查询，
仅将 TikTok HTTP 服务替换为受控模拟，覆盖请求结构/价格校验、重复通知、迟到/提前通知、
错误映射、sandbox 门禁、退款乱序、nonce 归属/重放/限额和失败事件重试。

CI 为 API 启动独立 PostgreSQL 16 服务，设置 `TEST_POSTGRES_URL`；
`tests/test_monetization_postgres.py` 在每个测试的随机独立 schema 中验证并发双领奖、
不同 nonce 的限额竞争、同订单并发回调、广告/支付同时发放，以及测试权益升级为正式权益。
测试结束只清理该随机 schema。本地未配置测试 PostgreSQL 时明确跳过这些用例；SQLite 不能证明行锁有效。

在 `apps/web`：

```sh
npm run gen:api
npm run check:api
npm test
npm run build
npm run check:minis:output
```

前端测试覆盖支付回调不即刻发货、轮询/退款/超时恢复、sandbox 已付未授权、广告未看完不领奖、
SDK 异常清理和领奖后 access 确认。生成的 OpenAPI 快照及 TypeScript 类型与约束同步。

## 真机恢复时的验收步骤

1. 准备美国 Test User 账号、Android 测试设备和对应内测 TikTok，确认应用资料及 IAP/IAA 可用。
2. 确认测试后端部署本 PR，`ENV=staging` 且 sandbox 权益已允许，提供实际已上架测试剧和付费集。
   2026-10-19 只读检查时，测试域名 `/healthz` 正常，但 `/api/v1/dramas` 返回空列表，尚无可选在线剧集。
3. 按本地官方调试文档启动 CLI，显式勾选 `enableIAPMock`；不要把非 Mock 流程当作无扣款测试。
4. 从设备静默登录取得真实用户会话，创建 Beans 订单并确认只使用平台 Mock 流程。
5. 验证真实平台通知包含的字段、sandbox 标识与订单关联，再核对订单轮询、权益及播放身份。
6. 设备端完整观看广告/中途关闭各测一次，验证 claim、nonce 单次使用和对应集权限。

当前没有执行以上真机验收，也未向共享 staging 伪造订单或人工写入权益。
验签、发货与权益相关文件按 `CLAUDE.md` 必须由同事逐行 review 后合并。

## 文档依据

- [TikTok Payment APIs](https://developers.tiktok.com/docs/en/minis-payment-apis)：Beans 下单结构及档位校验。
- [TikTok Beans 集成指南](https://developers.tiktok.com/docs/en/tiktok-minis-in-app-purchases)：Webhook 为准和支付后轮询。
- 仓库原始资料：`docs/official/30-iap-beans.md`、`40-iaa-rewarded-ad.md`、`14-dev-debugging.md`。
