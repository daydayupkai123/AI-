# 数字员工工作台（digital-employees）

一期交付四个审核类数字员工：**三会审查 / 采购审批 / 合同审核 / 报销初审**。
系统由**前端工作台**、**工作台服务**、**存储服务（资料中心）**三部分组成；四个数字员工按业务各自独立成包。

## 目录总览

```
digital-employees/
├── frontend/                     【前端】审核工作台（静态页 + 原生 JS，由工作台服务挂载到 /）
│
├── backend/                      【后端】Python 源码根（PYTHONPATH 指向此目录）
│   ├── workbench_service/        工作台服务 :8090 —— 登录、任务列表、发起审查、SSE、复核、托管前端
│   ├── storage_service/          存储服务（资料中心）:8091 —— 采集、下载、解析·OCR、原件与快照存储
│   │
│   ├── meeting_review/           数字员工 · 三会智能审查（公文系统）        任务前缀 SH
│   ├── procurement_review/       数字员工 · 采购审批（合同管理系统）        任务前缀 CG
│   ├── contract_review/          数字员工 · 合同审核（合同管理系统）        任务前缀 CT
│   ├── reimburse_review/         数字员工 · 财务报销初审（通财云）          任务前缀 BX
│   ├── employee_registry/        数字员工注册中心 —— 员工登记、流程定义、场景能力
│   │
│   └── shared/                   公共能力 —— 取数适配、登录会话、解析·OCR、规则框架、大模型、制度库、任务库
│
├── config/                       配置（员工规则参数、存储服务、OCR、模型、账号）
├── deploy/                       服务器部署（systemd：de-chrome / de-resource / de-web）
├── tests/                        自动化测试（目录与 backend/ 一一对应）
├── tools/                        脚本（运维 / 样例数据 / 联调自检 / 外部系统摸底）
├── pytest.ini
└── requirements.txt
```

每个目录都有 `README.md`，逐个说明其中文件的职责。

## 模块依赖

```
frontend ──HTTP /api/*──▶ workbench_service ──HTTP :8091──▶ storage_service
                                │                                  │
                                ▼                                  │
                        employee_registry                          │
                                │                                  │
            ┌──────────┬────────┴─┬────────────┐                   │
            ▼          ▼          ▼            ▼                   │
     meeting_review procurement_ contract_  reimburse_             │
                    review       review     review                 │
            └──────────┴─────┬────┴────────────┘                   │
                             ▼                                     ▼
                          shared ◀─────────────────────────────────┘
```

- `frontend` 只调用 `workbench_service` 的 `/api/*`，不直连存储服务。
- `workbench_service` 经 `storage_service.client` 访问存储服务（`config/resource.yaml`：`http` 独立进程 / `inprocess` 单进程调试）。
- 四个数字员工**互不引用**，只依赖 `shared`；工作台通过 `employee_registry` 按员工 id 找到对应员工。
- 新增数字员工：在 `backend/` 下新建 `<业务>_review/` 包（结构照抄现有员工），再到 `employee_registry/registry.py` 登记，工作台与前端不用改。

## 三个进程（部署形态）

| systemd | 代码入口 | 端口 | 职责 |
|---------|----------|------|------|
| `de-chrome` | `deploy/chrome.sh` | CDP 9222 | 常驻无头浏览器，门户登录 |
| `de-resource` | `python -m storage_service.server` | **8091** | 存储服务（资料中心） |
| `de-web` | `python -m workbench_service.server` | **8090** | 工作台 API + 前端静态页 |

## 「存储」在哪？——两套库，别混

| 名称 | 代码 | 运行时文件 | 存什么 |
|------|------|------------|--------|
| **资料中心库** | `backend/storage_service/store.py` | `.runtime/resource/resource.sqlite3` | 采集登记、同步任务、单据快照索引、执行档案 |
| **原件 / 解析缓存** | 同上 + `backend/shared/parsing/` | `.runtime/store/blobs/`、`parsed/`、`pages/`、`shots/` | 附件二进制、OCR / 文字层结果、截图 |
| **审查任务库** | `backend/shared/task_store.py` | `.runtime/store/de.sqlite3` | 审查任务、节点留痕、报告、复核备注、操作日志 |

结论：**原件与 OCR 结果在存储服务**；**审查结论与复核在任务库**（工作台和四个员工共用）。
运行时目录用环境变量 `DE_RUNTIME` 指定（服务器为 `/data/digital-employees/runtime`）。

## OCR 怎么跑？

配置：`config/ocr.yaml`

- 当前默认 / `.39` 实测：`engine: rapidocr`（本机 RapidOCR ONNX，存储服务进程内进程池）
- 可选：`paddleocr_vl` → 客户版面服务（`backend/shared/parsing/ocr_remote.py`）；地址可达后再切
- 仅扫描页 / 图片走 OCR；Word / Excel / 有文字层的 PDF 直接抽字

## 本地怎么起

后端以 `backend/` 为源码根，`python -m` 命令在 `backend/` 目录下执行（或设置 `PYTHONPATH=backend`）：

```powershell
# 存储服务（资料中心）
cd backend; ..\.venv\Scripts\python.exe -m storage_service.server

# 工作台（另开终端；需能访问 8091）→ http://127.0.0.1:8090
cd backend; ..\.venv\Scripts\python.exe -m workbench_service.server

# 命令行单跑某个数字员工（示例：三会本地样例）
cd backend; ..\.venv\Scripts\python.exe -m meeting_review.run DEMO-SH-001 --source local
```

调试可把 `config/resource.yaml` 的 `mode` 改为 `inprocess`（工作台进程内嵌存储服务，单进程）。

脚本与测试在项目根目录执行：

```powershell
.venv\Scripts\python.exe -m pytest                          # 全部测试
.venv\Scripts\python.exe -m pytest tests/meeting_review     # 只跑三会审查
.venv\Scripts\python.exe tools/samples/make_demo_cases.py   # 生成本地样例
.venv\Scripts\python.exe tools/ops/user_admin.py list       # 工作台账号
```

## 配置文件对照

| 文件 | 归属 |
|------|------|
| `meeting.yaml` / `procurement.yaml` / `contract.yaml` / `reimburse.yaml` | 对应数字员工的规则参数 |
| `regulations.yaml`、`lists/` | 制度库、标准与不合格供应商名单（员工共用） |
| `resource.yaml`、`collect.yaml` | 存储服务：访问方式、定时采集 |
| `ocr*.yaml` | 解析·OCR 引擎 |
| `llm.yaml` | 大模型 |
| `accounts.yaml`、`users.*.yaml` | 门户服务账号、工作台登录账号（`*.local.yaml` 不入库） |
