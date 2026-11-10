"""本地 OCR 服务（与客户 PaddleOCR-VL layout-parsing 接口同构），客户 OCR 只能内网访问时用于在本机验证对接链路。

  .venv\\Scripts\\python.exe tools\\ocr_local_server.py --backend rapidocr              # http://127.0.0.1:8092
  .venv\\Scripts\\python.exe tools\\ocr_local_server.py --backend ollama:qwen25vl-ocr --port 8093  # 本机 Ollama 视觉模型

接口：POST /paddleocr-vl/layout-parsing
  请求 {"file": base64 或 http(s) 地址, "fileType": 0 PDF / 1 图片, "useLayoutDetection": ...}（其余参数忽略）
  返回 {"errorCode": 0, "errorMsg": "Success", "result": {"layoutParsingResults": [
          {"prunedResult": {"width", "height", "parsing_res_list": [{"block_label", "block_content", "block_bbox"}]},
           "markdown": {"text", "images": {}}}]}}
后端：
  rapidocr      本地 RapidOCR 识别文字行，按行距聚成段落块（带坐标）；不识别表格结构
  ollama:<模型>  本机 Ollama 视觉模型转写为 Markdown（不带坐标）；输出退化（重复空表格行、明显缺字）的页
                 改用 RapidOCR 结果（带坐标），返回中 _backend 标明每页实际来源
"""
from __future__ import annotations

import argparse
import base64
import io
import re
import threading
import time
import uuid

import httpx
import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

VLM_PROMPT = ("请把图片中的全部文字按阅读顺序完整转写成 Markdown：标题用 #，段落原样保留，表格用 HTML <table> 表示；"
              "只输出转写内容，不要解释、不要总结、不要补充图片中没有的文字。")
_rapid = None
_init_lock = threading.Lock()
_rapid_lock = threading.Lock()  # RapidOCR 实例不保证线程安全，识别时串行


def rapid():
    global _rapid
    with _init_lock:
        if _rapid is None:
            from rapidocr_onnxruntime import RapidOCR

            _rapid = RapidOCR()
        return _rapid


def image_size(png: bytes) -> tuple[int, int]:
    from PIL import Image

    with Image.open(io.BytesIO(png)) as im:
        return im.size


def rapid_blocks(png: bytes) -> list[dict]:
    """RapidOCR 行 → 段落块：行距小于 1.6 倍行高的相邻行并为一块。"""
    engine = rapid()
    with _rapid_lock:
        result, _ = engine(png)
    lines = []
    for box, text, _conf in result or []:
        xs, ys = [p[0] for p in box], [p[1] for p in box]
        lines.append({"text": text, "bbox": [min(xs), min(ys), max(xs), max(ys)]})
    lines.sort(key=lambda ln: (round(ln["bbox"][1] / 10), ln["bbox"][0]))
    blocks: list[dict] = []
    for ln in lines:
        h = ln["bbox"][3] - ln["bbox"][1]
        if blocks and ln["bbox"][1] - blocks[-1]["bbox"][3] < 1.6 * max(h, 8):
            b = blocks[-1]
            sep = " " if abs(ln["bbox"][1] - b["_last_y"]) < h * 0.5 else "\n"
            b["block_content"] += sep + ln["text"]
            b["bbox"] = [min(b["bbox"][0], ln["bbox"][0]), min(b["bbox"][1], ln["bbox"][1]),
                         max(b["bbox"][2], ln["bbox"][2]), max(b["bbox"][3], ln["bbox"][3])]
            b["_last_y"] = ln["bbox"][1]
        else:
            blocks.append({"block_label": "text", "block_content": ln["text"], "bbox": list(ln["bbox"]),
                           "_last_y": ln["bbox"][1]})
    return [{"block_label": b["block_label"], "block_content": b["block_content"],
             "block_bbox": [round(float(x), 1) for x in b["bbox"]]} for b in blocks]


def vlm_markdown(model: str, png: bytes, base_url: str) -> str:
    r = httpx.post(f"{base_url}/api/chat", timeout=300, json={
        "model": model, "stream": False,
        "options": {"temperature": 0, "num_ctx": 8192, "num_predict": 3072, "repeat_penalty": 1.1},
        "messages": [{"role": "user", "content": VLM_PROMPT, "images": [base64.b64encode(png).decode()]}]})
    r.raise_for_status()
    return (r.json().get("message") or {}).get("content") or ""


