# 部署到 tt-shop-prod（203.0.113.10）

这台机器同时跑着 pubgm-* 和 tts-* 两套服务。我们的东西必须做到：**不占宿主机端口、不动现有容器的网络和数据、内存有上限**。

## 当前状态（2026-10-29 已部署 staging）

SailReels 已于 2026-10-29 部署（`ENV=staging`），健康检查、验签、CORS、真实签名 Webhook 与
client_credentials 换 token 均已验收。同一台机器上的旧 ZorvTales 栈仍在运行
（项目名 `zorvtales`、目录 `/opt/zorvtales`、域名 `zorvtales.sailson.com`），那是另一个 App，
归供应商使用。两套栈互相独立，不要复用 `zorvtales` 的容器或数据卷。

| 项 | 值 |
|-|-|
| 服务器 | tt-shop-prod = 203.0.113.10（阿里云硅谷，7.1G 内存无 swap） |
| 代码目录 | `/opt/sailreels`，用 ssh 别名 `github.com-zorvtales`（部署密钥 `/root/.ssh/zorvtales_deploy_key`）克隆 |
| Compose 项目名 | `sailreels`（容器 `sailreels-{api,db,redis,worker,beat}`） |
| 入口 | Caddy 容器 `tts-caddy`，走 `deploy_backend` 网络，转发到别名 `sailreels-api:8000` |
| 域名 | `sailreels.sailson.com`，A 记录已指向本机，证书由 Caddy 自动申请 |
| 数据卷 | `sailreels_pgdata` / `sailreels_beatdata`，与旧的 `zorvtales_*` 完全隔离 |

> **改名会影响数据卷**：compose 项目名和 `POSTGRES_DB` 都从 `zorvtales` 改成了 `sailreels`，
> 所以 `docker compose -p sailreels up` 会创建**全新的空数据库**，旧的 `zorvtales_pgdata` 不会被挂载。
> 这是有意为之——两个 App 的数据必须分开。如果确实要把旧库的数据带过来，需要显式 `pg_dump` / `pg_restore`，
> 不要指望改个名字就自动继承。

重启服务：

```bash
ssh tt-shop-prod 'cd /opt/sailreels && docker compose -p sailreels --env-file apps/api/.env -f docker-compose.prod.yml restart api'
```

## ⚠️ Caddyfile 配置漂移（必须处理）

`/opt/tt-shop/deploy/Caddyfile` **由 tt shop 仓库跟踪**，我们追加的站点现在是该文件的「本地未提交修改」（`M deploy/Caddyfile`）。

**风险**：tt shop 下次部署执行 `git pull` 时，可能因冲突失败，或把这段覆盖掉，`sailreels.sailson.com` 直接断掉。改动前的备份在 `/opt/tt-shop/deploy/Caddyfile.bak.<时间戳>`。

**处理办法**：把追加的 `caddy-snippet.conf` 内容正式提交进 tt shop 仓库（需与 tt shop 负责人确认）。在此之前，每次部署 tt shop 前先确认 `sailreels.sailson.com/healthz` 仍返回 200。

## 一次性准备

```bash
# 1) 磁盘：构建缓存占 31.65G，其中 29.8G 可回收（不动任何运行中的容器）
ssh tt-shop-prod 'docker builder prune -f'

# 2) DNS：阿里云加 A 记录  sailreels.sailson.com -> 203.0.113.10（Caddy 签证书前必须能解析）

# 3) 拉代码
ssh tt-shop-prod 'git clone https://github.com/weienwang919-web/ZorvTales.git /opt/sailreels'
```

`docker builder prune` 的影响：只删构建缓存，运行中的容器不受影响；以后 tt shop 重建镜像会慢几分钟。

## 配置

```bash
ssh tt-shop-prod
cd /opt/sailreels
cp deploy/env.prod.example apps/api/.env

# 生成一次密码，同时写进 POSTGRES_PASSWORD 和 DATABASE_URL —— 两处必须是同一个值
# （.env 是纯文本，没有插值，漏改一处会导致容器连不上库）
PGPW=$(openssl rand -hex 24)
sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$PGPW/" apps/api/.env
sed -i "s|^DATABASE_URL=.*|DATABASE_URL=postgresql+asyncpg://sailreels:$PGPW@db:5432/sailreels|" apps/api/.env
sed -i "s/^SESSION_SECRET=.*/SESSION_SECRET=$(openssl rand -hex 32)/" apps/api/.env

# 手工填 TIKTOK_CLIENT_SECRET（不要经过命令行历史）
vi apps/api/.env

# 自查：client_secret 只应出现在 apps/api/.env 里，不应出现在 Dockerfile 或 compose 中
grep -c "TIKTOK_CLIENT_SECRET" apps/api/.env
```

## 启动

