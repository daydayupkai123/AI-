'use strict';

/** 详情页按最新产品原型渲染：会议/采购/报销用表格结果；合同用左右分栏。 */

const DETAIL_STAGE_FALLBACK = ['取单', '下载附件', '解析材料', '归集材料', '抽取要素', '制度检索', '审查', '生成报告'];

const contractUi = {
  tab: 'workspace',
  outcomeFilter: '',
  issueId: null,
  file: null,
  anchor: null,
};

function auditDetailFooter() {
  return '<p class="audit-detail-footer small-text muted">本初审意见由 AI 辅助生成，仅作参考，不构成最终审核结论</p>';
}

function hintStat(label, value, glyph, tone) {
  return `<div class="hint-stat ${tone}">
    <span class="hint-stat-icon">${icon(glyph)}</span>
    <div class="hint-stat-content"><span class="hint-stat-label">${label}</span>
      <span class="hint-stat-value"><strong>${value}</strong> 项</span></div>
  </div>`;
}

function openDrawer(title, eyebrow, body, extraClass = '') {
  const overlay = document.getElementById('overlay');
  if (!overlay) return;
  overlay.className = '';
  overlay.classList.add('evidence-dialog');
  if (extraClass) extraClass.split(/\s+/).filter(Boolean).forEach(c => overlay.classList.add(c));
  overlay.innerHTML = `<div class="drawer"><header class="drawer-header">
    <div><div class="small-text muted">${safe(eyebrow)}</div><h2 id="dialog-title">${safe(title)}</h2></div>
    <button type="button" class="ui-btn icon-button" data-action="close-drawer" aria-label="关闭">${icon('x')}</button>
    </header><div class="drawer-body">${body}</div></div>`;
  // dialog 顶层偶发吃掉 document 委托；抽屉内再绑一层，保证报文 Tab / 关闭可用
  if (!overlay.dataset.drawerBound) {
    overlay.dataset.drawerBound = '1';
    overlay.addEventListener('click', (e) => {
      const btn = e.target.closest('[data-action]');
      if (!btn || !overlay.contains(btn)) return;
      const action = btn.dataset.action;
      const value = btn.dataset.value;
      if (action === 'close-drawer') { e.preventDefault(); closeDrawer(); return; }
      if (action === 'archive-packet-tab' || action === 'archive-copy') {
        e.preventDefault();
        e.stopPropagation();
        if (typeof handleArchiveAction === 'function') handleArchiveAction(action, value, btn);
      }
    });
  }
  if (!overlay.open) overlay.showModal();
  overlay.querySelector('[data-action="close-drawer"]')?.focus();
}

function closeDrawer() {
  const overlay = document.getElementById('overlay');
  if (overlay?.open) overlay.close();
  if (overlay) overlay.className = '';
}

function normalizeEvidence(ev) {
  if (!ev) return null;
  if (typeof ev === 'string') return { file: '', snippet: ev, page: null, label: '' };
  return {
    file: ev.file || ev.filename || ev.source || '',
    snippet: ev.snippet || ev.text || ev.quote || ev.summary || '',
    page: ev.page || ev.page_no || null,
    label: ev.label || '',
    value: ev.value || '',
  };
}

function ruleEvidenceList(rule) {
  const list = (rule.evidence || []).map(normalizeEvidence).filter(Boolean);
  for (const it of rule.items || []) list.push({ file: '', snippet: it, page: null, label: '要点' });
  return list;
}

