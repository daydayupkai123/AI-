"""命令行运行三会审查数字员工。

  ..\\.venv\\Scripts\\python.exe -m meeting_review.run DEMO-SH-001 --source local   # 本地事项
  ..\\.venv\\Scripts\\python.exe -m meeting_review.run <公文单号>                    # 公文系统（待摸底打通）
"""
from __future__ import annotations

import sys

from shared.employee_cli import main

from .workflow import SOURCES, run

if __name__ == "__main__":
    sys.exit(main("三会审查", run, SOURCES, sys.argv[1:]))
