"""四个数字员工的流程定义：节点（做什么、取数来源、产出）、规则挂载（执行节点 + 依赖节点）、可配置参数、
需求方案步骤 ↔ 实际节点对照。用于「流程与规则」页展示与规则配置；运行仍由各员工的流水线执行，
节点名称与规则全集由测试保证与流水线一致（tests/test_flows.py）。

只放静态数据，不导入员工模块（core.settings 叠加配置时会读取 CONFIG_FILES）。
"""
from __future__ import annotations

CONFIG_FILES = {"procurement.yaml": "procurement", "contract.yaml": "contract", "meeting.yaml": "meeting",
                "reimburse.yaml": "reimburse"}

# 参数类型：int / number / bool / text / list（字符串列表）
P = dict

FLOWS: dict[str, dict] = {
    "procurement": {
        "config": "procurement.yaml",
        "requirement": "需求场景/采购审批数字员工需求方案.docx",
        "exec": "规则校验",
        "tiers": ["一定不通过", "拿不准"],
        "nodes": [
            P(name="取单", kind="取数", desc="读取采购结果审批表单字段、审批日志与附件清单（只读）",
              sources=["合同系统 · 采购结果审批流程（wf=100）", "采购结果审批台账（customid 83）"],
              outputs=["表单字段", "审批日志", "附件清单"]),
            P(name="下载附件", kind="资料", desc="按内容签名复用资料中心已下载的原件，缺失的当场同步",
              sources=["资料中心"], outputs=["原件（SHA-256 签名）"]),
            P(name="解析材料", kind="资料", desc="Word / Excel 读正文与文档属性，PDF 先文字层再 OCR，压缩包解压后逐个处理",
              sources=["资料中心解析缓存", "OCR"], outputs=["正文", "文档属性（作者 / 最后修改人）"]),
            P(name="归集材料", kind="处理", desc="识别材料类型（采购公告、采购文件、评审报告、响应文件…）并归到各供应商",
              sources=[], outputs=["材料清单", "供应商归属"]),
            P(name="抽取事实", kind="处理", desc="抽取日期、金额、最高限价、报价、联系方式、公告与采购文件要素",
              sources=[], outputs=["关键时间", "金额", "报价", "联系方式", "要素清单"]),
            P(name="规则校验", kind="校验", desc="18 条规则逐条执行，结果为命中 / 未命中 / 未能识别 / 未执行",
              sources=[], outputs=["规则结论"]),
            P(name="生成报告", kind="报告", desc="按「一定不通过 / 拿不准」两档排列命中项，单列未能识别，入执行档案",
              sources=[], outputs=["分析报告", "执行档案"]),
        ],
        "deps": {
            "P01": ["取单"], "P02": ["抽取事实"], "P03": ["取单", "抽取事实"], "P04": ["抽取事实"],
            "P05": ["抽取事实"], "P06": ["取单", "抽取事实"], "P07": ["抽取事实"], "P08": ["抽取事实"],
            "P09": ["取单", "抽取事实"], "P10": ["解析材料", "归集材料"], "P11": ["归集材料", "抽取事实"],
            "P12": ["抽取事实"], "P13": ["（企业信息查询，待接入）"], "P14": ["（企业信息查询，待接入）"],
            "P15": ["（企业信息查询，待接入）"], "P16": ["抽取事实"], "P17": ["取单", "抽取事实"], "P18": ["抽取事实"],
        },
        "params": {
            "P08": [P(path="p08_min_days", label="最少自然日（含发布当日）", type="int", min=1, max=60, unit="天")],
            "P12": [P(path="p12_tolerance_ratio", label="等差判定容差（占最高报价比例）", type="number", min=0, max=0.1)],
        },
        "plan": [
            P(step="1 拉取待办", nodes=["取单"], match="调整",
              note="待办读取在确认不改变待办状态前只读；改为从采购结果审批台账采集 + 人工输入单号发起"),
            P(step="2 归集材料", nodes=["归集材料"], match="一致", note="表单字段与附件挂到同一笔申请下，附件从流程附件区读取"),
            P(step="3 附件预处理", nodes=["下载附件", "解析材料", "抽取事实"], match="拆分",
              note="下载（签名复用）、解析（文档 / OCR / 压缩包）、抽取要素拆成三个节点，解析失败记「未能识别」"),
            P(step="4 规则校验", nodes=["规则校验"], match="一致",
              note="18 条规则逐条执行；P04、P05、P17（语义）与 P13–P15（企业信息查询）待接入，记「未执行」"),
            P(step="5 生成报告", nodes=["生成报告"], match="一致", note="两档排列、单列未能识别、留存规则版本与生成时间"),
        ],
    },
    "contract": {
        "config": "contract.yaml",
        "requirement": "需求场景/合同审核数字员工.docx",
        "exec": "规则校验",
        "nodes": [
            P(name="取单", kind="取数", desc="读取主合同审批表单字段、审批日志与附件清单（只读；当前账号待办不打开）",
              sources=["合同系统 · 销售合同（主合同）审批流程（wf=99）"], outputs=["表单字段", "审批日志", "附件清单"]),
            P(name="读取台账", kind="取数", desc="按「选择投标项目」到投标及报价台账找到投标流程，读取中标通知书、投标文件、招标文件、联合体协议",
              sources=["投标及报价台账（customid 86）", "投标及报价审批流程（wf=98）"], outputs=["中标通知书", "投标文件", "招标文件", "联合体协议"]),
            P(name="下载附件", kind="资料", desc="按内容签名复用资料中心已下载的原件，缺失的当场同步", sources=["资料中心"],
              outputs=["原件（SHA-256 签名）"]),
            P(name="解析材料", kind="资料", desc="PDF 先文字层再 OCR，Word / Excel 读正文与表格，复用解析缓存",
              sources=["资料中心解析缓存", "OCR"], outputs=["正文（含页码）"]),
            P(name="归集材料", kind="处理", desc="识别合同正文、合同附件、中标通知书、投标文件、招标文件、授权委托书等",
              sources=[], outputs=["材料清单"]),
            P(name="抽取事实", kind="处理", desc="抽取合同价款、中标价、工期、付款节点、违约条款、相对方名称、日期、法律引用等",
              sources=["大模型（语义要点）"], outputs=["合同事实"]),
            P(name="外部查询", kind="取数", desc="查询合同相对方资信（失信 / 被执行 / 破产）、分公司信息、历史合同（重复签订）",
              sources=["天眼查（共享账号，缓存与限流）", "主合同台账（customid 78）"], outputs=["资信信息", "历史合同"]),
            P(name="规则校验", kind="校验", desc="30 条规则并发执行：确定性规则直接计算，语义规则结合大模型与原文证据，外部数据规则依赖外部查询",
              sources=["大模型"], outputs=["规则结论（通过 / 问题 / 复核 / 待补充 / 不适用）"]),
            P(name="生成报告", kind="报告", desc="汇总每条规则状态、说明、证据，渲染证据截图，入执行档案", sources=[],
              outputs=["审核报告", "证据截图", "执行档案"]),
        ],
        "deps": {
            "R01": ["读取台账", "抽取事实"], "R02": ["读取台账", "解析材料", "抽取事实"], "R03": ["读取台账", "抽取事实"],
            "R04": ["读取台账", "抽取事实"], "R05": ["读取台账", "抽取事实"], "R06": ["读取台账", "归集材料"],
            "R07": ["读取台账", "抽取事实"], "R08": ["读取台账", "抽取事实"], "R09": ["抽取事实"], "R10": ["抽取事实"],
            "R11": ["抽取事实"], "R12": ["抽取事实"], "R13": ["抽取事实"], "R14": ["抽取事实"],
            "R15": ["取单", "抽取事实"], "R16": ["外部查询", "归集材料"], "R17": ["外部查询"], "R18": ["抽取事实"],
            "R19": ["取单"], "R20": ["取单", "抽取事实"], "R21": ["外部查询"], "R22": ["取单", "抽取事实"],
            "R23": ["抽取事实"], "R24": ["读取台账", "取单"], "R25": ["取单", "抽取事实"], "R26": ["取单", "抽取事实"],
            "R27": ["取单", "抽取事实"], "R28": ["取单"], "R29": ["抽取事实", "外部查询"], "R30": ["读取台账", "抽取事实"],
        },
        "params": {
            "R10": [P(path="penalty_limit_ratio", label="违约金比例上限（占合同总价）", type="number", min=0, max=1)],
            "R15": [P(path="our_names", label="我方主体名称（用于识别合同相对方）", type="list")],
            "R24": [P(path="award_sign_days", label="中标通知书发出后应签订合同的天数", type="int", min=1, max=365, unit="天")],
        },
        "plan": [
            P(step="01 进入审核节点", nodes=["取单"], match="一致",
              note="读取合同审批事项及授权可访问的表单、正文与附件；另有资料中心定时采集台账单据"),
            P(step="02 启动智能审核", nodes=[], match="一致", note="人工点选 / 输入单号、批量审查、资料就绪后自动审查；每次生成新任务"),
            P(step="03 材料准备", nodes=["读取台账", "下载附件", "解析材料", "归集材料", "抽取事实"], match="拆分",
              note="中标与投标材料不在合同流程中，单独「读取台账」；下载、解析复用资料中心缓存"),
            P(step="04 并行规则校验", nodes=["外部查询", "规则校验"], match="拆分",
              note="外部数据（天眼查、主合同台账）提前在「外部查询」节点取回，再与其余规则一起并发执行"),
            P(step="05 汇总报告", nodes=["生成报告"], match="一致", note="每条规则明确状态（含「不适用」「无异常」）与证据"),
        ],
    },
    "meeting": {
        "config": "meeting.yaml",
        "requirement": "需求场景/三会智能审查数字员工_2026年10月19日112310.docx",
        "exec": "审查",
        "rules_are_nodes": True,
        "nodes": [
            P(name="取单", kind="取数", desc="在门户「我的发起 / 已办 / 已阅」定位内部请示，读取表单字段与附件清单（不打开待办）",
              sources=["公文系统 · 内部请示（致远）"], outputs=["标题", "事项类型", "会议类型", "审批 / 上会依据", "附件清单"]),
            P(name="下载附件", kind="资料", desc="按内容签名复用资料中心已下载的原件", sources=["资料中心"], outputs=["原件（SHA-256 签名）"]),
            P(name="解析材料", kind="资料", desc="优先文字层，必要时 OCR；复用解析缓存", sources=["资料中心解析缓存"], outputs=["正文"]),
            P(name="归集材料", kind="处理", desc="识别请示正文、采购公告、评审报告、成交通知书、报价表等", sources=[], outputs=["材料清单"]),
            P(name="抽取要素", kind="处理", desc="识别事项阶段、项目名称、金额（万元 / 元换算）、审批依据结构", sources=[],
              outputs=["事项阶段", "金额", "依据要素"]),
            P(name="制度检索", kind="取数", desc="在四份制度中定位所引用条款、金额档位与最终审批主体（红色标识）",
              sources=["权责手册（2026 修订版）", "重大经营管理事项清单", "党委决定的重大事项清单", "董事会授权决策方案"],
              outputs=["已核实条款", "档位", "审批主体"]),
            P(name="审查", kind="校验", desc="5 个审查节点并发执行，按 01–05 固定顺序输出综合意见；严格模式下模型失败则整单中止",
              sources=["大模型"], outputs=["综合意见（核查通过 / 发现问题 / 待补充 / 人工复核）"]),
            P(name="生成报告", kind="报告", desc="对话式逐条输出 + 表格汇总，入执行档案", sources=[], outputs=["审查报告", "执行档案"]),
        ],
        "deps": {"N01": ["归集材料", "抽取要素"], "N02": ["取单", "制度检索"], "N03": ["抽取要素", "制度检索"],
                 "N04": ["抽取要素"], "N05": ["归集材料", "解析材料"]},
        "params": {},
        "flow_params": [P(path="strict", label="严格模式：模型调用失败或返回无法解析时整单中止（需求 T07）", type="bool")],
        "plan": [
            P(step="01 进入审核页", nodes=["取单"], match="一致", note="读取授权可访问的表单、正文与附件；只定位我的发起 / 已办 / 已阅"),
            P(step="02 材料解析", nodes=["下载附件", "解析材料", "归集材料"], match="拆分", note="复用缓存时显示「复用解析结果」"),
            P(step="03 业务核验", nodes=["抽取要素", "制度检索", "审查"], match="拆分",
              note="识别事项阶段 → 检索四份制度 → N01–N05 五个审查节点"),
            P(step="04 结果展示", nodes=["生成报告"], match="一致", note="按 01–05 固定顺序，每个节点一条综合意见"),
            P(step="05 人工处理", nodes=[], match="系统外", note="审核人员按原流程处理，系统不改 OA 状态"),
            P(step="06 重新审查", nodes=[], match="一致", note="人工重新审查或材料指纹变化后自动重审，旧报告标记取代"),
        ],
    },
    "reimburse": {
        "config": "reimburse.yaml",
        "requirement": "需求场景/财务报销AI初审-需求说明书（讨论稿V2.1）.docx",
        "exec": "规则校验",
        "nodes": [
            P(name="取单", kind="取数", desc="读取报销单据字段、费用明细与附件清单（通财云外网不可达，当前读取本地事项）",
              sources=["通财云（金蝶云苍穹，待打通）", "本地事项"], outputs=["单据字段", "费用明细", "附件清单"]),
            P(name="下载附件", kind="资料", desc="按内容签名复用资料中心已下载的原件", sources=["资料中心"], outputs=["原件"]),
            P(name="解析材料", kind="资料", desc="发票、行程单、清单等文档与图片解析（OCR）", sources=["资料中心解析缓存", "OCR"], outputs=["正文"]),
            P(name="归集材料", kind="处理", desc="识别发票、行程单、会议通知、公文流转单、清单、入库单等材料类型", sources=[], outputs=["材料清单"]),
            P(name="抽取要素", kind="处理", desc="抽取发票号、日期、金额、人员、行程、商品名称等", sources=[], outputs=["票据要素"]),
            P(name="规则校验", kind="校验", desc="按单据类别执行 43 条规则（数据 / 材料 / 标准 / 风险）", sources=["报销标准（config/reimburse.yaml）"],
              outputs=["规则结论"]),
            P(name="生成报告", kind="报告", desc="生成初审提示单，入执行档案", sources=[], outputs=["初审提示单", "执行档案"]),
        ],
        "deps_by_category": {"数据": ["抽取要素"], "材料": ["归集材料"], "标准": ["抽取要素"], "风险": ["抽取要素"]},
        "params": {
            "ENT-02": [P(path="accompany.商务外事.small_max_guests", label="商务外事：可对等陪餐的最多来宾人数", type="int", min=1, max=50),
                       P(path="accompany.商务外事.over_ratio", label="商务外事：超过时陪餐不超过总人数的比例", type="number", min=0, max=1),
                       P(path="accompany.其他公务.small_max_guests", label="其他公务：小规模来宾人数上限", type="int", min=1, max=50),
                       P(path="accompany.其他公务.small_max_accompany", label="其他公务：小规模时陪餐人数上限", type="int", min=0, max=20),
                       P(path="accompany.其他公务.over_ratio", label="其他公务：超过时陪餐不超过总人数的比例", type="number", min=0, max=1)],
            "ENT-03": [P(path="per_capita.high.商务外事", label="高档职级 · 商务外事人均标准", type="int", min=0, max=5000, unit="元/人"),
                       P(path="per_capita.high.其他公务", label="高档职级 · 其他公务人均标准", type="int", min=0, max=5000, unit="元/人"),
                       P(path="per_capita.normal.商务外事", label="一般职级 · 商务外事人均标准", type="int", min=0, max=5000, unit="元/人"),
                       P(path="per_capita.normal.其他公务", label="一般职级 · 其他公务人均标准", type="int", min=0, max=5000, unit="元/人"),
                       P(path="per_capita.high_grades", label="高档职级名单", type="list")],
            "ENT-05": [P(path="gift.per_person_max", label="纪念品每人上限", type="int", min=0, max=5000, unit="元"),
                       P(path="gift.max_times", label="纪念品赠送次数上限", type="int", min=0, max=10, unit="次")],
            "ENT-06": [P(path="central_soes.keywords", label="中央企业名录（关键字）", type="list")],
            "ENT-09": [P(path="prior_year_cutoff_month", label="每年自此月起不允许报销上年度发票", type="int", min=1, max=12, unit="月")],
            "ENT-10": [P(path="entertain_invoice_days", label="招待日期与开票日期允许相差", type="int", min=0, max=30, unit="天")],
            "ENT-12": [P(path="sensitive_words", label="敏感单位字眼", type="list")],
            "OFF-04": [P(path="office_negative_list.maintained", label="负面清单已由财务确认", type="bool"),
                       P(path="office_negative_list.words", label="办公费发票内容负面清单", type="list")],
            "OFF-05": [P(path="prepaid_words", label="预付储值类关键词", type="list")],
            "TRA-01": [P(path="ride_platforms", label="第三方出行 / 租车平台", type="list")],
            "TRN-01": [P(path="training_item_name", label="培训费指定商品名称", type="text")],
        },
        "shared": {"TRV-07": "ENT-02"},  # 共用参数：在被共用的规则上修改
        "plan": [
            P(step="单据读取", nodes=["取单"], match="调整", note="通财云外网不可达，需在内网 / VPN 下打通；当前审查本地导入的事项"),
            P(step="附件解析", nodes=["下载附件", "解析材料"], match="一致", note="发票、行程单等图片走 OCR"),
            P(step="要素抽取", nodes=["归集材料", "抽取要素"], match="一致", note="材料识别与票据要素抽取"),
            P(step="规则初审", nodes=["规则校验"], match="一致", note="43 条规则按单据类别执行；部分规则待业务口径（停用并写明原因）"),
            P(step="初审提示单", nodes=["生成报告"], match="一致", note="提示单供会计审核岗参考，不写回通财云"),
        ],
    },
}


def deps_of(employee: str, rule: dict) -> list[str]:
    f = FLOWS[employee]
    if rule["rule_id"] in (f.get("deps") or {}):
        return f["deps"][rule["rule_id"]]
    return (f.get("deps_by_category") or {}).get(rule.get("category") or "", [])


def params_of(employee: str, rule_id: str) -> list[dict]:
    return (FLOWS[employee].get("params") or {}).get(rule_id, [])
