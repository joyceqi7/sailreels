# packages/api-types

由后端 OpenAPI 自动生成的前端类型，**禁止手改**。

```bash
# 从已提交的 docs/openapi/v1.json 生成，无需启动后端
cd apps/web && npm run gen:api
```

修改接口的流程：改 `apps/api` 的 Pydantic 模型 → 在 apps/api 执行
`uv run python -m scripts.export_openapi` → 重新生成本目录 → 在同一个 PR 里提交。
完整基线与登录联调说明见 `docs/openapi/README.md`。
