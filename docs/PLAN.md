# SailReels — TikTok Minis 短剧小程序 开发计划 v0.2

> 2026-10-27 W3 更新：Joyce 继续接管订阅前后端、进度、个人中心和预加载；本轮代码交付及真实验收条件见 [W3 交接说明](w3-2026-10-27-handoff.md)。BytePlus 试传按用户要求保持暂停。

> 2026-10-23 接管更新：Joyce Zhang 接管原 X Qi 的前端开发。本轮范围为看板中两人截止 10/23（含当日）的 13 项任务；代码与自动化交付、真实设备验收分别记录，见 [交付清单](w2-2026-10-23-handoff.md)。下文原排期保留用于追溯，Wayne 继续负责外部依赖。

> 依据：飞书「TikTok Minis 小程序开发指南ALL IN ONE」中链接的 14 份文档（原文已导出到代码仓库 `docs/official/`）
> 前提：3 人（前端 FE / 后端 BE / 全栈 FS）；首发美国；IAA + Beans + 订阅全量；企业认证、行业准入、EIS/USDS 已通过；BytePlus、片源、美区服务器尚未就绪
> 目标：**11/27（周五）前上线**，今天是 10/10（周六），开发从 10/12 开始

---

## 0. 结论先行

| 项 | 结论 |
|-|-|
| 工作量 | 约 **85 人天**（含联调）。3 人到 11/20 共约 90 人天，**可以完成，但几乎没有余量** |
| 关键路径 | ① 片源和媒资审核：平台规定**新开发者只能播放媒资审核通过的内容**，任意一集被拒，整个版本都不能播 ② 订阅 SKU 和 Tier ID 审批，最长 2 周 ③ BytePlus 开户 ④ 小程序提审 1–3 个工作日 |
| 必须本周发起的外部事项 | 上面 ①②③，以及美区测试账号和设备。**这几件晚一天开始，上线就晚一天** |
| 时间不够时先砍的 | 开发者优惠券（HMAC 签名）、多清晰度/HLS、运营后台的申诉 UI、平台券 QCPX。这些都不影响首发 |

---

## 1. 技术形态（先统一认知）

TikTok Minis **不是**微信那种 DSL 小程序，而是：

```
标准 Web 应用(H5)  +  window.TTMinis JSAPI  +  minis CLI(dev/build)
       │                    │                         │
   我们的 React 页面    登录/支付/订阅/广告/播放器      minis build → minis.zip → 控制台上传
```

- 前端产物是**静态包**，由 TikTok 托管，我们不用部署前端
- 我们要部署的只有**后端 API**（加运营后台），域名配在控制台的请求域名白名单里
- 视频**必须**走 BytePlus VOD 加平台播放器 VePlayer。不能自带播放器，也不能另外引入 `@byteplus/veplayer`
- 真机调试的方式：页面跑在电脑浏览器里，客户端能力通过扫码桥接到 Android 手机上的 TikTok **内测包**。iOS 只能上传后扫预览码看

---

## 2. 系统架构

```
┌──────────────── TikTok App (WebView) ────────────────┐
│  SailReels H5 (React+TS+Vite, minis.zip)             │
│  ├─ 剧场/首页  ├─ 播放页(VePlayer, playNext, 预加载)  │
│  ├─ 解锁面板(广告 / Beans 高中低档)  ├─ 订阅页        │
│  ├─ 我的/钱包/观看历史                                │
│  └─ sdk 适配层: login / pay / createSubscription /   │
│     createRewardedVideoAd / reportEvent / canIUse    │
└───────────────┬──────────────────────────────────────┘
                │ HTTPS (api.<域名>)
┌───────────────▼──────── 阿里云 美国(硅谷) ────────────┐
│  FastAPI (api)          Celery worker + beat          │
│  ├─ auth: code→token, 刷新     ├─ 媒资上传/审核轮询    │
│  ├─ catalog: 剧/集/进度        ├─ token 定时刷新       │
│  ├─ entitlement: 解锁判定      ├─ 订阅对账兜底         │
│  ├─ pay: Beans 下单+Webhook    └─ 失败重试            │
│  ├─ subscription: 下单+8类Webhook                     │
│  ├─ ad_reward: 广告解锁(一次性 nonce)                 │
│  └─ admin API ←── 运营后台 SPA (React+AntD)           │
│  PostgreSQL(RDS) · Redis · OSS(片源中转,公网可读URL)   │
└───────┬───────────────────────────┬───────────────────┘
        │ open.tiktokapis.com       │
   TikTok OpenAPI ──────────── BytePlus VOD (存储/转码/CDN)
   (oauth / trade_order / subscription / sg/shortdrama 媒资)
```

