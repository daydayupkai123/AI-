'use strict';

const icons = {
  dashboard: '<rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>',
  list: '<rect x="5" y="4" width="14" height="17" rx="2"/><path d="M9 4V3h6v1M9 9h6M9 13h6M9 17h4"/>',
  assistant: '<path d="M20 11.5a7.5 7.5 0 0 1-7.5 7.5H5l1.3-3.3A7.5 7.5 0 1 1 20 11.5Z"/><path d="M9 11.5h.1m3.4 0h.1m3.4 0h.1" stroke-width="2.5"/>',
  rules: '<path d="M4 6h16M4 12h16M4 18h16"/><circle cx="8" cy="6" r="2" fill="var(--ui-surface)"/><circle cx="15" cy="12" r="2" fill="var(--ui-surface)"/><circle cx="10" cy="18" r="2" fill="var(--ui-surface)"/>',
  monitor: '<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8m-4-4v4M8 10l3 3 5-5"/>',
  chevron: '<path d="m9 6 6 6-6 6"/>',
  sidebar: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M9 5v14m7-10-3 3 3 3"/>',
  sidebarExpand: '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M9 5v14m4-10 3 3-3 3"/>',
  check: '<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',
  alert: '<path d="M11 4 3 18a1.15 1.15 0 0 0 1 2h16a1.15 1.15 0 0 0 1-2L13 4a1.15 1.15 0 0 0-2 0ZM12 9v4m0 3v.2"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l4 2"/>',
  search: '<circle cx="10.5" cy="10.5" r="5.5"/><path d="m15 15 4 4"/>',
  file: '<path d="M6 3h8l4 4v14H6zM14 3v5h4M9 12h6m-6 4h6"/>',
  refresh: '<path d="M19 11a7 7 0 1 0-1 5m1-11v6h-6"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5m0-8v.2"/>',
  x: '<path d="m6 6 12 12M18 6 6 18"/>',
};

function icon(name, size = '') {
  return `<svg class="icon ${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name] || ''}</svg>`;
}

function safe(value) {
  return String(value ?? '').replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
}

function moneyish(value) {
  if (value == null || value === '') return '—';
  return String(value);
}

const tones = {
  已完成: 'success', 初审通过: 'success', 已复核: 'success', 启用: 'success',
  执行中: 'primary', 待审核: 'primary',
  风险提示: 'warning', 无法校验: 'warning', 待执行: 'warning', 待复核: 'warning', 确认问题: 'warning',
  失败: 'danger', 建议驳回: 'danger', 审查中止: 'danger',
  未执行: '', 不适用: '', 误报: 'primary', 已忽略: '',
};

function tag(label, tone, dot = false) {
  const t = tone || tones[label] || '';
  return `<span class="ui-tag${t ? ` ui-tag-${t}` : ''}">${dot ? '<span class="status-dot"></span>' : ''}${safe(label)}</span>`;
}

function statusTag(label) { return tag(label, tones[label], true); }

function button(label, action, { value = '', style = '', glyph = '', disabled = false } = {}) {
  return `<button type="button" class="ui-btn${style ? ` ui-btn-${style}` : ''}" data-action="${action}" data-value="${safe(value)}"${disabled ? ' disabled' : ''}>${glyph ? icon(glyph, 'small') : ''}${safe(label)}</button>`;
}

function textButton(label, action, value = '') {
  return `<button class="text-link" type="button" data-action="${action}" data-value="${safe(value)}">${safe(label)}</button>`;
}

function card(title, subtitle = '', action = '') {
  return `<div class="card-heading"><div><h2 class="ui-card-title">${safe(title)}</h2>${subtitle ? `<p class="card-subtitle">${safe(subtitle)}</p>` : ''}</div>${action}</div>`;
}

function metadata(pairs) {
  return `<dl class="detail-meta">${pairs.map(([name, value]) =>
    `<div><dt>${safe(name)}</dt><dd>${safe(value)}</dd></div>`).join('')}</dl>`;
}

function table(headers, rows, empty = '暂无符合条件的记录') {
  return `<div class="table-scroll"><table class="ui-table"><thead><tr>${headers.map(h => `<th scope="col">${safe(h)}</th>`).join('')}</tr></thead>
    <tbody>${rows.length ? rows.join('') : `<tr><td colspan="${headers.length}"><div class="empty">${safe(empty)}</div></td></tr>`}</tbody></table></div>`;
}

function tabs(action, options, current) {
  return `<div class="tabs">${options.map(([value, label]) =>
    `<button type="button" data-action="${action}" data-value="${value}" aria-pressed="${value === current}">${label}</button>`).join('')}</div>`;
}

function fmtTime(ts) {
  if (!ts) return '—';
  const d = new Date(typeof ts === 'number' ? (ts < 1e12 ? ts * 1000 : ts) : ts);
  if (Number.isNaN(d.getTime())) return '—';
  const p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

function fmtDuration(ms) {
  if (ms == null || ms < 0) return '—';
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  return m ? `${m}分${s % 60}秒` : `${s}秒`;
}

function showToast(message) {
  const el = document.getElementById('toast');
  if (!el) return;
  el.hidden = false;
  el.textContent = message;
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => { el.hidden = true; }, 2200);
}

function canReview(user) {
  return user && (user.role === 'admin' || user.role === 'reviewer');
}
