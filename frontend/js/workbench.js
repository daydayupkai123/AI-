'use strict';

const WORKBENCHES = {
  meeting: {
    route: 'meetings', employee: 'meeting', title: '三会智能审查',
    columns: ['任务编号', '申请事项', '事项类型', '会议类型', '申请人', '任务状态', '任务创建时间', '操作'],
    filters: { typeKey: 'meeting_type', typeLabel: '会议类型', typePlaceholder: '全部会议类型' },
  },
  procurement: {
    route: 'procurement', employee: 'procurement', title: '采购审批',
    columns: ['任务编号', '采购事项', '采购方式', '申请人', '任务状态', '任务创建时间', '操作'],
    filters: { typeKey: 'category', typeLabel: '采购方式', typePlaceholder: '全部采购方式' },
  },
  contract: {
    route: 'contracts', employee: 'contract', title: '合同审核',
    columns: ['任务编号', '合同事项', '业务类型', '申请人', '任务状态', '任务创建时间', '操作'],
    filters: { typeKey: 'category', typeLabel: '业务类型', typePlaceholder: '全部业务类型' },
  },
  reimburse: {
    route: 'tasks', employee: 'reimburse', title: '财务报销初审',
    columns: ['任务编号', '报销事项', '单据类型', '申请人', '任务状态', '任务创建时间', '操作'],
    filters: { typeKey: 'category', typeLabel: '单据类型', typePlaceholder: '全部单据类型' },
  },
};

const RESULT_STATS = [
  ['初审通过', 'check', 'pass-stat'],
  ['风险提示', 'alert', 'risk-stat'],
  ['无法校验', 'info', 'unverified-stat'],
  ['建议驳回', 'alert', 'risk-stat'],
];
const REVIEW_STATUSES = ['待复核', '确认问题', '误报', '已忽略'];
const TASK_STATUSES = ['待执行', '执行中', '已完成', '失败'];
const PAGE_SIZES = [5, 10, 20, 50];

const wbState = {
  cache: {},
  detail: null,
  filters: {},
  page: {},
  pageSize: {},
  detailTab: 'results',
  pollTimer: null,
  collecting: false,
  collectLog: '',
  resultFilter: '全部',
};

// 详情渲染委托 detail-views.js（对齐最新产品原型）

function wbKey(employee) { return employee; }

function wbFilters(employee) {
  if (!wbState.filters[employee]) {
    wbState.filters[employee] = { query: '', type: '', status: '', dateStart: '', dateEnd: '' };
  }
  return wbState.filters[employee];
}

function wbHead(cfg, title, description = '', status = '', breadcrumb = title) {
  const group = '审核工作台（一期）';
  const parent = title === cfg.title ? '' : `<a href="#${cfg.route}">${cfg.title}</a>${icon('chevron', 'small')}`;
  return `<div class="breadcrumbs"><span>${group}</span>${icon('chevron', 'small')}${parent}<strong>${safe(breadcrumb)}</strong></div>
    <div class="page-head"><div class="ui-page-title"><div class="page-title-line"><h1>${safe(title)}</h1>${status ? statusTag(status) : ''}</div>
    ${description ? `<p>${safe(description)}</p>` : ''}</div></div>`;
}

function auditTaskStatus(status, reason) {
  if (status !== '失败') return statusTag(status);
  return `<span class="task-failure-status" title="${safe(reason || '任务执行失败')}" tabindex="0">${statusTag(status)}</span>`;
}

function auditTaskActions(href, id, status) {
  return `<div class="audit-task-actions"><a class="text-link" href="${href}">详情</a>
    ${status === '失败' ? textButton('重试', 'wb-retry', id) : ''}</div>`;
}

function hintStat(label, count, glyph, tone) {
  return `<div class="hint-stat ${tone}"><span class="metric-icon">${icon(glyph)}</span><strong>${count}</strong><span>${safe(label)}</span></div>`;
}

async function loadWorkbench(employee, force = false) {
  if (!force && wbState.cache[employee] && Date.now() - wbState.cache[employee].at < 5000) {
    return wbState.cache[employee].data;
  }
  const data = await WorkAPI.list(employee);
  wbState.cache[employee] = { at: Date.now(), data };
  return data;
}

function filteredRows(cfg, data) {
  const f = wbFilters(cfg.employee);
  const q = f.query.trim().toLowerCase();
  return (data.rows || []).filter(row => {
    const hay = `${row.id} ${row.request_id} ${row.title}`.toLowerCase();
    const typeVal = row[cfg.filters.typeKey] || '';
    const day = fmtTime(row.created_at).slice(0, 10);
    return (!q || hay.includes(q))
      && (!f.type || f.type === typeVal)
      && (!f.status || f.status === row.status)
      && (!f.dateStart || day >= f.dateStart)
      && (!f.dateEnd || day <= f.dateEnd);
  });
}

