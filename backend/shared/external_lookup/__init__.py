"""外部查询：天眼查（企业工商、股东、主要人员、疑似关系、风险计数）、不合格供应商名单。

外部系统导致的查询失败一律抛 ExternalUnavailable（或其子类），依赖该数据的规则记「审查中止」并如实展示原因与处理办法，
不降级为人工复核、不当作通过。
"""
from ..errors import DEError


class ExternalUnavailable(DEError):
    title = "天眼查查询失败"
    hint = "可能是网络或天眼查页面异常，可稍后点「重新审查」；反复出现请把技术详情发给管理员。"


class TianyanchaNeedsLogin(ExternalUnavailable):
    title = "天眼查需要登录验证"
    hint = ("数字员工服务器上的天眼查未登录或登录已失效，天眼查要求人工完成登录验证（滑块 / 短信）。"
            "请天眼查账号提供人配合管理员重新登录后，再点「重新审查」。")


class TianyanchaBlocked(ExternalUnavailable):
    title = "天眼查暂停了访问"
    hint = ("天眼查检测到异常访问，暂停了数字员工服务器的查询。请天眼查账号提供人登录天眼查网页确认账号状态，"
            "必要时联系天眼查客服 400-608-0000 并提供技术详情中的识别码；恢复后点「重新审查」。")
