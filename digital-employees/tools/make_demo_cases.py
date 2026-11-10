"""生成本地样例事项（合成数据）到 .runtime/cases/<员工>/，供工作台「样例单据」与本地联调使用。

  .venv\\Scripts\\python.exe tools/make_demo_cases.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.sources.local import CASES  # noqa: E402
from employees.contract import samples as contract_samples  # noqa: E402
from employees.meeting import samples as meeting_samples  # noqa: E402
from employees.reimburse import samples as reimburse_samples  # noqa: E402

WRITERS = [("contract", contract_samples.write), ("meeting", meeting_samples.write),
           ("reimburse", reimburse_samples.write)]

if __name__ == "__main__":
    for employee, write in WRITERS:
        for d in write(CASES):
            print(f"{employee}: {d}")
