#!/bin/bash
# 在服务器上安装 / 更新数字员工（root 执行，可重复执行）。代码已解压到 $BASE/app。
#   Python 3.12 与 Chromium 从国内镜像下载；依赖走阿里云 PyPI 镜像。
set -euo pipefail
BASE=${DE_BASE:-/data/digital-employees}
APP=$BASE/app
PIP_INDEX=${PIP_INDEX:-https://mirrors.aliyun.com/pypi/simple/}
export UV_PYTHON_INSTALL_MIRROR=${UV_PYTHON_INSTALL_MIRROR:-https://registry.npmmirror.com/-/binary/python-build-standalone}
export UV_PYTHON_INSTALL_DIR=$BASE/python
export PLAYWRIGHT_BROWSERS_PATH=$BASE/browsers
mkdir -p "$BASE"/{runtime,browsers,chrome-profile,python,logs}

if [ ! -x "$BASE/uv/uv" ]; then
  python3 -m pip install -q --target "$BASE/uv-pkg" -i "$PIP_INDEX" --trusted-host mirrors.aliyun.com uv
  mkdir -p "$BASE/uv" && ln -sf "$BASE/uv-pkg/bin/uv" "$BASE/uv/uv"
fi
UV=$BASE/uv/uv
"$UV" python install 3.12
[ -x "$APP/.venv/bin/python" ] || "$UV" venv --python 3.12 "$APP/.venv"
"$UV" pip install -q --python "$APP/.venv/bin/python" -i "$PIP_INDEX" -r "$APP/requirements.txt"

if ! find "$BASE/browsers" -path '*chrome-linux*/chrome' -type f | grep -q .; then
  "$APP/.venv/bin/python" -m playwright install chromium \
    || PLAYWRIGHT_DOWNLOAD_HOST=https://registry.npmmirror.com/-/binary/playwright \
       "$APP/.venv/bin/python" -m playwright install chromium
fi

[ -f "$BASE/de.env" ] || { cp "$APP/deploy/de.env.example" "$BASE/de.env"; chmod 600 "$BASE/de.env"; \
  echo "已生成 $BASE/de.env，请填写账号与密钥后再启动服务"; }
install -m 644 "$APP"/deploy/systemd/*.service /etc/systemd/system/
systemctl daemon-reload
echo "安装完成：systemctl enable --now de-chrome de-resource de-web"