function metricsHtml(data) {
  const m = data.metrics || {};
  const items = [
    ['任务总数', m.total || 0, 'list', ''],
    ['待执行', m.pending || 0, 'clock', 'warning'],
    ['执行中', m.running || 0, 'refresh', ''],
    ['已完成', m.done || 0, 'check', 'success'],
  ];
  return items.map(([label, count, glyph, tone]) =>
    `<section class="ui-card"><div class="metric-head">${label}<span class="metric-icon ${tone}">${icon(glyph)}</span></div><div class="metric-value">${count}</div></section>`).join('');
}

function fmtHours(spec) {
  if (!spec) return '—';
  if (typeof spec === 'string') return spec;
  if (Array.isArray(spec) && spec.length >= 2) return `${spec[0]}:00-${spec[1]}:00`;
  return String(spec);
}

function collectSummary(c) {
  const lr = c.last_round;
  if (!c.reachable) return `资料中心不可达${c.error ? `：${c.error}` : ''}`;
  if (c.running || wbState.collecting) return '本轮采集进行中…';
  if (c.last_error) return `上一轮异常：${c.last_error}`;
  if (!lr) return '尚无采集轮次';
  const when = lr.finished_at || lr.started_at;
  return `上一轮 ${fmtTime(when)}：列出 ${lr.listed ?? 0}，入队 ${lr.queued ?? 0}`
    + (lr.failed ? `，失败 ${lr.failed}` : '')
    + (lr.error ? `（${lr.error}）` : '');
}

function collectBar(cfg, data) {
  const c = data.collect || {};
  const busy = !!(c.running || wbState.collecting);
  const hours = fmtHours(c.active_hours);
  return `<div class="meeting-collection" id="wb-collect-bar" data-source="${safe(c.source || '')}">
    <div class="meeting-collection-meta">
      <span>采集：${c.enabled ? `每 ${c.interval_minutes || '—'} 分钟一轮（${hours}）` : '未启用自动采集'}${c.active_now === false ? ' · 当前非采集时段' : ''}</span>
      <span>资料源：${safe(c.source || '—')}</span>
      <span>队列完成 ${c.queue_done ?? '—'}</span>
      <span>${c.auto_review ? '资料就绪后自动审查' : '资料就绪后需人工发起'}</span>
      <span id="wb-collect-summary" class="collect-summary">${safe(collectSummary(c))}</span>
    </div>
    <div class="meeting-collection-actions">
      ${button(busy ? '采集中…' : '立即采集', 'wb-collect', { value: cfg.employee, style: 'primary', disabled: busy })}
      ${button('刷新', 'wb-refresh', { value: cfg.employee, glyph: 'refresh' })}
    </div>
    <div id="wb-collect-progress" class="collect-progress" ${wbState.collectLog ? '' : 'hidden'}>${wbState.collectLog || ''}</div>
  </div>`;
}

function setCollectProgress(html) {
  wbState.collectLog = html || '';
  const el = document.getElementById('wb-collect-progress');
  if (!el) return;
  el.hidden = !html;
  el.innerHTML = html || '';
}

function pagination(employee, total, page, pageSize) {
  const maxPage = Math.max(1, Math.ceil(total / pageSize));
  page = Math.max(1, Math.min(page, maxPage));
  wbState.page[employee] = page;
  return `<nav class="table-footer pagination meeting-pagination" aria-label="分页">
    <span>共 ${total} 条</span>
    <select class="ui-input" data-wb-pagesize="${employee}" aria-label="每页条数">
      ${PAGE_SIZES.map(s => `<option value="${s}"${s === pageSize ? ' selected' : ''}>${s} 条/页</option>`).join('')}
    </select>
    <button type="button" class="ui-btn" data-action="wb-page" data-employee="${employee}" data-value="${page - 1}" ${page === 1 ? 'disabled' : ''}>‹</button>
    ${Array.from({ length: maxPage }, (_, i) => {
      const p = i + 1;
      return `<button type="button" class="ui-btn${p === page ? ' selected' : ''}" data-action="wb-page" data-employee="${employee}" data-value="${p}"${p === page ? ' aria-current="page"' : ''}>${p}</button>`;
    }).join('')}
    <button type="button" class="ui-btn" data-action="wb-page" data-employee="${employee}" data-value="${page + 1}" ${page === maxPage ? 'disabled' : ''}>›</button>
  </nav>`;
}

