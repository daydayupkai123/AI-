# 测试

在项目根目录执行 `.venv\Scripts\python.exe -m pytest`；`pytest.ini` 已把 `backend/` 和项目根加入导入路径。
目录与 `backend/` 的包一一对应：

| 目录 | 覆盖 |
|------|------|
| `meeting_review/` | 三会审查：`test_meeting` |
| `procurement_review/` | 采购审批：`test_procurement_quotes`（报价核验）、`test_procurement_replay`（历史单回放） |
| `contract_review/` | 合同审核：`test_contract`、`test_contract_extract` |
| `reimburse_review/` | 财务报销初审：`test_reimburse` |
| `employee_registry/` | 流程定义一致性 `test_flows`、场景能力 `test_scenes` |
| `workbench_service/` | 工作台：接口冒烟 `test_api`、任务列表 `test_worklist`、自动审查 `test_dispatch` |
| `storage_service/` | 存储服务：取单与同步 `test_resource`、采集 `test_collect`、证据定位 `test_locate` |
| `shared/` | 公共能力：规则与制度库 `test_core`、公文取数 `test_docflow`、解析 `test_doc_pieces`、OCR `test_ocr_*`、页面留档 `test_portal`、执行档案 `test_archive` |
| `e2e/` | 端到端：采集 → 同步 → 自动审查 → 报告 |
| `support/` | 测试辅助：临时库、假外部服务、历史数据回放、接口冒烟脚本 |
| `fixtures/` | 固定样本（天眼查接口报文等） |

`conftest.py` 让每个测试使用空的规则配置库，正式环境发布的规则配置不影响结论。