### 2.1 技术栈

| 层 | 选型 | 理由 |
|-|-|-|
| 前端 | React 19 + TypeScript + Vite | 官方 Demo 和 `plugins/minis-player/` 是 TS，可以直接 fork |
| 后端 | **Python 3.12 + FastAPI** + SQLAlchemy 2 + Alembic | 主要靠 AI 写代码，AI 写 FastAPI 很稳。前后端类型不一致的问题，用 FastAPI 自动生成的 OpenAPI 加 `openapi-typescript` 生成前端类型来解决，效果和 Node 共享类型差不多 |
| 任务 | Celery + Redis (beat 跑定时任务) | 媒资是异步 job，需要轮询；token 刷新和对账都是定时任务 |
| DB | PostgreSQL（阿里云 RDS 美西） | 订单、订阅、权益都要求强一致；JSONB 可以存原始 Webhook |
| 后台 | React + Ant Design，单独部署 | 不打进 minis 包 |
| 部署 | ECS + Docker Compose + Nginx (HTTPS) | 规模小，先不上 K8s |

### 2.2 核心数据模型（初稿）

```
user(open_id PK, access_token, refresh_token, access_exp, refresh_exp, nickname, avatar, beans_balance?)
drama(id, album_id, title, current_version, online_version, review_status, publish_status, free_episodes, ...)
episode(id, drama_id, episode_id, seq, byteplus_vid, unlock_price_beans, ...)   ← episode_id 每次 album/update 后用 episode_id_map 回写
media_job(id, type[video|image|subtitle], source_url, job_id, vid/open_pic_id, status, retries)
entitlement(open_id, drama_id, episode_seq, source[free|ad|beans|subscription], ref_id, created_at)  UNIQUE(open_id,drama_id,episode_seq)
beans_order(order_id PK, trade_order_id UNIQUE, open_id, sku, token_amount, status, is_sandbox)
subscription(subscription_id PK, open_id, tier_id, rights_valid, renewal_normal, benefit_end_time, is_sandbox)
webhook_event(id, event, dedup_key UNIQUE, raw JSONB, processed_at)            ← 所有 Webhook 先落库再处理
ad_reward(nonce PK, open_id, drama_id, episode_seq, status, created_at)
watch_progress(open_id, drama_id, last_seq, position)
```

### 2.3 必须事先约定的设计决策

1. **权益判定只在后端做**。前端调 `GET /episodes/{id}/access`，后端返回 `free / unlocked / locked + 可用解锁方式`
2. **支付和订阅以 Webhook 为准**。前端回调只用来触发轮询。所有 Webhook 先验签，再按幂等键落 `webhook_event`，最后处理
3. 订阅的幂等键**不能只用 trade_order_id**，因为 cancel 和 renew 都会生成新的 trade_order_id。`onhold` 和 `expire` 事件只带 subscription_id，所以要维护 `subscription_id → open_id` 映射
4. 有没有权益只看 `benefit_end_time` 和 `is_subscription_rights_valid`，不看状态名
5. 广告解锁：激励广告**没有服务端回调**，只能前端判断 `isEnded`。做法是：后端在广告展示前发一个一次性 nonce，前端看完后带 nonce 来领奖，后端校验 nonce 只能用一次，并做频控。这是我们自己加的风控
6. 广告时机是硬规定：激励广告只能在「本集看完、进入下一集前」或「用户主动跳集或拖进度条」时出现，**禁止在剧集中途无操作时弹出**，也禁止自动连播时自动弹
7. `is_sandbox=true` 的订单一律不发真实权益，也不计入 GMV
8. 最低基础库版本设为 44.9.0 以上（不用接 play_token）。IAA 需要 44.2.0 以上，低版本用 `canIUse` 判断后提示用户升级

---

## 3. 分工

