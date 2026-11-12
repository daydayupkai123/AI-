# 数字员工 · 财务报销初审（reimburse_review · BX）

通财云八类报销单据，43 条规则。

| 文件 | 作用 |
|------|------|
| `workflow.py` | 审查流程：取单 → 下载 → 解析 → 归集 → 抽取要素 → 规则校验（按单据类别）→ 报告 |
| `model.py` | 报销单统一模型 `Claim`（规则只依赖这个结构） |
| `extract.py` | 报销要素：单据结构化数据 + 附件归类 + 发票 |
| `materials.py` | 附件类型识别、发票文字识别兜底、签字盖章可判定性 |
| `rules/travel.py` | 差旅费 TRV-01–08 |
| `rules/entertain.py` | 业务招待费 ENT-01–12 |
| `rules/office.py` | 办公费 OFF-01–05 |
| `rules/vehicle.py` | 车辆使用费 VEH-01–03 |
| `rules/traffic.py` | 交通费 TRA-01–02 |
| `rules/meeting_fee.py` | 会议费 MTG-01–03 |
| `rules/training.py` | 培训费 TRN-01 |
| `rules/general.py` | 通用报销单 GEN-01–06 |
| `rules/asset.py` | 资产采购 AST-01–03 |
| `rules/_util.py` | 规则共用：取配置、附件、发票证据等 |
| `chat_prompts.py` | 受限对话提示词 |
| `samples.py` | 本地样例 DEMO-BX-* |
| `run.py` | 命令行单跑：`python -m reimburse_review.run DEMO-BX-001 --source local` |

配置：`config/reimburse.yaml`　测试：`tests/reimburse_review/`