function listRowsHtml(cfg, rows) {
  const pageSize = wbState.pageSize[cfg.employee] || 10;
  const page = wbState.page[cfg.employee] || 1;
  const maxPage = Math.max(1, Math.ceil(rows.length / pageSize));
  const cur = Math.max(1, Math.min(page, maxPage));
  const slice = rows.slice((cur - 1) * pageSize, cur * pageSize);
  const body = slice.map(row => {
    const cells = [`<td class="primary-cell"><a class="text-link mono" href="#${cfg.route}/${row.id}">${safe(row.id)}</a></td>`,
      `<td>${safe(row.title || '—')}</td>`];
    if (cfg.employee === 'meeting') {
      cells.push(`<td>${safe(row.category || '—')}</td>`, `<td>${row.meeting_type ? tag(row.meeting_type) : '—'}</td>`);
    } else {
      cells.push(`<td>${safe(row.category || '—')}</td>`);
    }
    cells.push(`<td>${safe(row.applicant || '—')}</td>`,
      `<td>${auditTaskStatus(row.status, row.reason)}</td>`,
      `<td class="mono meeting-nowrap">${fmtTime(row.created_at)}</td>`,
      `<td>${auditTaskActions(`#${cfg.route}/${row.id}`, row.id, row.status)}</td>`);
    return `<tr>${cells.join('')}</tr>`;
  });
  return table(cfg.columns, body) + pagination(cfg.employee, rows.length, cur, pageSize);
}

function filterOptions(rows, key) {
  return [...new Set(rows.map(r => r[key]).filter(Boolean))];
}

function listHtml(cfg, data) {
  const f = wbFilters(cfg.employee);
  const rows = filteredRows(cfg, data);
  const typeOpts = filterOptions(data.rows || [], cfg.filters.typeKey);
  return `${wbHead(cfg, cfg.title)}
    <div id="wb-metrics" class="dashboard-grid meeting-metrics">${metricsHtml(data)}</div>
    ${collectBar(cfg, data)}
    <section class="ui-card table-card task-records">
      <form id="wb-filters" class="toolbar task-filters" data-employee="${cfg.employee}">
        <label class="search">${icon('search', 'small')}<input type="search" class="ui-input" name="query" placeholder="搜索任务编号、单据编号或标题" value="${safe(f.query)}"></label>
        <select class="ui-input" name="type" aria-label="${cfg.filters.typeLabel}">
          <option value="">${cfg.filters.typePlaceholder}</option>
          ${typeOpts.map(o => `<option value="${safe(o)}"${f.type === o ? ' selected' : ''}>${safe(o)}</option>`).join('')}
        </select>
        <select class="ui-input" name="status" aria-label="任务状态">
          <option value="">全部任务状态</option>
          ${TASK_STATUSES.map(o => `<option value="${safe(o)}"${f.status === o ? ' selected' : ''}>${safe(o)}</option>`).join('')}
        </select>
        <input class="ui-input" type="date" name="dateStart" aria-label="开始日期" value="${safe(f.dateStart)}">
        <input class="ui-input" type="date" name="dateEnd" aria-label="结束日期" value="${safe(f.dateEnd)}">
        <button type="submit" class="ui-btn ui-btn-primary">查询</button>
        ${button('重置', 'wb-reset', { value: cfg.employee })}
      </form>
      <div id="wb-list-rows">${listRowsHtml(cfg, rows)}</div>
    </section>`;
}

function detailSubtitle(detail) {
  const elapsed = detail.started_at && detail.finished_at
    ? fmtDuration((detail.finished_at - detail.started_at) * (detail.finished_at < 1e12 ? 1000 : 1))
    : detail.status === '待执行' ? '—' : '进行中';
  return `任务创建时间 ${fmtTime(detail.created_at)} · 耗时 ${elapsed}`;
}

function infoMeta(detail) {
  const info = detail.info || {};
  const pairs = [
    ['单据编号', info.request_id],
    ['事项类型', info.category],
    ['会议类型', info.meeting_type],
    ['申请人', info.applicant],
    ['提交版本', `V${detail.version || 1}`],
    ['本次金额', info.amount],
    ['资料源', info.source],
    ['列表', info.list_name],
  ].filter(([, v]) => v != null && v !== '');
  return `<dl class="detail-meta meeting-meta">${pairs.map(([k, v]) =>
    `<div><dt>${safe(k)}</dt><dd>${safe(v)}</dd></div>`).join('')}</dl>`;
}

function progressHtml(detail) {
  const timings = detail.timings || [];
  const rules = detail.result?.rules || [];
  const counts = detail.result?.counts || {};
  if (!timings.length) {
    const note = {
      待执行: '任务已创建，等待系统调度。',
      执行中: '系统正在自动核验材料。',
      已完成: '审查流程已完成。',
      失败: detail.reason || '任务执行失败。',
    }[detail.status] || '';
    return `<div class="ui-notice">${safe(note)}</div>`;
  }
  const outcomeLine = rules.length
    ? `<div class="meeting-progress-outcome muted">${['初审通过', '风险提示', '无法校验', '建议驳回']
        .filter(l => counts[l]).map(l => `${l} ${counts[l]}`).join('，')}</div>
      <div class="inline meeting-progress-tags">${rules.map(r => tag(`${r.no} ${r.label}`, tones[r.label])).join('')}</div>`
    : '';
  return `<details class="meeting-timeline" open>
    <summary>
      <strong>任务进度</strong>
      <span class="meeting-timeline-dot" data-status="${safe(detail.status)}" aria-hidden="true"></span>
      <span class="muted">任务${safe(detail.status)}</span>
      <span class="meeting-timeline-chevron">${icon('chevron', 'small')}</span>
    </summary>
    <ol class="meeting-steps" aria-label="节点执行状态">${timings.map((t, i) => {
      const done = t.status === 'ok' || t.status === 'done';
      const failed = t.status === 'error' || t.status === 'failed';
      const running = t.status === 'running';
      const tone = done ? 'done' : failed ? 'stopped' : running ? 'live' : 'waiting';
      const state = done ? '已完成' : failed ? '失败' : running ? '进行中' : '待执行';
      const isReview = /审查|校验/.test(t.node || '');
      return `<li class="meeting-step is-${tone}">
        <span class="meeting-step-track" aria-hidden="true"><span class="meeting-step-icon mono">${done || failed ? icon(done ? 'check' : 'alert', 'small') : i + 1}</span></span>
        <div class="meeting-step-text"><strong>${safe(t.node)}</strong>
          <span class="meeting-step-state">${state}${t.ms != null ? ` · ${fmtDuration(t.ms)}` : ''}</span>
          ${t.summary || t.error ? `<p class="muted">${safe(t.summary || t.error)}</p>` : ''}
          ${isReview && done ? outcomeLine : ''}
        </div>
      </li>`;
    }).join('')}</ol>
  </details>`;
}

function evidenceCell(r) {
  const evidence = r.evidence || [];
  const items = r.items || [];
  if (!evidence.length && !items.length) return '—';
  const blocks = [];
  for (const ev of evidence) {
    if (typeof ev === 'string') {
      blocks.push(`<div class="evidence-item"><span class="muted">依据</span><p>${safe(ev)}</p></div>`);
      continue;
    }
    const quote = ev.text || ev.quote || ev.summary || '';
    const file = ev.filename || ev.file || ev.source || '';
    const located = ev.page_no || ev.located || ev.method === 'text' || ev.method === 'ocr';
    blocks.push(`<div class="evidence-item">
      <div class="evidence-item-head">
        <strong>${safe(file || '证据')}</strong>
        ${located ? tag('已定位', 'success') : (file ? tag('原文摘录', 'primary') : '')}
      </div>
      ${quote ? `<p>「${safe(String(quote).slice(0, 220))}」</p>` : ''}
      ${ev.page_no ? `<div class="muted small-text">第 ${safe(ev.page_no)} 页</div>` : ''}
    </div>`);
  }
  for (const it of items) {
    blocks.push(`<div class="evidence-item"><span class="muted">要点</span><p>${safe(it)}</p></div>`);
  }
  return `<div class="evidence-list">${blocks.join('')}</div>`;
}

function resultFilterChips(rules, counts) {
  const labels = ['全部', '建议驳回', '风险提示', '初审通过', '无法校验', '不适用', '审查中止', '未执行'];
  const total = rules.length;
  return `<div class="result-filters" role="tablist" aria-label="按校验结果筛选">
    ${labels.map(label => {
      const n = label === '全部' ? total : (counts[label] || rules.filter(r => r.label === label).length);
      if (label !== '全部' && !n) return '';
      const on = wbState.resultFilter === label;
      return `<button type="button" class="ui-btn${on ? ' ui-btn-primary' : ''}" data-action="wb-result-filter" data-value="${safe(label)}" aria-pressed="${on}">
        ${safe(label)} ${n}</button>`;
    }).join('')}
  </div>`;
}

function resultPanel(cfg, detail, user) {
  if (detail.status === '失败') return '<div class="empty">任务执行失败，暂无审查结果。</div>';
  if (detail.status === '待执行' || detail.status === '执行中') {
    return '<div class="ui-notice">初审尚未完成。任务结束后可查看建议审批意见和校验结果。</div>';
  }
  const result = detail.result;
  if (!result) return '<div class="empty">暂无审查结果。</div>';
  const rules = result.rules || [];
  const counts = result.counts || {};
  const editable = canReview(user);
  const filter = wbState.resultFilter || '全部';
  const shown = filter === '全部' ? rules : rules.filter(r => r.label === filter);
  const rows = shown.map(r => `<tr>
    <td class="mono">${safe(r.no)}</td><td>${safe(r.name)}</td><td>${statusTag(r.label)}</td>
    <td class="rule-result-note">${safe(r.message || '—')}</td>
    <td>${evidenceCell(r)}</td>
    <td class="rule-review-note">${editable
      ? `<textarea class="ui-input" name="note-${safe(r.rule_id)}" rows="1" maxlength="1000" placeholder="填写复核说明">${safe(r.review_note || '')}</textarea>`
      : safe(r.review_note || '—')}</td>
    <td class="rule-review-status">${editable
      ? `<select class="ui-input" name="status-${safe(r.rule_id)}" data-saved-status="${safe(r.review_status)}">${REVIEW_STATUSES.map(o =>
          `<option${o === r.review_status ? ' selected' : ''}>${o}</option>`).join('')}</select>`
      : statusTag(r.review_status)}</td>
  </tr>`);
  return `<div class="hint-stats meeting-result-stats" aria-label="初审结果统计">
      ${RESULT_STATS.map(([label, glyph, tone]) => hintStat(label, counts[label] || 0, glyph, tone)).join('')}
    </div>
    <section class="review-panel" aria-label="建议审批意见">
      ${card('建议审批意见', '', button('一键复制', 'wb-copy-opinion'))}
      <p class="copy opinion-copy" id="approval-opinion">${safe(result.suggestion || '')}</p>
    </section>
    <section class="review-panel" aria-label="校验结果">
      <form id="wb-review" data-employee="${cfg.employee}" data-id="${safe(detail.id)}">
        <div class="rule-results-heading"><h2 class="ui-card-title">校验结果</h2>
          ${editable ? '<button class="ui-btn ui-btn-primary" type="submit">保存复核备注</button>' : ''}
        </div>
        ${resultFilterChips(rules, counts)}
        ${table(['节点编号', '审查节点', '校验结果', 'AI 审查说明', '证据', '复核备注', '复核状态'], rows, '当前筛选下暂无记录')}
      </form>
    </section>`;
}

function materialsPanel(detail) {
  return materialsPrototype(detail);
}

function detailTabBody(cfg, detail, user) {
  return detailTabContent(cfg, detail, user);
}

function logsPanel(detail) {
  const logs = detail.logs || [];
  const rows = logs.map(l => `<tr>
    <td class="mono">${fmtTime(l.at)}</td><td>${safe(l.action)}</td><td>${safe(l.detail || '—')}</td><td>${safe(l.actor || '—')}</td>
  </tr>`);
  return table(['时间', '动作', '说明', '操作人'], rows, '暂无操作日志');
}

function afterDetailRender(cfg, detail, user) {
  bindDetailEvents(cfg, user, document.getElementById('view'));
  if (wbState.detailTab === 'archive' || (cfg.employee === 'contract' && wbState.detailTab === 'archive')) {
    loadArchivePanel(detail.task_id, detail.id, document.getElementById('wb-archive-mount'));
  }
}

function detailHtml(cfg, detail, user) {
  return buildDetailHtml(cfg, detail, user);
}

async function renderWorkbench(route, workId, user, view) {
  const cfg = Object.values(WORKBENCHES).find(w => w.route === route);
  if (!cfg) {
    view.innerHTML = '<div class="workbench-error">未知页面</div>';
    return;
  }
  view.innerHTML = '<div class="workbench-loading">加载中…</div>';
  try {
    if (!workId) {
      const data = await loadWorkbench(cfg.employee, true);
      view.innerHTML = listHtml(cfg, data);
      bindListEvents(cfg, user, view);
      startPolling(cfg, workId, user, view);
      return;
    }
    const detail = await WorkAPI.detail(cfg.employee, workId);
    wbState.detail = detail;
    wbState.resultFilter = '全部';
    if (typeof contractUi !== 'undefined') {
      contractUi.tab = 'workspace';
      contractUi.outcomeFilter = '';
      contractUi.issueId = null;
      contractUi.file = null;
      contractUi.anchor = null;
    }
    wbState.detailTab = cfg.employee === 'contract' ? 'workspace' : 'results';
    view.innerHTML = detailHtml(cfg, detail, user);
    afterDetailRender(cfg, detail, user);
    startPolling(cfg, workId, user, view);
  } catch (err) {
    view.innerHTML = `<div class="workbench-error">${safe(err.message || '加载失败')}</div>
      ${button('返回', 'wb-back', { value: cfg.route })}`;
  }
}

function startPolling(cfg, workId, user, view) {
  clearInterval(wbState.pollTimer);
  const need = () => {
    if (workId) {
      const d = wbState.detail;
      return d && (d.status === '执行中' || d.status === '待执行');
    }
    const data = wbState.cache[cfg.employee]?.data;
    return (data?.rows || []).some(r => r.status === '执行中' || r.status === '待执行');
  };
  if (!need()) return;
  wbState.pollTimer = setInterval(async () => {
    if (!need()) { clearInterval(wbState.pollTimer); return; }
    try {
      if (workId) {
        const detail = await WorkAPI.detail(cfg.employee, workId);
        wbState.detail = detail;
        const heading = view.querySelector('.page-title-line .ui-tag');
        if (heading && heading.textContent !== detail.status) heading.outerHTML = statusTag(detail.status);
        const tab = document.getElementById('wb-tab-body');
        if (tab) tab.innerHTML = detailTabBody(cfg, detail, user);
        if (detail.status === '已完成' || detail.status === '失败') clearInterval(wbState.pollTimer);
      } else {
        const data = await loadWorkbench(cfg.employee, true);
        const metrics = document.getElementById('wb-metrics');
        const list = document.getElementById('wb-list-rows');
        if (metrics) metrics.innerHTML = metricsHtml(data);
        if (list) list.innerHTML = listRowsHtml(cfg, filteredRows(cfg, data));
      }
    } catch { /* 轮询失败忽略，下一轮再试 */ }
  }, 3000);
}

function bindListEvents(cfg, user, view) {
  const form = document.getElementById('wb-filters');
  form?.addEventListener('submit', (e) => {
    e.preventDefault();
    const fd = new FormData(form);
    const f = wbFilters(cfg.employee);
    f.query = String(fd.get('query') || '');
    f.type = String(fd.get('type') || '');
    f.status = String(fd.get('status') || '');
    f.dateStart = String(fd.get('dateStart') || '');
    f.dateEnd = String(fd.get('dateEnd') || '');
    wbState.page[cfg.employee] = 1;
    const data = wbState.cache[cfg.employee]?.data;
    if (data) document.getElementById('wb-list-rows').innerHTML = listRowsHtml(cfg, filteredRows(cfg, data));
  });
}

function bindDetailEvents(cfg, user, view) {
  const form = document.getElementById('wb-review');
  form?.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!canReview(user)) return;
    const marks = [];
    for (const rule of (wbState.detail?.result?.rules || [])) {
      const noteEl = form.elements.namedItem(`note-${rule.rule_id}`);
      const statusEl = form.elements.namedItem(`status-${rule.rule_id}`);
      if (!noteEl || !statusEl) continue;
      const note = String(noteEl.value || '').trim();
      const status = String(statusEl.value || '');
      const noteChanged = note !== (rule.review_note || '');
      const statusChanged = status !== (statusEl.dataset.savedStatus || rule.review_status);
      if (noteChanged || statusChanged) marks.push({ rule_id: rule.rule_id, status, note });
    }
    if (!marks.length) { showToast('暂无复核改动'); return; }
    try {
      const detail = await WorkAPI.saveMarks(cfg.employee, form.dataset.id, marks);
      wbState.detail = detail;
      document.getElementById('wb-tab-body').innerHTML = detailTabBody(cfg, detail, user);
      bindDetailEvents(cfg, user, view);
      showToast('复核备注及状态已保存');
    } catch (err) {
      showToast(err.message || '保存失败');
    }
  });
}

