# 数字员工 · 采购审批（procurement_review · CG）

合同管理系统「采购结果审批流程」（wf=100），18 条规则。

| 文件 | 作用 |
|------|------|
| `workflow.py` | 审查流程：取单 → 下载 → 解析 → 归集 → 抽取 → 规则 → 报告 |
| `extract.py` | 从表单与材料中抽取规则所需事实 |
| `materials.py` | 材料归集：按文件名与字段判断类型，响应文件归到具体供应商 |
| `rules.py` | 18 条审批规则 |
| `chat_prompts.py` | 受限对话提示词 |
| `run.py` | 命令行单跑：`python -m procurement_review.run <requestid>` |

配置：`config/procurement.yaml`　测试：`tests/procurement_review/`
