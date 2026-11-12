# 存储服务（资料中心 · storage_service）

独立进程，负责原件与解析结果的采集、存储和读取；工作台只经 HTTP 访问，不直连库文件。

| 文件 | 作用 |
|------|------|
| `server.py` | 服务入口：HTTP 接口（默认 `:8091`） |
| `service.py` | 业务：取单、同步、读 blob、采集调度 |
| `store.py` | 资料中心库：SQLite + 原件 / 解析 / 截图路径 |
| `collector.py` | 定时 / 立即采集 |
| `listers.py` | 各来源系统的待办 / 已办列表拉取 |
| `client.py` | 工作台侧客户端（`http` / `inprocess`） |
| `fingerprint.py` | 单据快照指纹（判定资料是否变化） |
| `shots.py` | 原件页截图与证据定位 |
| `image_trim.py` | 截图留白裁剪 |
| `desensitize.py` | 入档脱敏（URL 参数、敏感字段） |
| `settings.py` | 读取 `config/resource.yaml`、`config/collect.yaml` |

运行：在 `backend/` 下执行 `python -m storage_service.server`
配置：`config/resource.yaml`、`config/collect.yaml`
数据：`DE_RUNTIME/resource/`、`DE_RUNTIME/store/`
解析·OCR 由本服务调用 `shared/parsing/`，不单独起进程。
