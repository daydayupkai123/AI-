# 数字员工 · 合同审核（contract_review · CT）

合同管理系统「主合同审批流程」，30 条规则。

| 文件 | 作用 |
|------|------|
| `workflow.py` | 审查流程：取单 → 下载 → 解析 → 归集 → 台账 → 抽取 → 外部查询 → 规则 → 报告 |
| `extract.py` | 事实抽取：表单字段、合同正文条款、中标通知书、投标 / 招标文件 |
| `materials.py` | 材料类型识别 |
| `ledgers.py` | 审核所需台账 |
| `rules/compare.py` | 多份材料比对（R01–R08、R20、R24、R30） |
| `rules/clauses.py` | 合同正文条款核验（R09–R15、R18、R19、R23、R25–R28） |
| `rules/external.py` | 依赖外部数据或台账（R16、R17、R21、R22、R29） |
| `rules/_util.py` | 规则共用小工具 |
| `chat_prompts.py` | 受限对话提示词 |
| `samples.py` | 本地样例 DEMO-HT-001 / 002 |
| `run.py` | 命令行单跑：`python -m contract_review.run DEMO-HT-001 --source local` |

配置：`config/contract.yaml`、`config/lists/`　测试：`tests/contract_review/`
