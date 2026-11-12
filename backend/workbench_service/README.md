# 工作台服务（workbench_service）

入口：在 `backend/` 下执行 `python -m workbench_service.server`（默认 `:8090`，`DE_HOST` / `DE_PORT` 可改）

| 文件 | 作用 |
|------|------|
| `server.py` | 服务入口：审查发起、SSE、材料代理、挂载 `frontend/` 静态页 |
| `auth.py` | 账号登录与权限（`config/users.local.yaml`） |
| `tasks_api.py` | 任务接口：一期任务列表 / 详情 / 复核 / 重试 |
| `flows_api.py` | 「流程与规则」页：流程定义、规则参数发布 |
| `compare_api.py` | 材料比对接口 |
| `auto_review.py` | 自动审查：资料就绪后按规则自动发起 |

对外只经本进程；原件与采集状态经 `storage_service.client` 转调存储服务。