| 角色 | 负责模块 | 估算 |
|-|-|-|
| **FE 前端 — X Qi** | 工程脚手架和 SDK 适配层 · 首页/剧场/详情 · **播放页**（VePlayer、单实例 playNext、预加载、错误码提示）· 解锁面板（广告/Beans 高中低档）· 订阅页（三种状态、平台券展示）· 我的/钱包/历史 · IAA 前端 · `reportEvent` 中间事件埋点（IAP 9 个 + IAA 3 个）· 英文文案 · canIUse 降级 | ~30 人天 |
| **BE 后端 — Joyce Zhang** | 登录/token 存储与刷新 · 剧集目录 API · **权益服务** · Beans 下单 + Webhook + 轮询接口 · **订阅全链路**（create/reactivate/查询 + 8 类 Webhook + 状态机 + 对账任务）· 广告领奖接口 · Webhook 验签框架 · OpenAPI 契约 | ~30 人天 |
| **FS 全栈 — Wayne Wang** | **基础设施**（阿里云美西 ECS/RDS/Redis/OSS、域名、HTTPS、CI/CD）· **媒资流水线**（上传/转码/建剧/版本/送审/轮询/上架，episode_id 回写）· 运营后台 · 片源上传和审核跟进 · 真机/账号/内测包环境 · 版本上传、提审、发布 · 播放失败率统计 | ~25 人天 + 联调 |
| **对外接口人 — Wayne Wang**（兼） | BD/客户经理对接、外部申请（见 §4）、文档矛盾确认、片源和版权、条款与隐私文本 | 每天约 1 小时 |

分工原则：**按「端到端链路」划分 owner，不按技术层划分。** 比如 Beans 支付这条链路由 BE 负责到底，FE 只负责调用；联调出问题时，由链路 owner 牵头排查。

---

## 4. 外部依赖清单（第一周全部发起）

| # | 事项 | 对接方 | 周期 | 阻塞什么 | 建议 owner |
|-|-|-|-|-|-|
| 1 | BytePlus：**先自助注册开户、建空间**（按量付费，当天可用）；同时填问卷，走签约拿优惠价 | BytePlus | 开户约 1 天；签约约 2 周 | 媒资上传，**不用等签约** | FS + 接口人 |
| 2 | TTOP 控制台 Media asset management → Activate → 填 AK/SK | 控制台 | 当天 | 媒资 API | FS |
| 3 | **SKU 提报**：Beans 档位 + 订阅 SKU 集（周/月/年等），拿 Tier ID | Dev Portal + BD | **最长 2 周** | 订阅正式上线（开发可以先用 sandbox 档位） | 接口人 |
| 4 | 签 IAP 合同，开 IAA；创建激励/插屏广告位并**手动激活**；配置支付和订阅 Webhook 地址 | Dev Portal | 当天 | 支付/广告联调 | BE |
| 5 | 基础信息：图标 600×600、名称、描述、**两份独立的**服务条款和隐私政策 URL、Apple Team ID、申诉邮箱（开双重验证）、版权自检表 | Dev Portal | 随审核 | 登录（不填会报 102102）、提审 | 接口人 |
| 6 | **片源（由下游供应方提供）**：每部剧至少 50 集、每集至少 60 秒、1080P 以上、无水印、英文配音或字幕、有版权链路证明（授权书 + 版权链）；AIGC 内容要标注。**需要和供应方约定：交付格式（MP4，moov 前置）、交付方式（OSS / 网盘）、英文字幕文件（SRT/VTT）、封面，以及被拒集的重新交付时限（建议 48 小时内）** | 下游供应方 | — | **第一部剧必须在 10/24 前交到我们手上，10/26 送审** | 接口人 |
| 7 | 美区测试环境：至少 2 个美国 TikTok 账号（年满 18 岁，1 个加入 Test User，1 个不加）、美区 Google Play 账号、美国代理、Android 真机装 M 包内测版 | 自备 | 1–2 天 | 所有真机联调 | FS |
| 8 | 阿里云美西服务器、域名、HTTPS 证书（不需要 ICP 备案） | 阿里云 | 1 天 | Webhook 联调，**第一周必须有公网 HTTPS** | FS |
| 9 | 投放准备：在 BC 做资产登记（r29），把 ADV ID 交给客户经理加白 | BC / BD | 未知 | 投放（不阻塞上线） | 接口人，第 6 周做 |
| 10 | 文档矛盾清单发 BD 确认（见 §8） | BD | — | 订阅接口地址等 | 接口人 |

