"""通财云（财务报销）只读取数适配器 —— 待接入 VPN 后摸底。

2026-11-09 摸底：系统为金蝶云苍穹（https://fc.gt.cn/ierp），门户工作台 app=1 列表可取到单据（formId + pkId）；
但外网访问 fc.gt.cn 被重定向到 /ierp-prompt「暂不支持直接从外网访问，请先连接 VPN」，须本机连接 VPN 后继续。

已知（doc/【20261106】四个场景访问路径.docx）：门户 → 应用 → 通财云 → 消息中心「待办任务 / 已办任务」，
可按「单据编码 / 单据」查询；单据编码形如 1000001431-CLBX2609-000579（CLBX 差旅、DGBX 对公通用费用报销等）。
测试账号待办 0、已办 101（以差旅报销单、通用费用报销单为主），样例需从「已办」中取。

需要摸底确认（tools/portal_probe.py watch fincloud）：
  1. 通财云域名、单点登录方式（写入 core/session.py 的 WARMUP）
  2. 待办 / 已办列表接口；单据详情接口（表单字段、费用明细、报销人职级/身份）
  3. 发票结构化数据（号码、类型、开票日期、金额、商品名称、备注、乘车日期）是否随单据提供，还是需要 OCR
  4. 附件下载方式
报销流程图只依赖 fetch() / download()；fetch 需返回 RequestData，并把单据结构化数据放在 extra["claim"]
（结构见 employees/reimburse/model.py 的 Claim）。
"""
from __future__ import annotations

from .contract import Attachment, RequestData
from .docflow import SourceNotReady

SOURCE = "fincloud"
HOST: str | None = None


class FincloudClient:
    def __init__(self, session):
        self.s = session

    def fetch(self, request_id: str) -> RequestData:
        raise SourceNotReady(f"通财云的单据、发票与附件接口尚未摸底，无法读取单据 {request_id}", title="通财云取数尚未打通")

    def download(self, att: Attachment) -> bytes:
        raise SourceNotReady(f"通财云附件下载方式尚未摸底：{att.filename}", title="通财云取数尚未打通")
