/* AI 数字员工工作台（测试版） */
const NODES = ["取单", "下载附件", "解析材料", "归集材料", "抽取事实", "规则校验", "生成报告"];
const NODE_HINT = {
  "取单": "读取表单字段与审批日志", "下载附件": "下载原件并计算内容签名", "解析材料": "文字层提取 / OCR / 解压，命中缓存直接复用",
  "归集材料": "识别材料类型并归到供应商", "抽取事实": "抽取时间、金额、报价、联系方式等", "规则校验": "18 条规则逐条执行", "生成报告": "按风险分档汇总并留存",
};
const COLOR = { procurement: "blue", contract: "purple", meeting: "green", reimburse: "orange" };
const TITLE = { procurement: "采购审批", contract: "合同审核", meeting: "三会审查", reimburse: "财务报销初审" };
const I = {
  chev: '<path d="M6 9l6 6 6-6"/>',
  arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  copy: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
  redo: '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>',
  down: '<path d="M12 4v12M6 11l6 6 6-6M5 20h14"/>',
  up: '<path d="M7 11v9H4v-9zM7 11l4-8c1.7 0 2.5 1 2.2 2.6L12.6 9H19a2 2 0 0 1 2 2.3l-1.2 7A2 2 0 0 1 17.8 20H7"/>',
  doc: '<path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5M9 13h6M9 17h4"/>',
  list: '<path d="M9 6h11M9 12h11M9 18h11"/><path d="M4 6h.01M4 12h.01M4 18h.01"/>',
  clock: '<circle cx="12" cy="12" r="8"/><path d="M12 8v4l3 2"/>',
  alert: '<path d="M12 4l9 16H3z"/><path d="M12 10v4M12 17h.01"/>',
  check: '<path d="M5 12l5 5 9-10"/>',
  x: '<path d="M6 6l12 12M18 6L6 18"/>',
  spark: '<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5L18 18M6 18l2.5-2.5M15.5 8.5L18 6"/>',
  bulb: '<path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 0-3.5 10.9c.6.4 1 1.1 1 1.9V16h5v-.2c0-.8.4-1.5 1-1.9A6 6 0 0 0 12 3z"/>',
  chat: '<path d="M4 5h16v11H9l-5 4z"/>',
  search: '<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4-4"/>',
  inbox: '<path d="M4 13l2.5-8h11L20 13v6H4z"/><path d="M4 13h5l1 2h4l1-2h5"/>',
  flow: '<circle cx="5" cy="12" r="2"/><circle cx="19" cy="5.5" r="2"/><circle cx="19" cy="18.5" r="2"/><path d="M7 12h4l6-6.5M11 12l6 6.5"/>',
  db: '<ellipse cx="12" cy="5.5" rx="7" ry="2.5"/><path d="M5 5.5v13c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5v-13"/><path d="M5 12c0 1.4 3.1 2.5 7 2.5s7-1.1 7-2.5"/>',
  refresh: '<path d="M20 11a8 8 0 1 0-2.3 5.7"/><path d="M20 4v7h-7"/>',
};
const svg = (k, cls = "") => `<svg class="${cls}" viewBox="0 0 24 24">${I[k]}</svg>`;
const RAIL = [
  ["工作台", '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/>'],
  ["资料中心", I.db],
  ["流程与规则", I.flow],
];

const $ = (s, root = document) => root.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const state = { employees: [], current: null, running: null, runningEmp: null, follow: true, last: {}, history: [], lastTask: null, llm: null, chatting: false };
const cur = () => state.current || "procurement";
const usable = (e) => e && (e.status === "online" || e.status === "beta");
const isReview = (id) => emp(id).kind === "review";
const DEMO_RE = /^DEMO-[A-Z]{2}-\d{3}$/i;
const DEMO_EMP = { HT: "contract", SH: "meeting", BX: "reimburse" };
const CODE_ST2 = { issue: "hit", review: "hitd", missing: "unread", error: "err", pass: "pass", na: "notrun", notrun: "notrun" };
const CODE_RL = { issue: "hc", review: "hd", missing: "ms", error: "er", pass: "ps" };
const STATUS_TEXT = { online: "已上线", beta: "测试中" };
const LIVE_SRC = { contract: "合同系统", docflow: "公文系统", fincloud: "通财云" };

function avatar(id, size = "", status = null) {
  const st = status === null ? "" : `<span class="st ${status ? "on" : ""}"></span>`;
  return `<div class="av ${size}"><img src="/assets/avatars/${id}.jpg" alt="" draggable="false">${st}</div>`;
}
const emp = (id) => state.employees.find((e) => e.id === id) || {};
const now = () => { const d = new Date(); return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`; };
function fmtMs(ms) {
  if (ms == null) return "";
  const s = ms / 1000;
  return s < 60 ? `${s.toFixed(1)}s` : `${Math.floor(s / 60)}分${String(Math.round(s % 60)).padStart(2, "0")}秒`;
}
function fmtTime(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000), n = new Date();
  const hm = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  return d.toDateString() === n.toDateString() ? hm : `${d.getMonth() + 1}月${d.getDate()}日`;
}
function methodTag(m) {
  const cls = /直接|单一/.test(m || "") ? "direct" : /招标|谈判/.test(m || "") ? "tender" : "";
  return `<span class="mt ${cls}">${esc(m || "—")}</span>`;
}
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.add("hidden"), 1800);
}
function errorCard({ title, hint, detail, code }, actions = {}) {
  const portal = code === "SessionExpired" || /登录/.test(title || "");
  return `<div class="ecard"><div class="ei">${svg("alert")}</div><div class="eb">
    <div class="et">${esc(title || "出现了一点问题")}</div>
    ${hint ? `<div class="eh">${esc(hint)}</div>` : ""}
    <div class="eacts">
      ${actions.retry ? `<button class="btn primary" data-a="retry">${svg("redo")}${esc(actions.retry)}</button>` : ""}
      ${portal ? `<a class="btn" href="https://i.gt.cn/" target="_blank">${svg("arrow")}打开门户登录</a>` : ""}
    </div>
    ${detail ? `<details class="edet"><summary>技术详情</summary><pre>${esc(detail)}</pre></details>` : ""}
  </div></div>`;
}

function greeting() {
  const h = new Date().getHours();
  return h < 6 ? "夜深了" : h < 11 ? "早上好" : h < 13 ? "中午好" : h < 18 ? "下午好" : "晚上好";
}

/* ============ 初始化 ============ */
async function init() {
  $("#rail").innerHTML = `<div class="me" title="我">${avatar("me", "md")}</div>` +
    RAIL.map(([n, p], i) => `<div class="rail-item ${i === 0 ? "active" : ""}" title="${n}" role="button" tabindex="0"><svg viewBox="0 0 24 24">${p}</svg>${n}</div>`).join("");
  $("#rail").onkeydown = (ev) => { if ((ev.key === "Enter" || ev.key === " ") && ev.target.closest(".rail-item")) { ev.preventDefault(); ev.target.click(); } };
  $("#rail").onclick = (ev) => {
    if (ev.target.closest(".rail-item[title='工作台']")) showWelcome();
    else if (ev.target.closest(".rail-item[title='资料中心']")) showCenter(state.current || "");
    else if (ev.target.closest(".rail-item[title='流程与规则']")) showFlows(state.current || "procurement");
  };
  bindCenter();
  $("#hello").innerHTML = `${avatar("me", "xs")}${greeting()}，今天想让哪位数字员工帮忙？`;

  state.employees = await (await fetch("/api/employees")).json();
  renderList();
  renderCards();
  $("#welcome-chips").innerHTML = state.employees.map((e) =>
    `<span class="qchip" data-emp="${e.id}">${avatar(e.id, "xs")}${esc(e.persona)} · ${TITLE[e.id]}</span>`).join("");
  $("#welcome-chips").onclick = (ev) => { const c = ev.target.closest(".qchip"); if (c) openChat(c.dataset.emp); };

  $("#search").oninput = renderList;
  $("#btn-collapse").onclick = () => $("#app").classList.toggle("collapsed");
  $("#btn-new").onclick = () => openChat(cur());
  $("#btn-newchat").onclick = () => openChat(cur());
  bindComposer("#welcome-input", "#welcome-send", (v) => { openChat(guessEmployee(v), true); handleInput(v); });
  refreshLlm();
  setInterval(refreshLlm, 15000);
  bindComposer("#chat-input", "#chat-send", (v) => handleInput(v));
  document.querySelectorAll("[data-act]").forEach((b) => (b.onclick = (ev) => {
    ev.stopPropagation();
    if (b.dataset.act === "flow") return showCenter(state.current || "");
    if (!state.current) openChat(cur(), true);
    if (!usable(emp(cur()))) return toast(`${emp(cur()).persona}正在建设中`);
    ({ samples: () => showSamples(true), rules: showRules, history: toggleHistory, queue: () => showQueue() })[b.dataset.act]();
  }));
  const box = $("#messages");
  box.addEventListener("scroll", () => {
    state.follow = box.scrollHeight - box.scrollTop - box.clientHeight < 80;
    $("#to-latest").classList.toggle("hidden", state.follow);
  });
  $("#to-latest").onclick = () => { state.follow = true; scrollBottom(true); };
  document.addEventListener("click", (ev) => { if (!ev.target.closest("#history-pop")) $("#history-pop").classList.add("hidden"); });
}

function guessEmployee(v) {
  const t = String(v).trim().toUpperCase();
  const m = t.match(/^DEMO-([A-Z]{2})-/);
  if (m && DEMO_EMP[m[1]]) return DEMO_EMP[m[1]];
  const rb = emp("reimburse");
  if (rb.id_pattern && new RegExp(`^(?:${rb.id_pattern})$`).test(t)) return "reimburse";
  return state.current || "procurement";
}

function renderList() {
  const f = $("#search").value.trim();
  const items = state.employees.filter((e) => !f || (e.name + e.persona + e.desc).includes(f));
  $("#employee-list").innerHTML = `<div class="sec">数字员工</div>` +
    items.map((e) => {
      const busy = state.running && e.id === state.runningEmp;
      const last = state.last[e.id];
      const l2 = busy ? `审查中 · 单据 ${esc(state.running)}` : last ? esc(last)
        : e.status === "online" ? `${esc(e.dept)} · 已接入${LIVE_SRC[e.live_source] || "客户系统"}`
        : e.status === "beta" ? `${esc(e.dept)} · ${LIVE_SRC[e.live_source] || "客户系统"}待打通，可审本地事项` : `${esc(e.dept)} · 建设中`;
      const tag = e.status === "online" ? ["", "已上线"] : e.status === "beta" ? ["beta", "测试中"] : ["gray", "建设中"];
      return `<div class="conv ${state.current === e.id ? "active" : ""}" data-emp="${e.id}" role="button" tabindex="0"
        aria-label="${esc(e.persona)} · ${TITLE[e.id]}">
        ${avatar(e.id, "", usable(e))}
        <div class="info">
          <div class="l1"><span class="name">${esc(e.persona)} · ${TITLE[e.id]}</span>
            <span class="tag ${tag[0]}">${tag[1]}</span></div>
          <div class="l2 ${busy ? "busy" : ""}">${l2}</div>
        </div>
        <div class="time">${fmtTime(e.last_run)}</div>
      </div>`;
    }).join("");
  $("#employee-list").onclick = (ev) => {
    const it = ev.target.closest(".conv");
    if (!it) return;
    openChat(it.dataset.emp);
  };
  $("#employee-list").onkeydown = (ev) => {
    if ((ev.key === "Enter" || ev.key === " ") && ev.target.classList.contains("conv")) {
      ev.preventDefault();
      ev.target.click();
    }
  };
}

function renderCards() {
  $("#cards").innerHTML = state.employees.map((e) => `
    <div class="pcard ${COLOR[e.id]} ${usable(e) ? "" : "off"}" data-emp="${e.id}">
      <div class="top"><span class="badge ${e.status === "online" ? "on" : e.status === "beta" ? "beta" : ""}"
        title="${e.status === "online" ? `已接入${LIVE_SRC[e.live_source] || "客户系统"}，参与采集与自动审查` : e.status === "beta" ? `${LIVE_SRC[e.live_source] || "客户系统"}取数待打通，当前审查本地事项` : ""}">${STATUS_TEXT[e.status] ? "● " + STATUS_TEXT[e.status] : "建设中"}</span></div>
      ${avatar(e.id, "", usable(e))}
      <div class="bd">
        <div class="nm"><b>${esc(e.persona)}</b><span>${esc(e.dept)}</span></div>
        <div class="role">${esc(e.name)}</div>
        <div class="ds">${esc(e.intro)}</div>
        <div class="go">${usable(e) ? "开始对话" : "敬请期待"}${svg("arrow")}</div>
      </div>
    </div>`).join("");
  $("#cards").onclick = (ev) => { const c = ev.target.closest(".pcard"); if (c) openChat(c.dataset.emp); };
}

function bindComposer(inputSel, btnSel, onSend) {
  const input = $(inputSel), btn = $(btnSel);
  const send = () => {
    const v = input.value.trim();
    if (!v) return;
    if (state.running) return toast("正在审查中，请稍候");
    input.value = "";
    input.style.height = "";
    onSend(v);
  };
  btn.onclick = send;
  input.addEventListener("keydown", (ev) => { if (ev.key === "Enter" && !ev.shiftKey && !ev.isComposing) { ev.preventDefault(); send(); } });
  input.addEventListener("input", () => { input.style.height = "auto"; input.style.height = Math.min(input.scrollHeight, 160) + "px"; });
}

function showWelcome() {
  state.current = null;
  renderList();
  showView("#view-welcome");
}

/* ============ 对话 ============ */
function openChat(id, quiet = false) {
  const e = emp(id);
  if (!e.id) return;
  state.current = id;
  state.history = [];
  state.lastTask = null;
  renderList();
  showView("#view-chat");
  renderHead();
  refreshLlm();
  $("#thread").innerHTML = "";
  const online = usable(e);
  $("#thread").insertAdjacentHTML("beforeend", `
    <div class="hero">
      <div class="glow">${avatar(id, "xl", online)}</div>
      <h2>${esc(e.persona)}<span class="rt">${esc(e.name)}</span></h2>
      <div class="dept">${esc(e.dept)} · ${STATUS_TEXT[e.status] || "建设中"}</div>
      <div class="intro">${esc(e.intro)}</div>
      <div class="skills">${(e.skills || []).map((s) => `<span>${esc(s)}</span>`).join("")}</div>
      ${e.live_note ? `<div class="src-note">${esc(e.live_note)}</div>` : ""}
      ${online ? "" : `<div class="suggest"><div class="sq" data-q="go:procurement"><span class="ic">${svg("arrow")}</span>先去体验采购审批数字员工 · 林悦${svg("arrow")}</div></div>`}
    </div>`);
  $("#thread").querySelectorAll(".sq").forEach((el) => (el.onclick = (ev) => {
    ev.stopPropagation();
    if (el.dataset.q.startsWith("go:")) openChat(el.dataset.q.slice(3));
  }));
  $("#chat-input").placeholder = online ? `点选上方任务，或输入单号 / “审查全部待审单据”指挥${e.persona}；Enter 发送` : `${e.persona}正在建设中`;
  if (online && !quiet) showTasks();
  $("#chat-input").focus();
}

function renderHead() {
  const e = emp(state.current);
  const busy = state.running && state.current === state.runningEmp;
  $("#chat-who").innerHTML = `${avatar(e.id, "md", usable(e))}
    <div><div class="n1"><b>${esc(e.persona)}</b><span class="rt">${esc(e.name)}</span></div>
    <div class="s2 ${busy ? "busy" : ""}">${busy ? `正在审查单据 ${esc(state.running)}…` : usable(e) ? `${STATUS_TEXT[e.status]} · ${esc(e.dept)}` : "建设中"}</div></div>`;
}

function handleInput(v) {
  const t = v.trim();
  const e = emp(cur());
  if (!usable(e)) return botMsg(`<p>${esc(e.persona)}正在建设中，可以先去体验其他数字员工。</p>`);
  if (/^(样例单据|看看样例|最近的单据)$/.test(t)) return showSamples(false);
  if (/^(规则清单|有哪些规则)$/.test(t)) { userMsg(t); return showRules(true); }
  if (/^历史报告$/.test(t)) return toggleHistory();
  if (/^(看看)?(待审单据|待审|待办|任务台)$/.test(t)) return showQueue();
  if (/^(帮助|菜单|任务|任务清单|你能做什么|能做什么|你会什么|开始)[？?！!。]*$/.test(t)) { userMsg(t); return showTasks(); }
  if (/^(把)?(全部|所有|批量)(待审)?(单据)?(都)?(审查|审核|审一下|过一遍)|^(审查|审核)(全部|所有)(待审)?(单据)?/.test(t)) { userMsg(t); return runBatch(); }
  if (/^(立即|马上|现在)?(采集|同步)(一下|最新)?(待审)?(单据)?$/.test(t)) { userMsg(t); return collectNow(); }
  if (e.id === "procurement") {
    if (/^\d{5,}$/.test(t) || /^(审查|帮我审查|审核)\s*(单据|单号)?\s*\d{5,}$/.test(t)) return startRun(t);
    return state.lastTask ? askLLM(t) : showGuide(t);
  }
  const id = t.replace(/^(审查|帮我审查|审核|初审)\s*(单据|单号|样例)?\s*/, "");
  if (DEMO_RE.test(id)) return startRun(id.toUpperCase(), "local");
  if (e.id_pattern && new RegExp(`^(?:${e.id_pattern})$`).test(id)) return startRun(id, e.live_source);
  // 受限对话：只有当前有报告时才追问，其余引导回可执行的任务（不调模型）
  state.lastTask ? askLLM(t) : showGuide(t);
}

const GUIDE_HINT = {
  procurement: "发送采购结果审批流程的单号（纯数字，如 1674771）",
  contract: "发送主合同审批流程的单号（纯数字，如 1609472）",
  meeting: "发送内部请示的内请号（如 通设请字[2026]76号）",
  reimburse: "发送通财云单据编码（如 1000001431-CLBX2609-000579）",
};

function showGuide(text) {
  if (text) userMsg(text);
  showTasks(`这不在我的工作范围内，我不闲聊。我按固定流程自动完成${TITLE[cur()]}，可以直接点选下面的任务：`);
}

/* ============ 开场任务清单：可执行流程 + 待审单据，点击即执行 ============ */
const TASK_ICON = { batch: "spark", run: "search", queue: "inbox", collect: "redo", samples: "doc", rules: "list", history: "clock", flow: "flow",
  "scene:list": "inbox", "scene:collusion": "alert", "scene:credit": "alert", "scene:clauses": "doc", "scene:invoice": "alert",
  "scene:authority": "search", "scene:regs": "db", "scene:standards": "list" };

async function showTasks(lead) {
  const e = emp(cur());
  // 旧的任务清单数字已过时：置灰并禁用，只保留最新一份可点
  document.querySelectorAll("#messages .taskmenu:not(.expired)").forEach((m) => {
    m.classList.add("expired");
    m.querySelectorAll("button").forEach((b) => (b.disabled = true));
    m.onclick = null;
  });
  const body = botMsg(`<div class="typing"><i></i><i></i><i></i></div>`);
  body.classList.add("taskmenu");
  let t;
  try {
    t = await (await fetch(`/api/${e.id}/tasks`)).json();
  } catch (err) {
    body.innerHTML = errorCard({ title: "任务清单读取失败", hint: "工作台服务可能刚重启，请刷新页面。", detail: String(err) });
    return;
  }
  const s = t.stats || {};
  const head = lead || `我是${e.persona}，${e.name}。我按固定流程自动完成${TITLE[e.id]}，不闲聊；点选下面的任务即可开始，也可以直接发送单号指挥我。`;
  const todo = (t.todo || []).map((r) => `
    <div class="trow" data-rid="${esc(r.request_id)}" data-src="${esc(r.source)}">
      <b>${esc(r.request_id)}</b><span class="tt3" title="${esc(r.title || "")}">${esc(r.title || "")}</span>
      ${r.material_changed ? '<span class="st2 hitd">材料已变化</span>' : r.latest && r.latest.status === "failed" ? '<span class="st2 hit">上次失败</span>' : '<span class="st2 unread">未审查</span>'}
      <button class="btn sm primary">审查</button></div>`).join("");
  const acts = t.actions || [];
  const card = (a) => `
    <button type="button" class="task ${a.group} ${a.id === "batch" && a.enabled ? "hero" : ""}" data-t="${a.id}"
      ${a.enabled ? "" : "disabled"} aria-label="${esc(a.title)}：${esc(a.desc)}">
      <span class="ti">${svg(TASK_ICON[a.id] || "arrow")}</span>
      <span class="tb"><span class="tt">${esc(a.title)}${a.badge ? `<em>${a.badge}</em>` : ""}</span><span class="td">${esc(a.desc)}</span></span>
      ${svg("arrow", "go")}</button>`;
  const chip = (label, n, cls = "") => (n ? `<span class="tchip ${cls}">${label}<b>${n}</b></span>` : "");
  const pill = (a) => `<button type="button" class="tpill" data-t="${a.id}" title="${esc(a.desc)}" ${a.enabled ? "" : "disabled"}>
    ${svg(TASK_ICON[a.id] || "arrow")}${esc(a.title)}${a.badge ? `<em>${a.badge}</em>` : ""}</button>`;
  const scenesHtml = acts.filter((a) => a.group === "scene");
  body.innerHTML = `<div class="md">${md(head)}</div>
    ${t.error ? `<div class="err">${esc(t.error)}</div>` : ""}
    ${scenesHtml.length ? `<div class="tgroup"><div class="tg-h">${esc(e.persona)}的${TITLE[e.id]}专属工作 <span>本场景特有的流程与分析</span></div>
      <div class="tasks scenes ${COLOR[e.id]}">${scenesHtml.map(card).join("")}</div></div>` : ""}
    <div class="tgroup"><div class="tg-h">通用操作 <span>点击即执行，全程只读客户系统</span></div>
      <div class="tasks">${acts.filter((a) => a.group === "do").map(card).join("")}</div></div>
    ${todo ? `<div class="tlist"><div class="tl-h">待审单据 <span>点击即开始审查</span></div>${todo}</div>` : ""}
    <div class="tgroup"><div class="tg-h">查看与追溯</div>
      <div class="tpills">${acts.filter((a) => a.group === "view").map(pill).join("")}</div></div>
    <div class="tstat"><span class="tl">资料中心</span>${chip("待审", s.todo ?? 0, "blue") || '<span class="tchip">待审<b>0</b></span>'}${chip("已就绪", s.ready)}${chip("已审查", s.reviewed)}${chip("审查中", s.running, "blue")}${chip("同步中", s.syncing, "blue")}${chip("待办只读", s.pending_locked, "gray")}${chip("当前账号不可见", s.stale, "gray")}
      <span class="tauto ${t.auto_review ? "on" : ""}">${autoText(t)}</span></div>`;
  body.onclick = (ev) => {
    const row = ev.target.closest(".trow");
    if (row) return startRun(row.dataset.rid, row.dataset.src);
    const a = ev.target.closest(".task, .tpill");
    if (!a || a.disabled) return;
    if (a.dataset.t.startsWith("scene:")) {
      const sc = acts.find((x) => x.id === a.dataset.t) || {};
      return ({ list: () => showQueue({ list: sc.list, title: sc.title }), insight: () => showInsight(sc.id.slice(6), sc.title),
                authority: () => showAuthority(), regs: () => showRegs(), standards: () => showStandards() })[sc.kind]();
    }
    ({ batch: () => runBatch(), run: () => { $("#chat-input").focus(); toast(GUIDE_HINT[e.id] || "请输入单号"); },
       queue: () => showQueue(), collect: () => collectNow(), samples: () => showSamples(false),
       rules: () => showRules(), history: toggleHistory, flow: () => showCenter(e.id) })[a.dataset.t]();
  };
  scrollBottom();
}

const SRC_NAME = { contract: "合同系统", docflow: "公文系统", fincloud: "通财云", local: "本地事项" };

function autoText(q) {
  return q.auto_review ? "资料就绪后自动审查" : q.auto_paused ? "自动审查已暂停，需手动发起" : "需手动发起审查";
}

async function collectNow() {
  const e = emp(cur());
  const st = await fetch("/api/collect/status").then((r) => (r.ok ? r.json() : null)).catch(() => null);
  if (!st) return botMsg(`<div class="err">资料中心无法访问，请先启动：python -m core.resource.api</div>`);
  const srcs = (e.sources || []).filter((s) => (st.sources[s] || {}).enabled);
  if (!srcs.length) return botMsg(`<p>${esc(e.persona)}的来源系统当前未开启采集（见 config/collect.yaml）。</p>`);
  const names = srcs.map((s) => SRC_NAME[s] || s).join("、");
  const body = botMsg(`<p>正在采集${esc(names)}：读取列表 → 读表单、下载附件、签名、解析入库…</p>`);
  const since = Date.now() / 1000 - 1;
  await Promise.all(srcs.map((s) => fetch(`/api/collect/run?source=${encodeURIComponent(s)}`, { method: "POST" }).catch(() => null)));
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const t0 = Date.now();
  let rounds = [];
  while (Date.now() - t0 < 120000) {   // 1) 等本轮列表读完（资料中心后台执行）
    await sleep(1500);
    const s2 = await fetch("/api/collect/status").then((r) => (r.ok ? r.json() : null)).catch(() => null);
    rounds = srcs.map((s) => ((s2 && s2.rounds) || []).find((x) => x.source === s && x.started_at >= since && x.finished_at));
    if (rounds.every(Boolean)) break;
  }
  const done = rounds.filter(Boolean);
  const listed = done.reduce((n, r) => n + (r.listed || 0), 0), queued = done.reduce((n, r) => n + (r.queued || 0), 0);
  const errs = done.filter((r) => r.error).map((r) => `${SRC_NAME[r.source] || r.source}：${r.error}`);
  const line = `列表中 <b>${listed}</b> 笔，本轮同步 <b>${queued}</b> 笔`;
  const errHtml = errs.length ? `<div class="err">${errs.map(esc).join("<br>")}</div>` : "";
  body.innerHTML = `<p>正在采集${esc(names)}：${line}，读表单、下载附件、解析入库中…</p>${errHtml}`;
  while (Date.now() - t0 < 300000) {   // 2) 等同步队列处理完
    const t = await fetch(`/api/${e.id}/tasks`).then((r) => r.json()).catch(() => null);
    if (t && !(t.stats || {}).syncing) break;
    await sleep(2000);
  }
  body.innerHTML = `<p>采集完成（${esc(names)}）：${line}${done.length < srcs.length ? "（部分来源仍在后台进行）" : ""}。</p>${errHtml}`;
  showTasks("资料已更新。下面是最新的待审情况，点选即可开始：");
}

async function runBatch(ids) {
  const e = emp(cur());
  const r = await fetch(`/api/${e.id}/batch`, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ request_ids: ids || null }) });
  const d = await r.json();
  if (!r.ok) return showTasks(`${d.detail || "没有可审查的单据"}。可以从下面的任务继续：`);
  const body = botMsg(`<p>好的，开始批量审查 <b>${d.total}</b> 笔单据，每笔都按完整流程执行并入执行档案：</p><div class="batch"></div>`);
  const render = (b) => {
    $(".batch", body).innerHTML = `<div class="bh">已完成 ${b.done}/${b.total}${b.finished ? " · 全部完成" : ""}</div>` + b.items.map((i) => {
      const v = i.verdict || {}, s = i.summary || {};
      const res = i.status === "done" ? `<span class="st2 ${{ bad: "hit", warn: "hitd", good: "pass" }[v.level] || (s["一定不通过"] > 0 ? "hit" : "pass")}">${esc(v.title || `不通过 ${s["一定不通过"] ?? 0} · 拿不准 ${s["拿不准"] ?? 0}`)}</span>`
        : i.status === "failed" ? `<span class="st2 hit" title="${esc(i.error || "")}">审查失败</span>` : `<span class="st2 unread">审查中…</span>`;
      return `<div class="brow" data-task="${i.task_id}" data-rid="${esc(i.request_id)}"><b>${esc(i.request_id)}</b><span class="tt3">${esc(i.title || "")}</span>${res}
        ${i.status === "done" ? '<button class="btn sm" data-a="report">查看报告</button><button class="btn sm" data-a="archive">档案</button>' : ""}</div>`;
    }).join("");
  };
  render(d);
  body.onclick = (ev) => {
    const b = ev.target.closest("button[data-a]");
    if (!b) return;
    const row = b.closest(".brow");
    if (b.dataset.a === "report") openReport(row.dataset.task, row.dataset.rid);
    else showArchive(row.dataset.task);
  };
  const iv = setInterval(async () => {
    const x = await fetch(`/api/batches/${d.batch_id}`).then((y) => y.json()).catch(() => null);
    if (!x) return;
    render(x);
    if (x.finished) { clearInterval(iv); refreshEmployees(); }
  }, 2500);
  scrollBottom();
}

/* ============ 大模型对话 ============ */
async function refreshLlm() {
  const chip = $("#llm-chip");
  try {
    const s = await (await fetch("/api/llm/status")).json();
    const label = s.model ? `${s.model}${s.type === "ollama" ? " · 本地" : ""}` : "未配置模型";
    chip.className = `llm-chip ${s.reachable && s.model_ready ? "ok" : "bad"}`;
    chip.querySelector("span").textContent = s.reachable ? (s.model_ready ? label : `${label} · 未下载`) : `${label} · 未连接`;
    chip.title = s.reachable && s.model_ready ? `对话模型：${s.provider}（${s.base_url}）` : (s.error || "模型服务不可用，请检查 config/llm.yaml");
  } catch { chip.className = "llm-chip bad"; chip.querySelector("span").textContent = "模型状态未知"; }
}

function md(src) {
  const blocks = [];
  let s = String(src).replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) => { blocks.push(`<pre><code>${esc(code.trim())}</code></pre>`); return `\u0000${blocks.length - 1}\u0000`; });
  s = esc(s);
  const inline = (t) => t.replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank">$1</a>').replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/`([^`]+)`/g, "<code>$1</code>").replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>").replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
  const out = [];
  let list = null;
  const close = () => { if (list) { out.push(`</${list}>`); list = null; } };
  for (const raw of s.split("\n")) {
    const line = raw.trimEnd();
    let m;
    if (/^\u0000\d+\u0000$/.test(line.trim())) { close(); out.push(line.trim()); continue; }
    if ((m = line.match(/^#{1,4}\s+(.*)/))) { close(); out.push(`<h4>${inline(m[1])}</h4>`); continue; }
    if (/^(-{3,}|\*{3,})$/.test(line.trim())) { close(); out.push("<hr>"); continue; }
    if ((m = line.match(/^\s*[-*•]\s+(.*)/))) { if (list !== "ul") { close(); list = "ul"; out.push("<ul>"); } out.push(`<li>${inline(m[1])}</li>`); continue; }
    if ((m = line.match(/^\s*(\d+)[.)、]\s+(.*)/))) { if (list !== "ol") { close(); list = "ol"; out.push(`<ol start="${m[1]}">`); } out.push(`<li>${inline(m[2])}</li>`); continue; }
    if ((m = line.match(/^&gt;\s?(.*)/))) { close(); out.push(`<blockquote>${inline(m[1])}</blockquote>`); continue; }
    if (!line.trim()) { close(); continue; }
    close();
    out.push(`<p>${inline(line)}</p>`);
  }
  close();
  return out.join("").replace(/\u0000(\d+)\u0000/g, (_, i) => blocks[+i]);
}

async function askLLM(text, { regenerate = false } = {}) {
  if (!state.current) openChat(cur(), true);
  if (state.chatting) return toast("我还在回答上一个问题");
  if (!regenerate) { userMsg(text); state.history.push({ role: "user", content: text }); }
  state.chatting = true;
  const body = botMsg(`<div class="reason hidden"><div class="rh"><span class="spin"></span><span class="rt2">深度思考中…</span>${svg("chev", "chev")}</div><div class="rb"></div></div>
    <div class="md"><div class="typing"><i></i><i></i><i></i></div></div><div class="llm-foot"></div>`);
  const reason = $(".reason", body), rb = $(".rb", reason), mdEl = $(".md", body);
  $(".rh", reason).onclick = () => reason.classList.toggle("closed");
  let answer = "", thinking = "", t0 = Date.now(), tThinkEnd = null, model = "", guided = false;
  const finishThink = () => {
    if (!thinking || tThinkEnd) return;
    tThinkEnd = Date.now();
    $(".rh .spin", reason)?.replaceWith(Object.assign(document.createElement("span"), { innerHTML: svg("bulb", "bulb") }));
    $(".rt2", reason).textContent = `已深度思考（用时 ${fmtMs(tThinkEnd - t0)}）`;
    reason.classList.add("closed");
  };
  try {
    const resp = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ employee: cur(), message: text, history: state.history.slice(0, -1), task_id: state.lastTask }) });
    const reader = resp.body.getReader(), dec = new TextDecoder();
    let buf = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
        const line = chunk.split("\n").find((l) => l.startsWith("data:"));
        if (!line) continue;
        const ev = JSON.parse(line.slice(5));
        if (ev.type === "start") model = ev.model;
        else if (ev.type === "guide") { answer = ev.text; mdEl.innerHTML = md(ev.text); model = "受限对话"; guided = true; }
        else if (ev.type === "think") {
          thinking += ev.text;
          reason.classList.remove("hidden");
          rb.textContent = thinking.trimStart();
          rb.scrollTop = rb.scrollHeight;
        } else if (ev.type === "text") {
          finishThink();
          answer += ev.text;
          mdEl.innerHTML = md(answer.trimStart()) ;
          mdEl.lastElementChild?.classList.add("cursor");
        } else if (ev.type === "error") throw Object.assign(new Error(ev.error), { info: ev });
        else if (ev.type === "done") {
          finishThink();
          mdEl.innerHTML = md(answer.trim() || "（模型没有返回内容）");
          $(".llm-foot", body).textContent = `${model} · ${fmtMs(ev.ms)}`;
        }
        scrollBottom();
      }
    }
    state.history.push({ role: "assistant", content: answer.trim() });
    body.insertAdjacentHTML("beforeend", `<div class="acts"><button class="act" data-a="copy">${svg("copy")}复制</button>
      <button class="act" data-a="redo">${svg("redo")}重新生成</button><button class="act" data-a="like">${svg("up")}有帮助</button></div>`);
    $(".acts", body).onclick = (ev) => {
      const a = ev.target.closest(".act");
      if (!a) return;
      if (a.dataset.a === "copy") navigator.clipboard.writeText(answer.trim()).then(() => toast("已复制"));
      else if (a.dataset.a === "redo") { state.history.pop(); askLLM(text, { regenerate: true }); }
      else { a.style.color = "var(--blue)"; toast("感谢反馈"); }
    };
  } catch (e) {
    reason.classList.add("hidden");
    const info = e.info || { title: "对话服务暂时不可用", hint: "请确认工作台服务正在运行，然后点「重新生成」。", detail: String(e.message || e) };
    mdEl.innerHTML = errorCard({ title: info.error || info.title, hint: info.hint, detail: info.detail }, { retry: "重新生成" });
    mdEl.querySelector("[data-a=retry]").onclick = () => { body.closest(".m").remove(); askLLM(text, { regenerate: true }); };
    refreshLlm();
  } finally {
    state.chatting = false;
    scrollBottom();
  }
  if (guided) showTasks("可以直接点选下面的任务继续：");
}

