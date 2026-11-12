# 后端

本目录是 Python 源码根：服务器经 `PYTHONPATH=…/app/backend` 加载；本地在此目录下执行 `python -m <包>.<模块>`。

| 包 | 类型 | 说明 |
|----|------|------|
| [`workbench_service/`](workbench_service/) | 服务 :8090 | 工作台：登录、任务列表、发起审查、SSE、复核、托管前端 |
| [`storage_service/`](storage_service/) | 服务 :8091 | 存储服务（资料中心）：采集、下载、解析·OCR、原件存储 |
| [`meeting_review/`](meeting_review/) | 数字员工 | 三会智能审查（SH） |
| [`procurement_review/`](procurement_review/) | 数字员工 | 采购审批（CG） |
| [`contract_review/`](contract_review/) | 数字员工 | 合同审核（CT） |
| [`reimburse_review/`](reimburse_review/) | 数字员工 | 财务报销初审（BX） |
| [`employee_registry/`](employee_registry/) | 注册中心 | 四个员工的登记、流程定义、场景能力 |
| [`shared/`](shared/) | 公共能力 | 取数适配、会话、解析·OCR、规则框架、大模型、制度库、任务库 |

命名约定：

- 服务以 `_service` 结尾，入口统一是 `server.py`。
- 数字员工以 `_review` 结尾，内部结构统一（见 `employee_registry/README.md`）。
- 四个员工之间禁止互相 import，共用的东西放进 `shared/`。
