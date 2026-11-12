# 数字员工注册中心（employee_registry）

工作台通过这里按员工 id 找到对应的数字员工；四个员工本身各自独立成包，互不引用，只依赖 `shared/`。

| 员工包 | 员工 | id / 任务前缀 | 取数来源 | 规则参数 | 测试 |
|--------|------|---------------|----------|----------|------|
| [`meeting_review/`](../meeting_review/) | 三会智能审查 | `meeting` / SH | 公文系统·内部请示 | `config/meeting.yaml` | `tests/meeting_review/` |
| [`procurement_review/`](../procurement_review/) | 采购审批 | `procurement` / CG | 合同管理系统·采购结果审批 | `config/procurement.yaml` | `tests/procurement_review/` |
| [`contract_review/`](../contract_review/) | 合同审核 | `contract` / CT | 合同管理系统·主合同审批 | `config/contract.yaml` | `tests/contract_review/` |
| [`reimburse_review/`](../reimburse_review/) | 财务报销初审 | `reimburse` / BX | 通财云·八类报销单据 | `config/reimburse.yaml` | `tests/reimburse_review/` |

本包文件：

| 文件 | 作用 |
|------|------|
| `registry.py` | 员工登记：流程、规则清单、对话提示词、来源；**新增员工只在这里登记** |
| `flows.py` | 流程定义：节点、规则挂载、可配置参数（一致性由 `tests/employee_registry/test_flows.py` 保证） |
| `scenes.py` | 场景专属能力：开场任务清单的专属卡片及背后的汇总 / 查询 |

## 员工包的统一结构

| 文件 | 作用 |
|------|------|
| `workflow.py` | 审查流程（LangGraph）：取单 → 下载 → 解析 → 归集 → 抽取 → 规则 → 报告 |
| `extract.py` | 要素抽取 |
| `materials.py` | 材料类型识别与归集 |
| `rules/`（或 `rules.py`、`checks/`） | 审查规则 / 审查节点 |
| `chat_prompts.py` | 受限对话提示词 |
| `samples.py` | 本地合成样例（三会 / 合同 / 报销；`tools/samples/make_demo_cases.py` 生成） |
| `run.py` | 命令行单跑（在 `backend/` 下 `python -m <员工包>.run`） |