async function showSamples(force, skipUser) {
  if (cur() !== "procurement") return showLocalSamples(skipUser);
  if (!skipUser) userMsg("看看台账里最近的采购结果审批单据");
  const body = botMsg(`<div class="typing"><i></i><i></i><i></i></div>`);
  try {
    const data = await (await fetch(`/api/procurement/samples${force ? "?refresh=1" : ""}`)).json();
    const rows = data.rows || [];
    body.innerHTML = `<p>我从「采购结果审批台账」${data.total ? `（共 ${data.total} 条已归档单据）` : ""}挑了近期有代表性的 ${rows.length} 笔，点击任意一笔即可开始审查：</p>
      ${data.error ? `<p class="muted">台账读取失败，先给你内置样例：${esc(data.error)}</p>` : ""}
      <div class="sugs">${rows.map((r) => `
        <div class="sug" data-rid="${esc(r.request_id)}">
          <div class="s1">${methodTag(r.method)}<span>单据 ${esc(r.request_id)}</span><span class="amt">${r.amount ? Number(r.amount).toFixed(2) + " 万元" : ""}</span></div>
          <div class="s2">${esc(r.content)}</div>
          <div class="s3">${esc(r.date)} · 候选 ${esc(r.supplier || "—")}</div>
        </div>`).join("")}</div>`;
    body.querySelectorAll(".sug").forEach((el) => (el.onclick = () => startRun(el.dataset.rid)));
  } catch (e) {
    body.innerHTML = `<div class="err">样例读取失败：${esc(e)}</div>`;
  }
  scrollBottom();
}

async function showLocalSamples(skipUser) {
  const e = emp(cur());
  if (!skipUser) userMsg("看看有哪些本地样例单据");
  const body = botMsg(`<div class="typing"><i></i><i></i><i></i></div>`);
  try {
    const data = await (await fetch(`/api/${e.id}/samples`)).json();
    const rows = data.rows || [];
    body.innerHTML = `<p>${rows.length ? `本地共有 <b>${rows.length}</b> 笔样例事项（合成数据），点击任意一笔即可开始审查：` : esc(data.error || "暂无样例")}</p>
      ${data.live_note ? `<p class="muted">${esc(data.live_note)}</p>` : ""}
      <div class="sugs">${rows.map((r) => `
        <div class="sug" data-rid="${esc(r.request_id)}">
          <div class="s1">${(r.tags || []).slice(0, 2).map((t) => `<span class="mt ${/问题/.test(t) ? "tender" : ""}">${esc(t)}</span>`).join("")}<span>${esc(r.request_id)}</span></div>
          <div class="s2">${esc(r.title)}</div>
          <div class="s3" title="${esc(r.summary)}">${esc(r.summary)}</div>
        </div>`).join("")}</div>`;
    body.querySelectorAll(".sug").forEach((el) => (el.onclick = () => startRun(el.dataset.rid, "local")));
  } catch (err) {
    body.innerHTML = `<div class="err">样例读取失败：${esc(err)}</div>`;
  }
  scrollBottom();
}

async function showReviewRules(skipUser) {
  const e = emp(cur());
  if (skipUser !== true) userMsg(e.id === "meeting" ? "三会审查有哪 5 个审查节点？" : `${TITLE[e.id]}有哪 ${e.rules_total} 条规则？`);
  const body = botMsg(`<div class="typing"><i></i><i></i><i></i></div>`);
  const data = await (await fetch(`/api/${e.id}/rules`)).json();
  const intro = {
    contract: "合同审核共 <b>30 条规则</b>，按实现方式分三类：<b>确定性</b>（金额、日期、大小写、名称等直接计算）、<b>语义</b>（范围、人员、付款、违约责任等由模型比对，且必须引用双方原文）、<b>外部数据</b>（天眼查、台账、名单）。数据源不可用时如实标为待补充或人工复核，不当作通过。",
    meeting: "三会审查分 <b>5 个审查节点</b>，每个节点输出一条综合意见，多个问题按（1）（2）（3）列示。审批/上会依据会在四份制度中逐项核验条款定位、适用事项、金额档位与最终审批主体（权责手册红色标识）。",
    reimburse: "报销初审共 <b>43 条规则</b>，单据里出现哪类费用就执行哪一类，差旅单不跑招待费规则；一张单同时含差旅与招待时两类都执行。阈值、标准与词表在 config/reimburse.yaml 中由财务维护。",
  }[e.id] || "";
  const groupCol = e.layout === "groups";
  let lastGroup = null;
  const rows = data.rules.map((r) => {
    const g = groupCol && r.group !== lastGroup ? `<tr class="grp"><td colspan="4">${esc(r.group)}</td></tr>` : "";
    lastGroup = r.group;
    return `${g}<tr><td>${esc(r.rule_id)}</td><td>${esc(r.name)}</td><td>${esc(r.category || "")}</td>
      <td><span class="st2 ${r.state === "已上线" ? "pass" : r.state === "部分上线" ? "hitd" : "notrun"}">${esc(r.state)}</span></td></tr>`;
  }).join("");
  body.innerHTML = `<p>${intro}</p>
    <details class="fold" open><summary>${e.id === "meeting" ? "审查节点" : "规则清单"}（${esc(data.version)}）${svg("chev", "chev")}</summary>
    <table class="rules-table"><thead><tr><th>编号</th><th>${e.id === "meeting" ? "审查节点" : "规则"}</th><th>类别</th><th>状态</th></tr></thead><tbody>${rows}</tbody></table></details>`;
  scrollBottom();
}