function infoMetaPrototype(detail) {
  const info = detail.info || {};
  const facts = info.facts || {};
  const pairs = detail.employee === 'meeting'
    ? [
      ['单据编号', info.request_id], ['事项类型', info.category], ['会议类型', info.meeting_type],
      ['申请人', info.applicant], ['提交版本', `V${detail.version || 1}`],
      ['单据创建时间', fmtTime(detail.created_at)], ['本次金额', info.amount],
      ['三重一大', facts['三重一大'] || facts['是否三重一大'] || '—'],
    ]
    : detail.employee === 'contract'
      ? [
        ['流程编号', info.request_id], ['业务类型', info.category], ['合同金额', info.amount],
        ['申请人', info.applicant], ['提交时间', fmtTime(detail.created_at)],
        ['提交版本', `V${detail.version || 1}`],
      ]
      : [
        ['单据编号', info.request_id], ['事项类型', info.category], ['申请人', info.applicant],
        ['提交版本', `V${detail.version || 1}`], ['创建时间', fmtTime(detail.created_at)],
        ['金额', info.amount], ['资料源', info.source],
      ];
  const basis = facts['审批/上会依据'] || facts['上会依据'] || facts['审批依据'] || '';
  return `<dl class="detail-meta meeting-meta">${pairs.filter(([, v]) => v != null && v !== '')
    .map(([k, v]) => `<div><dt>${safe(k)}</dt><dd>${safe(v)}</dd></div>`).join('')}
    ${basis ? `<div class="meeting-basis"><dt>审批/上会依据</dt><dd>${safe(basis)}</dd></div>` : ''}
  </dl>`;
}

function progressPrototype(detail) {
  const timings = detail.timings || [];
  const rules = detail.result?.rules || [];
  const counts = detail.result?.counts || {};
  const stages = timings.length ? timings.map(t => t.node) : DETAIL_STAGE_FALLBACK;
  const elapsed = detail.started_at && detail.finished_at
    ? (detail.finished_at - detail.started_at) : null;
  const headline = detail.status === '执行中' ? '正在执行' : `任务${detail.status}`;
  const byName = Object.fromEntries(timings.map(t => [t.node, t]));
  let active = -1;
  if (detail.status === '已完成') active = stages.length;
  else if (detail.status === '失败') active = Math.max(0, timings.findIndex(t => t.status === 'error' || t.status === 'failed'));
  else if (detail.status === '执行中') active = Math.max(0, timings.findIndex(t => t.status === 'running'));
  else if (detail.status === '待执行') active = -1;
  else active = timings.filter(t => t.status === 'ok' || t.status === 'done').length;

  const outcome = rules.length
    ? `<p>${['初审通过', '风险提示', '无法校验', '建议驳回'].filter(l => counts[l]).map(l => `${l} ${counts[l]}`).join('，') || '—'}</p>
       <div class="inline">${rules.map(r => tag(`${r.no || r.rule_id} ${r.label}`, tones[r.label])).join('')}</div>`
    : '';

  return `<details class="meeting-timeline" open>
    <summary>
      <strong id="meeting-progress-title">任务进度</strong>
      <span class="meeting-timeline-dot" data-status="${safe(detail.status)}"></span>
      <span class="muted">${safe(headline)}</span>
      <span class="muted mono">${elapsed != null ? `${elapsed.toFixed(1)}s` : '—'}</span>
      <span class="meeting-timeline-chevron">${icon('chevron', 'small')}</span>
    </summary>
    <ol aria-label="任务阶段">${stages.map((label, index) => {
      const t = byName[label] || timings[index];
      const done = detail.status === '已完成' || (t && (t.status === 'ok' || t.status === 'done')) || index < active;
      const running = index === active && detail.status === '执行中';
      const failed = (t && (t.status === 'error' || t.status === 'failed')) || (index === active && detail.status === '失败');
      const tone = done && !failed ? 'done' : running ? 'running' : failed ? 'failed' : 'waiting';
      const isReview = /审查|校验/.test(label);
      return `<li class="meeting-stage is-${tone}">
        <div class="meeting-stage-heading"><strong>${safe(label)}</strong>
          <span class="muted mono">${done && t?.ms != null ? fmtDuration(t.ms) : running ? '进行中' : failed ? '失败' : '待执行'}</span>
        </div>
        ${done || failed ? `<p>${safe(t?.summary || t?.error || (isReview ? '' : label))}</p>` : ''}
        ${isReview && (done || running || failed) ? outcome : ''}
      </li>`;
    }).join('')}</ol>
  </details>`;
}

