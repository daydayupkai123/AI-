# 解析与 OCR

由**存储服务（`storage_service`）**在同步附件时调用，不单独起进程。

| 文件 | 作用 |
|------|------|
| `pipeline.py` | 解析流水线（缓存、重试失败页） |
| `formats.py` | 按文件头抽文字层；标记需 OCR 的页 |
| `ocr.py` | 引擎选择：`rapidocr` / `paddleocr_vl` |
| `ocr_remote.py` | 客户 PaddleOCR-VL HTTP 客户端 |

配置：`config/ocr.yaml`。
