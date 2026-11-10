"""命令行运行三会审查数字员工。

  .venv\\Scripts\\python.exe -m employees.meeting.run DEMO-SH-001 --source local   # 本地事项
  .venv\\Scripts\\python.exe -m employees.meeting.run <公文单号>                    # 公文系统（待摸底打通）
"""
from __future__ import annotations

import sys

from core.cli import main

from .graph import SOURCES, run

if __name__ == "__main__":
    sys.exit(main("三会审查", run, SOURCES, sys.argv[1:]))
