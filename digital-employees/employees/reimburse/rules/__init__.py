"""财务报销初审 43 条规则（需求：需求场景/财务报销AI初审-需求说明书（讨论稿V2.1）.docx 第三章、附录）。

每类单据一个文件；单据里出现哪类费用就执行哪一类规则（extract.groups_of）。
category = 材料 / 数据 / 标准 / 风险；group = 单据类别。
"""
from __future__ import annotations

from core.rules.engine import Rule

from . import asset, entertain, general, meeting_fee, office, traffic, training, travel, vehicle

VERSION = "reimburse-2026.11.09-r1"
EMPLOYEE = "reimburse"
M, D, S, R = "材料", "数据", "标准", "风险"

_SPEC = [
    ("TRV", "差旅费", [
        ("TRV-01", "行程期间与行程单日期一致", D, travel.trv01),
        ("TRV-02", "铁路电子客票日期落在行程期间内", D, travel.trv02),
        ("TRV-03", "数电普通发票备注出行日期落在行程期间内", D, travel.trv03),
        ("TRV-04", "连号发票识别", R, travel.trv04),
        ("TRV-05", "数电普通发票匹配行程单", M, travel.trv05),
        ("TRV-06", "院车场景补助金额倍数", S, travel.trv06),
        ("TRV-07", "含招待费时陪餐人数上限", S, travel.trv07),
        ("TRV-08", "含招待费时标准天数应少于行程天数", S, travel.trv08)]),
    ("ENT", "业务招待费", [
        ("ENT-01", "其他公务招待公函附件", M, entertain.ent01),
        ("ENT-02", "陪餐人数合规性", S, entertain.ent02),
        ("ENT-03", "人均标准（职级 × 招待类型）", S, entertain.ent03),
        ("ENT-04", "其他公务招待赠礼风险", R, entertain.ent04),
        ("ENT-05", "商务/外事纪念品标准与附件", S, entertain.ent05),
        ("ENT-06", "央企之间商务宴请识别", R, entertain.ent06),
        ("ENT-07", "招待清单数据一致性", D, entertain.ent07),
        ("ENT-08", "连号发票识别", R, entertain.ent08),
        ("ENT-09", "上年度发票报销时限", R, entertain.ent09),
        ("ENT-10", "招待日期与开票日期匹配", D, entertain.ent10),
        ("ENT-11", "含招待费时标准天数应少于行程天数", S, entertain.ent11),
        ("ENT-12", "敏感单位字眼识别", R, entertain.ent12)]),
    ("OFF", "办公费", [
        ("OFF-01", "发票商品信息与配套清单完整性", M, office.off01),
        ("OFF-02", "清单与发票金额一致性", D, office.off02),
        ("OFF-03", "连号发票识别", R, office.off03),
        ("OFF-04", "发票内容与业务用途匹配", S, office.off04),
        ("OFF-05", "禁止预付储值类票据", R, office.off05)]),
    ("VEH", "车辆使用费", [
        ("VEH-01", "发票名称与费用项目匹配", D, vehicle.veh01),
        ("VEH-02", "附件完整性", M, vehicle.veh02),
        ("VEH-03", "附件信息审核（预算比对）", S, vehicle.veh03)]),
    ("TRA", "交通费", [
        ("TRA-01", "第三方平台发票匹配明细清单", M, traffic.tra01),
        ("TRA-02", "连号发票识别", R, traffic.tra02)]),
    ("MTG", "会议费", [
        ("MTG-01", "会议通知与审批件完整性", M, meeting_fee.mtg01),
        ("MTG-02", "审批件含参会人员名单", M, meeting_fee.mtg02),
        ("MTG-03", "费用人与参会人一致", D, meeting_fee.mtg03)]),
    ("TRN", "培训费", [
        ("TRN-01", "商品名称规范性", D, training.trn01)]),
    ("GEN", "通用报销单", [
        ("GEN-01", "综合管理部邮递费附件", M, general.gen01),
        ("GEN-02", "非综合管理部邮递费附件（对公/对私）", M, general.gen02),
        ("GEN-03", "房屋及建筑物租赁费附件", M, general.gen03),
        ("GEN-04", "车辆租赁费附件", M, general.gen04),
        ("GEN-05", "修理费附件与盖章", M, general.gen05),
        ("GEN-06", "修理费金额一致性", D, general.gen06)]),
    ("AST", "资产采购", [
        ("AST-01", "资产信息与发票信息校验", D, asset.ast01),
        ("AST-02", "附件完整性", M, asset.ast02),
        ("AST-03", "资产入库单签字", M, asset.ast03)]),
]

GROUP_NAMES = {code: name for code, name, _ in _SPEC}
RULES = [Rule(rid, name, cat, fn, group=gname) for code, gname, rules in _SPEC for rid, name, cat, fn in rules]


def select(groups: list[str]) -> list[Rule]:
    names = {GROUP_NAMES[g] for g in groups if g in GROUP_NAMES}
    return [r for r in RULES if r.group in names]


def catalog() -> list[dict]:
    return [{"rule_id": r.id, "name": r.name, "category": r.category, "group": r.group} for r in RULES]
