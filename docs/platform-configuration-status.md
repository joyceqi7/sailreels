# 平台配置记录

## SailReels（本仓库，2026-10-29 起）

| 项目 | 值 |
|---|---|
| 主体 | SAILSON PTE LTD（新加坡），8 Ubi Road 2, #08-16, Zervex, Singapore 408538 |
| App ID | `7000000000000000004` |
| 隐私政策 / 服务条款 | `https://sailreels.sailson.com/privacy`、`https://sailreels.sailson.com/terms`（内容在 `apps/api/app/legal/`，主体信息只改 `FACTS`） |
| 公开 clientKey | `mn_example_client_key`（`index.html` 与 `minis.config.json` 必须一致） |
| 激励视频广告位 | `ad7000000000000000001` |
| 插屏广告位 | 未创建 |
| 请求域名 / Webhook | `https://sailreels.sailson.com`、`https://sailreels.sailson.com/api/v1/webhooks/tiktok`（2026-10-29 已配，控制台 test event 已到达后端） |

此前仓库里记的 `mn_example_client_key` / `ad7000000000000000005` 已作废。

## SailShort（本仓库，尚未部署）

| 项目 | 值 |
|---|---|
| 主体 | BANG ENTERTAINMENT INC.（`LEGAL_ENTITY=bang_us`），登记号 `82-5480616` |
| 注册地址 | 100 S. Birch Rd., Suite 901, Jackson Tower, Fort Lauderdale, FL 33316, US |
| 联系 / DPO | `user1@example.com` |
| App ID | 未提供，不要编造 |
| 隐私政策 / 服务条款 | `https://sailshort.sailson.com/privacy`、`https://sailshort.sailson.com/terms`（主体事实在 `apps/api/app/legal/__init__.py` 的 `bang_us`） |
| 公开 clientKey | `mn_example_client_key`（`apps/web/.env.sailshort`，构建时写入 `index.html`） |
| 激励视频广告位 | `ad7000000000000000003` |
| 插屏广告位 | 未创建 |
| 请求域名 / Webhook | `https://sailshort.sailson.com`、`https://sailshort.sailson.com/api/v1/webhooks/tiktok`（部署时再配到 TikTok Developer Portal） |
| 变现 | IAA（`VITE_MONETIZATION=iaa`，服务器 `MONETIZATION_MODE=iaa`） |
| 构建 | `cd apps/web && npm run build:sailshort` |
| 部署命名 | 目录 `/opt/sailshort`，compose 项目 `sailshort`，API 别名 `sailshort-api`，Caddy 片段 `deploy/caddy-snippet-sailshort.conf` |

媒资不与 SailReels / SailTale 共用，各自的 BytePlus 空间单独上传、送审、上架。`client_secret` 只放服务器 `apps/api/.env`，不入库。本地 `apps/web/minis.config.json` 仍是 SailReels，给默认的 `ttdx minis debug` 用；SailShort 的 clientKey 以 Vite mode 注入的 `index.html` 为准。

## ZorvTales（已归供应商，以下为 2026-10-13 历史记录）

记录日期：2026-10-13。以下状态来自实际 TikTok Dev Portal，属于平台开通与配置验收，
不代表应用已发布或真实支付、订阅和广告链路已联调通过。

## 应用与主体

| 项目 | 已核验值 |
|---|---|
| 主体 | BANG ENTERTAINMENT INC. |
| 组织 ID | `7616632010328622091` |
| 应用 | ZorvTales |
| App ID | `7694134277340448786` |
| 公开 clientKey | `mn_example_client_key` |
| 当前发布状态 | 未发布 |

## 开通与广告位

| 项目 | 实际状态 |
|---|---|
| 短剧 IAP（活力豆和订阅） | 主体级已开启，控制台日期为 2026-10-08 |
| 短剧 IAA | 主体级已开启，控制台日期为 2026-10-08 |
| 激励视频广告位 | 名称 `ZorvTales`，ID `ad7000000000000000006`，原已创建并启用 |
| 插屏广告位 | 名称 `ZorvTales 插屏广告`，类型“插页广告”，ID `ad7000000000000000007`，2026-10-13 补建并启用 |

本次核验了已开通状态，没有重新签署合同，也没有获取已签合同文件或确认合同版本。
如需合同归档，由 Wayne 或有权签署人提供已签文件。控制台明确提示：广告位的启用状态在应用上线后生效。

前端统一配置在 `apps/web/src/minis/ad-config.ts`，也可由 `.env.example` 中的公开变量覆盖。
激励广告辅助函数默认使用上述 ID；插屏配置供后续页面接入，不自动展示。

## 请求域名与支付、订阅 Webhook

2026-10-12 已在应用开发配置保存以下值：

| 配置 | 保存值 |
|---|---|
| 请求域名白名单 | `https://zorvtales.sailson.com` |
| 应用级 Webhook | `https://zorvtales.sailson.com/api/v1/webhooks/tiktok` |
| 控制台测试回调 | Send test event 返回 `200 OK` |

当前控制台只有统一的应用级 Webhook 地址，支付和订阅使用同一入口。
测试回调成功验证了平台测试请求的公网可达与响应，不等于真实订单、退款、订阅八类事件均已处理验收。
本次未逐项确认所有业务事件的订阅状态；真实联调时需发送各类事件并核对后端落库、幂等和权益结果。

## 后续验收

- 前端解锁面板及插屏展示接入，验证完整观看、中途关闭、加载失败、低版本能力降级和插屏冷却。
- TikTok 真机登录、支付、退款与订阅事件联调；平台测试回调不能替代真实业务验收。
- 发布前核验应用资料、商品档位/Tier ID、测试账号、媒资与播放器，以及平台要求的上线条件。
- token 定时刷新沿用默认暂停配置，真实联调恢复后按交接说明开启并验证。

本记录只保存公开标识、回调地址和验收结果。真实 `client_secret`、token、银行及税务资料不入库。
