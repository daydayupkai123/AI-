"""从 ModelScope 下载模型文件（断点续传）：python tools/ops/fetch_model.py <repo> <文件名> [...] [--out D:\\Model\\gguf]"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import httpx


def fetch(repo: str, name: str, out: Path) -> Path:
    out.mkdir(parents=True, exist_ok=True)
    dst = out / name
    part = dst.with_suffix(dst.suffix + ".part")
    url = f"https://www.modelscope.cn/models/{repo}/resolve/master/{name}"
    done = part.stat().st_size if part.exists() else 0
    if dst.exists():
        print("已存在", dst)
        return dst
    headers = {"Range": f"bytes={done}-"} if done else {}
    t0, last = time.time(), 0.0
    with httpx.stream("GET", url, headers=headers, follow_redirects=True, timeout=60) as r:
        r.raise_for_status()
        total = done + int(r.headers.get("content-length") or 0)
        with part.open("ab") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
                done += len(chunk)
                if time.time() - last > 5:
                    last = time.time()
                    mb_s = (done / 1e6) / max(1, time.time() - t0)
                    print(f"{name}: {done / 1e9:.2f}/{total / 1e9:.2f} GB  {mb_s:.1f} MB/s", flush=True)
    part.replace(dst)
    print("完成", dst, f"{time.time() - t0:.0f}s")
    return dst


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("repo")
    ap.add_argument("files", nargs="+")
    ap.add_argument("--out", default=r"D:\Model\gguf")
    a = ap.parse_args()
    for n in a.files:
        fetch(a.repo, n, Path(a.out))
    sys.exit(0)