async function showRules(skipUser) {
  if (cur() !== "procurement") return showReviewRules(skipUser);
  if (skipUser !== true) userMsg("采购审批有哪 18 条规则？");
  const body = botMsg(`<div class="typing"><i></i><i></i><i></i></div>`);
  const data = await (await fetch("/api/procurement/rules")).json();
  const on = data.rules.filter((r) => r.state === "已上线").length;
  body.innerHTML = `<p>采购审批共 <b>18 条规则</b>，按判定确定性分两档：<b style="color:var(--red)">一定不通过</b>（材料上能直接看出的问题）和
    <b style="color:var(--orange)">拿不准</b>（串标线索、语义判断，需要人核实）。目前已上线 ${on} 条，其余在接入大模型与天眼查后上线。</p>
    <details class="fold" open><summary>规则清单（${esc(data.version)}）${svg("chev", "chev")}</summary>
    <table class="rules-table"><thead><tr><th>编号</th><th>规则</th><th>档位</th><th>状态</th></tr></thead><tbody>
    ${data.rules.map((r) => `<tr><td>${r.rule_id}</td><td>${esc(r.name)}</td>
      <td><span class="st2 ${r.tier === "一定不通过" ? "hit" : "hitd"}">${esc(r.tier)}</span></td>
      <td><span class="st2 ${r.state === "已上线" ? "pass" : "notrun"}">${esc(r.state)}</span></td></tr>`).join("")}</tbody></table></details>`;
  scrollBottom();
}

function userMsg(text) {
  $("#thread").insertAdjacentHTML("beforeend", `<div class="m user"><div class="ubbl">${esc(text)}</div></div>`);
  state.follow = true;
  scrollBottom(true);
}
function botMsg(html, empId) {
  const e = emp(empId || cur());
  const el = document.createElement("div");
  el.className = "m bot";
  el.innerHTML = `${avatar(e.id || "procurement", "sm")}<div class="col"><div class="meta"><b>${esc(e.persona)}</b><span>${now()}</span></div><div class="body">${html}</div></div>`;
  $("#thread").appendChild(el);
  scrollBottom();
  return el.querySelector(".body");
}
function scrollBottom(force) {
  const box = $("#messages");
  if (force || state.follow) requestAnimationFrame(() => (box.scrollTop = box.scrollHeight));
  else $("#to-latest").classList.remove("hidden");
}

/* ============ 发起审查 ============ */
async function startRun(input, source) {
  if (!state.current) openChat(cur(), true);
  if (state.running) return toast("正在审查中，请稍候");
  const empId = cur();
  if (empId !== "procurement") return startReviewRun(empId, String(input).trim(), source);
  const m = String(input).match(/\d{5,}/);
  userMsg(m && String(input).trim() === m[0] ? `帮我审查单据 ${m[0]}` : String(input));
  if (!m) return botMsg(`<p>请发送采购结果审批流程的单号（纯数字），例如 <b>1674771</b>。</p>`);
  const rid = m[0];
  setRunning(rid, empId);
  try {
    const r = await fetch("/api/runs", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ employee: "procurement", request_id: rid }) });
    if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
    follow((await r.json()).task_id, rid, empId);
  } catch (e) {
    setRunning(null);
    const b = botMsg(errorCard({ title: "没能开始审查", hint: "工作台服务可能未启动或刚刚重启，请刷新页面后再试。", detail: String(e.message || e) },
      { retry: "重试" }));
    b.querySelector("[data-a=retry]").onclick = () => startRun(rid);
  }
}

async function startReviewRun(empId, rid, source) {
  const e = emp(empId);
  const src = source || e.live_source;
  userMsg(`帮我审查${src === "local" ? "本地样例" : "单据"} ${rid}`);
  setRunning(rid, empId);
  try {
    const r = await fetch("/api/runs", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ employee: empId, request_id: rid, source: src }) });
    const data = await r.json();
    if (!r.ok) throw Object.assign(new Error(data.detail || r.statusText), { bad: r.status === 400 });
    follow(data.task_id, rid, empId, src);
  } catch (err) {
    setRunning(null);
    const b = botMsg(errorCard(err.bad ? { title: "没能开始审查", hint: String(err.message) }
      : { title: "没能开始审查", hint: "工作台服务可能未启动或刚刚重启，请刷新页面后再试。", detail: String(err.message || err) },
    { retry: "重试" }));
    b.querySelector("[data-a=retry]").onclick = () => startRun(rid, src);
  }
}

function setRunning(rid, empId) {
  state.running = rid;
  state.runningEmp = rid ? empId : null;
  $("#chat-send").disabled = $("#welcome-send").disabled = !!rid;
  renderList();
  if (state.current) renderHead();
}

function follow(taskId, rid, empId = "procurement", source = null) {
  const e = emp(empId);
  const nodes = e.nodes && e.nodes.length ? e.nodes : NODES;
  const hints = e.node_hints && Object.keys(e.node_hints).length ? e.node_hints : NODE_HINT;
  const ruleNode = nodes.includes("审查") ? "审查" : "规则校验";
  const review = empId !== "procurement";
  const live = e.layout === "nodes";
  const intro = review
    ? `好的，我来审查${source === "local" ? "本地样例" : "单据"} <b>${esc(rid)}</b>。会依次读取单据与附件、抽取要素，再${live ? "按 5 个审查节点逐一核验，每个节点完成后给出一条综合意见" : "逐条核验规则"}。`
    : `好的，我来审查单据 <b>${esc(rid)}</b>。会依次读取单据、下载并解析全部附件，再逐条核验规则。`;
  const body = botMsg(`
    <p>${intro}</p>
    <div class="think">
      <div class="think-head"><span class="spin"></span><span class="tt">正在审查</span><span class="tm">0.0s</span>${svg("chev", "chev")}</div>
      <div class="prog"><i style="width:4%"></i></div>
      <div class="think-body"><div>${nodes.map((n) => `
        <div class="stp pending" data-node="${n}">
          <div class="sh"><span class="sn">${n}</span><span class="sm"></span></div>
          <div class="ss">${esc(hints[n] || "")}</div>
          ${n === "解析材料" ? '<div class="files"></div>' : ""}
          ${n === ruleNode ? '<div class="rls"></div>' : ""}
        </div>`).join("")}</div></div>
    </div>
    ${live ? '<div class="live"></div>' : ""}
    <div class="result"></div>`, empId);
  const liveCards = {};
  let archiveShots = null, archivePage = null;
  const think = $(".think", body);
  $(".think-head", think).onclick = () => think.classList.toggle("closed");
  const t0 = Date.now(), timers = {}, rows = {};
  let done = 0;
  const tick = setInterval(() => {
    $(".tm", think).textContent = fmtMs(Date.now() - t0);
    for (const [n, st] of Object.entries(timers)) {
      const el = $(`.stp[data-node="${n}"] .sm`, think);
      if (el) el.textContent = `已用时 ${fmtMs(Date.now() - st)}`;
    }
  }, 200);
  const step = (n) => $(`.stp[data-node="${n}"]`, think);
  const prog = (p) => ($(".prog i", think).style.width = `${Math.max(4, p)}%`);
  const es = new EventSource(`/api/runs/${taskId}/events`);
  const stop = () => { es.close(); clearInterval(tick); setRunning(null); };

  es.onmessage = (msg) => {
    const ev = JSON.parse(msg.data);
    if (ev.type === "node.started") {
      const el = step(ev.node);
      if (el) { el.className = "stp running"; timers[ev.node] = Date.now(); $(".tt", think).textContent = `正在${ev.node}`; }
    } else if (ev.type === "node.completed" || ev.type === "node.failed") {
      const el = step(ev.node);
      delete timers[ev.node];
      done += 1;
      prog((done / nodes.length) * 100);
      if (el) {
        el.className = `stp ${ev.type === "node.completed" ? "ok" : "failed"}`;
        $(".sm", el).textContent = fmtMs(ev.ms);
        $(".ss", el).textContent = ev.summary || ev.error || "";
      }
    } else if (ev.type === "file.started") {
      const row = document.createElement("div");
      row.className = "fl";
      row.innerHTML = `<span class="pill busy">解析中…</span><span class="fn">${esc(ev.filename)}</span>`;
      $(".files", step("解析材料")).appendChild(row);
      (rows[ev.sig + ev.filename] ||= []).push(row);  // 同名同内容的附件可能出现多次
    } else if (ev.type === "file.parsed") {
      const row = (rows[ev.sig + ev.filename] || []).shift();
      if (row) {
        const pill = ev.cache === "hit" ? `<span class="pill cache">复用解析结果</span>`
          : ev.status !== "ok" && !ev.children ? `<span class="pill fail">未能识别</span>`
          : ev.ocr_pages ? `<span class="pill ocr">OCR ${ev.ocr_pages} 页 · ${fmtMs(ev.ms)}</span>`
          : ev.children ? `<span class="pill text">解压 ${ev.children} 个文件</span>`
          : `<span class="pill text">文字提取 · ${fmtMs(ev.ms)}</span>`;
        row.innerHTML = `${pill}<span class="fn">${esc(ev.filename)}</span>`;
      }
    } else if (ev.type === "rule.completed") {
      const cls = review ? (CODE_RL[ev.code] || "")
        : ev.status === "命中" ? (ev.tier === "一定不通过" ? "hc" : "hd") : ev.status === "未命中" ? "ps" : "";
      $(".rls", step(ruleNode)).insertAdjacentHTML("beforeend",
        `<span class="rl ${cls}" title="${esc(ev.name)}：${esc(ev.message)}">${ev.rule_id} ${esc(ev.status)}</span>`);
      if (live) {
        liveCards[ev.rule_id] = ev;
        $(".live", body).innerHTML = Object.keys(liveCards).sort().map((k) => opinionHtml(null, liveCards[k])).join("");
      }
    } else if (ev.type === "run.completed") {
      prog(100);
      $(".spin", think).className = "okc";
      $(".tt", think).textContent = "已完成审查";
      $(".tm", think).textContent = `用时 ${fmtMs(ev.ms ?? Date.now() - t0)}`;
      setTimeout(() => think.classList.add("closed"), 400);
      if (review) {
        if (live) $(".live", body).innerHTML = (ev.report.rules || []).map((r) => opinionHtml(ev.report, r)).join("");
        renderReviewReport($(".result", body), ev.report, rid, source, { compact: live });
        const v = ev.report.verdict || {};
        state.last[empId] = `${rid} · ${v.title || "已完成"}`;
        state.history.push({ role: "assistant", content: `已完成 ${rid} 的审查：${v.title || ""}。${v.subtitle || ""}` });
      } else {
        renderReport($(".result", body), ev.report, rid);
        const s = ev.report.summary || {};
        state.last.procurement = `单据 ${rid} · 不通过 ${s["一定不通过"] ?? 0} · 拿不准 ${s["拿不准"] ?? 0}`;
        state.history.push({ role: "assistant", content: `已完成单据 ${rid} 的审查：一定不通过 ${s["一定不通过"] ?? 0} 项、拿不准 ${s["拿不准"] ?? 0} 项、未能识别 ${s["未能识别"] ?? 0} 项。` });
      }
      state.lastTask = taskId;
      if (archiveShots || archivePage) $(".result", body).insertAdjacentHTML("beforeend",
        `<div class="arc-note">${svg("doc")}已入执行档案${archivePage ? (archivePage.ok ? "，已只读打开平台页面并截图" : `，平台页面未截图（${esc(archivePage.skip || archivePage.error || "")}）`) : ""}${archiveShots ? `，生成证据截图 ${archiveShots.count} 张（其中 ${archiveShots.located} 张定位到原文）` : ""}。</div>`);
      stop();
      refreshEmployees();
    } else if (ev.type === "node.note" || ev.type === "sync.notice" || ev.type === "sync.ready") {
      const running = think.querySelector(".stp.running");
      const cls = ev.type === "sync.notice" ? "note sync" : ev.type === "sync.ready" ? "note ready" : "note";
      if (running) running.insertAdjacentHTML("beforeend", `<div class="${cls}">${esc(ev.text)}</div>`);
      if (ev.type === "sync.notice") think.classList.remove("closed");
    } else if (ev.type === "file.ocr") {
      const row = (rows[ev.sig + ev.filename] || [])[0];
      if (row) row.querySelector(".pill").textContent = `OCR ${ev.done}/${ev.total} 页`;
    } else if (ev.type === "archive.shots") {
      archiveShots = ev;
    } else if (ev.type === "archive.page") {
      archivePage = ev;
    } else if (ev.type === "run.failed") {
      $(".spin", think).className = "bad";
      $(".tt", think).textContent = `审查未完成：${ev.error || "出现异常"}`;
      $(".tm", think).textContent = fmtMs(ev.ms ?? Date.now() - t0);
      const res = $(".result", body);
      res.innerHTML = errorCard({ title: ev.error, hint: ev.hint, detail: ev.detail, code: ev.code }, { retry: "重新审查" });
      res.querySelector("[data-a=retry]").onclick = () => startRun(rid, source);
      stop();
    }
    scrollBottom();
  };
  es.addEventListener("end", stop);
  es.onerror = () => { if (es.readyState === EventSource.CLOSED) stop(); };
}

async function refreshEmployees() {
  state.employees = await (await fetch("/api/employees")).json();
  renderList();
}

/* ============ 报告 ============ */
function fileLink(rep, name) {
  if (!name) return "";
  const m = (rep.materials || []).find((x) => x.filename === name || x.filename.endsWith("/" + name) || name.endsWith(x.filename));
  const label = esc(name.split("/").pop());
  if (!m || !m.sig) return label;
  return `<a href="/api/files/${m.sig}?name=${encodeURIComponent(name.split("/").pop())}" target="_blank">${label}</a>`;
}
function evidenceHtml(rep, e) {
  if (!e || typeof e !== "object") return "";
  if (e.sources) {
    return `<div class="ev"><span>${esc(e.kind)}「${esc(e.value)}」：${e.sources.map((s) =>
      `${esc(s.supplier)}（${fileLink(rep, s.file)}${s.page ? ` 第${s.page}页` : ""}）`).join("；")}</span></div>`;
  }
  const parts = [];
  if (e.item) parts.push(`<b style="color:var(--text-2);font-weight:500">${esc(e.item)}</b>`);
  if (e.supplier) parts.push(esc(e.supplier));
  if (e.file) parts.push(fileLink(rep, e.file) + (e.page ? ` 第${e.page}页` : ""));
  if ("author" in e) parts.push(`作者 ${esc(e.author || "—")}，最后修改人 ${esc((e.last_modified_by || "—").trim())}，创建于 ${esc((e.created || "").slice(0, 16).replace("T", " "))}`);
  else if (e.value !== undefined && e.value !== true) parts.push(`值 ${esc(e.value)}`);
  if (e.snippet) parts.push(`<span class="snip">${esc(String(e.snippet).slice(0, 80))}</span>`);
  return parts.length ? `<div class="ev"><span>${parts.join(" · ")}</span></div>` : "";
}
function findingHtml(rep, r, cls) {
  const evs = (r.evidence || []).slice(0, 6).map((e) => evidenceHtml(rep, e)).join("");
  return `<div class="fd ${cls}"><div class="t"><span class="rid">${r.rule_id}</span>${esc(r.name)}</div>
    <div class="x">${esc(r.message)}</div>${suggestHtml(r)}${evs ? `<div class="evs">${evs}</div>` : ""}</div>`;
}
function suggestHtml(r) {
  return r.suggest ? `<div class="sug"><b>核实建议</b>${esc(r.suggest)}</div>` : "";
}
function outdatedPill(rep) {
  const cur = emp(rep.employee || "procurement").effective_version;
  return cur && rep.rules_version && rep.rules_version !== cur
    ? `<span class="st2 old" title="当前生效版本 ${esc(cur)}；可在「流程与规则」页按新版规则批量重审">按旧版规则生成</span>` : "";
}
function renderReport(el, rep, rid) {
  const s = rep.summary || {}, h = rep.header || {};
  const v = s["一定不通过"] > 0 ? ["bad", "x", "存在一定不通过项", "材料上可直接看出问题，建议退回或补正"]
    : s["拿不准"] > 0 ? ["warn", "alert", "存在疑点，请核实", "以下线索需要审核人进一步核实后定性"]
    : ["good", "check", "未发现异常", "已执行的规则均未命中，仍请结合原件审核"];
  const certain = (rep.findings || []).filter((r) => r.tier === "一定不通过");
  const doubt = (rep.findings || []).filter((r) => r.tier === "拿不准");
  const unread = (rep.rules || []).filter((r) => r.status === "未能识别");
  const stCls = (r) => r.status === "命中" ? (r.tier === "一定不通过" ? "hit" : "hitd") : r.status === "未命中" ? "pass" : r.status === "未能识别" ? "unread" : "notrun";
  const l1 = (rep.cache || {}).L1;
  const sec = (title, n, items, cls) => `<h4>${title}<span class="n">${n}</span></h4>${items.map((r) => findingHtml(rep, r, cls)).join("") || '<div class="empty">无</div>'}`;
  el.innerHTML = `
    <div class="vcard ${v[0]}">
      <div class="vi">${svg(v[1])}</div>
      <div><div class="vt">${v[2]}</div><div class="vs">${v[3]}</div></div>
      <div class="nums">
        <div class="num c"><b>${s["一定不通过"] ?? 0}</b><span>一定不通过</span></div>
        <div class="num d"><b>${s["拿不准"] ?? 0}</b><span>拿不准</span></div>
        <div class="num p"><b>${s["未命中"] ?? 0}</b><span>未命中</span></div>
        <div class="num"><b>${(s["未能识别"] ?? 0) + (s["未执行"] ?? 0)}</b><span>待补充</span></div>
      </div>
    </div>
    <div class="facts">
      <div class="wide"><span>采购内容</span><b>${esc(h.采购内容)}</b></div>
      <div><span>采购方式</span><b>${esc(h.采购方式)}</b></div>
      <div><span>预算 / 采购价</span><b>${esc(h.预算)} / ${esc(h.采购价格)} 万元</b></div>
      <div><span>候选供应商</span><b title="${esc(h.候选供应商)}">${esc(h.候选供应商)}</b></div>
      <div><span>参与供应商</span><b>${(h.suppliers || []).length} 家</b></div>
    </div>
    ${sec("一定不通过", certain.length, certain, "c")}
    ${sec("拿不准", doubt.length, doubt, "d")}
    ${sec("未能识别", unread.length, unread, "")}
    <details class="fold"><summary>全部 ${(rep.rules || []).length} 条规则执行情况${svg("chev", "chev")}</summary>
      <table class="rules-table"><thead><tr><th>编号</th><th>规则</th><th>档位</th><th>结果</th><th>说明</th></tr></thead><tbody>
      ${(rep.rules || []).map((r) => `<tr><td>${r.rule_id}</td><td>${esc(r.name)}</td><td>${esc(r.tier)}</td>
        <td><span class="st2 ${stCls(r)}">${esc(r.status)}</span></td><td>${esc(r.message)}</td></tr>`).join("")}</tbody></table></details>
    <details class="fold"><summary>材料清单 · ${(rep.materials || []).length} 个文件${svg("chev", "chev")}</summary>
      <table><thead><tr><th>类型</th><th>文件</th><th>供应商</th><th>页数</th><th>解析</th></tr></thead><tbody>
      ${(rep.materials || []).map((m) => `<tr><td>${esc(m.role)}</td><td>${fileLink(rep, m.filename)}</td><td>${esc(m.supplier || "")}</td>
        <td>${m.pages}</td><td>${m.cache === "hit" ? '<span class="pill cache">复用</span>' : esc(m.status)}</td></tr>`).join("")}</tbody></table></details>
    <div class="foot"><span>任务 ${esc((rep.task_id || "").slice(0, 8))}</span><span>规则版本 ${esc(rep.rules_version)}</span>${outdatedPill(rep)}
      <span>生成于 ${esc((rep.generated_at || "").replace("T", " "))}</span>${l1 ? `<span>解析缓存命中 ${l1.hit}/${l1.total}</span>` : ""}</div>
    <div class="acts show">
      <button class="act" data-a="copy">${svg("copy")}复制结论</button>
      ${rid ? `<button class="act" data-a="redo">${svg("redo")}重新审查</button>` : ""}
      <button class="act" data-a="archive">${svg("doc")}执行档案</button>
      <button class="act" data-a="json">${svg("down")}导出报告</button>
      <button class="act" data-a="like">${svg("up")}有帮助</button>
    </div>`;
  el.querySelector(".acts").onclick = (ev) => {
    const a = ev.target.closest(".act");
    if (!a) return;
    if (a.dataset.a === "archive") return showArchive(rep.task_id);
    if (a.dataset.a === "copy") {
      const lines = [`单据 ${h.request_id}：${v[2]}（一定不通过 ${s["一定不通过"] ?? 0}，拿不准 ${s["拿不准"] ?? 0}）`,
        ...(rep.findings || []).map((r) => `- [${r.tier}] ${r.rule_id} ${r.name}：${r.message}`)];
      navigator.clipboard.writeText(lines.join("\n")).then(() => toast("结论已复制"));
    } else if (a.dataset.a === "redo") startRun(rid);
    else if (a.dataset.a === "json") {
      const blob = new Blob([JSON.stringify(rep, null, 2)], { type: "application/json" });
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = `采购审批报告_${h.request_id}_${(rep.task_id || "").slice(0, 8)}.json`;
      link.click();
    } else if (a.dataset.a === "like") { a.style.color = "var(--blue)"; toast("感谢反馈"); }
  };
}