---

## 5. 排期（6 周开发 + 1 周审核）

| 周 | 日期 | FE | BE | FS | 里程碑 |
|-|-|-|-|-|-|
| W1 | 10/12–16 | 脚手架、SDK 适配层；**用官方测试剧跑通 VePlayer 和 playNext** | 登录、token 刷新；数据模型；OpenAPI 契约 v1；Mock Server | 美西环境、域名、CI；minis CLI hello world 在真机跑通；BytePlus 开户；测试账号 | **M0（周五）：真机上能登录并播放测试剧** |
| W2 | 10/19–23 | 首页、详情、播放页 UI；解锁面板；IAA（Mock） | Beans 下单 + Webhook + 轮询（Mock）；权益服务；广告领奖 | 媒资 API client、视频和封面上传流水线 | Beans 和广告解锁在 Mock 下闭环 |
| W3 | 10/26–30 | 订阅页；我的/钱包/历史；预加载 | 订阅 create/reactivate/查询；8 类 Webhook；状态机 | 版本、送审、轮询、上架；episode_id 回写；**第一部真实剧送审** | **M1：第一部剧送审** |
| W4 | 11/2–6 | `reportEvent` 埋点；错误码兜底；canIUse 降级；英文文案 | 订阅对账任务；跑 Mock 订阅全周期（约 1 小时一轮）；风控 | 运营后台；播放失败统计；批量上传所有首发剧 | **M2：功能冻结，所有链路可用** |
| W5 | 11/9–13 | 联调、修 bug、iOS 预览验证 | 联调、修 bug、对账 | 测试矩阵执行；首发剧全部过审并上架 | 测试矩阵通过 |
| W6 | 11/16–20 | 修复 | 修复 | **11/18 上传正式包并提审** | **M3：提审** |
| W7 | 11/23–27 | 处理驳回 | 处理驳回 | 发布；BC 资产登记 | **M4：上线** |

审核时长是 1–3 个工作日，被驳回一次再加 2–3 天，所以 11/18 提审在 11/27 前大概率能通过一次驳回后上线。**如果到 W2 结束时进度明显落后，就从 §0 的可砍清单里先砍。**

---

## 6. 协作方式

### 6.1 仓库与分支
- **Monorepo**（GitHub 或 Codeup）：
  ```
  apps/web      # Minis H5
  apps/admin    # 运营后台
  apps/api      # FastAPI + worker
  packages/api-types   # 由 OpenAPI 自动生成，禁止手改
  docs/         # 14 份官方文档的 markdown 原文 + 本计划 + ADR
  CLAUDE.md     # AI 编码规范 + 文档索引（重要，见 6.4）
  ```
- 主干开发：在 `main` 上开短分支，PR 至少 1 人 review，CI 要跑通 lint、类型检查和测试。
- 环境：本地（`minis dev` 连 staging API）、staging（`api-staging.` 域名 + 控制台 preview 版本）、prod。

### 6.2 接口契约优先
- BE 先出 OpenAPI，`make types` 生成 TS 类型，FE 用 Mock Server 并行开发，不用等后端实现。
- 修改接口一律通过 PR 修改 schema，CI 检查生成的类型有没有同步更新。

### 6.3 节奏
- **每日站会 15 分钟**（也可以在飞书群异步）：昨天做了什么、今天做什么、卡在哪里。被外部依赖卡住的事当天上报给接口人。
- **每周五 Demo**：在真机上演示本周闭环的链路，对照里程碑。
- 任务看板用飞书多维表格，字段：模块 / owner / 状态 / 依赖 / 截止日期。
- 关键决策写成 ADR（`docs/adr/NNN-xxx.md`），每份半页即可。

### 6.4 AI 编码约定（既然主要用 AI 写代码）
- 把 `docs/` 里的官方文档原文放进仓库，由 `CLAUDE.md` 索引。**写某条链路之前先让 AI 读对应文档**，比如订阅读 r24，媒资读 r16。
- 在 `CLAUDE.md` 里写死 §2.3 那 8 条设计决策，以及「不要另外引入 @byteplus/veplayer」「client_secret 不能下发到前端」这类硬约束。
- **Webhook 验签、幂等、权益判定这三处代码必须人工逐行 review**，不能只依赖 AI 的自测。

