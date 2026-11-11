#!/bin/bash
# 常驻无界面 Chrome：只监听本机 9222，供取数、单点登录、天眼查、页面留档使用（服务账号模式）。
set -euo pipefail
BASE=${DE_BASE:-/data/digital-employees}
CHROME=$(find "$BASE/browsers" -path '*chrome-linux*/chrome' -type f 2>/dev/null | sort | tail -1)
[ -x "$CHROME" ] || { echo "未找到 Chromium，请先执行 deploy/install.sh" >&2; exit 1; }
exec "$CHROME" --headless=new --no-sandbox --disable-gpu --disable-dev-shm-usage --no-first-run \
  --no-default-browser-check --lang=zh-CN --window-size=1440,900 \
  --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 \
  --user-data-dir="$BASE/chrome-profile" about:blank
