# 脚本

都在项目根目录执行：`.venv\Scripts\python.exe tools/<分组>/<脚本>.py`。每个脚本开头的说明写了用法。

| 目录 | 用途 | 脚本 |
|------|------|------|
| `ops/` | 运维 | `user_admin` 工作台账号、`status` 服务状态、`reset_runtime` 清理运行时、`fetch_model` / `fetch_gguf` 下载模型、`ocr_local_server` 本地 OCR 仿真服务 |
| `samples/` | 样例数据 | `make_demo_cases` 本地合成样例、`make_meeting_real_cases` 三会真实材料改造事项 |
| `checks/` | 联调自检 | `e2e_live_check` 真实取数全链路、`ui_*` 界面截图与检查、`chat_*` 对话检查、`ocr_compare` / `ocr_review_check` OCR 效果、`session_check` / `run_check`、`dump_texts` / `try_parse` 解析结果查看 |
| `probes/` | 外部系统摸底（只读） | `m0_*` 合同 / 公文 / 通财云接口摸底、`portal_*` / `page_capture` / `login_probe` 门户、`tyc_*` 天眼查、`ocr_probe` 客户 OCR |

输出默认写到 `.runtime/`（不入库）。