### 6.5 测试矩阵（W5 执行）
- 登录：首次登录、token 过期刷新、refresh 失效后重新登录
- Beans：余额足够、余额不足需要充值、取消支付、Webhook 延迟到达、重复 Webhook、退款
- 订阅：create → renew ×N → cancel → reactivate → onhold → 恢复 → expire（Mock 每 5 分钟续费一次）；refund 和 revoke
- 广告：看完、中途关闭、拉取失败、低版本 canIUse=false
- 播放：切集、预加载命中、9303/9304/9310 等错误码、iOS 低电量模式、弱网
- 账号：Test User 账号和普通账号**都要测**（Test User 会看到灰度版本）

---

## 7. 主要风险

> ⚠️ Wayne 同时担任全栈和对外接口人，是全队最重的角色（W1 有 6 件对外事项 + 基础设施 + 真机环境）。W1 建议 Joyce 分担 Dev Portal 配置（IAP 合同/广告位/Webhook 地址），X Qi 分担测试账号和真机准备。


| 风险 | 影响 | 对策 |
|-|-|-|
| 片源晚到或审核被拒 | **直接延期上线**；一集被拒，整个版本不能播 | 10/26 前先送审 1 部；W5 前所有首发剧过审；和供应方签好被拒集 48 小时内重新交付的条款 |
| 首发部数未定 | 媒资上传和审核的工作量没法估 | **10/17 前定下首发部数**。建议 3–5 部：太少用户留不住，太多审核排不过来 |
| 订阅 Tier ID 迟迟拿不到 | 订阅无法上线 | W1 提报；如果 11/13 还拿不到，首发先只上 IAA 和 Beans，订阅做开关 |
| 美区账号或设备被风控 | 联调停摆 | 多备 1–2 个账号；账号地区、商店地区、代理地区三者一致 |
| 文档矛盾（见 §8） | 返工 | W1 统一发给 BD 确认；在确认前，涉及的代码用实际接口测一遍再写死 |
| 3 人没有余量 | 任何一人请假都会延期 | 每周五对照里程碑，落后就砍范围，不加班硬扛 |

---

## 7.5 代码仓库与看板

- 代码仓库：https://github.com/weienwang919-web/ZorvTales （私有，请把同事加为协作者）
- 任务看板：https://jjn12v6w4l.feishu.cn/wiki/TOYlwbsxQiCAMjkfTIccx7IInif （46 条任务；视图：全部任务 / 按负责人 / 按周次 / 状态看板 / 每人一个「XX 的任务」）

骨架已经搭好：
- `apps/web`：基于官方 demo，打包后 `ttdx minis check` 已通过；`src/minis/` 封装了登录、支付、订阅、广告和埋点
- `apps/api`：FastAPI，包含登录、权益判断、Beans 下单、广告 nonce、订阅下单、统一 Webhook 入口（验签 + 幂等 + 8 类订阅事件），8 个测试通过；数据库迁移已在 Postgres 上跑通
- `apps/api/app/services/media.py` + `scripts/media.py`：媒资流水线（上传轮询、建版本并回写 episode_id、送审、审核状态同步、过审才能上架），命令行可直接驱动，不用等 Celery
- `GET /dramas/{id}/episodes`：一次返回剧集列表和每集的观看权限，**未解锁的集不返回 vid**
- `CLAUDE.md`：AI 编码规范、文档索引、15 条硬约束

## 8. 需要 BD 确认的文档矛盾

1. 订阅下单接口：`open-api.tiktok.com/api/v1/payment/createSubscriptionTradeOrder` 还是 `open.tiktokapis.com/v2/minis/subscription/create/`？（按 v2 开发）
2. 订阅 Mock 的续费规则：每 5 分钟续一次、共 12 次后到期，还是 5 分钟后直接过期？
3. 渠道费：Apple 和 Google 的 Beans 费率，SKU 章节和结算章节写的正好相反
4. 订阅结算是 T+60 还是 T+5 月结？
5. 归因：7D CTA，还是 IAP 180 天 / IAA 7 天 Last Click？
6. 投放 URL 能不能追加参数？
7. 媒资 `album/create` 的请求参数表是空的；`tag_list` 示例里的 `[101]` 不在合法范围内
8. 中间事件 Q&A 要求带 `timestamp`，但事件参数表里没有这个字段
9. 平台分成比例（文档里没写）
