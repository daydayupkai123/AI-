"""自动审查派发：新单据发起、材料指纹变化重审、并发上限、失败不反复重试、未开启的员工不派发；受限对话的闲聊识别。"""
import pytest

from workbench_service.auto_review import AutoDispatcher, decide
from shared.restricted_chat import CHITCHAT_RE, guide_text
from storage_service import settings
from tests.support.env import temp_store


class Emp:
    def __init__(self, id, sources=("contract",)):
        self.id, self.sources = id, sources


class FakeRC:
    def __init__(self, snaps):
        self.snaps = snaps

    def requests(self, employee=None, status=None, limit=100):
        return [s for s in self.snaps if s["employee"] == employee and (status is None or s["status"] == status)]


def _snap(rid, fp, status="ready", emp="contract"):
    return {"source": "contract", "request_id": rid, "employee": emp, "status": status, "material_fp": fp}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    cfg = {"auto_review": {"contract": True, "procurement": False}, "auto_review_concurrency": 2}
    monkeypatch.setattr(settings, "collect", lambda: cfg)
    store = temp_store(tmp_path)
    rc = FakeRC([_snap("1", "fpA"), _snap("2", "fpB"), _snap("3", "fpC", status="listed"),
                 _snap("9", "fpZ", emp="procurement")])
    launched = []

    def launch(emp, rid, source, trigger_by):
        tid = store.create_task(emp.id, source, rid, "v1", trigger_by)
        snap = next(s for s in rc.snaps if s["request_id"] == rid)
        store.set_task_fp(tid, snap["material_fp"])
        launched.append((rid, trigger_by))
        return tid

    d = AutoDispatcher(store, lambda: rc, launch, [Emp("contract"), Emp("procurement")])
    return d, store, rc, launched, cfg


def test_decide():
    assert decide(_snap("1", "a"), None) == "new"
    assert decide(_snap("1", "a", status="partial"), None) is None
    assert decide(_snap("1", "a"), {"status": "running", "material_fp": "x"}) is None
    assert decide(_snap("1", "a"), {"status": "done", "material_fp": "a"}) is None
    assert decide(_snap("1", "b"), {"status": "done", "material_fp": "a"}) == "changed"
    assert decide(_snap("1", "a"), {"status": "failed", "material_fp": "a"}) is None  # 失败且材料未变不重试


def test_tick_launches_ready_and_respects_concurrency(env):
    d, store, rc, launched, cfg = env
    started = d.tick()
    assert [s["request_id"] for s in started] == ["1", "2"] and all(s["reason"] == "new" for s in started)
    assert launched == [("1", "auto"), ("2", "auto")]  # listed 的 3 未就绪、procurement 未开启
    assert d.tick() == []  # 两笔都在运行，且达到并发上限
    for t in store.list_tasks("contract"):
        store.finish_task(t["task_id"], "done")
    assert d.tick() == []  # 材料未变化，不重审
    rc.snaps[0]["material_fp"] = "fpA2"
    again = d.tick()
    assert [(s["request_id"], s["reason"]) for s in again] == [("1", "changed")]
    cfg["auto_review_concurrency"] = 0
    rc.snaps[1]["material_fp"] = "fpB2"
    assert d.tick() == []


def test_tick_records_errors(env):
    d, *_ = env
    d.resources = lambda: (_ for _ in ()).throw(RuntimeError("资料中心不可用"))
    assert d.tick() == [] and "资料中心不可用" in d.last_error


REPORT = {"header": {"request_id": "1671817"},
          "rules": [{"rule_id": "R07", "name": "违约责任条款识别", "code": "issue", "status": "发现问题", "message": "违约金比例变更",
                     "items": ["违约金 1‰ → 0.1‰"], "evidence": [{"file": "合同.pdf", "snippet": "每逾期一日支付 0.1‰"}]},
                    {"rule_id": "R13", "name": "价格表述规范性", "code": "pass", "status": "核查通过", "message": "无异常",
                     "evidence": [{"file": "合同.pdf", "snippet": "x" * 500}]}],
          "materials": [{"role": "合同正文", "filename": "审批修改版-津巴布韦勘测合同文本20261102.pdf"}]}


def test_report_related_gate():
    from shared.restricted_chat import report_related

    for q in ("R07 为什么判为发现问题？", "违约责任条款识别的依据是什么", "合同正文里怎么写的", "r13 呢",
              "审批修改版-津巴布韦勘测合同文本里有没有写", "还需要补充什么材料"):
        assert report_related(q, REPORT), q
    for q in ("帮我写一首关于秋天的诗", "今天股市怎么样", "给我讲讲量子计算"):
        assert not report_related(q, REPORT), q


def test_compact_focuses_on_asked_rules():
    from shared.restricted_chat import compact

    c = compact(REPORT, "R13 为什么通过")
    r07, r13 = c["规则结果"]
    assert "要点" not in r07 and r07 == {"编号": "R07", "名称": "违约责任条款识别", "结果": "发现问题"}
    assert r13["依据"][0]["snippet"] == "x" * 160  # 证据片段截断，控制上下文长度
    d = compact(REPORT, "有哪些问题")  # 未点名时展开问题 / 复核项
    assert "要点" in d["规则结果"][0] and "要点" not in d["规则结果"][1]


def test_chitchat_and_guide():
    for t in ("你好", "您好！", "在吗", "讲个笑话", "你是谁？"):
        assert CHITCHAT_RE.match(t), t
    for t in ("R05 为什么判了问题", "你好，R05 的依据是哪份文件"):
        assert not CHITCHAT_RE.match(t), t
    g = guide_text({"persona": "陈睿", "name": "合同审核数字员工", "desc": "主合同审批"}, "发送单号")
    assert "不闲聊" in g and "待审单据" in g and "发送单号" in g
