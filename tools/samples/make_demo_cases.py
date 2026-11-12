"""生成本地样例事项（合成数据）到 .runtime/cases/<员工>/，供工作台「样例单据」与本地联调使用。

  .venv\\Scripts\\python.exe tools/samples/make_demo_cases.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from shared.source_adapters.local import CASES  # noqa: E402
from contract_review import samples as contract_samples  # noqa: E402
from meeting_review import samples as meeting_samples  # noqa: E402
from reimburse_review import samples as reimburse_samples  # noqa: E402

WRITERS = [("contract", contract_samples.write), ("meeting", meeting_samples.write),
           ("reimburse", reimburse_samples.write)]

if __name__ == "__main__":
    for employee, write in WRITERS:
        for d in write(CASES):
            print(f"{employee}: {d}")
