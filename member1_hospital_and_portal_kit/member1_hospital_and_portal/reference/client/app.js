'use strict';
/* Portal runtime: reads portal.xml and renders dashboards, forms and the history timeline.
   Nothing here is specific to a role; to change what a role sees, edit portal.xml. */

const $ = (s, r = document) => r.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const kids = (el, tag) => [...el.children].filter(c => c.tagName === tag);
const attr = (el, n, d = '') => el.getAttribute(n) ?? d;
const fill = (t, row) => t.replace(/\{(\w+)\}/g, (_, k) => row[k] ?? '');
const has = (t, row) => [...t.matchAll(/\{(\w+)\}/g)].some(m => row[m[1]]);
const today = () => new Date().toLocaleDateString('en-CA');  // YYYY-MM-DD in local time
const vitalsText = r => [r.bp_sys && r.bp_dia ? `BP ${r.bp_sys}/${r.bp_dia}` : '', r.temp ? `${r.temp} °C` : '',
  r.pulse ? `pulse ${r.pulse}` : '', r.spo2 ? `SpO2 ${r.spo2}%` : '', r.vitals || ''].filter(Boolean).join(', ');
const rng = fd => ['min', 'max', 'step'].filter(k => attr(fd, k)).map(k => `${k}="${esc(attr(fd, k))}"`).join(' ');
const test = (cond, row) => !cond || cond.replaceAll('{today}', today()).replaceAll('{me}', S ? S.user : '').split(',').every(c => {
  const m = c.match(/^(\w+)(!?)=(.*)$/);
  return (String(row[m[1]] ?? '') === m[3]) !== (m[2] === '!');
});
const TONE = {pending: 'amber', open: 'blue', completed: 'green', reported: 'green', dispensed: 'green', closed: 'green', scheduled: 'blue', cancelled: 'red', yes: 'green', no: 'red', active: 'blue',
  treating: 'blue', referred: 'amber', 'treated by specialist': 'green', 'treatment recommended': 'blue', treated: 'green', recommended: 'blue',
  200: 'green', 401: 'amber', 403: 'amber', 404: 'amber', 409: 'amber', 422: 'amber', 500: 'red', 503: 'red'};