function meetingStyleResults(cfg, detail, user) {
  if (detail.status === '失败') return '<div class="empty">任务执行失败，暂无审查结果。</div>';
  if (detail.status === '待执行' || detail.status === '执行中') {
    return '<div class="ui-notice">初审尚未完成。任务结束后可查看建议审批意见和校验结果。</div>';
  }
  const result = detail.result;
  if (!result) return '<div class="empty">暂无审查结果。</div>';
  const rules = result.rules || [];
  const counts = result.counts || {};
  const editable = canReview(user);
  const rows = rules.map(r => `<tr>
    <td class="mono">${safe(r.no || r.rule_id)}</td>
    <td>${safe(r.name)}</td>
    <td>${statusTag(r.label)}</td>
    <td class="rule-result-note">${safe(r.message || '—')}</td>
    <td>${ruleEvidenceList(r).length ? textButton('查看证据', 'wb-evidence', r.rule_id) : '—'}</td>
    <td class="rule-review-note">${editable
      ? `<textarea class="ui-input" name="note-${safe(r.rule_id)}" rows="1" maxlength="1000" placeholder="填写复核说明">${safe(r.review_note || '')}</textarea>`
      : safe(r.review_note || '—')}</td>
    <td class="rule-review-status">${editable
      ? `<select class="ui-input" name="status-${safe(r.rule_id)}" data-saved-status="${safe(r.review_status)}">${REVIEW_STATUSES.map(o =>
          `<option${o === r.review_status ? ' selected' : ''}>${o}</option>`).join('')}</select>`
      : statusTag(r.review_status)}</td>
  </tr>`);
  return `<div class="hint-stats meeting-result-stats" aria-label="初审结果统计">
      ${[['初审通过', 'check', 'pass-stat'], ['风险提示', 'alert', 'risk-stat'], ['无法校验', 'info', 'unverified-stat']]
        .map(([label, glyph, tone]) => hintStat(label, counts[label] || 0, glyph, tone)).join('')}
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
        ${table(['节点编号', '审查节点', '校验结果', 'AI 审查说明', '证据', '复核备注', '复核状态'], rows)}
      </form>
    </section>`;
}

function materialParseTag(m) {
  if (!m.status) return '—';
  const ok = m.status === 'ok' || m.status === 'ready' || m.status === 'parsed';
  if (ok) return tag('已解析', 'success');
  if (m.status === 'failed' || m.status === 'error') return tag('读取失败', 'warning');
  return statusTag(m.status);
}

function materialsPrototype(detail) {
  const mats = detail.materials || [];
  if (!mats.length) return '<div class="empty">暂无材料记录</div>';
  return table(['类型', '文件', '页数', '解析'], mats.map((m, index) => {
    const name = m.filename || '—';
    const file = m.sig
      ? `<a class="text-link" href="/api/files/${encodeURIComponent(m.sig)}?name=${encodeURIComponent(name)}" target="_blank" rel="noopener">${safe(name)}</a>`
      : safe(name);
    const canPreview = Boolean(m.sig || m.filename || m.role);
    const preview = canPreview ? textButton('预览', 'material-preview', String(index)) : '';
    return `<tr><td>${safe(m.role || m.kind || '—')}</td>
      <td><span class="inline">${file}${preview}</span></td>
      <td>${m.pages != null ? m.pages : '—'}</td>
      <td>${materialParseTag(m)}</td></tr>`;
  }), '暂无已归集的材料');
}

function materialEvidenceSnippets(detail, filename) {
  const name = filename || '';
  const out = [];
  for (const r of detail.result?.rules || []) {
    for (const ev of ruleEvidenceList(r)) {
      const file = ev.file || '';
      if (!file || !name) continue;
      if (file === name || name.includes(file) || file.includes(name)) {
        out.push({ rule: r.name || r.rule_id, label: r.label, ...ev });
      }
    }
  }
  return out;
}

