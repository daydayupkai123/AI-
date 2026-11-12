'use strict';

async function api(path, options = {}) {
  const opts = {
    credentials: 'same-origin',
    headers: { Accept: 'application/json', ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...(options.headers || {}) },
    ...options,
  };
  if (opts.body && typeof opts.body !== 'string') opts.body = JSON.stringify(opts.body);
  const res = await fetch(path, opts);
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { detail: text }; }
  if (!res.ok) {
    const err = new Error((data && (data.detail || data.message)) || `请求失败 ${res.status}`);
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

const AuthAPI = {
  me: () => api('/api/auth/me'),
  login: (username, password) => api('/api/auth/login', { method: 'POST', body: { username, password } }),
  logout: () => api('/api/auth/logout', { method: 'POST' }),
};

const WorkAPI = {
  list: (employee) => api(`/api/${employee}/worklist`),
  detail: (employee, id) => api(`/api/${employee}/worklist/${encodeURIComponent(id)}`),
  saveMarks: (employee, id, marks) => api(`/api/${employee}/worklist/${encodeURIComponent(id)}/marks`, {
    method: 'PUT', body: { marks },
  }),
  retry: (employee, id) => api(`/api/${employee}/worklist/${encodeURIComponent(id)}/retry`, { method: 'POST' }),
  collect: (employee) => api(`/api/${employee}/collect`, { method: 'POST' }).catch(() =>
    api('/api/resource/collect', { method: 'POST', body: { employee } }).catch(() => null)),
};
