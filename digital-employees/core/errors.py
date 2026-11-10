"""业务异常与面向用户的错误说明（问题是什么 + 怎么处理），原始异常作为技术详情保留。"""
from __future__ import annotations


class DEError(RuntimeError):
    title = "审查过程中出现异常"
    hint = "可以稍后点「重新审查」再试；如果反复出现，请把技术详情发给管理员。"

    def __init__(self, detail: str = "", *, title: str | None = None, hint: str | None = None):
        super().__init__(detail or title or self.title)
        self.detail = detail
        if title:
            self.title = title
        if hint:
            self.hint = hint


class SessionExpired(DEError):
    title = "门户登录已失效"
    hint = "请在调试 Chrome 中打开 https://i.gt.cn 重新登录门户，登录完成后点「重新审查」。"


class BrowserUnavailable(DEError):
    title = "无法连接调试浏览器"
    hint = ("请先启动调试 Chrome 并登录门户：在 digital-employees 目录执行计划文档「本地运行」中的启动命令，"
            "确认 127.0.0.1:9222 可以访问后再试。")


class NoAccess(DEError):
    title = "当前账号无权查看该单据"
    hint = "请确认单号是否正确，或换用有该流程查看权限的账号登录门户。"


class WrongWorkflow(DEError):
    title = "该单号不是采购结果审批流程"
    hint = "采购审批数字员工只审查合同管理系统中的「采购结果审批流程」单据，请换一个单号，或点「样例单据」挑选。"


class UpstreamUnavailable(DEError):
    title = "合同管理系统暂时无法访问"
    hint = "可能是网络或合同系统本身的问题，请确认能在浏览器中正常打开合同系统后，再点「重新审查」。"


class UpstreamUnexpected(DEError):
    title = "合同管理系统返回了无法识别的内容"
    hint = "通常是登录状态异常或系统维护导致。请在调试 Chrome 中刷新门户确认已登录，再点「重新审查」。"


def friendly(exc: BaseException) -> dict:
    """把任意异常转换成 {title, hint, detail}。"""
    if isinstance(exc, DEError):
        return {"title": exc.title, "hint": exc.hint, "detail": exc.detail or str(exc), "code": type(exc).__name__}
    name, msg = type(exc).__name__, str(exc)
    low = msg.lower()
    if "9222" in msg or "connect_over_cdp" in msg or ("econnrefused" in low and "127.0.0.1" in msg):
        e: DEError = BrowserUnavailable(f"{name}: {msg}")
    elif name in ("ConnectionError", "ConnectTimeout", "ReadTimeout", "Timeout", "SSLError") or "max retries" in low:
        e = UpstreamUnavailable(f"{name}: {msg}")
    elif name == "JSONDecodeError":
        e = UpstreamUnexpected(f"{name}: {msg}")
    else:
        e = DEError(f"{name}: {msg}")
    return {"title": e.title, "hint": e.hint, "detail": e.detail, "code": type(e).__name__}