function openMaterialPreview(detail, index) {
  const mats = detail.materials || [];
  const m = mats[Number(index)];
  if (!m) return;
  const name = m.filename || m.role || '材料';
  const openLink = m.sig
    ? `<a class="text-link" href="/api/files/${encodeURIComponent(m.sig)}?name=${encodeURIComponent(name)}" target="_blank" rel="noopener">打开原件</a>`
    : '';
  const snippets = materialEvidenceSnippets(detail, m.filename);
  const body = `<div class="contract-evidence-body">
    <div class="contract-evidence-conclusion">
      ${materialParseTag(m)}
      <h3>${safe(name)}</h3>
      <p>${[m.role || m.kind, m.pages != null ? `${m.pages} 页` : ''].filter(Boolean).map(safe).join(' · ') || '材料预览'}</p>
      ${openLink ? `<p>${openLink}</p>` : '<p class="muted">暂无原件下载。</p>'}
    </div>
    <div class="contract-evidence-grid">${snippets.length ? snippets.map((ev, i) => `
      <section class="contract-evidence-source">
        <div class="contract-evidence-label">相关摘录 ${String(i + 1).padStart(2, '0')}</div>
        <h3>${safe(ev.rule || '规则')}</h3>
        <p class="contract-evidence-location">${ev.page ? `第 ${ev.page} 页` : (ev.label || '摘录')}</p>
        <blockquote>${safe(ev.snippet || '—')}</blockquote>
      </section>`).join('') : `<div class="empty">暂无该材料的定位摘录。${openLink ? '可打开原件查看。' : ''}</div>`}</div>
  </div>`;
  openDrawer(name, `${detail.id} · 材料预览`, body);
}

function previewContractMaterial(detail, index, user) {
  const mats = detail.materials || [];
  const m = mats[Number(index)];
  if (!m) return;
  contractUi.file = m.filename || m.role || contractUi.file;
  contractUi.anchor = null;
  contractUi.issueId = null;
  wbState.detailTab = 'workspace';
  document.querySelectorAll('.tabs [data-action="wb-tab"]').forEach(b => {
    b.setAttribute('aria-pressed', b.dataset.value === 'workspace');
  });
  const body = document.getElementById('wb-tab-body');
  if (body) body.innerHTML = detailTabContent({ employee: 'contract' }, detail, user);
  requestAnimationFrame(() => document.getElementById('contract-material')?.focus({ preventScroll: true }));
}

function logsPrototype(detail) {
  const logs = detail.logs || [];
  return table(['时间', '操作', '对象', '版本或说明', '操作人'],
    logs.map(l => `<tr><td class="mono">${fmtTime(l.at)}</td><td>${safe(l.action)}</td>
      <td class="mono">${safe(detail.id)}</td><td>${safe(l.detail || '—')}</td><td>${safe(l.actor || '—')}</td></tr>`),
    '暂无操作日志');
}

function openEvidenceDrawer(detail, ruleId) {
  const rule = (detail.result?.rules || []).find(r => r.rule_id === ruleId);
  if (!rule) return;
  const evidence = ruleEvidenceList(rule);
  const body = `<div class="contract-evidence-body">
    <div class="contract-evidence-conclusion">${statusTag(rule.label)}<h3>${safe(rule.message || rule.name)}</h3>
      <p>${safe((rule.items || []).join('；') || '结合下列材料核对。')}</p></div>
    <div class="contract-evidence-grid">${evidence.length ? evidence.map((ev, i) => `
      <section class="contract-evidence-source">
        <div class="contract-evidence-label">${i === 0 ? '核验材料' : '比对依据'} ${String(i + 1).padStart(2, '0')}</div>
        <h3>${safe(ev.file || ev.label || '材料')}</h3>
        <p class="contract-evidence-location">${ev.page ? `第 ${ev.page} 页` : (ev.label || '摘录')}</p>
        <blockquote>${safe(ev.snippet || '—')}</blockquote>
      </section>`).join('') : '<div class="empty">暂无证据摘录</div>'}</div>
  </div>`;
  openDrawer(rule.name, `${detail.id} · ${rule.rule_id}`, body);
}

/* ---------------- 合同：左右分栏 ---------------- */

function contractRules(detail) {
  return (detail.result?.rules || []).map(r => ({
    ...r,
    evidence: ruleEvidenceList(r),
  }));
}

