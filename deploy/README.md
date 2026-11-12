# 部署（客户 .39）

| 单元 | 作用 |
|------|------|
| `systemd/de-chrome.service` | 无头 Chrome（`chrome.sh`） |
| `systemd/de-resource.service` | 存储服务（资料中心）:8091 → `python -m storage_service.server` |
| `systemd/de-web.service` | 工作台 :8090（外网常映射 3039）→ `python -m workbench_service.server` |
| `de.env.example` | 环境变量模板 → `/data/digital-employees/de.env` |
| `llm.server.yaml` | 服务器使用的模型配置（`DE_LLM_CONFIG` 指向） |
| `install.sh` | 安装依赖与启用服务 |

代码落盘：`/data/digital-employees/app`（整个项目目录，含 `backend/`、`frontend/`、`config/`）
运行时：`/data/digital-employees/runtime`

两个 Python 服务的 unit 都设置了 `PYTHONPATH=/data/digital-employees/app/backend`。
后端包名或入口有变化时，重新执行 `install.sh` 覆盖 `/etc/systemd/system/` 下的 unit 文件，再重启服务。