/* ============ 审查类报告（合同 / 三会 / 报销）============ */
function reviewEvidenceHtml(rep, e) {
  if (!e || typeof e !== "object") return "";
  const parts = [];
  if (e.label) parts.push(`<span class="lb">${esc(e.label)}</span>`);
  const src = e.url ? `<a href="${esc(e.url)}" target="_blank">${esc(e.file || "链接")}</a>` : rep ? fileLink(rep, e.file) : esc(e.file || "");
  if (e.file) parts.push(src + (e.page ? ` 第${esc(e.page)}页` : ""));
  if (e.snippet) parts.push(`<span class="snip">${esc(String(e.snippet).slice(0, 140))}</span>`);
  else if (e.value !== undefined && e.value !== true) parts.push(`值 ${esc(e.value)}`);
  return parts.length ? `<div class="ev"><span>${parts.join(" · ")}</span></div>` : "";
}
function itemsHtml(items) {
  return items && items.length ? `<ol class="items">${items.map((i) => `<li>${esc(i)}</li>`).join("")}</ol>` : "";
}
function reviewFindingHtml(rep, r) {
  const cls = r.code === "issue" || r.code === "error" ? "c" : r.code === "review" ? "d" : "";
  const evs = (r.evidence || []).slice(0, 6).map((e) => reviewEvidenceHtml(rep, e)).join("");
  return `<div class="fd ${cls}"><div class="t"><span class="rid">${esc(r.rule_id)}</span>${esc(r.name)}
      ${r.group ? `<span class="st2 unread">${esc(r.group)}</span>` : ""}<span class="st2 ${CODE_ST2[r.code] || ""}">${esc(r.status)}</span></div>
    <div class="x">${esc(r.message)}</div>${itemsHtml(r.items)}${suggestHtml(r)}${evs ? `<div class="evs">${evs}</div>` : ""}</div>`;
}
function opinionHtml(rep, r) {
  const cls = r.code === "issue" || r.code === "error" ? "c" : r.code === "review" || r.code === "missing" ? "d" : r.code === "pass" ? "p" : "";
  const evs = rep ? (r.evidence || []).slice(0, 5).map((e) => reviewEvidenceHtml(rep, e)).join("") : "";
  return `<div class="op ${cls}"><div class="oh"><span class="ono">${esc(String(r.rule_id).replace(/^N/, ""))}</span><b>${esc(r.name)}</b>
      <span class="st2 ${CODE_ST2[r.code] || ""}">${esc(r.status)}</span><span class="otm">耗时 ${fmtMs(r.ms)}</span></div>
    <div class="ox">${esc(r.message)}</div>${itemsHtml(r.items)}${r.code !== "pass" ? suggestHtml(r) : ""}${evs ? `<div class="evs">${evs}</div>` : ""}</div>`;
}
function renderReviewReport(el, rep, rid, source, opts = {}) {
  const v = rep.verdict || {}, s = (rep.summary || {}).codes || {}, L = rep.labels || {}, h = rep.header || {};
  const icon = { bad: "x", warn: "alert", good: "check" }[v.level] || "alert";
  const attention = (rep.rules || []).filter((r) => ["issue", "review", "missing", "error"].includes(r.code));
  const nodes = rep.employee === "meeting";
  const sec = (code) => {
    const items = (rep.rules || []).filter((r) => r.code === code);
    return items.length ? `<h4>${esc(L[code] || code)}<span class="n">${items.length}</span></h4>${items.map((r) => reviewFindingHtml(rep, r)).join("")}` : "";
  };
  let lastGroup = null;
  const ruleRows = (rep.rules || []).map((r) => {
    const g = r.group && r.group !== lastGroup ? `<tr class="grp"><td colspan="4">${esc(r.group)}</td></tr>` : "";
    lastGroup = r.group;
    return `${g}<tr><td>${esc(r.rule_id)}</td><td>${esc(r.name)}</td><td><span class="st2 ${CODE_ST2[r.code] || ""}">${esc(r.status)}</span></td><td>${esc(r.message)}</td></tr>`;
  }).join("");
  const nums = [["issue", "c"], ["review", "d"], ["missing", ""], ["pass", "p"]];
  el.innerHTML = `
    <div class="vcard ${esc(v.level || "warn")}">
      <div class="vi">${svg(icon)}</div>
      <div><div class="vt">${esc(v.title || "审查完成")}</div><div class="vs">${esc(v.subtitle || "")}</div></div>
      <div class="nums">${nums.map(([c, k]) => `<div class="num ${k}"><b>${s[c] ?? 0}</b><span>${esc(L[c] || c)}</span></div>`).join("")}</div>
    </div>
    <div class="facts review">${(h.facts || []).map(([k, val]) => `<div class="${String(val).length > 16 || /依据|条款|标题|事由|名称/.test(k) ? "wide" : ""}"><span>${esc(k)}</span><b>${esc(val)}</b></div>`).join("")}</div>
    ${(rep.notes || []).length ? `<div class="notes">${rep.notes.map((n) => `<div>${esc(n)}</div>`).join("")}</div>` : ""}
    ${nodes && !opts.compact ? (rep.rules || []).map((r) => opinionHtml(rep, r)).join("") : ""}
    ${nodes ? "" : (["issue", "review", "missing", "error"].map(sec).join("") || '<div class="empty">无需要关注的事项</div>')}
    <details class="fold" ${nodes ? "open" : ""}><summary>${nodes ? "审查结果汇总" : `全部 ${(rep.rules || []).length} 条规则执行情况`}${svg("chev", "chev")}</summary>
      <table class="rules-table"><thead><tr><th>编号</th><th>${nodes ? "审查节点" : "规则"}</th><th>结果</th><th>说明</th></tr></thead><tbody>${ruleRows}</tbody></table></details>
    <details class="fold"><summary>材料清单 · ${(rep.materials || []).length} 个文件${svg("chev", "chev")}</summary>
      <table><thead><tr><th>类型</th><th>文件</th><th>页数</th><th>解析</th></tr></thead><tbody>
      ${(rep.materials || []).map((m) => `<tr><td>${esc(m.role)}</td><td>${fileLink(rep, m.filename)}</td><td>${m.pages}</td>
        <td>${m.cache === "hit" ? '<span class="pill cache">复用</span>' : m.status === "ok" ? "已识别" : `<span class="pill fail">${esc(m.status || "未识别")}</span>`}</td></tr>`).join("")}</tbody></table></details>
    <div class="foot"><span>任务 ${esc((rep.task_id || "").slice(0, 8))}</span><span>规则版本 ${esc(rep.rules_version)}</span>${outdatedPill(rep)}
      <span>生成于 ${esc((rep.generated_at || "").replace("T", " "))}</span>${h.source === "local" ? "<span>来源：本地事项</span>" : ""}
      ${rep.llm && rep.llm.calls ? `<span>模型调用 ${rep.llm.calls} 次（缓存 ${rep.llm.cached}）</span>` : ""}</div>
    <div class="acts show">
      <button class="act" data-a="copy">${svg("copy")}复制结论</button>
      ${rid ? `<button class="act" data-a="redo">${svg("redo")}重新审查</button>` : ""}
      ${attention.length && (rep.materials || []).length ? `<button class="act cmp-go" data-a="compare">${svg("search")}对照原文</button>` : ""}
      <button class="act" data-a="archive">${svg("doc")}执行档案</button>
      <button class="act" data-a="json">${svg("down")}导出报告</button>
      <button class="act" data-a="like">${svg("up")}有帮助</button>
    </div>`;
  el.querySelector(".acts").onclick = (ev) => {
    const a = ev.target.closest(".act");
    if (!a) return;
    if (a.dataset.a === "archive") return showArchive(rep.task_id);
    if (a.dataset.a === "compare") return openCompare(rep.task_id);
    if (a.dataset.a === "copy") {
      const lines = [`${h.request_id}：${v.title || ""}（${v.subtitle || ""}）`,
        ...attention.map((r) => [`- [${r.status}] ${r.rule_id} ${r.name}：${r.message}`, ...(r.items || []).map((x, i) => `  （${i + 1}）${x}`)].join("\n"))];
      navigator.clipboard.writeText(lines.join("\n")).then(() => toast("结论已复制"));
    } else if (a.dataset.a === "redo") startRun(rid, source || h.source);
    else if (a.dataset.a === "json") {
      const blob = new Blob([JSON.stringify(rep, null, 2)], { type: "application/json" });
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = `${TITLE[rep.employee] || "审查"}报告_${h.request_id}_${(rep.task_id || "").slice(0, 8)}.json`;
      link.click();
    } else if (a.dataset.a === "like") { a.style.color = "var(--blue)"; toast("感谢反馈"); }
  };
}

/* ============ 任务台：资料中心采集的待审单据 ============ */
const SNAP_ST = {
  ready: ["pass", "资料已就绪"], partial: ["hitd", "部分就绪"], syncing: ["unread", "同步中"],
  failed: ["hit", "同步失败"], excluded: ["notrun", "已按配置排除"],
};
function snapPill(r) {
  if (r.stale) return `<span class="st2 notrun" title="所属列表最近一次读取时已没有该单据（换账号后不可见，或已办结离开待办）">当前账号列表中已无此单</span>`;
  if (r.status === "listed") return r.open_detail ? `<span class="st2 unread">未同步 · 审查时当场同步</span>`
    : `<span class="st2 notrun" title="读取待办详情前需在测试待办上验证不改变单据状态">待办 · 只读列表</span>`;
  const [c, t] = SNAP_ST[r.status] || ["notrun", r.status];
  return `<span class="st2 ${c}" title="${esc(r.error || "")}">${t}${r.files_total != null && r.status !== "failed" ? ` · ${r.parsed_ready ?? 0}/${r.files_total} 份` : ""}</span>`;
}
function latestPill(r) {
  const l = r.latest;
  if (!l) return `<span class="st2 notrun">未审查</span>`;
  const auto = l.trigger_by === "auto" ? '<span class="st2 auto">自动</span>' : l.trigger_by === "batch" ? '<span class="st2 auto">批量</span>' : "";
  if (l.status === "running") return `${auto}<span class="st2 unread">审查中</span>`;
  if (l.status === "failed") return `${auto}<span class="st2 hit" title="${esc(l.error || "")}">审查失败</span>`;
  const v = l.verdict || {}, s = l.summary || {};
  const lvl = v.level || (s["一定不通过"] > 0 ? "bad" : s["拿不准"] > 0 ? "warn" : "good");
  const text = v.title || (s["一定不通过"] != null ? `不通过 ${s["一定不通过"]} · 拿不准 ${s["拿不准"] ?? 0}` : "已完成");
  return `${auto}<span class="st2 ${{ bad: "hit", warn: "hitd", good: "pass" }[lvl] || ""}">${esc(text)}</span>`;
}

async function showQueue(opts = {}) {
  if (!state.current) openChat(cur(), true);
  const e = emp(cur());
  userMsg(opts.list ? `看看「${opts.title || opts.list}」` : "看看资料中心已采集的待审单据");
  const body = botMsg(`<div class="typing"><i></i><i></i><i></i></div>`);
  const [q, st] = await Promise.all([
    fetch(`/api/${e.id}/queue`).then((r) => r.json()),
    fetch("/api/collect/status").then((r) => (r.ok ? r.json() : null)).catch(() => null),
  ]);
  const rows = (q.rows || []).filter((r) => !opts.list || r.list_name === opts.list);
  const listTodo = opts.list ? rows.filter((r) => r.needs_review) : [];
  const src = (rows[0] || {}).source || e.live_source;
  const s = st && st.sources ? st.sources[src] : null;
  const rounds = st ? (st.rounds || []).filter((x) => x.source === src) : [];
  const last = rounds[0];
  const head = st ? `<div class="qhead">
      <span>采集：${s && s.enabled ? `每 ${st.interval_minutes} 分钟一轮（${esc(st.active_hours || "全天")}）` : "该来源未开启采集"}</span>
      ${last ? `<span>上一轮 ${fmtTime(last.started_at)}：列出 ${last.listed ?? 0}，入队 ${last.queued ?? 0}${last.error ? `，<b class="bad">${esc(last.error.slice(0, 60))}</b>` : ""}</span>` : ""}
      <span>队列：${Object.entries(st.queue || {}).map(([k, n]) => `${({ queued: "排队", running: "同步中", done: "完成", failed: "失败" })[k] || k} ${n}`).join(" · ") || "空"}</span>
      <span>${autoText(q)}</span>
      ${s && s.enabled ? `<button class="btn sm" data-a="collect">立即采集</button>` : ""}
    </div>` : `<div class="qhead"><b class="bad">资料中心无法访问</b>（${esc(q.error || "请先启动 python -m core.resource.api")}）</div>`;
  const lead = opts.list
    ? `<p>「${esc(opts.title || opts.list)}」共 <b>${rows.length}</b> 笔：已审查 ${rows.filter((r) => r.latest && r.latest.status === "done").length} 笔，待审 <b>${listTodo.length}</b> 笔。</p>
      ${listTodo.length ? `<p><button class="btn primary" data-a="batch-list">${svg("spark")}一键审查这 ${listTodo.length} 笔待审单据</button></p>` : ""}`
    : `<p>资料中心为${esc(e.persona)}采集到 <b>${rows.length}</b> 笔待审单据：资料已就绪的直接复用解析结果；未同步的在审查时当场同步。</p>`;
  body.innerHTML = `${lead}
    ${head}
    ${q.error && st ? `<div class="err">${esc(q.error)}</div>` : ""}
    ${q.dispatcher_error ? `<div class="err">自动审查派发异常：${esc(q.dispatcher_error)}</div>` : ""}
    <div class="queue">${rows.map((r, i) => {
      const pendingLocked = !r.runnable;
      return `<div class="qrow ${r.stale ? "stale" : ""}" data-i="${i}">
        <div class="q1"><b>${esc(r.request_id)}</b><span class="ql">${esc(r.list_name || "")}</span>${snapPill(r)}
          ${r.material_changed ? '<span class="st2 hitd" title="附件或关键字段在最近一次审查后发生变化">材料已变化</span>' : ""}</div>
        <div class="q2" title="${esc(r.title || "")}">${esc(r.title || "")}</div>
        <div class="q3"><span class="qres">最近结论：${latestPill(r)}</span>
          <span class="qacts">
            <button class="btn sm primary" data-a="run" ${pendingLocked ? `disabled title="${r.stale ? "当前账号已看不到该单据" : "待办详情读取验证通过前不打开"}"` : ""}>审查</button>
            ${r.latest && r.latest.status === "done" ? '<button class="btn sm" data-a="report">查看报告</button>' : ""}
            ${r.latest ? '<button class="btn sm" data-a="archive">执行档案</button>' : ""}
          </span></div>
      </div>`;
    }).join("") || '<div class="empty">暂无采集到的单据（检查 config/collect.yaml 中该员工的采集列表，或点「立即采集」）</div>'}</div>`;
  body.onclick = async (ev) => {
    const b = ev.target.closest("button[data-a]");
    if (!b || b.disabled) return;
    if (b.dataset.a === "collect") {
      await fetch(`/api/collect/run?source=${encodeURIComponent(src)}`, { method: "POST" });
      return toast("已开始一轮采集，稍后点「待审单据」刷新");
    }
    if (b.dataset.a === "batch-list") return runBatch(listTodo.map((r) => r.request_id));
    const r = rows[+b.closest(".qrow").dataset.i];
    if (b.dataset.a === "run") startRun(r.request_id, r.source);
    else if (b.dataset.a === "archive") showArchive(r.latest.task_id);
    else if (b.dataset.a === "report") openReport(r.latest.task_id, r.request_id);
  };
  scrollBottom();
}

/* ============ 场景专属：汇总 / 权限查询 / 制度依据 / 报销标准 ============ */
function evLine(ev) {
  if (!ev || typeof ev !== "object") return "";
  const where = [ev.label || ev.supplier || ev.kind, (ev.file || "").split("/").pop(), ev.page ? `第 ${ev.page} 页` : ""].filter(Boolean).join(" · ");
  const what = ev.snippet || ev.value || [ev.author && `作者 ${ev.author}`, ev.last_modified_by && `最后修改人 ${ev.last_modified_by}`].filter(Boolean).join("，");
  return `<div class="ins-ev">${esc(where)}${what ? `：${esc(String(what).slice(0, 140))}` : ""}</div>`;
}

async function showInsight(name, title) {
  const e = emp(cur());
  userMsg(`看看${title}`);
  const body = botMsg(`<div class="typing"><i></i><i></i><i></i></div>`);
  const r = await fetch(`/api/${e.id}/insights/${name}`);
  const d = await r.json();
  if (!r.ok) { body.innerHTML = `<div class="err">${esc(d.detail || "汇总读取失败")}</div>`; return; }
  body.innerHTML = `<p>已汇总 <b>${d.reviewed}</b> 笔单据最近一次审查的结论${d.checked < d.reviewed ? `（其中 ${d.checked} 笔适用这类核查）` : ""}：
      ${d.rows.length ? `<b>${d.rows.length}</b> 笔共 <b>${d.hits}</b> 条需关注。` : "没有发现这类问题。"}</p>
    ${d.by_rule.length ? `<div class="ins-chips">${d.by_rule.map((b) => `<span class="tchip">${esc(b.rule_id)} ${esc(b.name)}<b>${b.n}</b></span>`).join("")}</div>` : ""}
    <div class="ins">${d.rows.map((row, i) => `
      <div class="ins-row" data-i="${i}">
        <div class="i1"><b>${esc(row.request_id)}</b><span class="tt3" title="${esc(row.subject)}">${esc(row.subject)}</span>
          <span class="muted">${fmtTime(row.created_at)}</span>
          <button class="btn sm" data-a="report">查看报告</button><button class="btn sm" data-a="archive">执行档案</button></div>
        ${row.hits.map((h) => `<div class="ins-hit"><div><span class="st2 ${h.code === "issue" || h.status === "命中" ? "hit" : "hitd"}">${esc(h.rule_id)} ${esc(h.status || "")}</span>
          <b>${esc(h.name)}</b></div><div class="ins-msg">${esc(h.message || "")}</div>${(h.evidence || []).slice(0, 2).map(evLine).join("")}</div>`).join("")}
      </div>`).join("")}</div>
    <p class="muted">只读取已有审查报告，不重新取数；单据材料变化后会自动重审，这里随之更新。</p>`;
  body.onclick = (ev) => {
    const b = ev.target.closest("button[data-a]");
    if (!b) return;
    const row = d.rows[+b.closest(".ins-row").dataset.i];
    if (b.dataset.a === "report") openReport(row.task_id, row.request_id);
    else showArchive(row.task_id);
  };
  scrollBottom();
}