function contractFileBundles(detail) {
  const mats = detail.materials || [];
  const byFile = {};
  for (const m of mats) {
    const name = m.filename || m.role || '材料';
    byFile[name] = {
      name,
      role: m.role || m.kind || '',
      sig: m.sig,
      pages: m.pages,
      sections: [],
    };
  }
  for (const r of contractRules(detail)) {
    r.evidence.forEach((ev, idx) => {
      const key = ev.file || r.name;
      if (!byFile[key]) byFile[key] = { name: key, role: '', sig: null, pages: null, sections: [] };
      byFile[key].sections.push({
        id: `${r.rule_id}-${idx}`,
        ruleId: r.rule_id,
        title: ev.label || (ev.page ? `第 ${ev.page} 页` : '摘录'),
        text: ev.snippet || '',
        page: ev.page,
      });
    });
  }
  return byFile;
}

function contractPreview(detail) {
  const files = contractFileBundles(detail);
  const names = Object.keys(files);
  if (!names.length) return '<div class="empty">暂无可预览材料</div>';
  if (!contractUi.file || !files[contractUi.file]) contractUi.file = names[0];
  const current = files[contractUi.file];
  const openLink = current.sig
    ? `<a class="text-link" href="/api/files/${encodeURIComponent(current.sig)}?name=${encodeURIComponent(current.name)}" target="_blank" rel="noopener">打开原件</a>`
    : '';
  const sections = current.sections.length
    ? current.sections.map((sec, i) => `<article class="contract-fragment${contractUi.anchor === i ? ' selected' : ''}" id="contract-fragment-${i}" tabindex="-1">
        <h4>${safe(sec.title)}</h4><p>${safe(sec.text || '（无摘录）')}</p></article>`).join('')
    : `<article class="contract-fragment"><h4>${safe(current.role || '材料')}</h4>
        <p class="muted">暂无定位摘录。可${openLink || '在材料记录中查看原件'}。</p></article>`;
  return `<div class="contract-source-controls">
      <label class="contract-label" for="contract-material">材料</label>
      <select id="contract-material" class="ui-input" data-action-change="contract-file">
        ${names.map(n => `<option value="${safe(n)}"${n === contractUi.file ? ' selected' : ''}>${safe(n)}</option>`).join('')}
      </select>
      ${openLink}
    </div>
    <div class="contract-document-scroll" id="contract-document-scroll">
      <article class="contract-paper">
        <div class="contract-paper-label">材料摘录 · 只读</div>
        <h3>${safe(current.name)}</h3>
        ${sections}
      </article>
    </div>`;
}

function contractIssueDetail(detail, rule) {
  const needs = ['风险提示', '无法校验', '建议驳回'].includes(rule.label);
  const sources = rule.evidence.map((ev, index) => {
    const active = contractUi.file === (ev.file || '') && contractUi.issueId === rule.rule_id;
    return `<li class="contract-inline-source${active ? ' selected' : ''}">
      <div class="contract-inline-source-head">
        <div><strong>${safe(ev.file || '材料')}</strong><span>${ev.page ? `第 ${ev.page} 页` : (ev.label || '摘录')}</span></div>
        ${ev.file || ev.snippet ? textButton(active && contractUi.anchor === index ? '已定位' : '定位原文', 'contract-locate', `${rule.rule_id}/${index}`) : ''}
      </div>
      <blockquote>${safe(ev.snippet || '—')}</blockquote>
    </li>`;
  }).join('');
  return `<article class="contract-issue-detail">
    <h4>${needs ? '问题描述' : '审核说明'}</h4>
    <p>${safe(rule.message || '—')}</p>
    ${needs ? `<h4>处理建议</h4><p>${safe((rule.items || [])[0] || '请核对关联依据后确认处理方式。')}</p>` : ''}
    <div class="contract-issue-evidence-head"><h4>依据</h4>${textButton('查看证据', 'wb-evidence', rule.rule_id)}</div>
    <ul class="contract-inline-sources">${sources || '<li class="muted">暂无依据摘录</li>'}</ul>
  </article>`;
}

