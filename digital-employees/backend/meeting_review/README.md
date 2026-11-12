# 数字员工 · 三会智能审查（meeting_review · SH）

公文系统「内部请示」：党委会 / 董事会 / 总经理办公会请示，5 个审查节点。

| 文件 | 作用 |
|------|------|
| `workflow.py` | 审查流程：取单 → 下载 → 解析 → 归集 → 抽取要素 → 制度检索 → 审查（5 节点并行）→ 报告 |
| `extract.py` | 要素抽取：表单字段、审批 / 上会依据拆解、正文与附件关键事实 |
| `materials.py` | 材料类型（附件名只是线索，以内容为准） |
| `prompts.py` | 审查用模型提示词（输出 JSON，引用原文回材料校验） |
| `checks/title.py` | 01 标题与附件关联性 |
| `checks/meeting_type.py` | 02 会议类型 |
| `checks/basis.py` | 03 审批 / 上会依据（制度条款定位、金额档位） |
| `checks/body.py` | 04 请示正文 |
| `checks/attachments.py` | 05 附件材料交叉核验 |
| `chat_prompts.py` | 受限对话提示词 |
| `samples.py` | 本地样例 DEMO-SH-001 / 002 |
| `run.py` | 命令行单跑：`python -m meeting_review.run DEMO-SH-001 --source local` |

配置：`config/meeting.yaml`、`config/regulations.yaml`　测试：`tests/meeting_review/`
