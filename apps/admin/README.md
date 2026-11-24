# apps/admin — 运营后台（W4, owner: FS）

尚未搭建。计划：React + Vite + Ant Design，独立部署（不进 minis 包），调用 `apps/api` 的 `/api/v1/admin/*`。

MVP 页面：
1. 剧目列表：标题、集数、review_status / publish_status、current/online version
2. 剧目编辑：录入剧集（源文件 OSS URL、封面）、免费集数、单集 Beans 价格
3. 媒资任务：上传进度、失败重试
4. 审核：一键送审、驳回原因展示（album/query 的 review_fail_reasons + 剧集级 exception_reason）、设线上版本、上下架

在后台做出来之前，先用 `apps/api/scripts/` 下的命令行脚本操作。
