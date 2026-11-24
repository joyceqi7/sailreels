# SailReels

> **关于这个仓库**：SailReels 是 Sailson 的 TikTok Minis 短剧小程序。我是核心开发，负责 W1–W4 四期迭代中的登录、支付、订阅和埋点链路，前后端都有参与。
>
> 这是公开展示版：只有最新代码，没有提交历史。TikTok 官方文档和各应用的生产配置已移除，平台 client key、广告位 ID 和服务器地址替换成了示例值，仓库不含任何凭据。

TikTok Minis short-drama mini app. Monorepo:

| Path | What |
|-|-|
| `apps/web` | Minis H5 (React + Vite), packaged with `ttdx minis build` → uploaded in Dev Portal |
| `apps/api` | Backend (FastAPI): login, entitlements, Beans/subscription webhooks, media library |
| `apps/admin` | Ops console (W4) |
| `docs/PLAN.md` | Plan, ownership, schedule |
| `docs/official/` | TikTok official docs (exported) |

Start here: `CLAUDE.md` (commands + hard rules).

OpenAPI v1 and auth integration: [`docs/openapi/README.md`](docs/openapi/README.md).
Worker/beat and Wayne's portal handoff: [`docs/worker-and-platform-handoff.md`](docs/worker-and-platform-handoff.md).

## Quick start

```bash
docker compose -p sailreels up -d db redis
cd apps/api && cp .env.example .env && uv sync && uv run alembic upgrade head \
  && uv run python -m scripts.seed_test_drama && uv run uvicorn app.main:app --reload --port 18800
# new terminal
cd apps/web && npm install && npm run dev      # http://localhost:5177
# new terminal (real device bridge)
cd apps/web && npx ttdx minis debug
```