const when = v => {
  const d = new Date(String(v).replace(' ', 'T') + 'Z');
  return isNaN(d) ? esc(v) : d.toLocaleString([], {day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'});
};

let X, data = {}, names = {}, people = {}, mineOn = true, tab = 0, query = '', sort = {f: null, dir: 1}, notes = [], unread = 0;
let S = null;
try { S = JSON.parse(sessionStorage.getItem('pps') || 'null'); } catch { /* storage unavailable */ }
const dlg = $('#dlg');
const cv = (c, r) => c.t === 'patient' ? (names[r[c.f]] ?? r[c.f]) : c.t === 'person' ? (people[r[c.f]] ?? r[c.f]) : c.t === 'vitals' ? vitalsText(r) : r[c.f];  // value as shown, for search, sort and export

/* ---------- api ---------- */
async function api(method, path, body) {
  const r = await fetch(path, {
    method,
    headers: {'content-type': 'application/json', accept: 'application/json', authorization: 'Bearer ' + S.token},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (r.status === 401) { logout(); throw new Error('Your session has ended. Log in again.'); }
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(typeof d.detail === 'string' ? d.detail : Array.isArray(d.detail) ? d.detail.map(x => x.msg).join('; ') : 'Request failed'), {status: r.status});
  return d;
}

function toast(msg, tone = 'green') {
  const t = document.createElement('div');
  t.className = 'toast ' + tone; t.textContent = msg;
  $('#toasts').append(t);
  setTimeout(() => t.remove(), 6000);
}

/* ---------- login ---------- */
const roleEl = () => X.querySelector(`portal > role[name="${S.role}"]`);

function buildLogin() {
  $('#login-form').onsubmit = async e => {
    e.preventDefault();
    $('#login-error').textContent = '';
    const user = $('#u').value.trim();
    try {
      const r = await fetch('/auth/login', {method: 'POST', headers: {'content-type': 'application/json'},
        body: JSON.stringify({username: user, password: $('#p').value})});
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail);
      S = {token: d.token, role: d.role, user: d.username || user, name: d.name || user, mustChange: !!d.must_change};
      try { sessionStorage.setItem('pps', JSON.stringify(S)); } catch { /* ignore */ }
      $('#p').value = '';
      start();
    } catch (err) {
      $('#login-error').textContent = err.message === 'Failed to fetch' ? 'Cannot reach the server.' : err.message;
    }
  };
}

function logout() {
  S = null; data = {}; notes = []; unread = 0; $('#bell-n').hidden = true;
  try { sessionStorage.removeItem('pps'); } catch { /* ignore */ }
  $('#login-view').hidden = false; $('#app-view').hidden = true; $('#who').hidden = true;
  $('#status').innerHTML = '';
  if (dlg.open) dlg.close();
}

function start() {
  if (!S || !roleEl()) return logout();
  $('#login-view').hidden = true; $('#app-view').hidden = false; $('#who').hidden = false;
  $('#who-name').textContent = S.name || S.user; $('#who-role').textContent = attr(roleEl(), 'label');
  tab = 0; query = ''; $('#q').value = '';
  data = {}; render();  // show the dashboard frame at once; tiles and tables fill in as the answers arrive
  load(); loadNotes();
  if (S.mustChange) {  // a password someone else chose: pick your own first
    toast('Please choose your own password before you continue.', 'amber');
    openForm('password');
  }
}

/* ---------- data ---------- */
async function refreshStatus() {
  try {
    const s = await api('GET', '/api/status');
    $('#status').innerHTML = Object.entries(s).map(([n, up]) =>
      `<span class="svc ${up ? '' : 'down'}" title="${up ? 'Online' : 'Offline'}"><i aria-hidden="true"></i>${esc(n)}<span class="sr-only"> ${up ? 'online' : 'offline'}</span></span>`).join('');
  } catch { $('#status').innerHTML = ''; }
}

let drawing = false;
function redraw() {  // many answers can arrive together: draw once per frame
  if (drawing || !S) return;
  drawing = true;
  requestAnimationFrame(() => { drawing = false; if (S) { names = Object.fromEntries((Array.isArray(data['/patients']) ? data['/patients'] : []).map(p => [p.id, p.name]));
    people = Object.fromEntries((Array.isArray(data['/api/people']) ? data['/api/people'] : []).map(p => [p.username, p.full_name])); render(); } });
}

async function load() {
  const role = roleEl();
  const sources = [...new Set([...role.querySelectorAll('stat,panel,chart,preload')].map(e => attr(e, 'source')))];
  refreshStatus();  // the status lights fill in on their own; nothing waits for them
  await Promise.all(sources.map(s => api('GET', s).then(rows => rows, err => err).then(r => { data[s] = r; redraw(); })));
}
const rowsOf = (src, where) => Array.isArray(data[src]) ? data[src].filter(r => test(where, r)) : null;

/* ---------- dashboard ---------- */
function render() {
  const role = roleEl();
  $('#hero-title').textContent = attr(role, 'title');
  $('#hero-sub').textContent = attr(role, 'blurb');
  $('#hero-actions').innerHTML = kids(role, 'button').map(b =>
    `<button class="btn primary" data-form="${esc(attr(b, 'form'))}" data-fill="${esc(attr(b, 'fill'))}">${esc(attr(b, 'label'))}</button>`).join('');
  $('#stats').innerHTML = kids(role, 'stat').map(s => {
    const rows = rowsOf(attr(s, 'source'), attr(s, 'where'));
    return `<div class="stat ${attr(s, 'tone', 'blue')}" role="listitem"><div><b>${rows ? rows.length : '–'}</b><small>${esc(attr(s, 'label'))}</small></div></div>`;
  }).join('');
  $('#charts').innerHTML = kids(role, 'chart').map(chart).join('');
  renderTabs();
}

function chart(c) {
  const rows = rowsOf(attr(c, 'source'), attr(c, 'where'));
  let body;
  if (!rows) body = `<p class="dim">${data[attr(c, 'source')] === undefined ? 'Loading...' : 'This service is offline.'}</p>`;
  else {
    const g = {};
    rows.forEach(r => { const k = r[attr(c, 'group')]; g[k] = (g[k] || 0) + 1; });
    const max = Math.max(1, ...Object.values(g));
    body = Object.keys(g).length
      ? Object.entries(g).map(([k, n]) => `<div class="bar"><span>${esc(k)}</span><div><i class="${TONE[k] || 'blue'}" style="width:${n / max * 100}%"></i></div><b>${n}</b></div>`).join('')
      : '<p class="dim">Nothing to show yet.</p>';
  }
  return `<section class="card chart"><h3>${esc(attr(c, 'title'))}</h3>${body}</section>`;
}

const panelEl = () => kids(roleEl(), 'panel')[tab];
const panelRows = p => {  // the panel's rows, narrowed to the signed-in person's own when the panel says mine="column" and "Only mine" is ticked
  const rows = rowsOf(attr(p, 'source'), attr(p, 'where'));
  return rows && attr(p, 'mine') && mineOn ? rows.filter(r => r[attr(p, 'mine')] === S.user) : rows;
};

function renderTabs() {
  const panels = kids(roleEl(), 'panel');
  if (tab >= panels.length) tab = 0;
  $('#tabs').innerHTML = panels.map((p, i) => {
    const n = panelRows(p);
    return `<button role="tab" id="tab-${i}" aria-controls="table" tabindex="${i === tab ? 0 : -1}" aria-selected="${i === tab}" data-tab="${i}">${esc(attr(p, 'title'))}<em>${n ? n.length : '–'}</em></button>`;
  }).join('');
  $('#table').setAttribute('aria-labelledby', `tab-${tab}`);
  renderTable();
}

function cell(type, v, row) {
  if (type === 'person') return v ? esc(people[v] ?? v) : '<span class="dim">–</span>';
  if (type === 'vitals') { const t = vitalsText(row); return t ? esc(t) : '<span class="dim">–</span>'; }
  if (type === 'interaction') return v ? `<span class="badge amber">${esc(v)}</span>` : '<span class="badge green plain">None found</span>';
  if (type === 'warn') return v ? `<span class="badge red">${esc(v)}</span>` : '<span class="badge green plain">Clear</span>';
  if (v === '' || v == null) return '<span class="dim">–</span>';
  switch (type) {
    case 'badge': return `<span class="badge ${TONE[v] || 'blue'}">${esc(v)}</span>`;
    case 'chips': return String(v).split(',').map(a => `<span class="chip">${esc(a.trim())}</span>`).join('');
    case 'time': return when(v);
    case 'patient': return esc(names[v] ? names[v] : 'Patient #' + v);
    default: return esc(v);
  }
}

function view() {
  const p = panelEl(), all = panelRows(p);
  $('#mine-wrap').hidden = !attr(p, 'mine');
  if (!all) return {p, all};
  const cols = attr(p, 'columns').split(',').map(c => { const [f, l, t] = c.split(':'); return {f, l, t}; });
  const q = query.toLowerCase();
  const val = cv;
  const text = (c, r) => String(val(c, r) ?? '').toLowerCase();
  const byDefault = attr(p, 'sort').split(',').filter(Boolean);
  const base = attr(p, 'newest') === 'first' || byDefault.length ? all.slice() : all.slice().reverse();
  const rows = base.filter(r => !q || cols.some(c => text(c, r).includes(q)));
  const keys = sort.f ? [sort.f] : byDefault, dir = sort.f ? sort.dir : 1;
  if (keys.length) rows.sort((a, b) => {
    for (const k of keys) {
      const c = cols.find(x => x.f === k) || {f: k}, x = val(c, a), y = val(c, b);
      const num = x !== '' && y !== '' && !isNaN(x) && !isNaN(y);
      const d = (num ? x - y : String(x ?? '').localeCompare(String(y ?? ''))) * dir;
      if (d) return d;
    }
    return 0;
  });
  return {p, all, cols, rows, acts: kids(p, 'rowaction')};
}

function renderTable() {
  const {p, all, cols, rows, acts} = view(), box = $('#table');
  if (data[attr(p, 'source')] === undefined) { box.innerHTML = '<div class="empty" role="status">Loading...</div>'; return; }
  if (!all) {
    box.innerHTML = '<div class="notice down"><b>This service is offline.</b> The rest of the portal keeps working. <button class="btn small" data-reload>Try again</button></div>';
    return;
  }
  if (!rows.length) {
    box.innerHTML = `<div class="empty">${esc(query ? `No matches for "${query}".` : attr(p, 'empty', 'Nothing here yet.'))}</div>`;
    return;
  }
  box.innerHTML = `<div class="table-wrap"><table><thead><tr>${cols.map(c => `<th aria-sort="${sort.f === c.f ? (sort.dir > 0 ? 'ascending' : 'descending') : 'none'}"><button class="sort" data-sort="${c.f}">${esc(c.l)}</button></th>`).join('')}${acts.length ? '<th></th>' : ''}</tr></thead><tbody>${
    rows.map(r => `<tr>${cols.map(c => `<td data-label="${esc(c.l)}">${cell(c.t, r[c.f], r)}</td>`).join('')}${acts.length
      ? `<td class="acts">${acts.map((a, i) => test(attr(a, 'when'), r) ? `<button class="btn small" data-act="${i}" data-id="${r.id}">${esc(attr(a, 'label'))}</button>` : '').join('')}</td>` : ''}</tr>`).join('')
  }</tbody></table></div>`;
}

function exportCsv() {  // exactly what is on screen: current tab, search and sort
  const {p, cols, rows} = view();
  if (!rows) return toast('Nothing to export: this service is offline.', 'amber');
  const field = (c, r) => {
    let v = String(cv(c, r) ?? '');
    if (/^[=+\-@]/.test(v)) v = "'" + v;  // stop spreadsheets running a cell as a formula
    return '"' + v.replace(/"/g, '""') + '"';
  };
  const csv = [cols.map(c => `"${c.l}"`).join(','), ...rows.map(r => cols.map(c => field(c, r)).join(','))].join('\r\n');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob(['\ufeff' + csv], {type: 'text/csv'}));
  a.download = `${attr(p, 'title').toLowerCase().replace(/\W+/g, '-')}-${today()}.csv`;
  a.click(); URL.revokeObjectURL(a.href);
  toast(`Exported ${rows.length} row${rows.length === 1 ? '' : 's'}.`);
}

/* ---------- notifications ---------- */
async function loadNotes(live) {
  try {
    notes = await api('GET', '/notifications');
    const n = notes.filter(x => x.unread).length;
    $('#bell-n').hidden = !n; $('#bell-n').textContent = n > 9 ? '9+' : n;
    $('#bell').setAttribute('aria-label', n ? `Notifications, ${n} unread` : 'Notifications');
    const grew = live && n > unread;
    unread = n;
    if (grew) { toast('You have new notifications.', 'amber'); load(); }
  } catch { /* ignore: the bell just stays as it was */ }
}

async function showNotes() {
  openDialog(`<div class="sheet"><h2>Notifications</h2>${notes.length
    ? `<ul class="nl">${notes.map(n => `<li class="${n.unread ? 'unread' : ''}"><span>${esc(n.text)}</span><small>${when(n.time)}</small></li>`).join('')}</ul>`
    : '<p class="empty">Nothing yet. Updates from other departments appear here.</p>'}<div class="row end"><button class="btn" data-close>Close</button></div></div>`);
  try { await api('POST', '/notifications/read'); unread = 0; $('#bell-n').hidden = true; $('#bell').setAttribute('aria-label', 'Notifications'); } catch { /* ignore */ }
}

/* ---------- dialogs ---------- */
let opener = null;
function openDialog(html, wide) {
  dlg.onclose = null;
  dlg.className = wide ? 'wide' : '';
  dlg.innerHTML = html;
  const h = dlg.querySelector('h2');
  if (h) { h.id = 'dlg-title'; dlg.setAttribute('aria-labelledby', 'dlg-title'); } else dlg.removeAttribute('aria-labelledby');
  if (!dlg.open) { opener = document.activeElement; dlg.showModal(); }
}
dlg.addEventListener('close', () => { if (opener && opener.isConnected) opener.focus(); else if (S) $('#table').focus?.(); });
dlg.addEventListener('click', e => { if (e.target === dlg || e.target.closest('[data-close]')) dlg.close(); });

function confirmBox(title, msg, ok, danger) {
  return new Promise(res => {
    openDialog(`<div class="sheet"><h2>${esc(title)}</h2><p class="pre">${esc(msg)}</p><div class="row end"><button class="btn" data-close>Cancel</button><button class="btn ${danger ? 'danger' : 'primary'}" id="ok">${esc(ok)}</button></div></div>`);
    $('#ok').onclick = () => { res(true); dlg.close(); };
    dlg.onclose = () => res(false);
  });
}

const parseFill = (spec, row = {}) => Object.fromEntries((spec || '').split(',').filter(Boolean).map(kv => { const [k, v] = kv.split('='); return [k, fill(v, row)]; }));
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

async function openForm(name, preset = {}, values = {}) {
  const f = X.querySelector(`form[name="${name}"]`);
  const sources = {};  // pickers (type="choice") read their options from the system, for example the doctors on the staff list
  await Promise.all([...f.querySelectorAll('field[type="choice"]')].filter(fd => !(attr(fd, 'name') in preset)).map(async fd => {
    const src = attr(fd, 'source');
    if (!(src in sources)) sources[src] = await api('GET', src).catch(() => []);
  }));
  const fields = [...f.querySelectorAll('field')].map(fd => {
    const n = attr(fd, 'name'), t = attr(fd, 'type', 'text'), req = attr(fd, 'required') ? 'required' : '';
    const label = esc(attr(fd, 'label', n)), ph = esc(attr(fd, 'placeholder'));
    const hint = attr(fd, 'hint') ? `<small>${esc(attr(fd, 'hint'))}</small>` : '';
    const wide = attr(fd, 'wide') || t === 'textarea' ? ' full' : '';
    if (n in preset) {
      const shown = n === 'patient_id' && names[preset[n]] ? `${names[preset[n]]} (patient #${preset[n]})` : preset[n];
      return `<input type="hidden" name="${n}" value="${esc(preset[n])}"><div class="field full"><span class="lbl">${label}</span><div class="locked">${esc(shown)}</div></div>`;
    }
    const val = esc(values[n] ?? '');
    let el;
    if (t === 'patient' && Object.keys(names).length) el = `<select name="${n}" ${req}><option value="">Choose a patient...</option>${Object.entries(names).sort((a, b) => a[1].localeCompare(b[1])).map(([id, nm]) => `<option value="${id}">${esc(nm)} (#${id})</option>`).join('')}</select>`;
    else if (t === 'choice') {
      const vf = attr(fd, 'value'), lf = attr(fd, 'label_field', vf);
      let rows = Array.isArray(sources[attr(fd, 'source')]) ? sources[attr(fd, 'source')] : [];
      if (attr(fd, 'unique')) { const seen = new Set(); rows = rows.filter(r => !seen.has(r[vf]) && seen.add(r[vf])); }
      el = `<select name="${n}" ${req}><option value="">${esc(attr(fd, 'any', 'Choose...'))}</option>${rows.map(r => `<option value="${esc(r[vf])}" ${r[vf] === values[n] ? 'selected' : ''}>${esc(r[lf])}</option>`).join('')}</select>`;
    }
    else if (t === 'days') {
      const on = String(values[n] ?? '').split(',');
      return `<fieldset class="field full days"><legend class="lbl">${label}</legend>${DAYS.map(d => `<label class="chk"><input type="checkbox" name="${n}" value="${d}" ${on.includes(d) ? 'checked' : ''}> ${d}</label>`).join('')}${hint}</fieldset>`;
    }
    else if (t === 'textarea') el = `<textarea name="${n}" rows="3" ${req} placeholder="${ph}">${val}</textarea>`;
    else if (t === 'select') el = `<select name="${n}" ${req}><option value="">Choose...</option>${attr(fd, 'options').split(',').map(o => { const [v, l] = o.split('|'); return `<option value="${esc(v)}" ${v === values[n] ? 'selected' : ''}>${esc(l ?? v)}</option>`; }).join('')}</select>`;
    else el = `<input type="${t === 'patient' ? 'number' : t}" name="${n}" ${req} placeholder="${ph}" value="${val}" ${rng(fd)}>`;
    return `<label class="field${wide}"><span class="lbl">${label}</span>${el}${hint}</label>`;
  }).join('');
  openDialog(`<form class="sheet" id="f"><h2>${esc(attr(f, 'title'))}</h2><div class="${attr(f, 'columns') === '2' ? 'grid2' : ''}">${fields}</div><p class="error" role="alert"></p><div class="row end"><button type="button" class="btn" data-close>Cancel</button><button class="btn primary">${esc(attr(f, 'submit', 'Save'))}</button></div></form>`);
  $('#f').onsubmit = async e => {
    e.preventDefault();
    const entries = [...new FormData(e.target)];
    const v = {};  // PUT may clear a field; several values for one name (ticked days) are joined with commas
    for (const [k, x] of entries) { if (attr(f, 'method') !== 'PUT' && x === '') continue; v[k] = k in v && v[k] !== '' ? v[k] + ',' + x : x; }
    const raw = attr(f, 'path');
    const body = Object.fromEntries(Object.entries(v).filter(([k]) => !raw.includes(`{${k}}`)));
    const btn = e.submitter; btn.disabled = true;
    try {
      const d = await api(attr(f, 'method'), fill(raw, v), body);
      dlg.close();
      done(d, attr(f, 'success'));
    } catch (err) {
      $('#f .error').textContent = err.status === 503 ? err.message + ' Try again when it is back online.' : err.message;
      btn.disabled = false;
    }
  };
}

function done(d, tpl) {
  if (S && S.mustChange && tpl === 'Your password was changed.') { S.mustChange = false; try { sessionStorage.setItem('pps', JSON.stringify(S)); } catch { /* ignore */ } }
  if (d.queued) toast(d.detail, 'amber');  // the service was offline: the gateway kept the request and will deliver it
  else {
    const named = {...d};  // {doctor_name} is the full name for {doctor}, and so on for any username in the answer
    for (const [k, v] of Object.entries(d)) if (typeof v === 'string' && people[v]) named[k + '_name'] = people[v];
    toast(fill(tpl || 'Saved.', named));
  }
  if (d.warning) toast('Allergy warning: ' + d.warning, 'red');
  if (d.interaction) toast('Drug interaction: ' + d.interaction, 'amber');
  if (d.sync_warning) toast(d.sync_warning, 'amber');
  load();
}

async function download(path, name) {  // authenticated file download (the discharge summary PDF)
  try {
    const r = await fetch(path, {headers: {authorization: 'Bearer ' + S.token}});
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || 'Download failed');
    const a = document.createElement('a');
    a.href = URL.createObjectURL(await r.blob()); a.download = name; a.click(); URL.revokeObjectURL(a.href);
    toast(`Downloaded ${name}.`);
  } catch (err) { toast(err.message, 'red'); }
}

async function runAct(a, row) {
  if (attr(a, 'download')) return download(fill(attr(a, 'download'), row), fill(attr(a, 'file'), row));
  if (attr(a, 'view') === 'history') return openHistory(row[attr(a, 'patient', 'id')]);
  if (attr(a, 'form')) {
    const preset = parseFill(attr(a, 'fill'), row);
    return openForm(attr(a, 'form'), preset, attr(a, 'prefill') ? row : {});
  }
  const msg = fill(attr(a, 'confirm', 'Are you sure?'), row) + (row.warning ? `\n\nAllergy warning: ${row.warning}` : '') + (row.interaction ? `\n\nDrug interaction: ${row.interaction}` : '');
  if (!await confirmBox(attr(a, 'label'), msg, attr(a, 'label'), !!(row.warning || row.interaction))) return;
  const body = Object.fromEntries(attr(a, 'body').split(',').filter(Boolean).map(kv => kv.split('=')));
  try { done(await api(attr(a, 'method'), fill(attr(a, 'path'), row), body), attr(a, 'success')); }
  catch (err) { toast(err.message, 'red'); }
}

function trends(consults) {  // small SVG line charts, defined in portal.xml under <vitals>
  if (!Array.isArray(consults) || !consults.length) return '';
  const pts = consults.slice().sort((a, b) => (a.created || '').localeCompare(b.created || '') || a.id - b.id);
  const W = 300, H = 120, L = 30, R = 10, T = 8, B = 18;
  const cards = [...X.querySelectorAll('vitals > trend')].map(t => {
    const fields = attr(t, 'fields').split(','), lo = +attr(t, 'low'), hi = +attr(t, 'high'), label = attr(t, 'label');
    const series = fields.map(f => pts.map(r => r[f] === '' || r[f] == null || isNaN(r[f]) ? null : +r[f]));
    const all = series.flat().filter(v => v != null);
    if (!all.length) return '';
    const min = Math.min(lo, ...all) - 5, max = Math.max(hi, ...all) + 5;
    const x = i => pts.length < 2 ? (L + W - R) / 2 : L + i * (W - L - R) / (pts.length - 1);
    const y = v => T + (max - v) * (H - T - B) / (max - min);
    const lines = series.map((s, k) => {
      const p = s.map((v, i) => v == null ? null : [x(i), y(v), v]).filter(Boolean);
      return `<path class="line l${k}" d="${p.map((q, i) => (i ? 'L' : 'M') + q[0].toFixed(1) + ' ' + q[1].toFixed(1)).join(' ')}"/>` +
        p.map(q => `<circle class="dot l${k} ${q[2] < lo || q[2] > hi ? 'out' : 'in'}" cx="${q[0].toFixed(1)}" cy="${q[1].toFixed(1)}" r="3.5"><title>${q[2]}</title></circle>`).join('');
    }).join('');
    const last = series.map(s => s.filter(v => v != null).pop());
    const flag = last.some(v => v != null && (v < lo || v > hi)) ? ' (outside the normal range)' : '';
    const text = `${label}: latest ${last.filter(v => v != null).join(' / ')}${flag}. Normal range ${lo} to ${hi}. ${pts.length} reading${pts.length === 1 ? '' : 's'}.`;
    return `<figure class="trend"><figcaption>${esc(label)}</figcaption><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(text)}">` +
      `<rect class="band" x="${L}" y="${y(hi).toFixed(1)}" width="${W - L - R}" height="${(y(lo) - y(hi)).toFixed(1)}"/>` +
      `<text class="ax" x="2" y="${y(hi) + 3}">${hi}</text><text class="ax" x="2" y="${y(lo) + 3}">${lo}</text>${lines}</svg>` +
      `<small>Latest ${last.filter(v => v != null).join(' / ')}${esc(flag)}</small></figure>`;
  }).join('');
  return cards ? `<h3 class="sect">Vital signs over time</h3><div class="trends">${cards}</div>` : '';
}

async function openHistory(id) {
  openDialog('<div class="sheet"><p class="dim">Loading history...</p></div>', true);
  try {
    const h = await api('GET', `/api/patients/${id}/full-history`);
    const p = h.patient && typeof h.patient === 'object' ? h.patient : null;
    const down = [], items = [];
    kids(X.querySelector('history'), 'timeline').forEach((t, order) => {
      const rows = h[attr(t, 'source')];
      if (Array.isArray(rows)) rows.forEach(r => { if (attr(t, 'source') === 'consultations') r.summary = vitalsText(r); items.push({t, r, order}); });
      else if (!down.includes(attr(t, 'org'))) down.push(attr(t, 'org'));
    });
    items.sort((a, b) => (a.r.created || '').localeCompare(b.r.created || '') || a.order - b.order || a.r.id - b.r.id);
    const line = (tpl, r) => tpl && has(tpl, r) ? `<p>${esc(fill(tpl, r))}</p>` : '';
    const initials = (p?.name || '?').split(/\s+/).slice(0, 2).map(w => w[0]).join('').toUpperCase();
    const head = p
      ? `<div class="phead"><span class="avatar">${esc(initials)}</span><div><h2>${esc(p.name)}</h2><p>National ID ${esc(p.national_id)}${p.dob ? ', born ' + esc(p.dob) : ''}</p></div><div class="allergies">${
          p.allergies ? p.allergies.split(',').map(a => `<span class="badge red">${esc(a.trim())}</span>`).join('') : '<span class="badge blue">No allergies recorded</span>'}</div></div>`
      : '<h2>Patient history</h2>';
    const banner = down.length ? `<div class="notice down" style="margin:0 0 1rem"><b>${esc(down.join(', '))} records unavailable.</b> Those services are offline. Everything else is shown.</div>` : '';
    const list = items.length ? `<ul class="timeline">${items.map(({t, r}) =>
      `<li><span class="node" aria-hidden="true"></span><div class="ev"><div class="evh"><b>${esc(fill(attr(t, 'title'), r))}</b>${r.status ? `<span class="badge ${TONE[r.status] || 'blue'}">${esc(r.status)}</span>` : ''}</div>${['detail', 'extra', 'more', 'more2'].map(k => line(attr(t, k), r)).join('')}${attr(t, 'warn').split(',').filter(k => r[k]).map(k => `<p class="alert">${esc(r[k])}</p>`).join('')}<small>${esc(attr(t, 'org'))}${attr(t, 'by') && r[attr(t, 'by')] ? ', ' + esc(people[r[attr(t, 'by')]] ?? r[attr(t, 'by')]) : ''}, ${when(r.created)}</small></div></li>`).join('')}</ul>`
      : '<p class="empty">No activity recorded yet.</p>';
    openDialog(`<div class="sheet"><div class="print-only"><h2>Patient summary</h2><p>Printed ${esc(new Date().toLocaleString())} by ${esc(S.user)}</p></div>${head}${banner}${trends(h.consultations)}<h3 class="sect">Timeline</h3>${list}<div class="row end no-print"><button class="btn" data-print>Print</button><button class="btn" data-close>Close</button></div></div>`, true);
  } catch (err) {
    openDialog(`<div class="sheet"><p class="error">${esc(err.message)}</p><div class="row end"><button class="btn" data-close>Close</button></div></div>`);
  }
}

/* ---------- events ---------- */
document.addEventListener('click', e => {
  const el = e.target.closest('[data-tab],[data-sort],[data-act],[data-form],[data-reload],[data-export],[data-print],#bell,#pw,#logout,#refresh');
  if (!el) return;
  if (el.dataset.sort !== undefined) { sort = {f: el.dataset.sort, dir: sort.f === el.dataset.sort ? -sort.dir : 1}; renderTable(); }
  else if (el.dataset.tab !== undefined) { tab = +el.dataset.tab; query = ''; sort = {f: null, dir: 1}; $('#q').value = ''; renderTabs(); }
  else if (el.dataset.act !== undefined) {
    const p = panelEl(), row = data[attr(p, 'source')].find(r => String(r.id) === el.dataset.id);
    runAct(kids(p, 'rowaction')[+el.dataset.act], row);
  }
  else if (el.dataset.form !== undefined) openForm(el.dataset.form, parseFill(el.dataset.fill));
  else if (el.dataset.export !== undefined) exportCsv();
  else if (el.dataset.print !== undefined) window.print();
  else if (el.id === 'bell') showNotes();
  else if (el.id === 'pw') openForm('password');
  else if (el.id === 'logout') logout();
  else load();
});
$('#tabs').addEventListener('keydown', e => {  // arrow keys move between tabs
  const n = kids(roleEl(), 'panel').length, d = {ArrowRight: 1, ArrowLeft: -1}[e.key];
  if (!d) return;
  tab = (tab + d + n) % n; query = ''; sort = {f: null, dir: 1}; $('#q').value = ''; renderTabs(); $(`#tab-${tab}`).focus(); e.preventDefault();
});
const THEMES = {auto: ['Theme: Auto', 'follows your system'], dark: ['Theme: Dark', 'dark'], light: ['Theme: Light', 'light']};
function showTheme() {
  const t = document.documentElement.dataset.theme || 'auto';
  $('#theme').textContent = THEMES[t][0];
  $('#theme').setAttribute('aria-label', `Colour theme: ${THEMES[t][1]}. Press to change.`);
}
$('#theme').addEventListener('click', () => {
  const next = {auto: 'dark', dark: 'light', light: 'auto'}[document.documentElement.dataset.theme || 'auto'];
  if (next === 'auto') delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = next;
  try { next === 'auto' ? localStorage.removeItem('pps-theme') : localStorage.setItem('pps-theme', next); } catch { /* ignore */ }
  showTheme();
});
showTheme();
$('#mine').addEventListener('change', e => { mineOn = e.target.checked; renderTabs(); });
$('#q').addEventListener('input', e => { query = e.target.value; renderTable(); });

setInterval(() => { if (S && !document.hidden) loadNotes(true); }, 20000);  // the bell checks for news

(async function init() {
  X = new DOMParser().parseFromString(await (await fetch('portal.xml')).text(), 'text/xml');
  buildLogin();
  if (S) start();
})();
