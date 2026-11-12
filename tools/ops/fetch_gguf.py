"""从 ModelScope 断点续传下载 GGUF 模型（绕开 Ollama 对代理 fake-ip 的跳转限制）。

  python tools/ops/fetch_gguf.py Qwen/Qwen3-8B-GGUF Qwen3-8B-Q4_K_M.gguf D:\\ollama-gguf
"""
import os
import sys
import time

import requests

repo, fname, out_dir = sys.argv[1], sys.argv[2], sys.argv[3]
os.makedirs(out_dir, exist_ok=True)
dst = os.path.join(out_dir, fname)
url = f"https://modelscope.cn/models/{repo}/resolve/master/{fname}"
s = requests.Session()
s.trust_env = True
for attempt in range(1, 30):
    have = os.path.getsize(dst) if os.path.exists(dst) else 0
    headers = {"Range": f"bytes={have}-"} if have else {}
    try:
        with s.get(url, headers=headers, stream=True, timeout=(15, 60), allow_redirects=True) as r:
            if r.status_code == 416:
                print("already complete", have, flush=True)
                break
            r.raise_for_status()
            total = have + int(r.headers.get("Content-Length", 0))
            mode = "ab" if have and r.status_code == 206 else "wb"
            if mode == "wb":
                have = 0
            t0, last, done = time.time(), 0.0, have
            with open(dst, mode) as fh:
                for chunk in r.iter_content(chunk_size=4 << 20):
                    fh.write(chunk)
                    done += len(chunk)
                    if time.time() - last > 10:
                        last = time.time()
                        speed = (done - have) / max(time.time() - t0, 1) / 1048576
                        print(f"{done / 1073741824:.2f}/{total / 1073741824:.2f} GB  {speed:.1f} MB/s", flush=True)
        if os.path.getsize(dst) >= total > 0:
            print("DONE", dst, os.path.getsize(dst), flush=True)
            break
    except Exception as exc:  # noqa: BLE001
        print(f"attempt {attempt} failed: {type(exc).__name__}: {exc}", flush=True)
        time.sleep(5)
