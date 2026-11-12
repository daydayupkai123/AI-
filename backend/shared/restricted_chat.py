"""受限对话：数字员工是自动化工作流，对话只是任务入口。

- 没有当前报告：不调模型，固定回复「我能做这些」（guide_text），由前端给出任务按钮
- 有当前报告：只依据该报告的结论与证据回答追问；与报告无关的问题固定拒答，不闲聊、不编造
"""
from __future__ import annotations

import json
import re

OUT_OF_SCOPE = "报告中没有相关依据。我只能就本次审查报告的结论与证据作答，其他事项请直接发送单号发起审查，或查看待审单据。"
CHITCHAT_RE = re.compile(r"^(你好|您好|hi|hello|嗨|在吗|谢谢|多谢|早上好|晚上好|下午好|你是谁|介绍一下你自己|讲个笑话|天气|今天几号)"
                         r"[呀啊吗呢！!。.？?\s]*$", re.I)


RULE_ID_RE = re.compile(r"(?<![A-Za-z0-9])([RNP]\d{2}|[A-Z]{2,4}-\d{2})(?![0-9])", re.I)
FOLLOWUP_WORDS = re.compile(r"为什么|为何|依据|原文|证据|结论|理由|怎么判|如何判|判定|问题|复核|补充|材料|附件|条款|哪份|哪个文件|"
                            r"规则|报告|通过|不适用|待补充|人工|差异|不一致|金额|价款|日期|工期|付款|违约|供应商|会议|档位|发票")


def rule_ids_in(msg: str, report: dict) -> list[str]:
    ids = {r["rule_id"].upper() for r in report.get("rules") or []}
    return [m.upper() for m in RULE_ID_RE.findall(msg or "") if m.upper() in ids]


def report_related(msg: str, report: dict) -> bool:
    """确定性判断问题是否针对当前报告：提到报告中的规则编号 / 规则名称 / 文件名 / 单号，或含追问用语。"""
    t = re.sub(r"\s+", "", msg or "")
    if not t:
        return False
    if rule_ids_in(t, report) or FOLLOWUP_WORDS.search(t):
        return True
    names = [r.get("name") or "" for r in report.get("rules") or []]
    names += [m.get(k) or "" for m in report.get("materials") or [] for k in ("filename", "role")]
    names.append(str((report.get("header") or {}).get("request_id") or ""))
    return any(len(n) >= 2 and (n in t or (len(n) >= 4 and n[:4] in t)) for n in names if n)


def guide_text(emp: dict, input_hint: str) -> str:
    return (f"我是{emp['persona']}，{emp['name']}，负责自动完成{emp.get('desc') or emp['name']}。"
            f"我不闲聊，可以为你做这些：\n"
            f"- **发起审查**：{input_hint}\n"
            f"- **待审单据**：查看资料中心已采集的待审单据及自动审查结果\n"
            f"- **规则清单 / 历史报告**：查看我核验的规则与以往的审查报告\n"
            f"- **报告追问**：审查完成后，可就报告中的结论与证据提问")


def system_prompt(emp: dict, report: dict | None, *, scope: str, input_hint: str,
                  rules: list[dict], rules_title: str, question: str = "") -> str:
    lines = "\n".join(f"- {r['rule_id']} {r['name']}（{r.get('category') or r.get('group') or ''}）" for r in rules)
    if report:  # 有报告时规则清单由报告给出，避免上下文过长被截断
        lines = "（见下方报告中的规则结果）"
    parts = [
        f"你是「{emp['persona']}」，通用技术集团工程设计有限公司{emp['dept']}的 AI 数字员工，职位是{emp['name']}。",
        f"你的工作：{emp['intro']}",
        f"工作方式：{scope}只读取单据与附件并输出审核报告；不审批、不退回、不改任何流程状态，结论供审核人参考。",
        f"{input_hint}你不要假装已经审查或编造审查结果。",
        f"{rules_title}：\n{lines}",
        "结果状态含义：发现问题 = 有原文依据的差异或违规；人工复核 = 证据冲突或数据源不可用，需要人确认；"
        "待补充 = 缺少材料或字段；不适用 = 规则适用条件不满足；审查中止 = 模型或系统失败，未形成结论。只有「核查通过」才表示该条无异常。",
        "对话边界：你是自动化审查工作流中的数字员工，不闲聊。只回答与下面这份审查报告直接相关的问题（某条结论为什么这样判、"
        "依据是哪份文件哪段原文、还需要补充什么材料）。问题与报告无关、或报告中没有依据时，只回复："
        f"「{OUT_OF_SCOPE}」不要给出其他内容。",
        "回答要求：使用简体中文；先给结论再给理由；简洁、条理清楚，可用 Markdown 的加粗、列表；"
        "只依据报告内容，引用规则编号与依据文件，不确定就直说，不编造文件、金额、日期或单位信息。",
    ]
    if report:
        parts.append("以下是本次对话中最近一份审核报告（JSON 摘要），用户的追问请基于它回答；回答中提到的规则编号与名称必须和报告一致：\n"
                     + json.dumps(compact(report, question), ensure_ascii=False))
    return "\n\n".join(parts)


def compact(rep: dict, question: str = "") -> dict:
    """按问题精简报告：问到的规则（或未点名时的问题 / 复核项）给完整结论、要点与证据，其余只给编号、名称、结果。
    本地模型上下文有限（8K），过长会从开头截断，连同对话边界一起丢失。"""
    def ev(e):
        if not isinstance(e, dict):
            return e
        out = {k: e.get(k) for k in ("label", "file", "page", "value") if e.get(k) not in (None, "")}
        if e.get("snippet"):
            out["snippet"] = str(e["snippet"])[:160]
        return out

    asked = set(rule_ids_in(question, rep))
    focus = asked or {r["rule_id"] for r in rep.get("rules", []) if r.get("code") in ("issue", "review")
                      or r.get("status") == "命中"}
    rules = []
    for r in rep.get("rules", []):
        if r["rule_id"] in focus:
            rules.append({"编号": r["rule_id"], "名称": r["name"], "结果": r["status"], "说明": r["message"],
                          "要点": (r.get("items") or [])[:6], "依据": [ev(e) for e in (r.get("evidence") or [])[:4]]})
        else:
            rules.append({"编号": r["rule_id"], "名称": r["name"], "结果": r["status"]})
    return {
        "单据": {k: v for k, v in (rep.get("header") or {}).items() if k in ("request_id", "request_name", "subject",
                                                                              "workflow_name", "source")},
        "要素": (rep.get("header") or {}).get("facts"),
        "结论": rep.get("verdict"),
        "规则结果": rules,
        "材料": [{"类型": m.get("role"), "文件": m.get("filename")} for m in rep.get("materials", [])][:30],
    }