function contractIssuesPanel(detail) {
  const rules = contractRules(detail);
  const filter = contractUi.outcomeFilter || '';
  const labels = ['全部', '建议驳回', '风险提示', '初审通过', '无法校验', '不适用', '审查中止', '未执行'];
  const counts = {};
  rules.forEach(r => { counts[r.label] = (counts[r.label] || 0) + 1; });
  const shown = filter ? rules.filter(r => r.label === filter) : rules;
  const filters = labels.map(label => {
    const n = label === '全部' ? rules.length : (counts[label] || 0);
    if (label !== '全部' && !n) return '';
    const value = label === '全部' ? '' : label;
    return `<button type="button" class="contract-outcome-filter" data-action="contract-outcome-filter" data-value="${safe(value)}" aria-pressed="${value === filter}">
      ${safe(label)}<span>${n}</span></button>`;
  }).join('');
  return `<header class="contract-issues-head">
      <h2>审核结果</h2>
      ${textButton('查看规则报告', 'wb-tab', 'report')}
    </header>
    <div class="contract-outcome-filters" role="group" aria-label="审核结果分类">${filters}</div>
    <div class="contract-issues-body" id="contract-issues-body">${shown.length ? `
      <ul class="contract-issue-list">${shown.map(rule => `
        <li class="contract-issue-card">
          <button type="button" class="contract-issue-option" data-action="contract-issue" data-value="${safe(rule.rule_id)}"
            aria-expanded="${contractUi.issueId === rule.rule_id}">
            ${tag(rule.label, tones[rule.label])}<span class="mono contract-rule-id">${safe(rule.rule_id)}</span>
            <strong>${safe(rule.name)}</strong>${icon('chevron', 'small')}
          </button>
          <div id="contract-issue-${safe(rule.rule_id)}"${contractUi.issueId === rule.rule_id ? '' : ' hidden'}>
            ${contractUi.issueId === rule.rule_id ? contractIssueDetail(detail, rule) : ''}
          </div>
        </li>`).join('')}</ul>` : `<div class="contract-empty">${icon('info')}<strong>该类别暂无审核结果</strong></div>`}
    </div>`;
}

function contractReportPanel(cfg, detail, user) {
  return meetingStyleResults(cfg, detail, user);
}

function contractWorkspace(detail) {
  if (detail.status === '待执行' || detail.status === '执行中') {
    return '<div class="ui-notice">初审尚未完成。任务结束后可在此对照原文查看审核结果。</div>';
  }
  if (detail.status === '失败') return '<div class="empty">任务执行失败，暂无审查结果。</div>';
  return `<div class="contract-workspace-grid">
      <div id="contract-source">${contractPreview(detail)}</div>
      <section class="contract-issues" id="contract-issues">${contractIssuesPanel(detail)}</section>
    </div>`;
}

function contractLocate(detail, value) {
  const [ruleId, idxStr] = String(value).split('/');
  const rule = contractRules(detail).find(r => r.rule_id === ruleId);
  const ev = rule?.evidence?.[Number(idxStr)];
  if (!ev) return;
  contractUi.issueId = ruleId;
  contractUi.file = ev.file || contractUi.file;
  const files = contractFileBundles(detail);
  const sections = (files[contractUi.file] || {}).sections || [];
  const anchor = sections.findIndex(s => s.id === `${ruleId}-${idxStr}`);
  contractUi.anchor = anchor >= 0 ? anchor : Number(idxStr);
  const source = document.getElementById('contract-source');
  const issues = document.getElementById('contract-issues');
  if (source) source.innerHTML = contractPreview(detail);
  if (issues) issues.innerHTML = contractIssuesPanel(detail);
  requestAnimationFrame(() => {
    const target = document.getElementById(`contract-fragment-${contractUi.anchor}`);
    const scroller = document.getElementById('contract-document-scroll');
    if (target && scroller) {
      target.focus({ preventScroll: true });
      scroller.scrollTop += target.getBoundingClientRect().top - scroller.getBoundingClientRect().top - 14;
    }
  });
}

function detailTabsFor(employee) {
  if (employee === 'contract') {
    return [
      ['workspace', '审查结果'], ['report', '规则报告'], ['materials', '材料记录'],
      ['archive', '执行档案'], ['audit', '操作记录'],
    ];
  }
  if (employee === 'reimburse') {
    return [['results', '规则结果'], ['materials', '材料记录'], ['archive', '执行档案'], ['audit', '操作日志']];
  }
  return [['results', '审查结果'], ['materials', '材料记录'], ['archive', '执行档案'], ['audit', '操作日志']];
}