const AUTH_EG = [["信息化项目采购结果", "80"], ["对外捐赠", "5"], ["年度预算调整", ""], ["资产处置", "300"]];

function showAuthority() {
  userMsg("事项审批权限查询");
  const body = botMsg(`<p>输入事项与金额，我按已启用的四份制度检索条款，并按金额落到对应档位，告诉你该上什么会、由谁审批：</p>
    <form class="auth">
      <input name="matter" placeholder="事项，如：信息化项目采购结果、对外捐赠、资产处置" aria-label="事项" required>
      <input name="amount" placeholder="金额（万元，可选）" aria-label="金额">
      <button class="btn primary" type="submit">查询</button>
    </form>
    <div class="auth-eg">试试：${AUTH_EG.map(([m, a]) => `<button type="button" class="tchip" data-m="${esc(m)}" data-a="${esc(a)}">${esc(m)}${a ? ` ${esc(a)} 万` : ""}</button>`).join("")}</div>
    <div class="auth-res"></div>`);
  const form = $("form.auth", body), res = $(".auth-res", body);
  const run = async () => {
    const matter = form.matter.value.trim(), amount = form.amount.value.trim();
    if (!matter) return form.matter.focus();
    res.innerHTML = `<div class="typing"><i></i><i></i><i></i></div>`;
    const r = await fetch("/api/meeting/authority", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ matter, amount }) });
    const d = await r.json();
    if (!r.ok) { res.innerHTML = `<div class="err">${esc(d.detail || "查询失败")}</div>`; return; }
    const top = d.results[0];
    const verdict = !top ? `<div class="err">四份制度中没有检索到与「${esc(matter)}」相关的条款，请换个说法（例如用制度里的事项名称）。</div>`
      : top.status === "matched" ? `<div class="auth-v">按《${esc(top.doc)}》${esc(top.ref)}「${esc(top.title)}」${d.amount_wan != null ? `（${d.amount_wan} 万元）` : ""}：
          由 <b>${esc(top.final.join("、") || "—")}</b> 审批 / 决策，${top.meetings.length ? `应上 <b>${esc(top.meetings.join("、"))}</b>` : "无需上会"}。</div>`
      : top.status === "need_amount" ? `<div class="auth-v warn">最相关条款按金额分档，请填写金额后再查。</div>`
      : `<div class="auth-v warn">最相关条款的档位无法唯一确定（${top.status === "no_tier" ? "金额未落入任何档位" : "多个档位审批主体不同"}），请对照下方档位人工判断。</div>`;
    res.innerHTML = `${verdict}${d.results.map((c, i) => `
      <details class="fold auth-c" ${i === 0 ? "open" : ""}><summary><span class="st2 ${i === 0 ? "pass" : "unread"}">${i === 0 ? "最相关" : `相关度 ${Math.round(c.score * 100)}`}</span>
        《${esc(c.doc)}》${esc(c.ref)}「${esc(c.title)}」${c.page ? `<span class="muted">第 ${c.page} 页</span>` : ""}${svg("chev", "chev")}</summary>
        <table><thead><tr><th>档位</th><th>审批 / 决策主体</th><th>流转顺序</th><th></th></tr></thead><tbody>
        ${c.tiers.map((t) => `<tr class="${t.fit ? "fit" : ""}"><td>${esc(t.tier)}${t.sub ? `<div class="muted">${esc(t.sub)}</div>` : ""}</td>
          <td><b>${esc((t.final || []).join("、") || "—")}</b>${t.meetings && t.meetings.length ? `<div class="muted">${esc(t.meetings.join("、"))}</div>` : ""}</td>
          <td class="auth-steps">${(t.steps || []).map((s) => `<span class="${s.final ? "fin" : ""}" title="${s.final ? "审批 / 决策（制度中红色标识）" : ""}">${esc(s.mark)}${esc(s.subject)}</span>`).join("<i>→</i>")}</td><td>${t.fit ? '<span class="st2 pass">金额落在此档</span>' : ""}</td></tr>`).join("")}</tbody></table>
      </details>`).join("")}
      <p class="muted">按文字相似度检索制度条款并按金额判断档位，供核对参考；正式审查以请示中写明的依据为准（三会审查第 03 节点同一套制度）。</p>`;
    scrollBottom();
  };
  form.onsubmit = (ev) => { ev.preventDefault(); run(); };
  $(".auth-eg", body).onclick = (ev) => {
    const c = ev.target.closest("[data-m]");
    if (!c) return;
    form.matter.value = c.dataset.m;
    form.amount.value = c.dataset.a;
    run();
  };
  form.matter.focus();
}

async function showRegs() {
  userMsg("看看四份制度依据");
  const body = botMsg(`<div class="typing"><i></i><i></i><i></i></div>`);
  const d = await (await fetch("/api/knowledge")).json();
  const ST = { enabled: ["pass", "已启用"], disabled: ["notrun", "已停用"], missing: ["hit", "文件缺失"], failed: ["hit", "解析失败"], registered: ["unread", "已登记"] };
  body.innerHTML = `<p>三会审查依据以下制度判断事项该上什么会、由谁审批（第 03 节点「审批/上会依据」与「事项审批权限查询」共用）：</p>
    <table class="rules-table"><thead><tr><th>制度</th><th>状态</th><th>条款数</th></tr></thead><tbody>
    ${(d.documents || []).map((x) => { const [c, t] = ST[x.state] || ["unread", x.state];
      return `<tr><td>${esc(x.name)}${x.error ? `<div class="bad">${esc(x.error)}</div>` : ""}</td><td><span class="st2 ${c}">${t}</span></td><td>${x.clauses ?? 0}</td></tr>`; }).join("")}
    </tbody></table>
    <p><button class="btn primary" data-a="auth">${svg("search")}按事项查审批权限</button></p>`;
  $("[data-a=auth]", body).onclick = () => showAuthority();
  scrollBottom();
}

async function showStandards() {
  userMsg("按单据类别查看报销标准");
  const body = botMsg(`<div class="typing"><i></i><i></i><i></i></div>`);
  const d = await (await fetch(`/api/${cur()}/rules`)).json();
  const groups = {};
  (d.rules || []).forEach((r) => (groups[r.group || "其他"] = groups[r.group || "其他"] || []).push(r));
  const CAT = { 数据: "unread", 材料: "pass", 标准: "hitd", 风险: "hit" };
  const render = (g) => `<table class="rules-table"><thead><tr><th>编号</th><th>核对项</th><th>类型</th><th>状态</th></tr></thead><tbody>
    ${groups[g].map((r) => `<tr><td>${esc(r.rule_id)}</td><td>${esc(r.name)}</td><td><span class="st2 ${CAT[r.category] || ""}">${esc(r.category)}</span></td>
      <td><span class="st2 ${r.state === "已上线" ? "pass" : "notrun"}">${esc(r.state)}</span></td></tr>`).join("")}</tbody></table>`;
  const names = Object.keys(groups);
  body.innerHTML = `<p>按单据类别查看我核对的项目（共 ${(d.rules || []).length} 项；类型：数据一致性 / 材料完整性 / 标准测算 / 票据风险）：</p>
    <div class="std-tabs">${names.map((g, i) => `<button type="button" class="tchip ${i === 0 ? "on" : ""}" data-g="${esc(g)}">${esc(g)}<b>${groups[g].length}</b></button>`).join("")}</div>
    <div class="std-body">${render(names[0])}</div>`;
  $(".std-tabs", body).onclick = (ev) => {
    const c = ev.target.closest("[data-g]");
    if (!c) return;
    body.querySelectorAll(".std-tabs .tchip").forEach((x) => x.classList.toggle("on", x === c));
    $(".std-body", body).innerHTML = render(c.dataset.g);
  };
  scrollBottom();
}

async function openReport(taskId, rid) {
  userMsg(`查看单据 ${rid} 的报告`);
  const r = await fetch(`/api/runs/${taskId}`);
  if (!r.ok) return botMsg(`<div class="err">该任务没有生成报告。</div>`);
  const rep = await r.json();
  state.lastTask = taskId;
  const b = botMsg(`<p>这是 ${esc((rep.generated_at || "").replace("T", " "))} 生成的报告：</p><div class="result"></div>`);
  if (rep.kind === "review") renderReviewReport($(".result", b), rep, rid, (rep.header || {}).source);
  else renderReport($(".result", b), rep, rid);
  scrollBottom();
}

/* ============ 执行档案 ============ */
const ARC_KIND = { snapshot: "表单快照", event: "过程", api: "接口报文", llm: "模型调用", check: "原文校验", rules: "规则结论",
  report: "报告", shots: "证据截图", page: "平台页面" };
// 接口地址 → 在客户平台上做了什么（只读）
const OP_NAME = [
  [/reqform\/loadForm/, "读取审批单据表单（字段、附件清单）"],
  [/getRequestLogBaseInfo|getRequestLogList/, "读取审批流转日志"],
  [/govdoc\/summary\/v1\/deal-base-info/, "读取公文详情（标题、模板、附件清单）"],
  [/content\/content\.do/, "读取公文表单内容"],
  [/getQueryResult/, "公司数据查询 · 内部请示查询（只读）"],
  [/tyssj\.do/, "经门户统一认证单点登录"],
  [/fileDownload|FileDownload|downloadFile|doDownload/i, "下载附件原件"],
  [/cube\/search\/getList|ec\/dev\/table\/datas/, "读取台账"],
  [/reqlist|splitPageKey/, "读取待办 / 已办列表（只读列表）"],
  [/tianyancha|tyc/i, "查询企业资信（天眼查）"],
];
const opName = (url) => (OP_NAME.find(([re]) => re.test(url || "")) || [null, "调用平台接口"])[1];
const host = (url) => { try { return new URL(url).host; } catch { return ""; } };

function pageCard(p, pageMeta) {
  const meta = (pageMeta || []).find((x) => x.page_id === p.page_id) || {};
  const ops = p.ops || [], blocked = p.blocked || [];
  return `<div class="pcap">
    <div class="pc-h">${svg("doc")}<b>${esc(p.title || "客户平台页面")}</b>${p.ms ? `<span>${fmtMs(p.ms)}</span>` : ""}</div>
    <div class="pc-u" title="${esc(p.final_url || p.url || "")}">${esc(p.url || "")}</div>
    ${p.skip ? `<div class="pc-skip">未打开页面：${esc(p.skip)}</div>` : ""}
    ${p.error ? `<div class="err">${esc(p.error)}</div>` : ""}
    ${p.page_id ? `<a class="pc-img" href="/api/archive/pages/${p.page_id}.png" target="_blank" title="点击查看原尺寸（已打码）">
        <img loading="lazy" src="/api/archive/pages/${p.page_id}.png?w=960" alt="${esc(p.title || "")}"></a>
      <div class="pc-m"><span>${p.width}×${p.height}${p.truncated ? "（超长已截断）" : ""}</span>
        <span>敏感信息打码 ${meta.pii_count ?? 0} 处（原图留存于资料中心）</span><span>页面请求 ${ops.length} 个</span>
        <span class="${blocked.length ? "warn" : ""}">拦截写请求 ${blocked.length} 个</span></div>` : ""}
    ${blocked.length ? `<div class="pc-block">只读保护已拦截：${blocked.map((b) => `<code>${esc(b.method)} ${esc((b.url || "").split("?")[0].split("/").slice(-2).join("/"))}</code>`).join(" ")}</div>` : ""}
    ${ops.length ? `<details class="raw"><summary>页面加载过程中发出的请求 · ${ops.length} 个</summary><table>${ops.map((o) =>
      `<tr><td>${o.at}s</td><td>${esc(o.method)}</td><td>${o.status}</td><td title="${esc(o.url)}">${esc((o.url || "").split("?")[0])}</td></tr>`).join("")}</table></details>` : ""}
  </div>`;
}

function stepsHtml(items, pages) {
  const rows = [];
  for (const i of items) {
    const b = i.body || {};
    if (i.kind === "event" && b.type === "node.started") rows.push(`<div class="op-n">${esc(b.node)}</div>`);
    else if (i.kind === "api") rows.push(`<div class="op"><span class="op-t">${new Date(i.at * 1000).toLocaleTimeString()}</span>
      <span class="op-d">${esc(opName(b.url))}</span><span class="op-h">${esc(host(b.url))}</span>
      <span class="st2 ${b.status < 400 ? "pass" : "hit"}">${esc(b.method)} ${b.status}</span><span class="op-ms">${fmtMs(b.ms)}</span></div>`);
    else if (i.kind === "page") rows.push(`<div class="op"><span class="op-t">${new Date(i.at * 1000).toLocaleTimeString()}</span>
      <span class="op-d">${b.page_id ? "只读打开单据页面并整页截图（见上方「客户平台页面」）" : `未打开单据页面：${esc(b.skip || b.error || "")}`}</span>
      <span class="op-h">${esc(host(b.url))}</span>${b.page_id ? '<span class="st2 pass">截图</span>' : '<span class="st2 notrun">跳过</span>'}</div>`);
    else if (i.kind === "event" && b.type === "sync.notice") rows.push(`<div class="op"><span class="op-d muted">${esc(b.text || "")}</span></div>`);
  }
  return rows.join("") || '<div class="muted">本次执行没有访问客户平台（本地事项或全部复用资料中心已入库的资料）。</div>';
}
const SHOT_METHOD = { text: "精确定位", ocr: "OCR 定位", page: "未定位到原文（整页）", none: "无页面图", error: "渲染失败" };

async function fetchArchive(taskId) {
  const r = await fetch(`/api/runs/${taskId}/archive`);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || "没有执行档案");
  return r.json();
}

async function showArchive(taskId) {
  if (!taskId) return toast("该报告没有任务编号");
  const body = botMsg(`<div class="typing"><i></i><i></i><i></i></div>`);
  try {
    body.innerHTML = archiveHtml(await fetchArchive(taskId), taskId);
  } catch (err) {
    body.innerHTML = `<div class="err">${esc(err.message)}</div>`;
  }
  scrollBottom();
}

function archiveHtml(a, taskId) {
  const v = a.versions || {}, items = a.items || [];
  const count = {};
  items.forEach((i) => (count[i.kind] = (count[i.kind] || 0) + 1));
  const llms = items.filter((i) => i.kind === "llm"), apis = items.filter((i) => i.kind === "api");
  const checks = items.filter((i) => i.kind === "check");
  const dur = a.finished_at ? fmtMs((a.finished_at - a.started_at) * 1000) : "未结束";
  const judge = ((v.llm || {}).judge || {}).model || "—";
  const pre = (o) => `<pre>${esc(JSON.stringify(o, null, 1).slice(0, 4000))}</pre>`;
  return `<div class="arc">
    <div class="arc-h"><b>执行档案</b><span>任务 ${esc(taskId.slice(0, 8))}</span><span>${esc(a.request_id)}</span>
      <span>${{ auto: "自动审查", batch: "批量审查" }[a.trigger_by] || "人工发起"}</span><span>${esc({ done: "已完成", failed: "失败", running: "进行中" }[a.status] || a.status)} · ${dur}</span></div>
    <div class="arc-v">
      <div><span>规则版本</span><b>${esc(v.rules || "—")}</b></div><div><span>代码版本</span><b>${esc(v.code || "—")}</b></div>
      <div><span>解析引擎</span><b>${esc(((v.ocr || {}).engine) || "—")}</b></div><div><span>判定模型</span><b>${esc(judge)}</b></div>
      <div><span>制度文件</span><b>${Array.isArray(v.regulations) ? v.regulations.filter((d) => d.state === "enabled").length + " 份启用" : "—"}</b></div>
      <div><span>材料指纹</span><b title="${esc(a.material_fp || "")}">${esc((a.material_fp || "—").slice(0, 12))}</b></div>
    </div>
    <div class="arc-c">${Object.entries(count).map(([k, n]) => `<span>${esc(ARC_KIND[k] || k)} ${n}</span>`).join("")}</div>
    ${a.error ? `<div class="err">${esc(a.error)}</div>` : ""}
    ${items.some((i) => i.kind === "page") ? `<h4>客户平台页面<span class="n">${(a.pages || []).length}</span></h4>${items.filter((i) => i.kind === "page").map((i) => pageCard(i.body || {}, a.pages)).join("")}` : ""}
    <details class="fold" open><summary>平台操作步骤 · ${items.filter((i) => i.kind === "api").length} 次接口调用${svg("chev", "chev")}</summary>
      <div class="ops">${stepsHtml(items, a.pages)}</div></details>
    ${(a.shots || []).length ? `<h4>证据截图<span class="n">${a.shots.length}</span></h4><div class="shots">${a.shots.map((s) => `
      <figure>${s.png_uri ? `<a href="/api/archive/shots/${s.shot_id}.png" target="_blank"><img loading="lazy" src="/api/archive/shots/${s.shot_id}.png"></a>` : '<div class="noimg">无页面图</div>'}
        <figcaption><b>${esc(s.rule_id)}</b> ${esc(s.filename.split("/").pop())}${s.page_no ? ` · 第 ${s.page_no} 页` : ""}
          <span class="st2 ${s.method === "text" || s.method === "ocr" ? "pass" : "notrun"}">${esc(SHOT_METHOD[s.method] || s.method)}</span>
          <div class="q">「${esc((s.quote || "").slice(0, 80))}」</div></figcaption></figure>`).join("")}</div>` : ""}
    <details class="fold"><summary>模型调用 · ${llms.length} 次${svg("chev", "chev")}</summary>
      <table><thead><tr><th>用途</th><th>模型</th><th>缓存</th><th>耗时</th><th>结果</th></tr></thead><tbody>
      ${llms.map((i) => `<tr><td>${esc(i.title)}</td><td>${esc(i.body.model || "")}</td><td>${i.body.cached ? "命中" : "—"}</td>
        <td>${fmtMs(i.body.ms)}</td><td>${i.body.ok ? "成功" : `<span class="bad">${esc(i.body.error || "失败")}</span>`}</td></tr>`).join("")}</tbody></table>
      ${llms.slice(0, 20).map((i) => `<details class="raw"><summary>${esc(i.title)} 完整输入输出</summary>${pre({ messages: i.body.messages, raw: i.body.raw, output: i.body.output })}</details>`).join("")}</details>
    <details class="fold"><summary>原文校验 · ${checks.length} 条${svg("chev", "chev")}</summary>${checks.map((i) => `<details class="raw"><summary>${esc(i.title)}</summary>${pre(i.body)}</details>`).join("")}</details>
    <details class="fold"><summary>接口报文 · ${apis.length} 次（已脱敏）${svg("chev", "chev")}</summary>
      <table><thead><tr><th>请求</th><th>状态</th><th>耗时</th><th>大小</th></tr></thead><tbody>
      ${apis.map((i) => `<tr><td title="${esc(i.body.url)}">${esc(i.title)}</td><td>${i.body.status}</td><td>${fmtMs(i.body.ms)}</td><td>${Math.round((i.body.bytes || 0) / 1024)} KB</td></tr>`).join("")}</tbody></table></details>
    <details class="fold"><summary>完整时间线 · ${items.length} 条${svg("chev", "chev")}</summary><div class="tl">
      ${items.map((i) => `<details class="raw"><summary><span class="tk">${esc(ARC_KIND[i.kind] || i.kind)}</span>${esc(i.title || "")}<span class="tt2">${new Date(i.at * 1000).toLocaleTimeString()}</span></summary>${pre(i.body)}</details>`).join("")}</div></details>
  </div>`;
}

