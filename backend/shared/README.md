# 公共能力（shared）

工作台、存储服务和四个数字员工共用的底座，不包含任何单个员工的业务规则。

| 目录 / 文件 | 作用 |
|-------------|------|
| `source_adapters/` | 客户系统只读取数适配器：合同管理系统、公文系统、通财云、本地事项 |
| `parsing/` | 解析·OCR（由存储服务调用，见该目录 README） |
| `rule_framework/` | 规则框架：执行引擎、统一状态、通用判断、语义比对 |
| `regulation_kb/` | 制度知识库：制度 PDF → 条款、检索与金额档位核验 |
| `external_lookup/` | 外部查询：天眼查、不合格供应商名单 |
| `llm/` | 大模型客户端、结构化判定（带缓存） |
| `employee_runtime.py` | 员工运行时：取数客户端与自动重登、节点留痕、流程图组装 |
| `employee_cli.py` | 员工命令行运行的公共部分（各员工 `run.py` 调用） |
| `material_nodes.py` | 通用材料节点：经存储服务补齐附件、读取解析结果、展开压缩包 |
| `report_builder.py` | 规则结果 → 报告（JSON + Markdown） |
| `task_store.py` | 审查任务库（SQLite）：任务、节点留痕、规则结果、报告、缓存 |
| `run_archive.py` | 执行档案记录器：审查全过程脱敏后写入存储服务 |
| `portal_snapshot.py` | 平台页面留档：只读打开单据详情页截图并记录请求 |
| `rule_config.py` | 规则配置：草稿 → 发布 → 版本留痕 |
| `restricted_chat.py` | 受限对话：只做任务入口与报告追问 |
| `session.py` | 登录会话（无头 Chrome CDP / 服务账号密码），按 `config/accounts.yaml` 选择 |
| `env_config.py` | 环境变量与运行目录（`DE_RUNTIME`、库路径、CDP 地址、OCR 并发） |
| `settings.py` | 读取 `config/*.yaml`（按修改时间缓存） |
| `errors.py` | 业务异常与面向用户的错误说明 |
| `signing.py` | 内容签名、处理键、完整性签名 |