```bash
cd /opt/sailreels
# --env-file 必须带：POSTGRES_PASSWORD 是 Compose 在插值阶段读的，不是容器内的 env_file。
# 不带会报 "POSTGRES_PASSWORD is missing"。
docker compose -p sailreels --env-file apps/api/.env -f docker-compose.prod.yml up -d --build
docker compose -p sailreels --env-file apps/api/.env -f docker-compose.prod.yml ps
```

迁移不用手动跑：api 容器的启动命令是 `alembic upgrade head && uvicorn ...`，会先迁移再起服务。

命令太长，建议在服务器上加个别名：

```bash
echo "alias sc='docker compose -p sailreels --env-file /opt/sailreels/apps/api/.env -f /opt/sailreels/docker-compose.prod.yml'" >> ~/.bashrc
```

## 加 Caddy 站点（会动到生产配置，逐步确认）

```bash
# 把 deploy/caddy-snippet.conf 里的 block 追加到 /opt/tt-shop/deploy/Caddyfile
ssh tt-shop-prod 'vi /opt/tt-shop/deploy/Caddyfile'
# 先校验，再 reload（校验失败会保留旧配置，现有站点不受影响）
ssh tt-shop-prod 'docker exec tts-caddy caddy validate --config /etc/caddy/Caddyfile'
ssh tt-shop-prod 'docker exec tts-caddy caddy reload --config /etc/caddy/Caddyfile'
curl -sS https://sailreels.sailson.com/healthz
```

**同时把这段提交到 tt shop 的仓库**（该 Caddyfile 由 tt-shop 仓库跟踪），否则下次 tt shop 重新部署 Caddy 会把这段覆盖掉。

## 验收

```bash
curl -sS https://sailreels.sailson.com/healthz                    # {"ok":true,"env":"staging"}
curl -sS -X POST https://sailreels.sailson.com/api/v1/webhooks/tiktok \
  -H 'TikTok-Signature: t=1,s=x' -d '{}' -o /dev/null -w '%{http_code}\n'   # 401 = 验签生效
curl -sS -o /dev/null -w '%{http_code}\n' \
  https://sailreels.sailson.com/api/v1/dramas/1/episodes           # 401 = 需要登录，符合预期
```

控制台「请求域名」白名单填 `sailreels.sailson.com`；支付与订阅的 Webhook 地址都填
`https://sailreels.sailson.com/api/v1/webhooks/tiktok`。

## 出问题怎么回退

```bash
sc down                      # 只停我们的容器（用上面的别名）
# Caddy：把追加的 block 删掉再 validate + reload，现有站点全程不受影响
```

回退时数据库卷会保留；要彻底清掉用 `sc down -v`（会删掉短剧的库，不影响 tt shop 和 pubgm）。

## SailShort（同一套代码，独立栈，尚未部署）

不要和 SailReels 或 SailTale 共用目录、compose 项目、数据库卷、Caddy 别名、client secret 或已送审剧目。按上面的 SailReels 步骤换名字即可。本文件不执行部署。

| 项 | 值 |
|-|-|
| 代码目录 | `/opt/sailshort` |
| Compose 项目名 | `sailshort`（`docker compose -p sailshort --env-file apps/api/.env -f docker-compose.prod.yml up -d --build`） |
| Caddy 站点 | `sailshort.sailson.com`，片段 `deploy/caddy-snippet-sailshort.conf`，反代 `sailshort-api:8000` |
| 服务器 `.env` | `APP_NAME=SailShort`，`LEGAL_ENTITY=bang_us`，`API_ALIAS=sailshort-api`，`MONETIZATION_MODE=iaa` |
| 公开 client key | `TIKTOK_CLIENT_KEY=mn_example_client_key`。`TIKTOK_CLIENT_SECRET` 只写在这台机器的 `apps/api/.env`，用占位符入库 |
| 域名 | `PUBLIC_API_ORIGIN=https://sailshort.sailson.com`，`CORS_ORIGINS` 改成该域名（不要留 SailReels 的源） |
| Webhook | `https://sailshort.sailson.com/api/v1/webhooks/tiktok` |
| 前端包 | `cd apps/web && npm run build:sailshort`（Vite mode `sailshort`，读 `apps/web/.env.sailshort`） |
| 主体 | BANG ENTERTAINMENT INC.，登记号 82-5480616，地址 100 S. Birch Rd., Suite 901, Jackson Tower, Fort Lauderdale, FL 33316, US |

SailShort 的剧必须上传到它自己的 BytePlus 空间并单独送审。`album/authorize` 不能把 SailReels 或 SailTale 的剧目授给这个 client key。部署前还要做的事：DNS 把 `sailshort.sailson.com` 指到这台机器、把 Caddy 片段追加进 tt-shop 的 Caddyfile 并提交到 tt-shop 仓库、在 TikTok Developer Portal 配好受信域名和 Webhook、填好该 App 自己的 `TIKTOK_CLIENT_SECRET` 和 BytePlus 空间。App ID 未提供，不要编。