/* ============ 历史 ============ */
async function toggleHistory() {
  const pop = $("#history-pop");
  if (!pop.classList.contains("hidden")) return pop.classList.add("hidden");
  pop.classList.remove("hidden");
  const empId = cur();
  pop.innerHTML = `<div class="ttl">历史审查报告</div><div class="hist"><div class="typing"><i></i><i></i><i></i></div></div>`;
  const runs = await (await fetch(`/api/runs?employee=${empId}&limit=40`)).json();
  pop.innerHTML = `<div class="ttl">历史审查报告 · ${runs.length} 条</div>` + (runs.length ? runs.map((r) => {
    const s = r.summary || {}, c = s.codes;
    const tags = r.status === "failed" ? `<span class="st2 hit">审查失败</span>` : r.status === "running" ? `<span class="st2 unread">审查中</span>`
      : c ? `<span class="st2 hit">问题 ${c.issue ?? 0}</span><span class="st2 hitd">复核 ${c.review ?? 0}</span><span class="st2 unread">待补充 ${c.missing ?? 0}</span>`
      : `<span class="st2 hit">不通过 ${s["一定不通过"] ?? 0}</span><span class="st2 hitd">拿不准 ${s["拿不准"] ?? 0}</span><span class="st2 unread">未能识别 ${s["未能识别"] ?? 0}</span>`;
    const meta = `${r.trigger_by === "auto" ? '<span class="st2 auto">自动</span>' : r.trigger_by === "batch" ? '<span class="st2 auto">批量</span>' : ""}${r.superseded_by ? '<span class="st2 old">已被新版本取代</span>' : ""}`;
    return `<div class="hist ${r.superseded_by ? "superseded" : ""}" data-task="${r.task_id}" data-rid="${esc(r.request_id)}">
      <div class="h1"><span>单据 ${esc(r.request_id)}${meta}</span><span>${fmtTime(r.created_at)}</span></div>
      <div class="h2">${esc(r.subject || r.采购内容 || r.error || "")}</div><div class="h3">${tags}</div></div>`;
  }).join("") : `<div class="hist"><div class="h2">暂无历史记录</div></div>`);
  pop.querySelectorAll(".hist[data-task]").forEach((el) => (el.onclick = async (ev) => {
    ev.stopPropagation();
    pop.classList.add("hidden");
    userMsg(`查看单据 ${el.dataset.rid} 的历史报告`);
    const r = await fetch(`/api/runs/${el.dataset.task}`);
    if (!r.ok) return botMsg(`<div class="err">该任务没有生成报告。</div>`);
    const rep = await r.json();
    state.lastTask = el.dataset.task;
    const b = botMsg(`<p>这是 ${esc((rep.generated_at || "").replace("T", " "))} 生成的报告：</p><div class="result"></div>`);
    if (rep.kind === "review") renderReviewReport($(".result", b), rep, el.dataset.rid, (rep.header || {}).source);
    else renderReport($(".result", b), rep, el.dataset.rid);
    scrollBottom();
  }));
}

/* ============ 原文对照：左侧源文件，右侧问题项，点击 / 悬停联动高亮 ============ */
const cmp = { data: null, panes: [null, null], split: false, sel: null };
const LOC_TXT = { text: ["pass", "精确定位"], ocr: ["pass", "OCR 行定位"], para: ["pass", "段落定位"], page: ["hitd", "仅定位到页"],
  none: ["notrun", "未定位"], error: ["hit", "定位失败"] };

async function openCompare(taskId) {
  let el = $("#cmp");
  if (!el) {
    el = document.createElement("div");
    el.id = "cmp";
    el.className = "cmp";
    el.setAttribute("role", "dialog");
    el.setAttribute("aria-label", "对照原文");
    document.body.appendChild(el);
  }
  el.innerHTML = `<div class="ctr-loading"><div class="typing"><i></i><i></i><i></i></div><p class="muted">正在定位证据原文…</p></div>`;
  el.classList.remove("hidden");
  const r = await fetch(`/api/runs/${taskId}/compare`);
  const d = await r.json();
  if (!r.ok) { el.innerHTML = `<div class="err">${esc(d.detail || "读取失败")}</div>`; return; }
  cmp.data = d;
  cmp.split = false;
  cmp.sel = null;
  const firstSig = (d.items.flatMap((it) => it.evidence).find((e) => e.loc && e.loc.sig) || {}).loc?.sig || (d.files[0] || {}).sig;
  cmp.panes = [firstSig, null];
  el.innerHTML = `
    <div class="cmp-h"><b>对照原文</b><span>${esc(d.request_id || "")}</span><span class="muted" title="${esc(d.title)}">${esc(d.title)}</span>
      <span class="st2 pass">证据定位 ${d.located}/${d.evidence_total}</span><span class="grow"></span>
      <label class="sw"><input type="checkbox" id="cmp-split"> 并列对照（两份材料左右对照）</label>
      <button class="icon-btn" data-a="close" title="关闭（Esc）">${svg("x")}</button></div>
    <div class="cmp-b">
      <div class="cmp-l"><div class="cmp-pane" data-p="0"></div><div class="cmp-pane hidden" data-p="1"></div></div>
      <div class="cmp-r">
        <div class="cmp-rh">需关注 <b>${d.items.length}</b> 项 <span class="muted">点击项目或证据定位原文；悬停预览</span></div>
        ${d.items.map((it, i) => `<div class="ci ${it.code === "issue" || it.status === "命中" ? "c" : it.code === "review" ? "d" : ""}" data-i="${i}">
          <div class="ci-h"><b>${esc(it.rule_id)}</b>${esc(it.name || "")}<span class="st2 ${CODE_ST2[it.code] || (it.status === "命中" ? "hit" : "unread")}">${esc(it.status || "")}</span></div>
          <div class="ci-m">${esc(it.message || "")}</div>${it.suggest ? `<div class="sug"><b>核实建议</b>${esc(it.suggest)}</div>` : ""}
          <div class="ci-e">${it.evidence.map((e, j) => {
            const [c, t] = LOC_TXT[(e.loc || {}).method] || LOC_TXT.none;
            const f = d.files.find((x) => x.sig === (e.loc || {}).sig);
            return `<div class="ce" data-i="${i}" data-j="${j}" tabindex="0"><div><span class="st2 ${c}">${t}</span>${e.label ? `<b>${esc(e.label)}</b>` : ""}
              <span class="muted">${esc(f ? f.name : (e.file || ""))}${(e.loc || {}).page_no ? ` · 第 ${e.loc.page_no} 页` : ""}</span></div>
              <div class="ce-s">${esc(String(e.value && String(e.value).length >= 6 ? e.value : e.snippet || "").slice(0, 120))}</div>
              ${(e.loc || {}).why ? `<div class="muted">${esc(e.loc.why)}</div>` : ""}</div>`; }).join("")}</div>
        </div>`).join("") || '<div class="empty">本报告没有需关注的项目</div>'}
      </div>
    </div>`;
  renderPane(0);
  const right = $(".cmp-r", el);
  right.onclick = (ev) => {
    const ce = ev.target.closest(".ce");
    if (ce) return selectEvidence(+ce.dataset.i, +ce.dataset.j, true);
    const ci = ev.target.closest(".ci");
    if (ci) selectItem(+ci.dataset.i);
  };
  right.onmouseover = (ev) => {
    const ce = ev.target.closest(".ce");
    if (ce) previewEvidence(+ce.dataset.i, +ce.dataset.j);
  };
  right.onmouseleave = () => document.querySelectorAll("#cmp .hl.hov").forEach((x) => x.remove());
  right.onkeydown = (ev) => { if (ev.key === "Enter" && ev.target.closest(".ce")) selectEvidence(+ev.target.dataset.i, +ev.target.dataset.j, true); };
  $("#cmp-split").onchange = (ev) => {
    cmp.split = ev.target.checked;
    $(".cmp-pane[data-p='1']", el).classList.toggle("hidden", !cmp.split);
    $(".cmp-l", el).classList.toggle("split", cmp.split);
    if (cmp.split && cmp.sel) selectItem(cmp.sel.i); else if (!cmp.split) cmp.panes[1] = null;
  };
  el.onclick = (ev) => { if (ev.target.closest("[data-a=close]")) closeCompare(); };
  const first = d.items.findIndex((it) => it.evidence.some((e) => e.loc && e.loc.sig));
  if (first >= 0) selectItem(first);
}

function closeCompare() {
  const el = $("#cmp");
  if (el) el.classList.add("hidden");
}

function renderPane(p) {
  const d = cmp.data, sig = cmp.panes[p];
  const pane = $(`#cmp .cmp-pane[data-p='${p}']`);
  const f = d.files.find((x) => x.sig === sig);
  pane.innerHTML = `<div class="cmp-tabs">${d.files.filter((x) => !/\.(zip|rar|7z)$/i.test(x.filename)).map((x) =>
      `<button class="ct ${x.sig === sig ? "on" : ""}" data-sig="${x.sig}" title="${esc(x.filename)}">${esc(x.role || "")} · ${esc(x.name)}</button>`).join("")}</div>
    <div class="cmp-view" tabindex="0"></div>`;
  $(".cmp-tabs", pane).onclick = (ev) => {
    const b = ev.target.closest("[data-sig]");
    if (b) { cmp.panes[p] = b.dataset.sig; renderPane(p); }
  };
  const view = $(".cmp-view", pane);
  if (!f) { view.innerHTML = '<div class="empty">请选择左侧上方的文件</div>'; return; }
  if (f.kind === "pdf" || f.kind === "image") {
    const n = f.kind === "image" ? 1 : Math.max(1, f.pages || 1);
    view.innerHTML = Array.from({ length: n }, (_, k) => `<div class="pg" data-no="${k + 1}"><img loading="lazy" alt="第 ${k + 1} 页"
        src="/api/files/${f.sig}/pages/${k + 1}.png" onload="this.parentNode.style.aspectRatio=this.naturalWidth+'/'+this.naturalHeight">
        <div class="hl-layer"></div><span class="pgno">${k + 1} / ${n}</span></div>`).join("");
  } else {
    view.innerHTML = `<div class="ctr-loading"><div class="typing"><i></i><i></i><i></i></div></div>`;
    fetch(`/api/files/${f.sig}/parsed`).then((r) => r.json()).then((doc) => {
      if (cmp.panes[p] !== f.sig) return;
      view.innerHTML = `<div class="txt">${(doc.pages || []).map((pg) => `<div class="tp" data-no="${pg.no}">${(doc.pages.length > 1 ? `<div class="pgno2">第 ${pg.no} 页</div>` : "")}${
        String(pg.text || "").split("\n").map((t, i) => `<p data-para="${i}">${esc(t) || "&nbsp;"}</p>`).join("")}</div>`).join("")}</div>`;
      if (view._pending) { const x = view._pending; view._pending = null; highlightIn(p, x.loc, x.sticky); }
    }).catch(() => { view.innerHTML = '<div class="err">正文读取失败</div>'; });
  }
}

function paneFor(i, j) {
  if (!cmp.split) return 0;
  const evs = cmp.data.items[i].evidence;
  const groups = [];
  evs.forEach((e) => { const g = String(e.label || e.file || "").split(/[·\s]/)[0]; if (!groups.includes(g)) groups.push(g); });
  const g = String(evs[j].label || evs[j].file || "").split(/[·\s]/)[0];
  return groups.indexOf(g) % 2;
}

function highlightIn(p, loc, sticky) {
  const pane = $(`#cmp .cmp-pane[data-p='${p}']`);
  const view = $(".cmp-view", pane);
  const cls = sticky ? "hl" : "hl hov";
  if (!sticky) view.querySelectorAll(".hl.hov").forEach((x) => x.remove());
  else view.querySelectorAll(".hl, .tp p.on, .pg.on").forEach((x) => (x.classList.contains("hl") ? x.remove() : x.classList.remove("on")));
  if (loc.method === "para") {
    const tp = view.querySelector(`.tp[data-no='${loc.page_no || 1}']`);
    if (!tp) { view._pending = { loc, sticky }; return; }
    const para = tp.querySelector(`p[data-para='${loc.para}']`);
    if (para) { para.classList.add("on"); if (sticky) para.scrollIntoView({ block: "center", behavior: "smooth" }); }
    return;
  }
  const pg = view.querySelector(`.pg[data-no='${loc.page_no}']`);
  if (!pg) return;
  if (!loc.rects || !loc.rects.length) { if (sticky) { pg.classList.add("on"); pg.scrollIntoView({ block: "start", behavior: "smooth" }); } return; }
  const layer = $(".hl-layer", pg);
  loc.rects.forEach(([x0, y0, x1, y1]) => {
    const h = document.createElement("div");
    h.className = cls;
    h.style.cssText = `left:${(x0 / loc.page_w) * 100}%;top:${(y0 / loc.page_h) * 100}%;width:${((x1 - x0) / loc.page_w) * 100}%;height:${((y1 - y0) / loc.page_h) * 100}%`;
    layer.appendChild(h);
  });
  if (sticky) {
    pg.style.aspectRatio = pg.style.aspectRatio || `${loc.page_w}/${loc.page_h}`;
    requestAnimationFrame(() => {
      const y = pg.offsetTop + (loc.rects[0][1] / loc.page_h) * pg.clientHeight - view.clientHeight / 3;
      view.scrollTo({ top: Math.max(0, y), behavior: "smooth" });
    });
  }
}

function selectEvidence(i, j, sticky) {
  const e = cmp.data.items[i].evidence[j];
  document.querySelectorAll("#cmp .ce.on").forEach((x) => x.classList.remove("on"));
  const ce = $(`#cmp .ce[data-i='${i}'][data-j='${j}']`);
  if (ce) ce.classList.add("on");
  const loc = e.loc || {};
  if (!loc.sig) return toast(loc.why || "该证据未能在源文件中定位");
  const p = paneFor(i, j);
  if (cmp.panes[p] !== loc.sig) { cmp.panes[p] = loc.sig; renderPane(p); }
  setTimeout(() => highlightIn(p, loc, sticky), cmp.panes[p] === loc.sig ? 30 : 30);
}

function previewEvidence(i, j) {
  const loc = (cmp.data.items[i].evidence[j] || {}).loc || {};
  const p = paneFor(i, j);
  if (loc.sig && cmp.panes[p] === loc.sig) highlightIn(p, loc, false);
}

function selectItem(i) {
  cmp.sel = { i };
  document.querySelectorAll("#cmp .ci.on").forEach((x) => x.classList.remove("on"));
  const ci = $(`#cmp .ci[data-i='${i}']`);
  if (ci) ci.classList.add("on");
  const evs = cmp.data.items[i].evidence;
  const located = evs.map((e, j) => [e, j]).filter(([e]) => e.loc && e.loc.sig);
  if (!located.length) return;
  if (!cmp.split) return selectEvidence(i, located[0][1], true);
  const seen = new Set();
  located.forEach(([e, j]) => { const p = paneFor(i, j); if (!seen.has(p)) { seen.add(p); selectEvidence(i, j, true); } });
}

/* ============ 流程与规则 ============ */
const fl = { emp: "procurement", data: null, node: null, q: "" };
const MATCH_CLS = { 一致: "pass", 拆分: "unread", 调整: "hitd", 系统外: "notrun" };
const KIND_CLS = { 取数: "k-src", 资料: "k-res", 处理: "k-proc", 校验: "k-chk", 报告: "k-rep" };
const CODE_TXT = { issue: "问题", review: "复核", missing: "待补充", pass: "通过", na: "不适用", notrun: "未执行", error: "中止",
  命中: "命中", 未命中: "未命中", 未能识别: "未能识别", 未执行: "未执行" };
const author = () => localStorage.getItem("de.author") || "";
const fmtVal = (v) => (v === null || v === undefined ? "—" : Array.isArray(v) ? (v.length ? v.join("、") : "（空）") : typeof v === "boolean" ? (v ? "是" : "否") : String(v));

async function showFlows(empId) {
  fl.emp = empId || fl.emp;
  fl.node = null;
  fl.q = "";
  showView("#view-flows");
  closeFlDrawer();
  await renderFlows();
}

