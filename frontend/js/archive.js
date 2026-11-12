'use strict';

/** 执行档案：对齐产品原型（嵌在详情 Tab），数据来自资料中心 /api/runs/{task_id}/archive */

let archiveCache = null;
const packetLazy = new Map(); // drawer 内响应体懒渲染缓存

const ARC_KIND = {
  snapshot: '表单快照', event: '过程', api: '接口报文', llm: '模型调用', check: '原文校验',
  rules: '规则结论', report: '报告', shots: '证据截图', page: '平台页面',
};

const OP_NAME = [
  [/reqform\/loadForm/, '读取审批单据表单（字段、附件清单）'],
  [/getRequestLogBaseInfo|getRequestLogList/, '读取审批流转日志'],
  [/govdoc\/summary\/v1\/deal-base-info/, '读取公文详情（标题、模板、附件清单）'],
  [/content\/content\.do/, '读取公文表单内容'],
  [/getQueryResult/, '公司数据查询 · 内部请示查询（只读）'],
  [/tyssj\.do/, '经门户统一认证单点登录'],
  [/fileDownload|FileDownload|downloadFile|doDownload/i, '下载附件原件'],
  [/cube\/search\/getList|ec\/dev\/table\/datas/, '读取台账'],
  [/reqlist|splitPageKey/, '读取待办 / 已办列表（只读列表）'],
  [/tianyancha|tyc/i, '查询企业资信（天眼查）'],
];

function arcOpName(url) {
  return (OP_NAME.find(([re]) => re.test(url || '')) || [null, '调用平台接口'])[1];
}

function arcHost(url) {
  try { return new URL(url).host; } catch { return ''; }
}

