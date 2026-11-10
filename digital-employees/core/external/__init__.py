"""外部查询：天眼查（企业工商、股东、主要人员、疑似关系、风险计数）、不合格供应商名单。

所有查询失败都抛 ExternalUnavailable，调用方据此记「人工复核」，不当作通过。
"""
from ..errors import DEError


class ExternalUnavailable(DEError):
    title = "外部数据暂不可用"
    hint = "请确认调试 Chrome 中天眼查已登录（tools/tyc_login.py），然后点「重新审查」。"