async function renderFlows(keepNode) {
  const body = $("#fl-body");
  if (!keepNode) body.innerHTML = `<div class="ctr-loading"><div class="typing"><i></i><i></i><i></i></div></div>`;
  let idx, d;
  try {
    [idx, d] = await Promise.all([fetch("/api/flows").then((r) => r.json()), fetch(`/api/flows/${fl.emp}`).then((r) => r.json())]);
  } catch (err) {
    body.innerHTML = errorCard({ title: "流程与规则读取失败", hint: "工作台服务可能刚重启，请刷新页面。", detail: String(err) });
    return;
  }
  fl.data = d;
  $("#fl-emps").innerHTML = idx.map((e) => `<button class="fl-emp ${e.id === fl.emp ? "on" : ""}" data-emp="${e.id}">${avatar(e.id, "xs")}${esc(e.persona)} · ${TITLE[e.id]}${e.has_draft ? '<i class="dot" title="有未发布的草稿"></i>' : ""}</button>`).join("");
  $("#fl-emps").onclick = (ev) => { const b = ev.target.closest("[data-emp]"); if (b) showFlows(b.dataset.emp); };
  const byId = Object.fromEntries(d.rules.map((r) => [r.rule_id, r]));
  const node = (n, i) => `
    <div class="fl-node ${KIND_CLS[n.kind] || ""} ${fl.node === n.name ? "sel" : ""}" data-node="${esc(n.name)}" tabindex="0" role="button" aria-label="节点 ${esc(n.name)}">
      <div class="fn-h"><span class="fn-i">${i + 1}</span><b>${esc(n.name)}</b><span class="fn-k">${esc(n.kind)}</span></div>
      <div class="fn-d">${esc(n.desc)}</div>
      ${(n.sources || []).length ? `<div class="fn-s">${n.sources.map((s) => `<span>${esc(s)}</span>`).join("")}</div>` : ""}
      ${(n.outputs || []).length ? `<div class="fn-o">产出：${esc(n.outputs.join("、"))}</div>` : ""}
      <div class="fn-r">${n.exec_rules.length ? `<span class="fn-x">执行 ${n.exec_rules.length} 条规则</span>` : ""}${n.dep_rules.length ? `<span>${n.dep_rules.length} 条规则依赖此节点</span>` : ""}</div>
      ${d.rules_are_nodes && n.exec_rules.length ? `<div class="fn-sub">${n.exec_rules.map((id) => `<span data-rule="${id}">${id} ${esc(byId[id].name)}</span>`).join("")}</div>` : ""}
      ${n.stats ? `<div class="fn-st">近 30 天执行 ${n.stats.runs} 次 · 平均 ${fmtMs(n.stats.avg_ms)}${n.stats.failed ? ` · <b class="bad">失败 ${n.stats.failed}</b>` : ""}</div>` : ""}
    </div>`;
  const ruleState = (r) => r.draft.enabled === false && r.published.enabled !== false ? '<span class="st2 hitd">草稿：停用</span>'
    : r.published.enabled === false ? `<span class="st2 notrun" title="${esc(r.published.reason || "")}">已停用</span>`
    : `<span class="st2 ${r.state === "已上线" ? "pass" : "notrun"}">${esc(r.state)}</span>`;
  const hits = (r) => Object.entries(r.hits || {}).filter(([k]) => !["pass", "未命中", "na"].includes(k))
    .map(([k, n]) => `<span class="hchip ${k}">${esc(CODE_TXT[k] || k)} ${n}</span>`).join("");
  const q = fl.q.trim();
  const rows = d.rules.filter((r) => (!fl.node || r.exec === fl.node || r.deps.includes(fl.node))
    && (!q || (r.rule_id + r.name + (r.category || "") + (r.group || "")).includes(q)));
  const nodeChip = (nm) => `<span class="nchip ${fl.node === nm ? "on" : ""}" data-node="${esc(nm)}">${esc(nm)}</span>`;
  const changes = d.draft_changes || [];
  body.innerHTML = `
    <div class="fl-ver">
      <div class="fv-l"><b>生效版本</b><code>${esc(d.effective_version)}</code>
        <span class="muted">代码规则 ${esc(d.code_version)} · 配置已发布 ${d.published_n} 次</span>
        ${changes.length ? `<span class="st2 hitd">草稿有 ${changes.length} 项改动未发布</span>` : '<span class="muted">无未发布草稿</span>'}
        ${d.outdated ? `<span class="st2 old">${d.outdated} 份报告按旧版规则生成</span>` : ""}</div>
      <div class="fv-r">
        <button class="btn primary" data-a="publish" ${changes.length ? "" : "disabled"}>发布草稿</button>
        <button class="btn" data-a="discard" ${changes.length ? "" : "disabled"}>放弃草稿</button>
        <button class="btn" data-a="versions">版本记录</button>
        ${d.flow_params.length ? '<button class="btn" data-a="flowparams">流程参数</button>' : ""}
        <a class="btn" href="/api/flows/${fl.emp}/export" target="_blank">导出 YAML</a>
        <button class="btn" data-a="import">导入 YAML</button>
        ${d.outdated ? `<button class="btn" data-a="rerun">按新版规则批量重审</button>` : ""}
      </div>
    </div>
    <div class="ctr-sec">${esc(d.employee.persona)} · ${esc(d.employee.name)}的流程线 <span>点击节点，下方只看在此执行或依赖此节点的规则</span></div>
    <div class="fl-line">${d.nodes.map(node).join(`<div class="fl-arrow">${svg("arrow")}</div>`)}</div>
    <div class="panel"><h4>与需求方案对照 <span>${esc(d.requirement)}</span></h4>
      <table><thead><tr><th>需求方案步骤</th><th>对应节点</th><th>对照</th><th>说明</th></tr></thead><tbody>
      ${d.plan.map((p) => `<tr><td><b>${esc(p.step)}</b></td><td>${p.nodes.length ? p.nodes.map(nodeChip).join("") : '<span class="muted">—</span>'}</td>
        <td><span class="st2 ${MATCH_CLS[p.match] || ""}">${esc(p.match)}</span></td><td class="muted">${esc(p.note)}</td></tr>`).join("")}</tbody></table></div>
    <div class="panel"><h4>规则 · ${rows.length}/${d.rules.length} 条${fl.node ? ` <span>与「${esc(fl.node)}」相关（执行或依赖）<a href="#" data-a="clearnode">看全部</a></span>` : ""}
        <input class="fl-q" placeholder="搜索编号 / 名称" value="${esc(fl.q)}" aria-label="搜索规则"></h4>
      <table class="fl-rules"><thead><tr><th>编号</th><th>规则</th><th>${d.tiers.length ? "档位" : "类别"}</th><th>执行节点</th><th>依赖节点</th><th>状态</th><th>可配参数</th><th>近期结论</th></tr></thead><tbody>
      ${rows.map((r) => `<tr data-rule="${r.rule_id}" tabindex="0" class="${r.changed ? "chg" : ""}">
        <td><b>${esc(r.rule_id)}</b>${r.changed ? '<i class="dot" title="草稿有改动"></i>' : ""}</td>
        <td>${esc(r.published.name || r.name)}${r.group ? `<div class="sub">${esc(r.group)}</div>` : ""}${r.llm ? ' <span class="st2 auto">模型</span>' : ""}</td>
        <td>${esc(r.published.tier || r.tier || r.category || "")}</td><td>${nodeChip(r.exec)}</td>
        <td>${r.deps.map((x) => (d.nodes.some((n) => n.name === x) ? nodeChip(x) : `<span class="muted">${esc(x)}</span>`)).join("")}</td>
        <td>${ruleState(r)}</td><td>${r.params.length ? `${r.params.length} 项` : r.shared_with ? `与 ${esc(r.shared_with)} 共用` : '<span class="muted">—</span>'}</td>
        <td>${hits(r) || '<span class="muted">—</span>'}</td></tr>`).join("")}
      </tbody></table></div>`;
  body.onclick = (ev) => {
    const sub = ev.target.closest(".fn-sub [data-rule]");
    if (sub) return openRuleEditor(sub.dataset.rule);
    const n = ev.target.closest(".nchip") || (!ev.target.closest("tr[data-rule]") && ev.target.closest(".fl-node"));
    if (n) {
      fl.node = fl.node === n.dataset.node ? null : n.dataset.node;
      return renderFlows(true);
    }
    const tr = ev.target.closest("tr[data-rule]");
    if (tr) return openRuleEditor(tr.dataset.rule);
    const a = ev.target.closest("[data-a]");
    if (!a) return;
    if (a.dataset.a === "clearnode") { ev.preventDefault(); fl.node = null; return renderFlows(true); }
    ({ publish: openPublish, discard: discardDraft, versions: openVersions, import: openImport, rerun: rerunOutdated,
       flowparams: openFlowParams })[a.dataset.a]?.();
  };
  body.onkeydown = (ev) => {
    if (ev.key !== "Enter") return;
    const tr = ev.target.closest("tr[data-rule]");
    if (tr) openRuleEditor(tr.dataset.rule);
    const n = ev.target.closest(".fl-node");
    if (n) { fl.node = fl.node === n.dataset.node ? null : n.dataset.node; renderFlows(true); }
  };
  const qi = $(".fl-q", body);
  qi.oninput = () => { fl.q = qi.value; clearTimeout(qi._t); qi._t = setTimeout(async () => { await renderFlows(true); const x = $(".fl-q"); x.focus(); x.setSelectionRange(x.value.length, x.value.length); }, 250); };
}

function openFlDrawer(html) {
  const dr = $("#fl-drawer");
  dr.innerHTML = html;
  dr.classList.remove("hidden");
  $("#fl-mask").classList.remove("hidden");
  return dr;
}
function closeFlDrawer() {
  $("#fl-drawer").classList.add("hidden");
  $("#fl-mask").classList.add("hidden");
}

function draftBody() {
  const rules = {};
  for (const r of fl.data.rules) if (r.draft && Object.keys(r.draft).length) rules[r.rule_id] = JSON.parse(JSON.stringify(r.draft));
  const flow_params = {};
  for (const p of fl.data.flow_params) if (p.draft !== null && p.draft !== undefined) flow_params[p.path] = p.draft;
  return { rules, flow_params };
}

async function saveDraft(body, note) {
  const r = await fetch(`/api/flows/${fl.emp}/draft`, { method: "PUT", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...body, author: author(), note: note || "" }) });
  const d = await r.json();
  if (!r.ok) { toast(d.detail || "保存失败"); return false; }
  fl.data = d;
  await renderFlows(true);
  return true;
}

function paramInput(p, cur) {
  const v = cur === undefined || cur === null ? "" : cur;
  const hint = `默认 ${esc(fmtVal(p.default))}${p.published !== null && p.published !== undefined ? ` · 当前生效 ${esc(fmtVal(p.published))}` : ""}${p.min !== undefined && p.min !== null ? ` · 范围 ${p.min}–${p.max}` : ""}`;
  const field = p.type === "bool"
    ? `<select name="p:${esc(p.path)}"><option value="">使用默认（${esc(fmtVal(p.default))}）</option><option value="true" ${v === true ? "selected" : ""}>是</option><option value="false" ${v === false ? "selected" : ""}>否</option></select>`
    : p.type === "list"
      ? `<textarea name="p:${esc(p.path)}" rows="3" placeholder="每行一项；留空使用默认">${esc(Array.isArray(v) ? v.join("\n") : "")}</textarea>`
      : `<input name="p:${esc(p.path)}" value="${esc(v)}" placeholder="留空使用默认 ${esc(fmtVal(p.default))}" ${p.type === "int" || p.type === "number" ? 'inputmode="decimal"' : ""}>`;
  return `<label class="pf"><span>${esc(p.label)}${p.unit ? `（${esc(p.unit)}）` : ""}</span>${field}<em>${hint}</em></label>`;
}

function readParam(p, form) {
  const el = form.elements[`p:${p.path}`];
  const raw = el.value.trim();
  if (raw === "") return undefined;
  if (p.type === "bool") return raw === "true";
  if (p.type === "list") return raw.split(/\n|,|，/).map((x) => x.trim()).filter(Boolean);
  return raw;
}

function openRuleEditor(rid) {
  const r = fl.data.rules.find((x) => x.rule_id === rid);
  if (!r) return;
  const cur = Object.keys(r.draft || {}).length ? r.draft : r.published || {};
  const enabled = cur.enabled !== false;
  const dr = openFlDrawer(`
    <div class="dr-h"><div><b>${esc(r.rule_id)}</b>${esc(r.name)}
      <div class="dr-t">${esc(r.category || "")}${r.group ? ` · ${esc(r.group)}` : ""} · 执行节点「${esc(r.exec)}」 · 依赖 ${esc(r.deps.join("、"))}${r.llm ? " · 使用大模型" : ""}</div></div>
      <button class="icon-btn" data-a="close" title="关闭">${svg("x")}</button></div>
    <form class="rcfg">
      <label class="pf"><span>显示名称</span><input name="name" value="${esc(cur.name || "")}" placeholder="${esc(r.name)}"><em>留空使用代码中的名称</em></label>
      <label class="sw"><input type="checkbox" name="enabled" ${enabled ? "checked" : ""}> 启用本条规则</label>
      <label class="pf reason ${enabled ? "hidden" : ""}"><span>停用原因（报告中显示为「未执行」及原因）</span><input name="reason" value="${esc(cur.reason || "")}"></label>
      ${fl.data.tiers.length ? `<label class="pf"><span>档位</span><select name="tier"><option value="">默认（${esc(r.tier)}）</option>${fl.data.tiers.map((t) => `<option ${cur.tier === t ? "selected" : ""}>${esc(t)}</option>`).join("")}</select><em>决定命中后在报告中的排列：一定不通过在前，拿不准在后</em></label>` : ""}
      <label class="pf"><span>核实建议（结论为问题 / 复核时在报告中显示）</span><textarea name="suggest" rows="2" placeholder="如：请核对合同首页与签章页的相对方名称">${esc(cur.suggest || "")}</textarea></label>
      <h5>参数</h5>
      ${r.params.length ? r.params.map((p) => paramInput(p, (cur.params || {})[p.path])).join("")
        : `<p class="muted">${r.shared_with ? `本条与 ${esc(r.shared_with)} 共用参数，请在 ${esc(r.shared_with)} 中修改。` : "本条规则没有可配置参数（判定逻辑在代码中）。"}</p>`}
      <div class="rc-btns"><button class="btn primary" type="submit">保存到草稿</button><button class="btn" type="button" data-a="reset">恢复默认（清除本条配置）</button></div>
      <p class="muted">保存后进入草稿，发布后下一次审查生效；已有报告不会自动重审，会标注「按旧版规则生成」。</p>
    </form>
    ${Object.keys(r.hits || {}).length ? `<h5>近期结论分布（每笔单据最近一次审查）</h5><div class="hchips">${Object.entries(r.hits).map(([k, n]) => `<span class="hchip ${k}">${esc(CODE_TXT[k] || k)} ${n}</span>`).join("")}</div>` : ""}`);
  const form = $("form.rcfg", dr);
  form.enabled.onchange = () => $(".reason", form).classList.toggle("hidden", form.enabled.checked);
  dr.onclick = async (ev) => {
    const a = ev.target.closest("[data-a]");
    if (!a) return;
    if (a.dataset.a === "close") return closeFlDrawer();
    if (a.dataset.a === "reset") {
      const body = draftBody();
      delete body.rules[rid];
      if (await saveDraft(body, `${rid} 恢复默认`)) { toast(`${rid} 已恢复默认（草稿）`); closeFlDrawer(); }
    }
  };
  form.onsubmit = async (ev) => {
    ev.preventDefault();
    const rc = {};
    if (form.name.value.trim()) rc.name = form.name.value.trim();
    if (!form.enabled.checked) { rc.enabled = false; rc.reason = form.reason.value.trim(); }
    if (form.tier && form.tier.value) rc.tier = form.tier.value;
    if (form.suggest.value.trim()) rc.suggest = form.suggest.value.trim();
    const params = {};
    r.params.forEach((p) => { const v = readParam(p, form); if (v !== undefined) params[p.path] = v; });
    if (Object.keys(params).length) rc.params = params;
    const body = draftBody();
    if (Object.keys(rc).length) body.rules[rid] = rc; else delete body.rules[rid];
    if (await saveDraft(body, `编辑 ${rid}`)) { toast(`${rid} 已保存到草稿，发布后生效`); closeFlDrawer(); }
  };
}

function openFlowParams() {
  const ps = fl.data.flow_params;
  const dr = openFlDrawer(`<div class="dr-h"><div><b>流程参数</b><div class="dr-t">作用于整条流程（如严格模式）</div></div><button class="icon-btn" data-a="close">${svg("x")}</button></div>
    <form class="rcfg">${ps.map((p) => paramInput(p, p.draft ?? p.published)).join("")}
      <div class="rc-btns"><button class="btn primary" type="submit">保存到草稿</button></div></form>`);
  dr.onclick = (ev) => { if (ev.target.closest("[data-a=close]")) closeFlDrawer(); };
  $("form", dr).onsubmit = async (ev) => {
    ev.preventDefault();
    const body = draftBody();
    body.flow_params = {};
    ps.forEach((p) => { const v = readParam(p, ev.target); if (v !== undefined) body.flow_params[p.path] = v; });
    if (await saveDraft(body, "编辑流程参数")) { toast("流程参数已保存到草稿"); closeFlDrawer(); }
  };
}

const FIELD_TXT = { enabled: "启用", reason: "停用原因", name: "显示名称", tier: "档位", suggest: "核实建议" };
const changeRow = ([rid, field, a, b]) => `<tr><td><b>${esc(rid)}</b></td><td>${esc(FIELD_TXT[field] || field)}</td>
  <td class="muted">${esc(fmtVal(a === null ? null : a))}</td><td>${esc(fmtVal(b === null ? null : b))}</td></tr>`;

function openPublish() {
  const changes = fl.data.draft_changes || [];
  const dr = openFlDrawer(`<div class="dr-h"><div><b>发布草稿</b><div class="dr-t">${esc(fl.data.employee.persona)} · 当前生效 ${esc(fl.data.effective_version)}</div></div><button class="icon-btn" data-a="close">${svg("x")}</button></div>
    <h5>本次改动 · ${changes.length} 项</h5>
    <table class="chg"><thead><tr><th>规则</th><th>项</th><th>原值</th><th>新值</th></tr></thead><tbody>${changes.map(changeRow).join("")}</tbody></table>
    <form class="rcfg">
      <label class="pf"><span>操作人</span><input name="author" value="${esc(author())}" placeholder="姓名（记入变更记录）" required></label>
      <label class="pf"><span>发布说明</span><textarea name="note" rows="2" placeholder="改了什么、为什么（例如：业务确认违约金上限调整为 20%）" required></textarea></label>
      <div class="rc-btns"><button class="btn primary" type="submit">确认发布</button></div>
      <p class="muted">发布后下一次审查按新配置执行；已有报告不自动重审，会标注「按旧版规则生成」，可一键批量重审。</p>
    </form>`);
  dr.onclick = (ev) => { if (ev.target.closest("[data-a=close]")) closeFlDrawer(); };
  $("form", dr).onsubmit = async (ev) => {
    ev.preventDefault();
    const f = ev.target;
    localStorage.setItem("de.author", f.author.value.trim());
    const r = await fetch(`/api/flows/${fl.emp}/publish`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ author: f.author.value.trim(), note: f.note.value.trim() }) });
    const d = await r.json();
    if (!r.ok) return toast(d.detail || "发布失败");
    await refreshEmployees();
    toast(`已发布第 ${d.n} 版，下一次审查生效`);
    closeFlDrawer();
    await renderFlows(true);
  };
}

async function discardDraft() {
  if (!confirm("放弃全部未发布的草稿改动？")) return;
  await fetch(`/api/flows/${fl.emp}/discard`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ author: author() }) });
  toast("草稿已放弃");
  renderFlows(true);
}