FENCE_RE = re.compile(r"^\s*```[A-Za-z]*\s*$", re.M)
EMPTY_ROW_RE = re.compile(r"^\s*\|[\s|:\-]*\|\s*$")
NOISE_RE = re.compile(r"[\s|#:*`\-]")


def clean_markdown(md: str) -> str:
    """去掉代码围栏、空表格行（小模型常见的重复空行循环）与连续重复行。"""
    out: list[str] = []
    for ln in FENCE_RE.sub("", md).splitlines():
        if EMPTY_ROW_RE.match(ln) or (out and ln.strip() and ln == out[-1]):
            continue
        out.append(ln)
    return "\n".join(out).strip()


def degenerate(md: str, blocks: list[dict]) -> bool:
    """视觉模型输出明显缺字（有效字符不到 RapidOCR 的一半）视为退化。"""
    base = sum(len(NOISE_RE.sub("", b["block_content"])) for b in blocks)
    return base >= 40 and len(NOISE_RE.sub("", md)) < base * 0.5


def page_result(png: bytes, backend: str, ollama_url: str) -> dict:
    w, h = image_size(png)
    blocks = rapid_blocks(png)
    if backend.startswith("ollama:"):
        md = clean_markdown(vlm_markdown(backend.split(":", 1)[1], png, ollama_url))
        if not degenerate(md, blocks):
            # 视觉模型不给坐标：正文以模型转写为准，此页证据截图只能整页展示、不能高亮
            return {"prunedResult": {"width": w, "height": h, "parsing_res_list": []},
                    "markdown": {"text": md, "images": {}}, "_backend": "vlm"}
    md = "\n\n".join(b["block_content"] for b in blocks)
    return {"prunedResult": {"width": w, "height": h, "parsing_res_list": blocks}, "markdown": {"text": md, "images": {}},
            "_backend": "rapidocr" if backend == "rapidocr" else "rapidocr-fallback"}


def build_app(backend: str, ollama_url: str, fail_every: int = 0) -> FastAPI:
    app = FastAPI(title="本地 OCR（PaddleOCR-VL 同构接口）")
    stats = {"n": 0}

    @app.post("/paddleocr-vl/layout-parsing")
    def layout_parsing(body: dict):
        stats["n"] += 1
        if fail_every and stats["n"] % fail_every == 0:
            return JSONResponse(status_code=503, content={"errorCode": 503, "errorMsg": "模拟服务繁忙"})
        t0 = time.time()
        src = body.get("file") or ""
        data = httpx.get(src, timeout=60).content if src.startswith(("http://", "https://")) else base64.b64decode(src)
        if int(body.get("fileType", 1)) == 0:
            import pymupdf

            doc = pymupdf.open(stream=data, filetype="pdf")
            pngs = [p.get_pixmap(dpi=150).tobytes("png") for p in doc]
        else:
            pngs = [data]
        results = [page_result(p, backend, ollama_url) for p in pngs]
        return {"logId": uuid.uuid4().hex, "errorCode": 0, "errorMsg": "Success",
                "result": {"layoutParsingResults": results, "dataInfo": {"type": "pdf" if len(pngs) > 1 else "image",
                                                                          "pages": len(pngs)}},
                "_ms": int((time.time() - t0) * 1000), "_backend": backend}

    @app.get("/health")
    def health():
        return {"ok": True, "backend": backend, "calls": stats["n"]}

    return app


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="rapidocr", help="rapidocr 或 ollama:<模型名>")
    ap.add_argument("--port", type=int, default=8092)
    ap.add_argument("--ollama", default="http://127.0.0.1:11434")
    ap.add_argument("--fail-every", type=int, default=0, help="每 N 次请求返回一次 503（验证重试）")
    a = ap.parse_args()
    print(f"本地 OCR 服务：http://127.0.0.1:{a.port}/paddleocr-vl/layout-parsing  后端 {a.backend}")
    uvicorn.run(build_app(a.backend, a.ollama, a.fail_every), host="127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
