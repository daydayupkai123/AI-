"""OCR 引擎：按 config/ocr.yaml 选择（修改后下一次解析生效）。

- rapidocr：本地 RapidOCR 进程池，开发与离线兜底；处理参数与历史一致，已有缓存继续命中。
- paddleocr_vl：客户 PaddleOCR-VL 版面解析服务（core/parsing/ocr_remote.py），限流、重试、输出归一。
客户 OCR 不可达时不自动降级到本地引擎（避免同一份文件出现两种结果），需在配置中显式切换。
"""
from __future__ import annotations

import atexit
import os
import threading
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from typing import Callable

import yaml

from ..config import OCR_DPI, OCR_THREADS_PER_WORKER, OCR_WORKERS, ROOT

CONFIG_PATH = Path(os.environ.get("DE_OCR_CONFIG", str(ROOT / "config" / "ocr.yaml")))
RAPID_NAME = "rapidocr_onnxruntime"
ENGINE = RAPID_NAME  # 兼容旧引用

_engine = None
_pool: ProcessPoolExecutor | None = None
_pool_lock = threading.Lock()
_cfg = {"mtime": None, "cfg": None, "engine": None}
_cfg_lock = threading.Lock()


def config() -> dict:
    with _cfg_lock:
        mtime = CONFIG_PATH.stat().st_mtime if CONFIG_PATH.exists() else None
        if _cfg["mtime"] != mtime or _cfg["cfg"] is None:
            _cfg["cfg"] = (yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}) if mtime else {}
            _cfg["mtime"] = mtime
            _cfg["engine"] = None
        return _cfg["cfg"]


def engine():
    cfg = config()
    with _cfg_lock:
        if _cfg["engine"] is None:
            name = (cfg.get("engine") or "rapidocr").strip()
            if name == "rapidocr":
                _cfg["engine"] = RapidEngine(cfg.get("rapidocr") or {})
            elif name == "paddleocr_vl":
                from .ocr_remote import PaddleVLEngine

                _cfg["engine"] = PaddleVLEngine(cfg.get("paddleocr_vl") or {})
            else:
                raise RuntimeError(f"config/ocr.yaml 中的 engine「{name}」不支持（可选 rapidocr / paddleocr_vl）")
        return _cfg["engine"]


# ---------------------------------------------------------------------------- RapidOCR（本地）
def _init_worker(threads: int) -> None:
    os.environ.setdefault("OMP_NUM_THREADS", str(threads))
    global _engine
    from rapidocr_onnxruntime import RapidOCR

    _engine = RapidOCR(intra_op_num_threads=threads, inter_op_num_threads=1)


def _ocr_png(png: bytes) -> dict:
    result, _ = _engine(png)
    lines = []
    for box, text, conf in result or []:
        lines.append({"text": text, "conf": round(float(conf), 4),
                      "box": [[int(x), int(y)] for x, y in box]})
    lines.sort(key=lambda ln: (round(ln["box"][0][1] / 12), ln["box"][0][0]))
    confs = [ln["conf"] for ln in lines]
    return {"lines": lines, "text": _join(lines), "conf": round(sum(confs) / len(confs), 4) if confs else 0.0}


def _join(lines: list[dict]) -> str:
    out, last_y = [], None
    for ln in lines:
        y = ln["box"][0][1]
        if last_y is not None and abs(y - last_y) <= 12 and out:
            out[-1] += " " + ln["text"]
        else:
            out.append(ln["text"])
        last_y = y
    return "\n".join(out)


def pool(reset: bool = False) -> ProcessPoolExecutor:
    """全进程唯一的 RapidOCR 池；多线程并发调用时只创建一次（Windows 下须先在主线程创建）。"""
    global _pool
    with _pool_lock:
        if reset and _pool is not None:
            _pool.shutdown(wait=False, cancel_futures=True)
            _pool = None
        if _pool is None:
            _pool = ProcessPoolExecutor(max_workers=OCR_WORKERS, initializer=_init_worker,
                                        initargs=(OCR_THREADS_PER_WORKER,))
            atexit.register(_pool.shutdown, wait=False, cancel_futures=True)
        return _pool


class RapidEngine:
    name = "rapidocr"

    def __init__(self, cfg: dict):
        self.dpi = int(cfg.get("dpi") or OCR_DPI)
        self.sec_per_page = float(cfg.get("sec_per_page") or 2.5)

    def params(self) -> dict:
        return {"ocr": RAPID_NAME, "dpi": self.dpi}

    def ocr_images(self, pngs: list[bytes], on_page: Callable[[int, int], None] | None = None) -> list[dict]:
        if not pngs:
            return []
        for attempt in (0, 1):
            try:
                out = []
                for i, res in enumerate(pool(reset=attempt == 1).map(_ocr_png, pngs)):
                    out.append(res)
                    if on_page:
                        on_page(i + 1, len(pngs))
                return out
            except BrokenProcessPool:
                if attempt:
                    raise
        raise AssertionError("unreachable")

    def estimate_seconds(self, pages: int) -> float:
        # sec_per_page 是进程池并行后的整体每页耗时（实测 157 页约 6 分钟），不再除以进程数
        return pages * self.sec_per_page


def ocr_images(pngs: list[bytes], on_page: Callable[[int, int], None] | None = None) -> list[dict]:
    return engine().ocr_images(pngs, on_page)