async function openVersions() {
  const dr = openFlDrawer(`<div class="ctr-loading"><div class="typing"><i></i><i></i><i></i></div></div>`);
  const d = await (await fetch(`/api/flows/${fl.emp}/versions`)).json();
  const ACT = { edit: "编辑草稿", publish: "发布", discard: "放弃草稿" };
  dr.innerHTML = `<div class="dr-h"><div><b>版本记录</b><div class="dr-t">${esc(fl.data.employee.persona)} · 当前生效 ${esc(fl.data.effective_version)}</div></div><button class="icon-btn" data-a="close">${svg("x")}</button></div>
    <div class="vers">${d.versions.map((v) => `<div class="ver" data-n="${v.n}">
        <div><b>第 ${v.n} 版</b><span class="muted">${fmtFull(v.created_at)} · ${esc(v.author || "未署名")} · 改动 ${v.changes} 项</span></div>
        <div class="vn">${esc(v.note || "")}</div>
        <div class="vb"><button class="btn sm" data-a="diff">查看改动</button><button class="btn sm" data-a="rollback">回退到此版（进草稿）</button></div>
        <div class="vd"></div></div>`).join("") || '<p class="muted">还没有发布过配置，当前按代码默认规则执行。</p>'}
      ${d.versions.length ? `<div class="ver"><div><b>代码默认</b><span class="muted">不叠加任何配置</span></div><div class="vb"><button class="btn sm" data-a="rollback0">恢复代码默认（进草稿）</button></div></div>` : ""}</div>
    <h5>变更记录</h5>
    <table class="chg"><tbody>${d.log.map((x) => `<tr><td class="muted">${fmtFull(x.at)}</td><td>${esc(x.author || "")}</td><td>${esc(ACT[x.action] || x.action)}</td>
      <td>${x.rule_id ? `<b>${esc(x.rule_id)}</b> ${esc(FIELD_TXT[x.field] || x.field || "")}：${esc(fmtVal(x.old ? JSON.parse(x.old) : null))} → ${esc(fmtVal(x.new ? JSON.parse(x.new) : null))}` : esc(x.note || "")}</td></tr>`).join("")}</tbody></table>`;
  dr.onclick = async (ev) => {
    const a = ev.target.closest("[data-a]");
    if (!a) return;
    if (a.dataset.a === "close") return closeFlDrawer();
    if (a.dataset.a === "rollback0") {
      await fetch(`/api/flows/${fl.emp}/rollback/0`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ author: author() }) });
      toast("已把草稿恢复为代码默认，发布后生效"); closeFlDrawer(); return renderFlows(true);
    }
    const box = a.closest(".ver"), n = box.dataset.n;
    if (a.dataset.a === "diff") {
      const v = await (await fetch(`/api/flows/${fl.emp}/versions/${n}`)).json();
      $(".vd", box).innerHTML = `<table class="chg"><thead><tr><th>规则</th><th>项</th><th>原值</th><th>新值</th></tr></thead><tbody>${v.diff.map(changeRow).join("") || '<tr><td colspan="4" class="muted">无改动</td></tr>'}</tbody></table>`;
    } else if (a.dataset.a === "rollback") {
      await fetch(`/api/flows/${fl.emp}/rollback/${n}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ author: author() }) });
      toast(`草稿已设为第 ${n} 版内容，发布后生效`); closeFlDrawer(); renderFlows(true);
    }
  };
}

function openImport() {
  const dr = openFlDrawer(`<div class="dr-h"><div><b>导入 YAML</b><div class="dr-t">粘贴「导出 YAML」得到的内容，导入后进入草稿，需发布才生效</div></div><button class="icon-btn" data-a="close">${svg("x")}</button></div>
    <form class="rcfg"><textarea name="y" rows="16" placeholder="employee: ${esc(fl.emp)}&#10;rules:&#10;  ..."></textarea>
      <div class="rc-btns"><button class="btn primary" type="submit">导入到草稿</button></div></form>`);
  dr.onclick = (ev) => { if (ev.target.closest("[data-a=close]")) closeFlDrawer(); };
  $("form", dr).onsubmit = async (ev) => {
    ev.preventDefault();
    const r = await fetch(`/api/flows/${fl.emp}/import`, { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ yaml_text: ev.target.y.value, author: author() }) });
    const d = await r.json();
    if (!r.ok) return toast(d.detail || "导入失败");
    fl.data = d;
    toast("已导入到草稿"); closeFlDrawer(); renderFlows(true);
  };
}

async function rerunOutdated() {
  const d = await (await fetch(`/api/flows/${fl.emp}/outdated`)).json();
  const ids = d.rows.filter((r) => r.runnable).map((r) => r.request_id);
  if (!ids.length) return toast("没有可重审的单据（待办只读或当前账号不可见的不重审）");
  if (!confirm(`按新版规则（${d.current}）重审 ${Math.min(ids.length, 20)} 笔单据${ids.length > 20 ? `（共 ${ids.length} 笔，每批最多 20 笔）` : ""}？`)) return;
  const r = await fetch(`/api/${fl.emp}/batch`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ request_ids: ids.slice(0, 20) }) });
  const b = await r.json();
  if (!r.ok) return toast(b.detail || "批量重审发起失败");
  toast(`已发起 ${b.total} 笔重审，可在对话的历史报告或资料中心查看结果`);
  setTimeout(() => renderFlows(true), 1500);
}

/* ============ 资料中心 · 全流程演示 ============ */
const TRIG_TEXT = { auto: "自动审查", batch: "批量审查", web: "人工发起", cli: "命令行" };
const ctr = { emp: "", rows: [], overview: null };
const fmtBytes = (n) => (n >= 1 << 30 ? `${(n / (1 << 30)).toFixed(2)} GB` : n >= 1 << 20 ? `${(n / (1 << 20)).toFixed(1)} MB` : `${Math.round((n || 0) / 1024)} KB`);
const fmtFull = (ts) => (ts ? new Date(ts * 1000).toLocaleString("zh-CN", { hour12: false }) : "—");
const sum = (o) => Object.values(o || {}).reduce((a, b) => a + (b || 0), 0);

function gotoChat(id) {
  // 回到已打开的对话时保留对话内容；换员工才新开
  if (state.current === id) return showView("#view-chat");
  openChat(id, true);
}

function showView(id) {
  ["#view-welcome", "#view-chat", "#view-center", "#view-flows"].forEach((s) => $(s).classList.toggle("hidden", s !== id));
  const tab = { "#view-center": "资料中心", "#view-flows": "流程与规则" }[id] || "工作台";
  document.querySelectorAll("#rail .rail-item[title]").forEach((r) => r.classList.toggle("active", r.title === tab));
}

async function showCenter(empId = "") {
  ctr.back = state.current;
  ctr.emp = empId || "";
  showView("#view-center");
  $("#ctr-emp").innerHTML = `<option value="">全部数字员工</option>` + state.employees.map((e) =>
    `<option value="${e.id}" ${e.id === ctr.emp ? "selected" : ""}>${esc(e.persona)} · ${TITLE[e.id]}</option>`).join("");
  $("#ctr-back").textContent = ctr.back ? `返回与${emp(ctr.back).persona}的对话` : "返回工作台";
  closeDrawer();
  await renderCenter();
}

async function renderCenter() {
  const body = $("#ctr-body");
  body.innerHTML = `<div class="ctr-loading"><div class="typing"><i></i><i></i><i></i></div></div>`;
  let ov, rq;
  try {
    [ov, rq] = await Promise.all([
      fetch("/api/center/overview").then((r) => r.json()),
      fetch("/api/center/requests?limit=500").then((r) => r.json()),
    ]);
  } catch (err) {
    body.innerHTML = errorCard({ title: "资料中心数据读取失败", hint: "确认工作台与资料中心（python -m core.resource.api）都已启动。", detail: String(err) });
    return;
  }
  ctr.overview = ov;
  const all = rq.rows || [];
  ctr.rows = ctr.emp ? all.filter((r) => r.employee === ctr.emp) : all;
  const st = ov.stats || {}, col = ov.collect || {}, tk = ov.tasks || {};
  const names = ov.source_names || {};
  const snaps = st.snapshots || {}, occ = st.occurrences || {}, bl = st.blobs || {}, pr = st.parse || {};
  const arcs = st.archives || {}, items = st.archive_items || {};
  const locked = all.filter((r) => r.pending_locked).length, stale = all.filter((r) => r.stale).length;
  const scope = ctr.emp ? `${emp(ctr.emp).persona} · ${TITLE[ctr.emp]}` : "全部数字员工";
  const srcOn = Object.entries(col.sources || {}).filter(([, v]) => v.enabled).map(([k]) => names[k] || k);
  const stage = (n, icon, title, big, unit, lines, note) => `
    <div class="stg"><div class="stg-h"><span class="stg-n">${n}</span>${svg(icon)}<b>${title}</b></div>
      <div class="stg-big">${big}<small>${unit}</small></div>
      <ul>${lines.filter(Boolean).map((l) => `<li>${l}</li>`).join("")}</ul>
      <div class="stg-note">${note}</div></div>`;
  const flow = [
    stage(1, "inbox", "采集登记", sum(snaps), "笔单据", [
      `来源：${esc(srcOn.join("、") || "未开启")}`, `已运行 ${st.rounds ? st.rounds.n : 0} 轮 · 最近 ${fmtTime((st.rounds || {}).last_at) || "—"}`,
      locked ? `待办只读 ${locked} 笔（只登记单号与标题）` : "", stale ? `当前账号不可见 ${stale} 笔（不再自动审查）` : ""],
      `每 ${col.interval_minutes ?? "—"} 分钟读取一次待审列表（${esc(col.active_hours || "全天")}），只读不改客户系统`),
    stage(2, "doc", "取单 · 原件签名", bl.n ?? 0, "份原件", [
      `资料就绪 ${snaps.ready || 0} 笔，表单快照逐笔留存`, `附件出现 ${occ.n ?? 0} 次 → 去重后 ${bl.n ?? 0} 份（${fmtBytes(bl.bytes)}）`,
      occ.extracted ? `压缩包内解出 ${occ.extracted} 份` : ""],
      "SHA-256 内容签名，同一文件只存一份，版本未变不重复下载"),
    stage(3, "search", "解析 · OCR", pr.n ?? 0, "份解析结果", [
      `共 ${pr.pages ?? 0} 页，其中扫描页 OCR ${pr.ocr_pages ?? 0} 页`, `当前引擎：${esc(st.ocr_engine || "—")}`],
      "文字层直接读取，只有扫描页 / 图片走 OCR；结果按引擎入库、审查直接复用"),
    stage(4, "spark", "自动审查", sum(tk.by_trigger), "次审查", [
      Object.entries(tk.by_trigger || {}).map(([k, n]) => `${TRIG_TEXT[k] || k} ${n}`).join(" · "),
      tk.superseded ? `材料变化后重审，旧报告已取代 ${tk.superseded} 份` : ""],
      "资料就绪且未审查 / 材料指纹变化时自动发起，结果推送到任务台"),
    stage(5, "clock", "执行档案", sum(arcs), "份档案", [
      `接口报文 ${items.api || 0} · 模型调用 ${items.llm || 0} · 原文校验 ${items.check || 0}`, `证据截图 ${st.shots || 0} 张`],
      "每次执行的版本、表单快照、接口报文（脱敏）、模型输入输出与证据截图全程留档"),
  ].join("");
  const srcRows = Object.entries(col.sources || {}).map(([k, v]) => `
    <tr><td><b>${esc(names[k] || k)}</b></td><td>${v.enabled ? '<span class="st2 pass">开启</span>' : '<span class="st2 notrun">未开启</span>'}</td>
      <td class="muted">${esc((v.lists || []).join("、") || "—")}</td><td>${fmtTime(v.last_round_at) || "—"}</td>
      <td>${v.running ? '<span class="st2 unread">采集中</span>' : v.last_error ? `<span class="st2 hit" title="${esc(v.last_error)}">上轮出错</span>` : v.enabled ? `下轮 ${fmtTime(v.next_round_at) || "—"}` : "—"}</td></tr>`).join("");
  const rounds = (col.rounds || []).slice(0, 6).map((r) => `
    <tr><td>${esc(names[r.source] || r.source)}</td><td>${fmtFull(r.started_at)}</td><td>${r.listed ?? 0}</td><td>${r.queued ?? 0}</td>
      <td>${r.error ? `<span class="bad" title="${esc(r.error)}">${esc(r.error.slice(0, 30))}</span>` : r.finished_at ? "完成" : "进行中"}</td></tr>`).join("");
  const reqRows = ctr.rows.map((r, i) => `
    <tr class="${r.stale ? "stale" : ""}" data-i="${i}" tabindex="0">
      <td><b>${esc(r.request_id)}</b><div class="sub" title="${esc(r.title || "")}">${esc(r.title || "")}</div></td>
      <td>${esc(emp(r.employee).persona || r.employee)}</td>
      <td class="muted">${esc(names[r.source] || r.source)} · ${esc(r.list_name || "")}</td>
      <td>${snapPill(r)}${r.material_changed ? ' <span class="st2 hitd">材料已变化</span>' : ""}</td>
      <td>${latestPill(r)}</td><td class="go">${svg("arrow")}</td></tr>`).join("");
  body.innerHTML = `
    ${ov.error || rq.error ? `<div class="err">${esc(ov.error || rq.error)}</div>` : ""}
    <div class="ctr-sec">资料中心总览 <span>五个环节的实时数字（全部数字员工）</span></div>
    <div class="flow">${flow}</div>
    <div class="ctr-grid">
      <div class="panel"><h4>来源系统</h4><table><thead><tr><th>系统</th><th>采集</th><th>列表</th><th>上一轮</th><th>状态</th></tr></thead><tbody>${srcRows}</tbody></table></div>
      <div class="panel"><h4>最近采集轮次</h4><table><thead><tr><th>系统</th><th>开始</th><th>列出</th><th>同步</th><th>结果</th></tr></thead><tbody>${rounds || '<tr><td colspan="5" class="muted">暂无</td></tr>'}</tbody></table></div>
    </div>
    <div class="panel"><h4>单据快照 · ${esc(scope)} <span>${ctr.rows.length} 笔 · 点击任一单据，逐步查看它在资料中心的全流程</span></h4>
      <table class="reqs"><thead><tr><th>单号 / 标题</th><th>员工</th><th>来源 · 列表</th><th>资料状态</th><th>最近审查</th><th></th></tr></thead>
      <tbody>${reqRows || '<tr><td colspan="6" class="muted">暂无单据（点右上角「立即采集」）</td></tr>'}</tbody></table></div>`;
  const tb = $(".reqs tbody", body);
  const open = (ev) => { const tr = ev.target.closest("tr[data-i]"); if (tr) openDrawer(ctr.rows[+tr.dataset.i]); };
  tb.onclick = open;
  tb.onkeydown = (ev) => { if (ev.key === "Enter") open(ev); };
}

function closeDrawer() {
  $("#ctr-drawer").classList.add("hidden");
  $("#ctr-mask").classList.add("hidden");
}

async function openDrawer(row) {
  const dr = $("#ctr-drawer");
  dr.classList.remove("hidden");
  $("#ctr-mask").classList.remove("hidden");
  dr.innerHTML = `<div class="ctr-loading"><div class="typing"><i></i><i></i><i></i></div></div>`;
  const r = await fetch(`/api/center/requests/${encodeURIComponent(row.source)}/${encodeURIComponent(row.request_id)}`);
  const d = await r.json();
  if (!r.ok) { dr.innerHTML = `<div class="dr-h"><b>${esc(row.request_id)}</b><button class="icon-btn" data-a="close">${svg("x")}</button></div><div class="err">${esc(d.detail || "读取失败")}</div>`; dr.querySelector("[data-a=close]").onclick = closeDrawer; return; }
  const s = d.snapshot, files = s.files || [], tasks = d.tasks || [];
  const locked = s.list_scope === "pending" && !s.open_detail;
  const tops = files.filter((f) => !f.parent_sig);
  const ocrPages = files.reduce((n, f) => n + ((f.parsed || {}).ocr_pages || 0), 0);
  const parsedOk = files.filter((f) => (f.parsed || {}).status === "ok").length;
  const step = (n, title, ok, html) => `<li class="${ok ? "ok" : "skip"}"><div class="sn">${ok ? svg("check") : n}</div><div class="sb"><h5>${title}</h5>${html}</div></li>`;
  const fileRows = files.map((f) => {
    const p = f.parsed || {};
    return `<tr><td title="${esc(f.filename)}">${f.parent_sig ? '<span class="inzip">压缩包内</span>' : ""}${esc((f.filename || "").split("/").pop())}</td>
      <td class="mono" title="${esc(f.content_sig)}">${esc(f.content_sig.slice(0, 12))}</td><td>${f.size_bytes != null ? fmtBytes(f.size_bytes) : "—"}</td>
      <td>${p.status === "ok" && /\.(zip|rar|7z)$/i.test(f.filename || "") ? '<span class="st2 pass">已解压</span>'
        : p.status === "ok" ? `<span class="st2 pass">${p.pages ?? 0} 页${p.ocr_pages ? ` · OCR ${p.ocr_pages}` : ""}</span>` : p.status ? `<span class="st2 hit" title="${esc(p.error || "")}">${esc(p.status)}</span>` : '<span class="st2 notrun">未解析</span>'}</td></tr>`;
  }).join("");
  const fields = (s.fields || []).filter((f) => (f.display || f.value) && String(f.display || f.value).length < 200);
  const arcIds = new Set((s.archives || []).map((a) => a.task_id));
  const taskRows = tasks.map((t) => `
    <div class="dtask ${t.superseded_by ? "old" : ""}" data-task="${t.task_id}" data-emp="${t.employee}">
      <div><b>${fmtFull(t.created_at)}</b><span class="st2 auto">${esc(TRIG_TEXT[t.trigger_by] || t.trigger_by || "人工发起")}</span>${t.superseded_by ? '<span class="st2 old">已被新版本取代</span>' : ""}</div>
      <div>${latestPill({ latest: { ...t, trigger_by: "" } })}<span class="mono" title="材料指纹">${esc((t.material_fp || "").slice(0, 12))}</span></div>
      <div class="acts">${t.status === "done" ? '<button class="btn sm" data-a="report">查看报告</button>' : ""}${arcIds.has(t.task_id)
        ? '<button class="btn sm primary" data-a="archive">执行档案</button>' : '<span class="muted">资料中心上线前的审查，无执行档案</span>'}</div>
    </div>`).join("");
  dr.innerHTML = `
    <div class="dr-h"><div><b>${esc(s.request_id)}</b><span class="muted">${esc(d.source_name)} · ${esc(emp(s.employee).persona || s.employee || "")}</span>
      <div class="dr-t">${esc(s.title || "")}</div></div><button class="icon-btn" data-a="close" title="关闭">${svg("x")}</button></div>
    <ol class="steps">
      ${step(1, "采集登记", true, `<p>列表「${esc(s.list_name || "人工发起时当场同步")}」${s.list_scope === "pending" ? "（待办）" : ""} · 首次发现 ${fmtFull(s.first_seen_at)}${s.listed_at ? ` · 最近列出 ${fmtFull(s.listed_at)}` : ""}</p>
        ${row.stale ? '<p class="warn">所属列表最近一次读取时已没有该单据（换账号后不可见或已离开待办），不再自动审查。</p>' : ""}`)}
      ${step(2, "取单 · 表单快照", !locked && !!s.synced_at, locked ? '<p class="warn">待办只读：读取详情不改变单据状态验证通过前，只登记单号与标题，不打开详情、不下载附件。</p>'
        : `<p>${esc(s.workflow_name || "")} · ${(s.fields || []).length} 个字段 · 同步于 ${fmtFull(s.synced_at)}</p>
          <p>材料指纹 <span class="mono" title="${esc(s.material_fp || "")}">${esc((s.material_fp || "—").slice(0, 16))}</span>（表单关键字段 + 附件签名，变化即触发重审）</p>
          ${fields.length ? `<details class="fold"><summary>表单字段（已脱敏）${svg("chev", "chev")}</summary><table>${fields.slice(0, 60).map((f) => `<tr><td class="muted">${esc(f.label || f.field || "")}</td><td>${esc(String(f.display || f.value))}</td></tr>`).join("")}</table></details>` : ""}
          <div id="dr-page"></div>`)}
      ${step(3, "原件下载 · 内容签名", tops.length > 0, tops.length ? `<p>${tops.length} 份附件${files.length > tops.length ? `，压缩包内另解出 ${files.length - tops.length} 份` : ""}；按 SHA-256 内容签名入库，同一文件只存一份。</p>` : "<p>暂无附件</p>")}
      ${step(4, "解析 · OCR 入库", parsedOk > 0, files.length ? `<p>已解析 ${parsedOk}/${files.length} 份，扫描页 OCR 共 ${ocrPages} 页；审查时直接复用，不重复识别。</p>
        <table class="files"><thead><tr><th>文件</th><th>签名</th><th>大小</th><th>解析</th></tr></thead><tbody>${fileRows}</tbody></table>` : "<p>—</p>")}
      ${step(5, "审查", tasks.length > 0, tasks.length ? `<p>共 ${tasks.length} 次审查（最新在上）；材料变化后的重审会把旧报告标为已取代。</p>${taskRows}` : `<p>${locked ? "待办只读，不发起审查。" : "尚未审查。"}</p>`)}
      ${step(6, "执行档案", (s.archives || []).length > 0, `<p>${(s.archives || []).length} 份执行档案：点上方「执行档案」查看接口报文、模型调用、原文校验、证据截图与完整时间线。</p><div id="dr-arc"></div>`)}
    </ol>`;
  const latestArc = (s.archives || [])[0];
  if (latestArc) {
    fetchArchive(latestArc.task_id).then((a) => {
      const items = a.items || [];
      const pages = items.filter((i) => i.kind === "page");
      const box = $("#dr-page", dr);
      if (!box) return;
      box.innerHTML = `<p class="dr-sub">最近一次审查（${fmtFull(latestArc.started_at)}）在客户平台上的操作：</p>
        ${pages.map((i) => pageCard(i.body || {}, a.pages)).join("") || '<p class="muted">该次审查没有平台页面截图（资料中心上线前的审查或本地事项）。</p>'}
        <details class="fold"><summary>平台操作步骤 · ${items.filter((i) => i.kind === "api").length} 次接口调用${svg("chev", "chev")}</summary><div class="ops">${stepsHtml(items, a.pages)}</div></details>`;
    }).catch(() => {});
  }
  dr.onclick = async (ev) => {
    const b = ev.target.closest("[data-a]");
    if (!b) return;
    if (b.dataset.a === "close") return closeDrawer();
    const t = b.closest(".dtask");
    if (b.dataset.a === "report") {
      closeDrawer();
      gotoChat(t.dataset.emp);
      return openReport(t.dataset.task, s.request_id);
    }
    if (b.dataset.a === "archive") {
      const box = $("#dr-arc", dr);
      box.innerHTML = `<div class="typing"><i></i><i></i><i></i></div>`;
      try { box.innerHTML = archiveHtml(await fetchArchive(t.dataset.task), t.dataset.task); } catch (err) { box.innerHTML = `<div class="err">${esc(err.message)}</div>`; }
      box.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  };
}

async function centerCollect() {
  const ov = ctr.overview || {};
  const empSrc = ctr.emp ? emp(ctr.emp).sources || [] : null;
  const srcs = Object.entries((ov.collect || {}).sources || {}).filter(([k, v]) => v.enabled && (!empSrc || empSrc.includes(k))).map(([k]) => k);
  if (!srcs.length) return toast("没有开启采集的来源");
  const btn = $("#ctr-collect");
  btn.disabled = true;
  btn.textContent = "采集中…";
  const since = Date.now() / 1000 - 1;
  await Promise.all(srcs.map((s) => fetch(`/api/collect/run?source=${encodeURIComponent(s)}`, { method: "POST" }).catch(() => null)));
  for (let i = 0; i < 60; i++) {
    await new Promise((r) => setTimeout(r, 2000));
    const st = await fetch("/api/collect/status").then((r) => (r.ok ? r.json() : null)).catch(() => null);
    if (st && srcs.every((s) => (st.rounds || []).some((x) => x.source === s && x.started_at >= since && x.finished_at))
        && !((st.queue || {}).queued || (st.queue || {}).running)) break;
  }
  btn.disabled = false;
  btn.textContent = "立即采集";
  toast("采集完成，数据已刷新");
  renderCenter();
}

function bindCenter() {
  $("#ctr-emp").onchange = (ev) => { ctr.emp = ev.target.value; closeDrawer(); renderCenter(); };
  $("#ctr-refresh").onclick = () => renderCenter();
  $("#ctr-collect").onclick = centerCollect;
  $("#ctr-back").onclick = () => (ctr.back ? gotoChat(ctr.back) : showWelcome());
  $("#ctr-mask").onclick = closeDrawer;
  $("#fl-mask").onclick = closeFlDrawer;
  document.addEventListener("keydown", (ev) => { if (ev.key === "Escape") { closeDrawer(); closeFlDrawer(); closeCompare(); } });
  $("#btn-center").onclick = () => showCenter();
}

init();
