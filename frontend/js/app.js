'use strict';

const appState = {
  user: null,
  route: 'meetings',
  workId: '',
  sidebarCollapsed: false,
};

const navigationGroups = [
  ['审核工作台（一期）', [
    ['tasks', '财务报销初审', 'list'],
    ['meetings', '三会智能审查', 'assistant'],
    ['procurement', '采购审批', 'file'],
    ['contracts', '合同审核', 'file'],
  ]],
  ['审核工作台（二期）', [
    ['overview', '统计看版', 'dashboard', true],
    ['rules', '规则管理', 'rules', true],
    ['permissions', '权限管理', 'rules', true],
  ]],
];

const routeEmployee = {
  meetings: 'meeting', procurement: 'procurement', contracts: 'contract', tasks: 'reimburse',
};

function parseHash() {
  const raw = (location.hash || '#meetings').replace(/^#/, '');
  const [route, workId = ''] = raw.split('/');
  const known = Object.keys(routeEmployee).concat(['overview', 'rules', 'permissions', 'login']);
  return {
    route: known.includes(route) ? route : 'meetings',
    workId: workId || '',
  };
}

function renderSidebar() {
  const nav = document.getElementById('sidebar-nav');
  nav.innerHTML = navigationGroups.map(([title, items]) => {
    const links = items.map(([key, label, glyph, phase2]) => {
      const active = appState.route === key ? ' aria-current="page"' : '';
      const cls = phase2 ? 'nav-link phase-muted' : 'nav-link';
      const href = phase2 ? 'javascript:void(0)' : `#${key}`;
      const tip = phase2 ? ' title="二期规划"' : '';
      return `<a class="${cls}" href="${href}" data-route="${key}"${active}${tip}>${icon(glyph, 'small')}<span>${label}</span></a>`;
    }).join('');
    return `<div class="nav-group"><div class="nav-group-title">${title}</div>${links}</div>`;
  }).join('');
}

function updateChrome() {
  const u = appState.user;
  document.getElementById('user-avatar').textContent = (u?.name || '?').slice(0, 1);
  document.getElementById('user-label').textContent = u
    ? `${u.name} · ${u.role_name || u.role || ''}` : '';
  renderSidebar();
  document.getElementById('shell').classList.toggle('sidebar-collapsed', appState.sidebarCollapsed);
  document.getElementById('sidebar-toggle').setAttribute('aria-expanded', String(!appState.sidebarCollapsed));
  document.getElementById('sidebar-toggle').innerHTML = icon(appState.sidebarCollapsed ? 'sidebarExpand' : 'sidebar', 'small');
}

function showLogin(error = '') {
  const shell = document.getElementById('shell');
  shell.hidden = true;
  shell.setAttribute('hidden', '');
  const root = document.getElementById('login-root');
  root.hidden = false;
  root.removeAttribute('hidden');
  // removeAttribute 后再显式打开，避免个别浏览器 hidden 状态不同步
  root.hidden = false;
  root.innerHTML = `<form class="login-card" id="login-form">
    <h1>财务审核数字员工</h1>
    <p>请使用工作台账号登录。一期支持管理员、复核员、只读人员。</p>
    ${error ? `<p class="login-error">${safe(error)}</p>` : ''}
    <label><span>账号</span><input class="ui-input" name="username" autocomplete="username" required autofocus></label>
    <label><span>密码</span><input class="ui-input" type="password" name="password" autocomplete="current-password" required></label>
    <div class="login-actions"><button class="ui-btn ui-btn-primary" type="submit" style="flex:1">登录</button></div>
  </form>`;
  document.getElementById('login-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(e.target);
    try {
      await AuthAPI.login(String(fd.get('username')), String(fd.get('password')));
      await boot();
    } catch (err) {
      showLogin(err.message || '登录失败');
    }
  });
}

function showShell() {
  const root = document.getElementById('login-root');
  root.hidden = true;
  root.setAttribute('hidden', '');
  root.innerHTML = '';
  const shell = document.getElementById('shell');
  shell.hidden = false;
  shell.removeAttribute('hidden');
  shell.hidden = false;
  updateChrome();
}

async function renderView() {
  const view = document.getElementById('view');
  const { route, workId } = parseHash();
  appState.route = route;
  appState.workId = workId;
  updateChrome();

  if (routeEmployee[route]) {
    wbState.detailTab = workId ? wbState.detailTab : 'results';
    await renderWorkbench(route, workId, appState.user, view);
    return;
  }
  view.innerHTML = `${`<div class="breadcrumbs"><span>审核工作台（二期）</span>${icon('chevron', 'small')}<strong>规划中</strong></div>`}
    <div class="page-head"><div class="ui-page-title"><h1>二期功能</h1>
    <p>统计看版、规则管理、权限管理将在二期提供。当前请使用左侧一期审核工作台。</p></div></div>`;
}

function navigate(hash) {
  if (location.hash === hash) renderView();
  else location.hash = hash;
}

async function boot() {
  try {
    const me = await AuthAPI.me();
    appState.user = me;
    showShell();
    await renderView();
  } catch (err) {
    appState.user = null;
    showLogin(err.status === 401 ? '' : (err.message || '无法连接工作台'));
  }
}

document.getElementById('logout-btn')?.addEventListener('click', async () => {
  try { await AuthAPI.logout(); } catch { /* ignore */ }
  appState.user = null;
  showLogin();
});

document.getElementById('sidebar-toggle')?.addEventListener('click', () => {
  appState.sidebarCollapsed = !appState.sidebarCollapsed;
  updateChrome();
});

document.addEventListener('click', async (e) => {
  const btn = e.target.closest('[data-action]');
  if (!btn) return;
  const handled = await handleWorkbenchAction(btn.dataset.action, btn.dataset.value, btn, appState.user, navigate);
  if (handled) e.preventDefault();
});

window.addEventListener('hashchange', () => {
  if (appState.user) renderView();
});

boot();