async function handleWorkbenchAction(action, value, el, user, navigate) {
  if (action === 'wb-back') { navigate(`#${value}`); return true; }
  if (action === 'wb-tab') {
    wbState.detailTab = value;
    if (typeof contractUi !== 'undefined') contractUi.tab = value;
    const cfg = Object.values(WORKBENCHES).find(w => w.employee === (wbState.detail?.employee));
    if (cfg && wbState.detail) {
      document.querySelectorAll('.tabs [data-action="wb-tab"]').forEach(b => b.setAttribute('aria-pressed', b.dataset.value === value));
      document.getElementById('wb-tab-body').innerHTML = detailTabContent(cfg, wbState.detail, user);
      afterDetailRender(cfg, wbState.detail, user);
    }
    return true;
  }
  if (typeof handleArchiveAction === 'function' && handleArchiveAction(action, value, el)) return true;
  if (handleDetailAction(action, value, el, user)) return true;
  if (action === 'wb-reset') {
    wbState.filters[value] = { query: '', type: '', status: '', dateStart: '', dateEnd: '' };
    wbState.page[value] = 1;
    const cfg = Object.values(WORKBENCHES).find(w => w.employee === value);
    if (cfg) navigate(`#${cfg.route}`);
    return true;
  }
  if (action === 'wb-refresh') {
    const cfg = Object.values(WORKBENCHES).find(w => w.employee === value);
    if (cfg) {
      // 刷新只重拉列表；保留最近一次采集进度文案，避免一点刷新就「消失」
      const keepLog = wbState.collectLog;
      delete wbState.cache[value];
      await renderWorkbench(cfg.route, '', user, document.getElementById('view'));
      if (keepLog) setCollectProgress(keepLog);
    }
    return true;
  }
  if (action === 'wb-page') {
    const employee = el.dataset.employee;
    wbState.page[employee] = Number(value);
    const cfg = Object.values(WORKBENCHES).find(w => w.employee === employee);
    const data = wbState.cache[employee]?.data;
    if (cfg && data) document.getElementById('wb-list-rows').innerHTML = listRowsHtml(cfg, filteredRows(cfg, data));
    return true;
  }
  if (action === 'wb-copy-opinion') {
    const text = document.getElementById('approval-opinion')?.textContent || '';
    try {
      await navigator.clipboard.writeText(text);
      showToast('已复制建议审批意见');
    } catch {
      showToast('复制失败，请手动选择文本');
    }
    return true;
  }
  if (action === 'wb-retry') {
    const detail = wbState.detail;
    const employee = detail?.employee || Object.values(WORKBENCHES).find(w => true)?.employee;
    const cfg = Object.values(WORKBENCHES).find(w => w.employee === (detail?.employee))
      || Object.values(WORKBENCHES).find(w => location.hash.includes(w.route));
    if (!cfg) return true;
    try {
      await WorkAPI.retry(cfg.employee, value);
      showToast('已重新发起');
      delete wbState.cache[cfg.employee];
      navigate(`#${cfg.route}/${value}`);
    } catch (err) {
      showToast(err.message || '重试失败');
    }
    return true;
  }
  if (action === 'wb-collect') {
    const cfg = Object.values(WORKBENCHES).find(w => w.employee === value);
    const source = wbState.cache[value]?.data?.collect?.source;
    if (!source) { showToast('未配置资料源'); return true; }
    if (wbState.collecting) { showToast('上一轮采集尚未结束'); return true; }
    wbState.collecting = true;
    const startedAt = Date.now();
    const setBusyUi = (busyText) => {
      const btn = document.querySelector('[data-action="wb-collect"]');
      if (btn) { btn.disabled = true; btn.textContent = busyText || '采集中…'; }
      const summary = document.getElementById('wb-collect-summary');
      if (summary) summary.textContent = '本轮采集进行中…';
    };
    const renderLive = (st, note) => {
      const src = (st?.sources || {})[source] || {};
      const last = (st?.rounds || []).find(r => r.source === source) || {};
      const secs = Math.round((Date.now() - startedAt) / 1000);
      const q = st?.queue || {};
      setCollectProgress(`<strong>正在采集 ${safe(source)}…（已用时 ${secs}s）</strong>
        <div class="collect-progress-bar" aria-hidden="true"><span style="width:${Math.min(95, 12 + secs * 3)}%"></span></div>
        <p>${safe(note || (src.running ? '正在拉取列表并登记单据…' : '列表轮次收尾中…'))}</p>
        <p>本轮：列出 <b>${last.listed ?? '—'}</b>，入队 <b>${last.queued ?? '—'}</b>，失败 <b>${last.failed ?? '—'}</b></p>
        <p class="muted">同步队列：完成 ${q.done ?? '—'} · 排队/执行中 ${q.queued ?? '—'} / ${q.running ?? '—'}</p>`);
    };
    setBusyUi('采集中…');
    setCollectProgress(`<strong>正在启动采集 ${safe(source)}…</strong>
      <div class="collect-progress-bar" aria-hidden="true"><span style="width:8%"></span></div>
      <p>已提交采集请求，正在等待资料中心开始本轮…</p>`);
    try {
      const kick = await api(`/api/collect/run?source=${encodeURIComponent(source)}`, { method: 'POST' });
      if (kick?.skipped) {
        setCollectProgress(`<strong>未重复启动</strong><p>${safe(kick.skipped)}</p>`);
        showToast(kick.skipped);
        wbState.collecting = false;
        delete wbState.cache[value];
        if (cfg) await renderWorkbench(cfg.route, '', user, document.getElementById('view'));
        return true;
      }
      // 资料中心 /v1/collect/run 立即返回 {started}；完整结果靠轮询 status，直到 running=false
      const syncResult = kick && (kick.listed != null || kick.lists);
      let finalRound = syncResult ? kick : null;
      let sawRunning = false;
      const deadline = Date.now() + 180000;
      while (Date.now() < deadline) {
        let st = null;
        try { st = await api('/api/collect/status'); } catch { /* 忽略单次轮询失败 */ }
        const src = (st?.sources || {})[source] || {};
        const last = (st?.rounds || []).find(r => r.source === source);
        if (src.running) sawRunning = true;
        renderLive(st, src.running ? '正在拉取列表 / 入队同步…' : (sawRunning ? '本轮列表已结束，正在汇总…' : '等待资料中心接手…'));
        setBusyUi(`采集中… ${Math.round((Date.now() - startedAt) / 1000)}s`);
        if (syncResult) break;
        // 已见过 running，且当前不在跑，并有本轮 finished → 结束
        if (sawRunning && !src.running && last?.finished_at && last.finished_at * 1000 >= startedAt - 2000) {
          finalRound = last;
          break;
        }
        // 同步接口直接返回了完整统计
        if (kick?.listed != null && !src.running && sawRunning) {
          finalRound = kick;
          break;
        }
        // 启动后短时间内一直没 running：可能极快结束，用最新 round
        if (!sawRunning && last?.finished_at && last.finished_at * 1000 >= startedAt - 2000 && Date.now() - startedAt > 2500) {
          finalRound = last;
          break;
        }
        await new Promise(r => setTimeout(r, 1000));
      }
      if (!finalRound) {
        try {
          const st = await api('/api/collect/status');
          finalRound = (st.rounds || []).find(r => r.source === source) || {};
          renderLive(st, '已到等待上限，以下为最近一轮状态');
        } catch { finalRound = {}; }
      }
      const lists = (finalRound.lists || []).map(x => x.error
        ? `<li>${safe(x.name)}：失败 · ${safe(x.error)}</li>`
        : `<li>${safe(x.name)}：读到 ${x.rows ?? 0} 条，入队 ${x.queued ?? 0}</li>`).join('');
      const listed = finalRound.listed ?? 0;
      const queued = finalRound.queued ?? 0;
      const failed = finalRound.failed ?? 0;
      setCollectProgress(`<strong>本轮采集完成（${safe(source)}）</strong>
        <p>列出 <b>${listed}</b>，入队同步 <b>${queued}</b>，列表失败 <b>${failed}</b>${finalRound.error ? ` · ${safe(finalRound.error)}` : ''}</p>
        <p class="muted">「列出」为本轮扫到的单据；未到重采间隔的不会再入队。附件下载 / OCR 在后台继续，可点「刷新」查看任务列表。</p>
        ${lists ? `<ul>${lists}</ul>` : ''}`);
      showToast(`采集完成：列出 ${listed}，入队 ${queued}`);
      wbState.collecting = false;
      delete wbState.cache[value];
      if (cfg) await renderWorkbench(cfg.route, '', user, document.getElementById('view'));
    } catch (err) {
      setCollectProgress(`<strong>采集失败</strong><p>${safe(err.message || '未知错误')}</p>`);
      showToast(err.message || '采集触发失败');
      wbState.collecting = false;
      const btn2 = document.querySelector('[data-action="wb-collect"]');
      if (btn2) { btn2.disabled = false; btn2.textContent = '立即采集'; }
      const summary2 = document.getElementById('wb-collect-summary');
      if (summary2) summary2.textContent = collectSummary(wbState.cache[value]?.data?.collect || {});
    } finally {
      wbState.collecting = false;
    }
    return true;
  }
  return false;
}

document.addEventListener('change', (e) => {
  const sel = e.target.closest('[data-wb-pagesize]');
  if (!sel) return;
  const employee = sel.dataset.wbPagesize;
  wbState.pageSize[employee] = Number(sel.value) || 10;
  wbState.page[employee] = 1;
  const cfg = Object.values(WORKBENCHES).find(w => w.employee === employee);
  const data = wbState.cache[employee]?.data;
  if (cfg && data) document.getElementById('wb-list-rows').innerHTML = listRowsHtml(cfg, filteredRows(cfg, data));
});