function detailTabContent(cfg, detail, user) {
  const tab = wbState.detailTab;
  if (cfg.employee === 'contract') {
    if (tab === 'workspace' || tab === 'results') return contractWorkspace(detail);
    if (tab === 'report') return contractReportPanel(cfg, detail, user);
    if (tab === 'materials') return materialsPrototype(detail);
    if (tab === 'audit') return logsPrototype(detail);
    if (tab === 'archive') {
      return `<div id="wb-archive-mount"><div class="workbench-loading">加载执行档案…</div></div>`;
    }
  }
  if (tab === 'materials') return materialsPrototype(detail);
  if (tab === 'archive') return `<div id="wb-archive-mount"><div class="workbench-loading">加载执行档案…</div></div>`;
  if (tab === 'audit') return logsPrototype(detail);
  return meetingStyleResults(cfg, detail, user);
}

function buildDetailHtml(cfg, detail, user) {
  const tabDefs = detailTabsFor(cfg.employee);
  if (!tabDefs.some(([k]) => k === wbState.detailTab)) {
    wbState.detailTab = tabDefs[0][0];
  }
  const workspaceClass = cfg.employee === 'contract' ? ' ui-card contract-workspace' : ' ui-card';
  return `${wbHead(cfg, `${detail.id} · ${(detail.info || {}).title || detail.id}`, detailSubtitle(detail), detail.status, '任务详情')}
    <section class="ui-card meeting-detail-card">
      ${card('任务信息')}
      ${infoMetaPrototype(detail)}
    </section>
    <section class="ui-card meeting-detail-card" aria-labelledby="meeting-progress-title">
      ${progressPrototype(detail)}
    </section>
    <section class="${workspaceClass.trim()}">
      ${tabs('wb-tab', tabDefs, wbState.detailTab)}
      <div id="wb-tab-body">${detailTabContent(cfg, detail, user)}</div>
    </section>
    ${auditDetailFooter()}
    <div class="actions" style="margin-top:16px">
      ${button('返回列表', 'wb-back', { value: cfg.route })}
      ${detail.status === '失败' && canReview(user) ? button('重新发起', 'wb-retry', { value: detail.id, style: 'primary' }) : ''}
    </div>`;
}

function handleDetailAction(action, value, el, user) {
  const detail = wbState.detail;
  if (!detail) return false;
  if (action === 'close-drawer') { closeDrawer(); return true; }
  if (action === 'wb-evidence') { openEvidenceDrawer(detail, value); return true; }
  if (action === 'material-preview') {
    if (detail.employee === 'contract') previewContractMaterial(detail, value, user);
    else openMaterialPreview(detail, value);
    return true;
  }
  if (action === 'contract-outcome-filter') {
    contractUi.outcomeFilter = value;
    const panel = document.getElementById('contract-issues');
    if (panel) panel.innerHTML = contractIssuesPanel(detail);
    return true;
  }
  if (action === 'contract-issue') {
    contractUi.issueId = contractUi.issueId === value ? null : value;
    const rule = contractRules(detail).find(r => r.rule_id === value);
    if (rule?.evidence?.[0]?.file) contractUi.file = rule.evidence[0].file;
    const source = document.getElementById('contract-source');
    const issues = document.getElementById('contract-issues');
    if (source) source.innerHTML = contractPreview(detail);
    if (issues) issues.innerHTML = contractIssuesPanel(detail);
    return true;
  }
  if (action === 'contract-locate') {
    contractLocate(detail, value);
    return true;
  }
  return false;
}

document.addEventListener('change', (e) => {
  const sel = e.target.closest('[data-action-change="contract-file"]');
  if (!sel || !wbState.detail) return;
  contractUi.file = sel.value;
  contractUi.anchor = null;
  const source = document.getElementById('contract-source');
  if (source) source.innerHTML = contractPreview(wbState.detail);
});