function arcClock(ts) {
  if (!ts) return '—';
  const d = new Date(ts < 1e12 ? ts * 1000 : ts);
  const p = n => String(n).padStart(2, '0');
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

function arcMs(ms) {
  if (ms == null) return '—';
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${Math.round(ms)}ms`;
}

function arcSection(title, body, expanded = true) {
  return `<details class="meeting-archive-section"${expanded ? ' open' : ''}>
    <summary><strong>${safe(title)}</strong>${icon('chevron', 'small')}</summary>${body}
  </details>`;
}

function arcPageCard(body, pagesMeta) {
  const p = body || {};
  const meta = (pagesMeta || []).find(x => x.page_id === p.page_id) || {};
  const ops = p.ops || [];
  const blocked = p.blocked || [];
  const opsRows = ops.map(o => {
    const when = o.at != null ? (o.at + 's') : '—';
    const path = (o.url || '').split('?')[0];
    return '<tr><td class="mono">' + when + '</td><td>' + safe(o.method) + '</td><td>'
      + (o.status ?? '—') + '</td><td class="mono">' + safe(path) + '</td></tr>';
  });
  const opsBlock = ops.length
    ? arcSection('页面加载请求 · ' + ops.length + ' 次', table(['时间', '方法', '状态', '接口'], opsRows), false)
    : '';
  const shot = p.page_id
    ? ('<button type="button" class="meeting-archive-shot" data-action="archive-page" data-value="'
      + safe(p.page_id) + '"><img loading="lazy" src="/api/archive/pages/'
      + encodeURIComponent(p.page_id) + '.png?w=960&amp;trim=1" alt="平台页面截图（已打码）"></button>'
      + '<div class="inline meeting-archive-shot-actions">'
      + textButton('预览截图', 'archive-page', p.page_id)
      + `<a class="text-link" href="/api/archive/pages/${encodeURIComponent(p.page_id)}.png?trim=1" target="_blank" rel="noopener">新窗口打开</a>`
      + '</div>'
      + '<div class="muted small-text">打码 ' + (meta.pii_count ?? 0) + ' 处 · 页面请求 ' + ops.length
      + ' · 拦截写请求 ' + blocked.length + '</div>')
    : '';
  return '<section class="meeting-archive-section meeting-archive-platform">'
    + '<div class="inline"><strong>' + safe(p.title || '客户平台页面') + '</strong>'
    + tag('公司数据查询只读视图', 'primary') + '</div>'
    + '<div class="muted small-text mono">' + safe((p.final_url || p.url || '').slice(0, 120)) + '</div>'
    + (p.skip ? '<div class="ui-notice">未打开页面：' + safe(p.skip) + '</div>' : '')
    + (p.error ? '<div class="workbench-error">' + safe(p.error) + '</div>' : '')
    + shot + opsBlock + '</section>';
}

function arcApiIndex(items, target) {
  let n = 0;
  for (const i of items || []) {
    if (i.kind !== 'api') continue;
    if (i === target) return n;
    n += 1;
  }
  return -1;
}

function arcSteps(items) {
  // 「平台操作步骤」只展示「有客户平台接口/截图」的阶段；无内容的阶段不放空标题。
  const groups = [];
  let cur = null;
  for (const i of items || []) {
    const b = i.body || {};
    if (i.kind === 'event' && b.type === 'node.started') {
      cur = { name: b.node || i.title || '', ops: [] };
      groups.push(cur);
    } else if (i.kind === 'api' || i.kind === 'page') {
      if (!cur) {
        cur = { name: '', ops: [] };
        groups.push(cur);
      }
      cur.ops.push(i);
    }
  }
  const rows = [];
  for (const g of groups) {
    if (!g.ops.length) continue; // 有标题无内容 → 不展示该标题
    if (g.name) rows.push(`<div class="meeting-archive-step-node"><strong>${safe(g.name)}</strong></div>`);
    for (const i of g.ops) {
      const b = i.body || {};
      if (i.kind === 'api') {
        const idx = arcApiIndex(items, i);
        rows.push(`<div class="meeting-archive-step-row">
          <span class="mono muted">${arcClock(i.at)}</span>
          <span>${safe(arcOpName(b.url))}</span>
          <span class="mono muted">${safe(arcHost(b.url))}</span>
          ${tag(`${b.method || ''} ${b.status ?? ''}`, (b.status || 0) < 400 ? 'success' : 'danger')}
          <span class="mono muted">${arcMs(b.ms)}</span>
          ${textButton('查看详情', 'archive-api', String(idx))}
        </div>`);
      } else if (b.page_id) {
        rows.push(`<div class="meeting-archive-step-row">
          <span class="mono muted">${arcClock(i.at)}</span>
          <span>只读打开单据页面并整页截图</span>
          ${tag('截图', 'success')}
          ${textButton('查看截图', 'archive-page', b.page_id)}
        </div>`);
      } else {
        rows.push(`<div class="meeting-archive-step-row">
          <span class="mono muted">${arcClock(i.at)}</span>
          <span>未打开单据页面：${safe(b.skip || b.error || '')}</span>
          ${tag('跳过', 'warning')}
        </div>`);
      }
    }
  }
  return rows.length
    ? `<div class="meeting-archive-steps">${rows.join('')}</div>`
    : '<div class="empty">本次执行没有客户平台接口调用（资料已在本地就绪或未打开客户系统页面）。全过程见下方完整时间线。</div>';
}

function prettyPayload(raw, limit = 16000) {
  if (raw == null || raw === '') return { kind: 'empty', html: '<div class="empty">无内容</div>', text: '' };
  let text = String(raw);
  let kind = 'text';
  const trimmed = text.trim();
  try {
    if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
      text = JSON.stringify(JSON.parse(trimmed), null, 2);
      kind = 'json';
    } else if (trimmed.includes('=') && !trimmed.includes('\n') && trimmed.length < 8000) {
      const params = new URLSearchParams(trimmed);
      if ([...params.keys()].length) {
        const obj = {};
        params.forEach((v, k) => { obj[k] = v; });
        text = JSON.stringify(obj, null, 2);
        kind = 'form';
      }
    }
  } catch { /* 保持原文 */ }
  const clipped = text.length > limit;
  text = text.slice(0, limit) + (clipped ? '\n…（已截断）' : '');
  return {
    kind,
    text,
    lines: text.split('\n').length,
    html: kind === 'json' || kind === 'form' ? highlightJson(text) : `<span class="json-plain">${safe(text)}</span>`,
  };
}

function highlightJson(text) {
  // 轻量着色：避免复杂正则在大报文上卡死主线程
  return safe(text)
    .replace(/(&quot;[^&]*&quot;)(\s*:)/g, '<span class="json-key">$1</span>$2')
    .replace(/(:\s*)(&quot;[^&]*&quot;)/g, '$1<span class="json-str">$2</span>')
    .replace(/(:\s*)(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)/g, '$1<span class="json-num">$2</span>')
    .replace(/(:\s*)(true|false|null)/g, '$1<span class="json-lit">$2</span>');
}

function payloadPanel(label, raw, limit) {
  const pretty = prettyPayload(raw, limit);
  if (pretty.kind === 'empty') return `<div class="api-packet-pane"><div class="empty">${label}为空</div></div>`;
  const badge = pretty.kind === 'json' ? 'JSON' : pretty.kind === 'form' ? 'Form → JSON' : 'Text';
  return `<div class="api-packet-pane">
    <div class="api-packet-toolbar">
      <span class="api-fmt-badge">${badge}</span>
      <span class="muted small-text">${label} · 已脱敏 · ${pretty.lines} 行</span>
      <button type="button" class="text-link" data-action="archive-copy">复制</button>
    </div>
    <pre class="api-json" tabindex="0">${pretty.html}</pre>
    <textarea class="api-copy-src" hidden readonly>${safe(pretty.text)}</textarea>
  </div>`;
}

function switchPacketTab(root, value) {
  if (!root) return;
  root.querySelectorAll('.api-packet-tab').forEach(b => {
    const on = b.getAttribute('data-value') === value;
    b.setAttribute('aria-pressed', on ? 'true' : 'false');
  });
  root.querySelectorAll('[data-packet-panel]').forEach(p => {
    const on = p.getAttribute('data-packet-panel') === value;
    p.classList.toggle('is-active', on);
    p.hidden = !on;
    p.style.display = on ? '' : 'none';
  });
  // 响应体懒渲染：首次点开再格式化，避免打开抽屉时卡顿
  const panel = root.querySelector(`[data-packet-panel="${value}"]`);
  const slot = panel?.querySelector('[data-lazy-id]');
  if (slot && !slot.dataset.ready) {
    const pack = packetLazy.get(slot.getAttribute('data-lazy-id')) || {};
    slot.dataset.ready = '1';
    slot.innerHTML = pack.raw != null && pack.raw !== ''
      ? payloadPanel('响应体', pack.raw, 16000)
      : `<div class="api-packet-pane"><div class="empty">${safe(pack.empty || '未入档响应正文')}</div></div>`;
  }
}

function openArchiveApiDrawer(index) {
  const apis = (archiveCache?.items || []).filter(i => i.kind === 'api');
  const item = apis[Number(index)];
  if (!item || typeof openDrawer !== 'function') return;
  const b = item.body || {};
  const ok = (b.status || 0) < 400;
  const method = (b.method || 'GET').toUpperCase();
  let path = b.url || '';
  try { path = new URL(b.url).pathname + new URL(b.url).search; } catch { /* keep */ }
  const lazyId = `pkt-${index}-${Date.now()}`;
  packetLazy.set(lazyId, {
    raw: b.response != null ? String(b.response) : '',
    empty: b.omitted || (b.sha256 ? `二进制响应 · sha256 ${b.sha256}` : '未入档响应正文'),
  });
  const body = `<div class="api-packet">
    <div class="api-packet-head">
      <div class="api-packet-line">
        <span class="api-method api-method-${method.toLowerCase()}">${safe(method)}</span>
        <span class="api-status ${ok ? 'is-ok' : 'is-err'}">${b.status ?? '—'}</span>
        <code class="api-url" title="${safe(b.url || '')}">${safe(path || b.url || '')}</code>
      </div>
      <div class="api-packet-meta muted small-text">
        <span>${safe(arcOpName(b.url))}</span>
        <span title="${safe(b.url || '')}">${safe(arcHost(b.url))}</span>
        <span>${arcClock(item.at)}</span>
        <span>${arcMs(b.ms)}</span>
        <span>${Math.round((b.bytes || 0) / 1024)} KB</span>
        ${b.content_type ? `<span>${safe(String(b.content_type).split(';')[0])}</span>` : ''}
        ${b.truncated ? '<span>响应已截断</span>' : ''}
      </div>
    </div>
    <div class="api-packet-tabs" role="tablist">
      <button type="button" class="api-packet-tab" data-action="archive-packet-tab" data-value="req" aria-pressed="true">请求体</button>
      <button type="button" class="api-packet-tab" data-action="archive-packet-tab" data-value="resp" aria-pressed="false">响应体</button>
    </div>
    <div class="api-packet-panels">
      <div class="is-active" data-packet-panel="req">${payloadPanel('请求体', b.request_body, 12000)}</div>
      <div data-packet-panel="resp" hidden style="display:none">
        <div data-lazy-id="${safe(lazyId)}">
          <div class="api-packet-pane"><div class="muted small-text" style="padding:12px 16px">点击「响应体」加载…</div></div>
        </div>
      </div>
    </div>
  </div>`;
  openDrawer(`${method} ${path || ''}`.trim(), '接口报文详情 · 已格式化', body, 'api-packet-dialog');
}

function openArchivePage(pageId) {
  if (!pageId || typeof openDrawer !== 'function') return;
  const src = `/api/archive/pages/${encodeURIComponent(pageId)}.png`;
  const body = `<div class="archive-shot-viewer">
    <img src="${src}?w=1400&amp;trim=1" alt="平台页面截图">
    <div class="archive-shot-viewer-actions">
      <a class="text-link" href="${src}?trim=1" target="_blank" rel="noopener">新窗口打开</a>
    </div>
  </div>`;
  openDrawer('平台页面截图', '网页操作留档 · 已裁切留白', body, 'archive-shot-dialog');
}

function openArchiveLlmDrawer(index) {
  const llms = (archiveCache?.items || []).filter(i => i.kind === 'llm');
  const item = llms[Number(index)];
  if (!item || typeof openDrawer !== 'function') return;
  const b = item.body || {};
  const payload = { messages: b.messages, output: b.output, raw: b.raw, error: b.error };
  const body = `<div class="api-packet">
    <div class="api-packet-head">
      <div class="api-packet-line"><strong>${safe(item.title || '模型调用')}</strong>
        ${b.ok ? statusTag('成功') : statusTag('失败')}</div>
      <div class="api-packet-meta muted small-text">
        <span>${safe(b.model || '—')}</span><span>${arcMs(b.ms)}</span>
        ${b.cached ? '<span>缓存命中</span>' : ''}
      </div>
    </div>
    ${payloadPanel('模型输入输出', JSON.stringify(payload), 14000)}
  </div>`;
  openDrawer(item.title || '模型调用', '模型调用详情', body, 'api-packet-dialog');
}

function handleArchiveAction(action, value, el) {
  if (action === 'archive-api') { openArchiveApiDrawer(value); return true; }
  if (action === 'archive-page') { openArchivePage(value); return true; }
  if (action === 'archive-llm') { openArchiveLlmDrawer(value); return true; }
  if (action === 'archive-shot') {
    if (!value) return true;
    const src = `/api/archive/shots/${encodeURIComponent(value)}.png`;
    if (typeof openDrawer === 'function') {
      openDrawer('证据截图', '规则定位截图', `<div class="archive-shot-viewer"><img src="${src}" alt="证据截图">
        <div class="archive-shot-viewer-actions"><a class="text-link" href="${src}" target="_blank" rel="noopener">新窗口打开</a></div></div>`,
        'archive-shot-dialog');
    } else {
      window.open(src, '_blank', 'noopener');
    }
    return true;
  }
  if (action === 'archive-packet-tab') {
    switchPacketTab(el?.closest('.api-packet'), value);
    return true;
  }
  if (action === 'archive-copy') {
    const src = el?.closest('.api-packet-pane')?.querySelector('textarea.api-copy-src');
    const text = src?.value || '';
    if (text) {
      navigator.clipboard?.writeText(text).then(() => showToast?.('已复制')).catch(() => showToast?.('复制失败'));
    }
    return true;
  }
  return false;
}

function renderArchive(a, workId) {
  archiveCache = a || null;
  if (!a) return '<div class="empty">该次审查没有执行档案。</div>';
  const v = a.versions || {};
  const items = a.items || [];
  const count = {};
  items.forEach(i => { count[i.kind] = (count[i.kind] || 0) + 1; });
  const llms = items.filter(i => i.kind === 'llm');
  const apis = items.filter(i => i.kind === 'api');
  const checks = items.filter(i => i.kind === 'check');
  const pages = items.filter(i => i.kind === 'page');
  const statusMap = { done: '已完成', failed: '失败', running: '执行中' };
  const status = statusMap[a.status] || a.status || '—';
  const dur = a.finished_at && a.started_at
    ? `${((a.finished_at - a.started_at)).toFixed(1)}s` : '—';
  const trigger = ({ auto: '自动审查', batch: '批量审查', web: '人工发起' }[a.trigger_by])
    || (String(a.trigger_by || '').startsWith('retry') ? '重新发起' : (a.trigger_by || '—'));
  const judge = ((v.llm || {}).judge || {}).model || '—';
  const regs = Array.isArray(v.regulations)
    ? `${v.regulations.filter(d => d.state === 'enabled').length} 份启用` : '—';
  const counts = Object.entries(count).map(([k, n]) => tag(`${ARC_KIND[k] || k} ${n}`, 'primary')).join('');

  return `<div class="meeting-archive">
    <div class="meeting-archive-head inline">
      <strong>执行档案</strong>
      <span class="mono">任务 ${safe(workId || (a.task_id || '').slice(0, 8))}</span>
      <span>${safe(a.request_id || '—')}</span>
      <span>${safe(trigger)}</span>
      ${statusTag(status)}
      <span class="mono">${safe(dur)}</span>
    </div>
    <div class="meeting-archive-meta">${metadata([
      ['规则版本', v.rules || '—'],
      ['代码版本', (v.code || '—').toString().slice(0, 16)],
      ['解析引擎', ((v.ocr || {}).engine) || '—'],
      ['判定模型', judge],
      ['制度文件', regs],
      ['材料指纹', (a.material_fp || '—').toString().slice(0, 16)],
    ])}</div>
    <div class="inline meeting-archive-counts">${counts}</div>
    ${a.error ? `<div class="workbench-error">${safe(a.error)}</div>` : ''}
    <div class="meeting-archive-platform-title inline"><strong>客户平台页面</strong>${tag(String(pages.length), 'primary')}</div>
    <p class="muted small-text">点击下方页面缩略图可打开整页截图；步骤中的「查看截图 / 查看详情」可查看网页操作截图与接口报文。</p>
    ${pages.length ? pages.map(i => arcPageCard(i.body, a.pages)).join('') : '<div class="empty">暂无平台页面截图</div>'}
    ${arcSection(`平台操作步骤 · ${apis.length} 次接口调用`, arcSteps(items))}
    ${(a.shots || []).length ? arcSection(`证据截图 · ${a.shots.length}`, `<div class="meeting-archive-shots">${(a.shots || []).map(s => `
      <figure>
        ${s.shot_id ? `<a href="/api/archive/shots/${encodeURIComponent(s.shot_id)}.png" target="_blank" rel="noopener">
          <img loading="lazy" src="/api/archive/shots/${encodeURIComponent(s.shot_id)}.png" alt=""></a>` : '<div class="empty">无图</div>'}
        <figcaption><b>${safe(s.rule_id)}</b> ${safe((s.filename || '').split('/').pop())}
          ${s.page_no ? ` · 第 ${s.page_no} 页` : ''}
          ${s.shot_id ? textButton('查看原图', 'archive-shot', s.shot_id) : ''}
          <div class="muted">「${safe((s.quote || '').slice(0, 80))}」</div>
        </figcaption>
      </figure>`).join('')}</div>`, true) : ''}
    ${arcSection(`模型调用 · ${llms.length} 次`,
      table(['用途', '模型', '缓存', '耗时', '结果', '操作'], llms.map((i, idx) => {
        const b = i.body || {};
        return `<tr><td>${safe(i.title)}</td><td>${safe(b.model || '—')}</td><td>${b.cached ? '命中' : '—'}</td>
          <td class="mono">${arcMs(b.ms)}</td><td>${b.ok ? statusTag('成功') : statusTag('失败')}</td>
          <td>${textButton('查看详情', 'archive-llm', String(idx))}</td></tr>`;
      }), '暂无模型调用'),
      false)}
    ${arcSection(`原文校验 · ${checks.length} 条`, checks.length
      ? checks.map(i => arcSection(i.title || '校验', `<pre class="archive-pre">${safe(JSON.stringify(i.body, null, 2).slice(0, 3000))}</pre>`, false)).join('')
      : '<div class="empty">暂无记录</div>', false)}
    ${arcSection(`接口报文 · ${apis.length} 次（已脱敏）`, apis.length
      ? table(['操作', '状态', '耗时', '大小', '详情'], apis.map((i, idx) => {
          const b = i.body || {};
          return `<tr><td title="${safe(b.url || '')}">${safe(i.title || arcOpName(b.url))}</td>
            <td>${b.status ?? '—'}</td><td class="mono">${arcMs(b.ms)}</td>
            <td>${Math.round((b.bytes || 0) / 1024)} KB</td>
            <td>${textButton('查看详情', 'archive-api', String(idx))}</td></tr>`;
        }))
      : '<div class="empty">暂无记录</div>', false)}
    ${arcSection(`完整时间线 · ${items.length} 条`, items.length
      ? `<ol class="meeting-archive-events">${items.map(i => `<li>${tag(ARC_KIND[i.kind] || i.kind, 'primary')}
          <span>${safe(i.title || '')}</span><time class="mono muted">${arcClock(i.at)}</time></li>`).join('')}</ol>`
      : '<div class="empty">暂无记录</div>', false)}
  </div>`;
}

async function loadArchivePanel(taskId, workId, mount) {
  if (!mount) return;
  archiveCache = null;
  if (!taskId) {
    mount.innerHTML = '<div class="ui-notice">任务尚未执行，暂无执行档案。待审查完成后可在此查看平台页面、接口步骤与模型调用。</div>';
    return;
  }
  mount.innerHTML = '<div class="workbench-loading">加载执行档案…</div>';
  try {
    const data = await api(`/api/runs/${encodeURIComponent(taskId)}/archive`);
    mount.innerHTML = renderArchive(data, workId);
  } catch (err) {
    mount.innerHTML = `<div class="workbench-error">${safe(err.message || '加载执行档案失败')}</div>`;
  }
}
