"""合同事实抽取的边界（来自真实单据联调中发现的误报，文本为改写后的合成样例）。"""
from core.materials import Material
from employees.contract import extract as E
from employees.contract.rules import clauses as CL
from employees.contract.rules import compare as CP
from employees.contract.rules.external import NOT_NAME, PERSON_RE


def mat(text: str, name: str = "合同.pdf") -> Material:
    return Material(sig="s", filename=name, role="contract", doc={"status": "ok", "pages": [{"no": 1, "text": text}]})


def test_parties_supervision_roles_and_military_unit():
    m = mat("第一部分协议书\n委托人（全称）：\n某某部队32139 部队\n监理人（全称）：通用技术集团工程设计有限公司\n")
    ps = E.parties(m)
    assert [p["name"] for p in ps["甲方"]] == ["某某部队32139部队"]
    assert [p["name"] for p in ps["乙方"]] == ["通用技术集团工程设计有限公司"]
    cp = E.counterparty(ps, ["通用技术集团工程设计有限公司"])
    assert cp["side"] == "甲方" and cp["name"] == "某某部队32139部队"


def test_laws_prefix_not_confused_with_civil_code():
    m = mat("根据《中华人民共和国民法典》、《中华人民共和国建筑法》、《中华人民共和国民法》及《合同法》订立本合同。")
    wrong = {x["value"]: x["wrong"] for x in E.laws(m)}
    assert wrong["中华人民共和国民法典"] is None
    assert wrong["中华人民共和国建筑法"] is None
    assert wrong["中华人民共和国民法"] == "名称有误"
    assert "废止" in wrong["合同法"]


def test_payment_ignores_fee_ratio_and_marks_cumulative():
    m = mat("本合同采用固定总价方式，乙方中标取费比例为76%。\n"
            "首付款：签订合同并递交履约保函（保证金）的15 个工作日支付签约合同价\n的10%。\n"
            "中期支付：工程竣工验收后，支付至建安费计算的\n80%。\n结算支付：工程结算审核后，支付至结算审核价格计算的95%\n"
            "签订合同15日内，乙方向甲方递交合同价5%的履约保函。\n")
    pc = E.payment_percentages([m])
    assert pc["value"] == [10, 80, 95] and pc["cumulative"] is True
    f = {"contract": m, "payment_contract": pc,
         "payment_form": {"value": [10, 80, 95], "file": "审批表单", "snippet": "10%、80%、95%"},
         "form": {"付款节点明细": {"value": "10%、80%、95%", "label": "付款条件"}}}
    assert CP.r20(f).code == "pass"


def test_payment_milestone_table_keeps_retention_and_drops_total():
    m = mat("附件2 合同价格和付款里程碑序号付款里程碑建议比例金额\n1合同生效，乙方提交项目实施计划20%420000\n"
            "2现场测量外业完工15%315000\n3岩土勘察外业完工35%735000\n4成果交付评审通过25%525000\n"
            "5质量保证金5%105000质保期内无缺陷\n合计100%2100000\n")
    assert E.payment_percentages([m])["value"] == [20, 15, 35, 25, 5]


def test_tax_rate_in_brackets_and_partial_message():
    m = mat("本合同价格¥ 236200.00 元，本合同价格是包含增值税的价税合计金额，增值税率为【6】%。")
    assert E._tax_rate_finder(m.text)[0] == "6%"
    f = {"contract": m, "price": {"value": 236200.0, "file": "合同.pdf", "snippet": ""},
         "tax": {"不含税金额": None, "税率": {"value": "6%", "file": "合同.pdf", "snippet": ""}, "税额": None}}
    r = CL.r12(f)
    assert r.code == "issue" and "已列明税率 6%" in r.message and "未列明不含税金额、税额" in r.message


def test_dispute_choice_litigation_means_no_arbitration():
    text = ("7.2.仲裁或诉讼 合同争议的最终解决方式为下列第（2）种方式：（1）提请/仲裁委员会进行仲裁。"
            "（2）向当地人民法院提起诉讼。")
    assert E.dispute_choice(text) == "诉讼"
    assert E.dispute_choice("争议解决方式为下列第（1）种：（1）提交济南仲裁委员会仲裁。（2）向法院起诉。") == "仲裁"
    assert E.dispute_choice("双方协商解决。") is None
    r = CL.r14({"contract": mat(text), "arbitration": [], "has_arbitration": True, "dispute_choice": "诉讼"})
    assert r.code == "na" and "诉讼" in r.message
    r = CL.r14({"contract": mat(text), "arbitration": [], "has_arbitration": True, "dispute_choice": "仲裁"})
    assert r.code == "review"


def test_person_names_require_label_separator():
    text = ("总监理工程师姓名：张胜，身份证号码：1234。总监理工程师及重要岗位监理人员应保持稳定。"
            "乙方擅自更换人员的，总监按照4万元/人/次缴纳违约金。项目负责人为李四。")
    names = {m.group(2): m.group(1) for m in PERSON_RE.finditer(text) if not NOT_NAME.search(m.group(2))}
    assert names == {"张胜": "总监理工程师", "李四": "项目负责人"}


def test_liability_formula_cut_at_next_clause():
    m = mat("4.1.1.监理人赔偿金额按下列方法确定：\n赔偿金＝直接经济损失×正常工作酬金÷工程概算投资额（或建筑安装工程\n费）\n"
            "4.2.委托人的违约责任\n")
    m.role = "contract_text"
    f = E.extract({}, [m], {})
    assert f["liability_formula"][0]["value"] == "赔偿金＝直接经济损失×正常工作酬金÷工程概算投资额（或建筑安装工程费）"


def test_liability_formula_goes_to_review():
    f = {"contract": mat("x"), "cap_hits": [],
         "liability_hits": [{"value": "监理人的违约责任", "file": "合同.pdf", "snippet": "监理人的违约责任"}],
         "liability_formula": [{"value": "赔偿金＝直接经济损失×正常工作酬金÷工程概算投资额", "file": "合同.pdf", "snippet": ""}]}
    r = CL.r09(f)
    assert r.code == "review" and "公式" in r.message
