/* =============================================================================
   OSIRIS Control Plane — app (English, glass UI) · by mlkblk
   ============================================================================= */
'use strict';

const API = (p) => fetch(p).then((r) => r.json());
const GH = { user: 'https://github.com/MlkBlk-IT', repo: 'https://github.com/MlkBlk-IT/osiris', issues: 'https://github.com/MlkBlk-IT/osiris/issues' };

const S = { view: 'overview', taskId: null, health: null, overview: null, task: null, panelOpen: true, every: 15, timer: null };
try { const e = Number(localStorage.getItem('osiris.every')); if ([0, 5, 15, 30, 60].includes(e)) S.every = e; } catch (e) {}

const el = (id) => document.getElementById(id);
const esc = (v) => String(v === null || v === undefined ? '' : v).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const num = (n) => { const v = Number(n || 0); return isFinite(v) ? v.toLocaleString('en-US') : '0'; };
const ts = (t) => { if (!t) return '—'; const d = new Date(Number(t) * 1000); return isNaN(d) ? '—' : d.toLocaleString('en-US'); };
const bytes = (b) => { const v = Number(b || 0); return v < 1024 ? v + ' B' : v < 1048576 ? (v / 1024).toFixed(1) + ' KB' : (v / 1048576).toFixed(2) + ' MB'; };
const sgn = (n) => (n > 0 ? '+' : '') + num(n);
const lvlCls = (l) => (l === 'light' ? 'info' : l === 'full' ? 'violet' : 'muted');

function toast(msg, ms = 2400) { const t = el('toast'); t.textContent = msg; t.classList.add('show'); clearTimeout(t._t); t._t = setTimeout(() => t.classList.remove('show'), ms); }
function loading() { el('view').innerHTML = '<div class="loading"><span class="spin">◌</span> loading…</div>'; }

/* ------------------------------------------------------------ components */
const card = (title, body, tag, cls) => `<div class="card ${cls || ''}"><h3>${esc(title)}${tag ? `<span class="tag">${esc(tag)}</span>` : ''}</h3>${body}</div>`;
const stat = (n, t, s, cls) => `<div class="card"><div class="stat"><span class="n ${cls || ''}">${esc(n)}</span><span class="t">${esc(t)}</span>${s ? `<span class="s">${esc(s)}</span>` : ''}</div></div>`;
function table(cols, rows, render) {
  if (!rows || !rows.length) return '<div class="empty">no data</div>';
  return `<div class="scroll"><table><thead><tr>${cols.map((c) => `<th>${esc(c)}</th>`).join('')}</tr></thead><tbody>${rows.map((r) => `<tr>${render(r).map((c) => `<td>${c}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
}
function hbars(items, cls) {
  const max = Math.max(1, ...items.map((i) => Number(i.value || 0)));
  return items.map((i) => `<div class="barrow"><div class="top"><span class="mono">${esc(i.label)}</span><span class="mono muted">${esc(i.note || num(i.value))}</span></div><div class="bar ${i.cls || cls || ''}"><i style="width:${Math.round((Number(i.value || 0) / max) * 100)}%"></i></div></div>`).join('');
}
const PAL = ['#2456c8', '#12a594', '#e1a21a', '#5b41d1', '#c9304f', '#0f7d56', '#d9801c', '#6b7f9b'];
function donut(segs, centerTop, centerSub) {
  const total = segs.reduce((a, s) => a + Number(s.value || 0), 0);
  if (!total) return '<div class="empty">nothing to chart yet</div>';
  const R = 62, C = 2 * Math.PI * R; let off = 0;
  const arcs = segs.map((s, i) => {
    const len = (Number(s.value || 0) / total) * C; const col = s.color || PAL[i % PAL.length];
    const a = `<circle cx="85" cy="85" r="${R}" fill="none" stroke="${col}" stroke-width="16" stroke-dasharray="${len} ${C - len}" stroke-dashoffset="${-off}" transform="rotate(-90 85 85)" stroke-linecap="butt"><title>${esc(s.label)}: ${num(s.value)}</title></circle>`;
    off += len; return a;
  }).join('');
  const legend = segs.map((s, i) => `<div><span class="sw" style="background:${s.color || PAL[i % PAL.length]}"></span>${esc(s.label)} <span class="mono muted">${num(s.value)} · ${Math.round((Number(s.value || 0) / total) * 100)}%</span></div>`).join('');
  return `<div class="donutwrap"><svg viewBox="0 0 170 170"><circle cx="85" cy="85" r="${R}" fill="none" stroke="rgba(15,23,42,.12)" stroke-width="16"/>${arcs}<text x="85" y="84" text-anchor="middle" class="gauge-n">${esc(centerTop)}</text><text x="85" y="102" text-anchor="middle" style="fill:var(--dim);font-size:12px;font-family:var(--mono)">${esc(centerSub || '')}</text></svg><div class="legend">${legend}</div></div>`;
}
function lineChart(series, labels) {
  const W = 560, H = 190, P = { l: 44, r: 12, t: 12, b: 22 };
  const all = series.flatMap((s) => s.values); const max = Math.max(1, ...all);
  const n = Math.max(2, Math.max(...series.map((s) => s.values.length)));
  const X = (i) => P.l + (i / (n - 1)) * (W - P.l - P.r), Y = (v) => P.t + (1 - v / max) * (H - P.t - P.b);
  let g = '';
  for (let k = 0; k <= 4; k++) { const v = (max / 4) * k, y = Y(v); g += `<line x1="${P.l}" x2="${W - P.r}" y1="${y}" y2="${y}" stroke="rgba(15,23,42,.12)"/><text x="${P.l - 6}" y="${y + 3}" text-anchor="end">${v >= 1000 ? Math.round(v / 1000) + 'k' : Math.round(v)}</text>`; }
  const defs = series.map((s, i) => `<linearGradient id="lg${i}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${s.color}" stop-opacity=".35"/><stop offset="1" stop-color="${s.color}" stop-opacity="0"/></linearGradient>`).join('');
  const paths = series.map((s, i) => {
    if (!s.values.length) return '';
    const pts = s.values.map((v, j) => `${X(j).toFixed(1)},${Y(v).toFixed(1)}`);
    return `<polygon points="${P.l},${H - P.b} ${pts.join(' ')} ${X(s.values.length - 1).toFixed(1)},${H - P.b}" fill="url(#lg${i})"/><polyline points="${pts.join(' ')}" fill="none" stroke="${s.color}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`;
  }).join('');
  const leg = series.map((s) => `<span class="pill" style="color:${s.color};border-color:${s.color}55">${esc(s.name)}</span>`).join(' ');
  return `<svg class="chart" viewBox="0 0 ${W} ${H}"><defs>${defs}</defs>${g}${paths}<text x="${P.l}" y="${H - 6}">${esc((labels || [])[0] || '')}</text><text x="${W - P.r}" y="${H - 6}" text-anchor="end">${esc((labels || [])[1] || '')}</text></svg><div class="chiprow" style="margin-top:6px">${leg}</div>`;
}
function groupedBars(rows, aKey, bKey, aName, bName) {
  const W = 560, H = 200, P = { l: 44, r: 10, t: 12, b: 26 };
  const max = Math.max(1, ...rows.flatMap((r) => [Number(r[aKey] || 0), Number(r[bKey] || 0)]));
  const gw = (W - P.l - P.r) / Math.max(1, rows.length), bw = Math.min(26, gw / 3);
  const Y = (v) => P.t + (1 - v / max) * (H - P.t - P.b);
  let g = '';
  for (let k = 0; k <= 4; k++) { const v = (max / 4) * k, y = Y(v); g += `<line x1="${P.l}" x2="${W - P.r}" y1="${y}" y2="${y}" stroke="rgba(15,23,42,.12)"/><text x="${P.l - 6}" y="${y + 3}" text-anchor="end">${v >= 1000 ? Math.round(v / 1000) + 'k' : Math.round(v)}</text>`; }
  const bars = rows.map((r, i) => {
    const cx = P.l + gw * i + gw / 2, a = Number(r[aKey] || 0), b = Number(r[bKey] || 0);
    return `<rect x="${cx - bw - 2}" y="${Y(a)}" width="${bw}" height="${H - P.b - Y(a)}" rx="4" fill="#60a5fa" opacity=".85"><title>${aName}: ${num(a)}</title></rect><rect x="${cx + 2}" y="${Y(b)}" width="${bw}" height="${H - P.b - Y(b)}" rx="4" fill="#34d399" opacity=".9"><title>${bName}: ${num(b)}</title></rect><text x="${cx}" y="${H - 8}" text-anchor="middle">${num(r.payload_tokens)}</text>`;
  }).join('');
  return `<svg class="chart" viewBox="0 0 ${W} ${H}">${g}${bars}</svg><div class="chiprow" style="margin-top:6px"><span class="pill" style="color:#60a5fa">${aName}</span><span class="pill ok">${bName}</span><span class="pill muted">x-axis = payload tokens</span></div>`;
}
function code(txt) { return `<div class="code"><span>${esc(txt)}</span><button data-copy="${esc(txt)}">copy</button></div>`; }
function wireCopy(root) { (root || document).querySelectorAll('[data-copy]').forEach((b) => b.addEventListener('click', () => { try { navigator.clipboard.writeText(b.dataset.copy); toast('copied'); } catch (e) { toast('copy failed'); } })); }

/* ------------------------------------------------------- eye + plain words */
const EYE = (cls = '') => `<svg class="eye ${cls}" viewBox="0 0 200 150" role="img" aria-label="The eye of Osiris">
  <defs>
    <radialGradient id="ig" cx="50%" cy="45%" r="60%"><stop offset="0" stop-color="#7fe3d6"/><stop offset=".55" stop-color="#1fa7a0"/><stop offset="1" stop-color="#1d4fb8"/></radialGradient>
    <linearGradient id="gold" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#f5c453"/><stop offset="1" stop-color="#b9790a"/></linearGradient>
    <linearGradient id="glassy" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".96"/><stop offset="1" stop-color="#d6e6fb" stop-opacity=".8"/></linearGradient>
  </defs>
  <path class="eye-brow" d="M14 36 C52 8 122 2 184 24"/>
  <g class="eye-ball">
    <path class="eye-shape" d="M12 64 C46 26 78 18 100 18 C122 18 154 26 188 64 C154 102 122 110 100 110 C78 110 46 102 12 64 Z"/>
    <circle class="eye-iris" cx="100" cy="64" r="31"/><circle class="eye-ring" cx="100" cy="64" r="31"/>
    <g class="eye-pupil"><circle cx="100" cy="64" r="13"/><circle cx="106" cy="57" r="4" fill="#fff" opacity=".9"/></g>
  </g>
  <path class="eye-tear" d="M96 110 L88 134"/><path class="eye-spiral" d="M124 108 C146 114 154 134 140 142 C128 148 116 138 124 128"/>
</svg>`;
document.addEventListener('mousemove', (e) => {
  document.querySelectorAll('.eye').forEach((svg) => {
    const p = svg.querySelector('.eye-pupil'); if (!p) return;
    const r = svg.getBoundingClientRect(), k = r.width / 200;
    const dx = e.clientX - (r.left + r.width / 2), dy = e.clientY - (r.top + r.height * 0.43), d = Math.hypot(dx, dy) || 1, m = Math.min(15, d / (10 * k));
    p.style.transform = `translate(${(dx / d) * m}px, ${(dy / d) * m * 0.55}px)`;
  });
});
const KIND = { overhead: 'Osiris cost', observe: 'Items stored', saving: 'Savings proven' };
const kindName = (k) => KIND[k] || k;
const EVENT = { task_start: 'Task started', externalize: 'Big result stored', observe: 'Action logged', checkpoint: 'Checkpoint saved', saving: 'Saving recorded', prefix: 'Manifest sealed', note: 'Note kept', action: 'Action run', resume: 'Task resumed' };
const eventName = (k) => EVENT[k] || k;
const TITLES = {
  overview: ['Overview', 'Is Osiris watching, and is it paying off?'], tasks: ['Tasks', 'Every job your AI agent started'], events: ['Journal', 'Everything that happened, in order'],
  ledger: ['Ledger', 'Tokens saved and spent, line by line'], bench: ['Benchmark', 'When does Osiris pay for itself?'], refs: ['Stored items', 'Big results kept safe outside the AI’s context'],
  memory: ['Memory', 'Notes and decisions Osiris remembers'], prefix: ['Manifest', 'The sealed summary of the selected task'], audit: ['Integrity check', 'Proof that nothing was lost'],
  loopguard: ['Loop guard', 'Stops the agent from repeating itself'], help: ['Help', 'How Osiris works, in plain words'], quickstart: ['Quickstart', 'Set up in seven steps'],
  handoffs: ['Handoffs', 'Work passed to sub-agents'], invariants: ['Rules', 'Things the agent must never break'], tools: ['MCP tools', 'The six tools your AI can call'],
  diagnostics: ['Diagnostics', 'Known problems and fixes'], config: ['Settings', 'Configuration and refresh rate'],
};
const emptyState = (ico, title, text, snippet) => `<div class="card empty-state"><div class="es-ico">${ico}</div><h3>${esc(title)}</h3><p>${esc(text)}</p>${snippet ? code(snippet) : ''}</div>`;
function columns(vals, labels, color) {
  const W = 560, H = 170, P = { l: 34, r: 8, t: 10, b: 22 };
  const max = Math.max(1, ...vals), n = vals.length, gw = (W - P.l - P.r) / n, bw = Math.max(3, gw * 0.62);
  let g = '';
  for (let k = 0; k <= 3; k++) { const v = (max / 3) * k, y = P.t + (1 - v / max) * (H - P.t - P.b); g += `<line x1="${P.l}" x2="${W - P.r}" y1="${y}" y2="${y}" stroke="rgba(31,64,120,.14)"/><text x="${P.l - 6}" y="${y + 3}" text-anchor="end">${Math.round(v)}</text>`; }
  const bars = vals.map((v, i) => { const h = (v / max) * (H - P.t - P.b), x = P.l + gw * i + (gw - bw) / 2; return `<rect x="${x.toFixed(1)}" y="${(H - P.b - h).toFixed(1)}" width="${bw.toFixed(1)}" height="${h.toFixed(1)}" rx="3" fill="${color}" opacity=".88"><title>${esc(labels[i])}: ${v}</title></rect>`; }).join('');
  const lab = [0, Math.floor(n / 2), n - 1].map((i) => `<text x="${(P.l + gw * i + gw / 2).toFixed(1)}" y="${H - 6}" text-anchor="middle">${esc(labels[i])}</text>`).join('');
  return `<svg class="chart" viewBox="0 0 ${W} ${H}">${g}${bars}${lab}</svg>`;
}

/* ------------------------------------------------------------------ boot */
async function boot() {
  document.querySelectorAll('.nav-item').forEach((n) => n.addEventListener('click', () => { S.view = n.dataset.view; syncNav(); render(); }));
  el('btn-refresh').addEventListener('click', () => refresh(true));
  el('btn-panel').addEventListener('click', togglePanel);
  el('btn-close-panel').addEventListener('click', togglePanel);
  document.querySelectorAll('#panel .actions .btn').forEach((b) => b.addEventListener('click', () => panelAction(b.dataset.act)));
  setInterval(() => { el('db-clock').textContent = new Date().toLocaleTimeString('en-US'); }, 1000);
  schedule();
  syncNav();
  await refresh(false);
}
function schedule() { clearInterval(S.timer); if (S.every > 0) S.timer = setInterval(() => refresh(false, true), S.every * 1000); }
function togglePanel() { S.panelOpen = !S.panelOpen; el('app').classList.toggle('no-panel', !S.panelOpen); }
function syncNav() {
  document.querySelectorAll('.nav-item').forEach((n) => n.classList.toggle('active', n.dataset.view === S.view));
  const [title, sub] = TITLES[S.view] || [S.view, '']; el('page-title').textContent = title; el('page-sub').textContent = sub;
  const hidden = document.querySelector('.nav-more .nav-item.active'); if (hidden) hidden.closest('details').open = true;
}

async function refresh(manual, silent) {
  try {
    const h = await API('/api/health'); S.health = h;
    el('db-dot').className = 'dot ' + (h.db_exists ? (h.empty ? 'warn' : 'ok') : 'bad');
    el('db-state').textContent = h.db_exists ? (h.empty ? 'database empty' : 'connected') : 'database not found';
    el('db-path').textContent = h.db;
  } catch (e) { el('db-dot').className = 'dot bad'; el('db-state').textContent = 'server unreachable'; }
  try {
    const o = await API('/api/overview'); S.overview = o; paintKpis(o);
    if (silent) { if (S.view === 'overview') VIEWS.overview(); return; }
    paintBadges(); await render();
  } catch (e) { if (!silent) el('view').innerHTML = `<div class="card"><div class="empty">cannot reach /api/overview: ${esc(e.message)}</div></div>`; }
  if (manual) toast('refreshed');
}
function paintKpis(o) {
  const t = o.totals || {};
  el('k-saved').textContent = num(t.tokens_saved);
  el('k-net').textContent = sgn(t.net_gain); el('k-net').parentElement.className = 'kpi ' + (t.net_gain > 0 ? 'good' : t.net_gain < 0 ? 'bad' : '');
  const i = o.integrity || S.integrity || '—'; el('k-integrity').textContent = i; el('k-integrity').parentElement.className = 'kpi ' + (i === 'LOSSLESS' ? 'good' : '');
}
function paintBadges() {
  const c = (S.overview && S.overview.counts) || {};
  const map = { 'b-tasks': c.tasks, 'b-events': c.events, 'b-memory': c.memory, 'b-refs': c.refs, 'b-handoffs': c.handoffs, 'b-ledger': c.ledger, 'b-fp': (S.overview && S.overview.fingerprints) || 0 };
  Object.entries(map).forEach(([id, v]) => { setBadge(id, v); });
}
function setBadge(id, v) { const b = el(id); if (b) { b.textContent = num(v); b.classList.toggle('zero', !Number(v)); } }

/* ----------------------------------------------------------------- views */
const VIEWS = {
  async overview() {
    const o = S.overview, t = o.totals || {}, c = o.counts || {}, led = o.ledger || [];
    const [lg, tk, ev] = await Promise.all([API('/api/ledger').catch(() => ({})), API('/api/tasks').catch(() => ({})), API('/api/events').catch(() => ({}))]);
    const rows = (lg.items || []).slice().reverse(), tasks = tk.tasks || [], events = ev.items || [];
    const saved = Number(t.tokens_saved || 0), moved = Number(t.tokens_moved || 0), over = Number(t.overhead || 0), net = Number(t.net_gain || 0);
    const ratio = over ? saved / over : 0;
    const ok = (o.integrity || S.integrity) === 'LOSSLESS';

    // cumulative curves, oldest -> newest
    let cs = 0, cm = 0, co = 0; const sv = [], mv = [], ov = [];
    rows.forEach((r) => { cs += Number(r.tokens_saved || 0); cm += Number(r.tokens_moved || 0); if (r.kind === 'overhead' || r.kind === 'schema_access') co += Number(r.tokens_in || 0); sv.push(cs); mv.push(cm); ov.push(co); });
    const when = (r) => (r ? new Date(r.ts * 1000).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }) : '');
    const flow = sv.length > 1
      ? lineChart([{ name: 'moved to the vault', color: '#2456c8', values: mv }, { name: 'saved (proven)', color: '#0f7d56', values: sv }, { name: 'Osiris cost', color: '#c9304f', values: ov }], [when(rows[0]), when(rows[rows.length - 1])])
      : '<div class="empty">Not enough activity yet. Run a task and the curves appear here.</div>';

    // events per day, last 14 days
    const now = Date.now() / 1000, days = Array(14).fill(0);
    events.forEach((e) => { const d = Math.floor((now - e.ts) / 86400); if (d >= 0 && d < 14) days[13 - d]++; });
    const dayLabels = days.map((_, i) => { const d = new Date((now - (13 - i) * 86400) * 1000); return d.getMonth() + 1 + '/' + d.getDate(); });
    const activity = days.some((v) => v) ? columns(days, dayLabels, '#12a594') : '<div class="empty">No activity in the last 14 days.</div>';

    // where the savings come from: net gain per task, named by objective
    const obj = Object.fromEntries(tasks.map((x) => [x.task_id, x.objective || x.task_id]));
    const per = Object.entries(lg.per_task || {})
      .map(([id, a]) => ({ label: (obj[id] || id).slice(0, 46), value: Math.abs(a.net_gain || 0), cls: a.net_gain >= 0 ? 'emerald' : 'rose', note: sgn(a.net_gain) }))
      .filter((x) => x.value > 0).sort((a, b) => b.value - a.value).slice(0, 7);

    const KC = { observe: '#2456c8', overhead: '#e1a21a', saving: '#0f7d56' };
    const dn = donut(led.map((r) => ({ label: kindName(r.kind), value: r.n, color: KC[r.kind] })), num(c.ledger), 'ledger lines');
    const sc = donut([{ label: 'saved (proven)', value: saved, color: '#0f7d56' }, { label: 'Osiris cost', value: over, color: '#e1a21a' }], ratio ? '×' + ratio.toFixed(1) : '—', 'per token');

    const recent = events.slice(0, 8).map((r) => `<div class="feed-item ${r.kind === 'checkpoint' ? 'ok' : r.action_state === 'failed' ? 'bad' : ''}"><div class="k">${esc(eventName(r.kind))}</div><div class="t">${esc((obj[r.task_id] || r.task_id || '').slice(0, 60))}</div><div class="ts">${ts(r.ts)}</div></div>`).join('') || '<div class="empty">Nothing yet.</div>';

    const head = ok ? 'Osiris is watching.' : 'Osiris needs a look.';
    const line = ok ? `${num(c.tasks)} tasks followed, ${num(c.refs)} big results kept safe, nothing lost.` : 'The integrity check has not passed or has not run yet. Open Integrity check.';
    const money = saved > 0 ? `So far it kept ${num(saved)} tokens out of the AI’s working memory, for a cost of ${num(over)}.` : 'No savings proven yet. See Help, “Why is Saved 0?”.';
    el('view').innerHTML = `
      <div class="card glass hero-eye mb">
        ${EYE(ok ? '' : 'warn')}
        <div>
          <h2>${head}</h2>
          <p>${esc(line)} ${esc(money)}</p>
          <div class="bignums">
            <div class="bignum"><span class="n emerald">${num(saved)}</span><span class="t">tokens saved</span></div>
            <div class="bignum"><span class="n blue">${num(moved)}</span><span class="t">moved to the vault</span></div>
            <div class="bignum"><span class="n amber">${num(over)}</span><span class="t">Osiris cost</span></div>
            <div class="bignum"><span class="n ${net >= 0 ? 'emerald' : 'rose'}">${sgn(net)}</span><span class="t">net gain</span></div>
            <div class="bignum"><span class="n cyan">${ratio ? '×' + ratio.toFixed(1) : '—'}</span><span class="t">saved per token spent</span></div>
          </div>
        </div>
      </div>
      <div class="grid c2 mb">
        ${card('Token flow over time', flow, 'cumulative')}
        ${card('Activity per day', activity, 'last 14 days')}
      </div>
      <div class="grid c2 mb">
        ${card('Where the savings come from', per.length ? hbars(per) : '<div class="empty">No task has saved anything yet.</div>', 'net gain per task')}
        ${card('Savings versus cost', sc, 'proven only')}
      </div>
      <div class="grid c2">
        ${card('What the ledger holds', dn, 'by type')}
        ${card('Latest activity', `<div class="feed" style="max-height:none">${recent}</div>`, 'newest first')}
      </div>`;
  },

  async tasks() {
    const rows = (await API('/api/tasks')).tasks || [];
    el('view').innerHTML = card('Tasks', table(['Task', 'Objective', 'Level', 'Volume', 'Plan', 'Decisions', 'Updated'], rows, (r) => [
      `<span class="mono">${esc(r.task_id)}</span>`, esc((r.objective || '—').slice(0, 90)),
      `<span class="pill ${lvlCls(r.level)}">${esc(r.level || '—')}</span>`, `<span class="mono">${num(r.volume)} tok</span>`,
      `<span class="mono">${r.plan_done}/${r.plan_total}</span>`, `<span class="mono">${num(r.decisions)}</span>`, `<span class="mono muted">${ts(r.updated_at)}</span>`,
    ]).replace(/<tr>/g, (m, off, str) => m), num(rows.length) + ' task(s)');
    el('view').querySelectorAll('tbody tr').forEach((tr, i) => { if (rows[i]) { tr.dataset.task = rows[i].task_id; tr.addEventListener('click', () => selectTask(rows[i].task_id)); } });
  },

  async events() {
    const rows = (await API('/api/events')).items || [];
    el('view').innerHTML = card('Append-only journal', table(['Seq', 'Task', 'Kind', 'State', 'Run key', 'Timestamp'], rows, (r) => [
      `<span class="mono">${num(r.seq)}</span>`, `<span class="mono">${esc(r.task_id)}</span>`, `<span class="pill info">${esc(r.kind)}</span>`,
      r.action_state ? `<span class="pill ${r.action_state === 'succeeded' ? 'ok' : r.action_state === 'failed' ? 'bad' : 'muted'}">${esc(r.action_state)}</span>` : '<span class="muted">—</span>',
      `<span class="mono muted">${esc((r.run_key || '—').slice(0, 14))}</span>`, `<span class="mono muted">${ts(r.ts)}</span>`,
    ]), num(rows.length) + ' event(s)');
  },

  async prefix() {
    const t = S.taskId ? await API('/api/task/' + S.taskId) : null;
    const st = t ? t.state || {} : {}, flags = st.flags || {}, p = t ? t.prefix || {} : {}, b = t ? t.budget || {} : {};
    const head = p.head_hash || flags.head_hash || '', zoneB = p.zoneB_hash || flags.zoneB_hash || '', tail = p.tail_hash || flags.tail_hash || '', ph = p.prefix_hash || flags.prefix_hash || '';
    const zone = (name, hash, cls, note) => `<div class="mb"><div style="display:flex;align-items:center;gap:9px;margin-bottom:5px"><span class="mono" style="color:var(--cyan)">${esc(name)}</span><span class="pill ${cls}">${hash ? 'set' : 'empty'}</span></div><div class="mono-box">${esc(hash || '—')}</div><div class="muted" style="font-size:10.5px;margin-top:4px">${esc(note)}</div></div>`;
    el('view').innerHTML = `<div class="grid c2">
      ${card('Prefix zones', (t ? '' : '<div class="empty">select a task to display its prefix</div>') +
        zone('head_hash', head, head ? 'ok' : 'muted', 'system + rules + constraints · immutable · any change = CRITICAL DRIFT') +
        zone('zoneB_hash', zoneB, zoneB ? 'warn' : 'muted', 'objective + global plan + tool contract · quasi-stable') +
        zone('tail_hash', tail, tail ? 'info' : 'muted', 'pinned decisions · append-only · normal growth') +
        zone('prefix_hash', ph, ph ? 'ok' : 'muted', 'sha256(head ‖ zoneB) · what is actually cached'), t ? t.task_id : 'no task')}
      ${card('State & budget', `<dl class="kv">
        <dt>Objective</dt><dd>${esc(t ? t.objective || '—' : '—')}</dd><dt>Level</dt><dd>${esc(t ? t.level || '—' : '—')}</dd>
        <dt>Volume</dt><dd>${num(t ? t.volume : 0)} tokens</dd><dt>Tokens</dt><dd>${num(b.tokens_used || b.tokens || b.tokens_estimated || 0)}</dd>
        <dt>Budget</dt><dd>${esc(b.ok === undefined ? '—' : b.ok ? 'ok' : 'exceeded')}</dd><dt>Files</dt><dd>${num(Object.keys(st.files || {}).length)}</dd>
        <dt>Decisions</dt><dd>${num((st.decisions || []).length)}</dd><dt>Memory</dt><dd>${num(Object.keys(st.memory || {}).length)}</dd></dl>`, 'task state')}</div>`;
  },

  async memory() {
    const d = await API('/api/memory'), rows = d.items || [];
    const sc = Object.entries(d.by_scope || {}).map(([k, v]) => ({ label: k, value: v })), kd = Object.entries(d.by_kind || {}).map(([k, v]) => ({ label: k, value: v }));
    el('view').innerHTML = `<div class="grid c2 mb">${card('By scope', donut(sc, num(rows.length), 'entries'), 'task / project / agent / global')}${card('By kind', donut(kd, num(kd.length), 'kinds'), 'semantic / decision / workflow…')}</div>
      ${card('Typed memory', table(['Id', 'Scope', 'Kind', 'Body', 'Pinned', 'Seq'], rows, (r) => [
        `<span class="mono">${esc(r.mem_id)}</span>`, `<span class="pill muted">${esc(r.scope)}</span>`, `<span class="pill violet">${esc(r.kind)}</span>`,
        `<div style="max-height:130px;overflow:auto;white-space:pre-wrap">${esc(r.body)}</div>`, r.pinned ? '<span class="pill ok">yes</span>' : '<span class="pill muted">no</span>', `<span class="mono">${num(r.seq)}</span>`]), num(rows.length) + ' entr(ies)')}`;
  },

  async refs() {
    const d = await API('/api/refs'), rows = d.items || [];
    const top = rows.slice().sort((a, b) => Number(b.size_bytes || 0) - Number(a.size_bytes || 0)).slice(0, 8).map((r) => ({ label: (r.ref || '').slice(0, 26) + '…', value: r.size_bytes, note: bytes(r.size_bytes) }));
    el('view').innerHTML = `<div class="grid c4 mb">
        ${stat(num(d.count), 'Refs', 'content-addressed', 'cyan')}${stat(bytes(d.total_bytes), 'Volume', 'externalized content', 'violet')}
        ${stat(num(d.redactions), 'Redactions', 'secrets masked before hashing', 'amber')}${stat('sha256', 'Algorithm', 'verified on read', 'emerald')}</div>
      <div class="mb">${card('Largest refs', top.length ? hbars(top) : '<div class="empty">no refs</div>', 'top 8 by size')}</div>
      ${card('Content-addressed store', table(['Ref', 'Task', 'Hash', 'Size', 'Redactions', 'Expires', 'Created'], rows, (r) => [
        `<span class="mono">${esc(r.ref)}</span>`, `<span class="mono">${esc(r.task_id || '—')}</span>`, `<span class="mono muted">${esc((r.content_hash || '').slice(0, 20))}</span>`,
        `<span class="mono">${bytes(r.size_bytes)}</span>`, `<span class="mono">${num(r.redactions)}</span>`, `<span class="mono muted">${r.expires_at ? ts(r.expires_at) : '—'}</span>`, `<span class="mono muted">${ts(r.created_at)}</span>`]), num(rows.length) + ' ref(s)')}`;
  },

  async handoffs() {
    const rows = (await API('/api/handoffs')).items || [];
    if (!rows.length) { el('view').innerHTML = emptyState('⇄', 'No handoffs yet', 'A handoff is a short contract given to a sub-agent: its mission, what it must know and its token budget. This page fills up the first time your agent delegates work.', 'osiris.handoff { mission: "…", must_know: ["…"], budget_tokens: 2000 }'); wireCopy(el('view')); return; }
    el('view').innerHTML = card('Delegation contracts', table(['Id', 'Status', 'Mission', 'Budget', 'Parent', 'Created', 'Expires'], rows, (r) => { const c = r.contract || {}; return [
      `<span class="mono">${esc(r.handoff_id)}</span>`, `<span class="pill ${r.status === 'open' ? 'info' : r.status === 'completed' ? 'ok' : 'muted'}">${esc(r.status)}</span>`,
      esc((c.mission || '—').slice(0, 80)), `<span class="mono">${num((c.budget || {}).tokens || 0)}</span>`, `<span class="mono">${esc(r.parent_task_id || '—')}</span>`,
      `<span class="mono muted">${ts(r.created_at)}</span>`, `<span class="mono muted">${r.expires_at ? ts(r.expires_at) : '—'}</span>`]; }), num(rows.length) + ' contract(s)');
  },

  async ledger() {
    const d = await API('/api/ledger'), rows = d.items || [], per = Object.entries(d.per_task || {});
    const now = Date.now() / 1000, sv = Array(14).fill(0), ov = Array(14).fill(0);
    rows.forEach((r) => { const d = Math.floor((now - r.ts) / 86400); if (d >= 0 && d < 14) { sv[13 - d] += Number(r.tokens_saved || 0); if (r.kind === 'overhead' || r.kind === 'schema_access') ov[13 - d] += Number(r.tokens_in || 0); } });
    const dl = sv.map((_, i) => { const x = new Date((now - (13 - i) * 86400) * 1000); return (x.getMonth() + 1) + '/' + x.getDate(); });
    const perBars = per.map(([tid, a]) => ({ label: tid, value: Math.abs(a.net_gain || 0), cls: a.net_gain > 0 ? 'emerald' : 'rose', note: sgn(a.net_gain) }));
    el('view').innerHTML = `<div class="grid c2 mb">
      ${card('Tokens saved per day', sv.some((v) => v) ? columns(sv, dl, '#0f7d56') : '<div class="empty">Nothing saved in the last 14 days.</div>', 'last 14 days')}
      ${card('Osiris cost per day', ov.some((v) => v) ? columns(ov, dl, '#e1a21a') : '<div class="empty">No cost recorded in the last 14 days.</div>', 'last 14 days')}
    </div><div class="grid c2 mb">
      ${card('Net gain per task', perBars.length ? hbars(perBars) : '<div class="empty">no entries</div>', 'savings − overhead')}
      ${card('Totals per task', per.length ? table(['Task', 'Entries', 'In', 'Out', 'Cached', 'Saved', 'Overhead', 'Net'], per, ([tid, a]) => [
        `<span class="mono">${esc(tid)}</span>`, `<span class="mono">${num(a.entries)}</span>`, `<span class="mono">${num(a.tokens_in)}</span>`, `<span class="mono">${num(a.tokens_out)}</span>`,
        `<span class="mono" style="color:var(--cyan)">${num(a.tokens_cached)}</span>`, `<span class="mono" style="color:var(--emerald)">${num(a.tokens_saved)}</span>`, `<span class="mono" style="color:var(--amber)">${num(a.overhead)}</span>`,
        `<span class="mono" style="color:${a.net_gain > 0 ? 'var(--emerald)' : 'var(--rose)'}">${sgn(a.net_gain)}</span>`]) : '<div class="empty">no entries</div>', 'cumulative')}</div>
      ${card('Ledger journal', table(['Task', 'Kind', 'In', 'Out', 'Cached', 'Fresh', 'Saved', 'Note'], rows.slice(0, 120), (r) => [
        `<span class="mono">${esc(r.task_id)}</span>`, `<span class="pill ${r.kind === 'overhead' ? 'warn' : 'info'}">${esc(r.kind)}</span>`, `<span class="mono">${num(r.tokens_in)}</span>`, `<span class="mono">${num(r.tokens_out)}</span>`,
        `<span class="mono" style="color:var(--cyan)">${num(r.tokens_cached)}</span>`, `<span class="mono">${num(r.tokens_fresh)}</span>`, `<span class="mono" style="color:var(--emerald)">${num(r.tokens_saved)}</span>`, `<span class="mono muted">${esc((r.note || '').slice(0, 30))}</span>`]), num(rows.length) + ' entr(ies)')}`;
  },

  async bench() {
    const d = await API('/api/bench');
    if (d.running) { el('view').innerHTML = '<div class="loading"><span class="spin">◌</span> benchmark running (isolated)…</div>'; setTimeout(() => { if (S.view === 'bench') VIEWS.bench(); }, 4000); return; }
    const rows = d.rows || [], g = d.gate || {};
    el('view').innerHTML = `<div class="grid c3 mb">
        ${stat(g.passed ? 'GREEN' : 'RED', 'Benchmark gate', g.criterion || '', g.passed ? 'emerald' : 'rose')}
        ${stat(num(d.access_tokens), 'Access cost', 'schema tokens per request', 'cyan')}
        ${stat((g.worst_adaptive_pct > 0 ? '+' : '') + num(g.worst_adaptive_pct) + ' %', 'Worst delta', 'adaptive mode vs baseline', g.worst_adaptive_pct >= 0 ? 'emerald' : 'rose')}</div>
      <div class="mb">${card('Baseline vs OSIRIS (adaptive)', rows.length ? groupedBars(rows, 'baseline', 'osiris_adaptive', 'baseline', 'osiris_adaptive') : '<div class="empty">no rows</div>', 'tokens per payload size')}</div>
      ${card('Profitability by payload size', table(['Payload', 'Baseline', 'OSIRIS fixed', 'OSIRIS adaptive', 'Fixed %', 'Adaptive %', 'Mode', 'Overhead', 'Net gain', 'Payback'], rows, (r) => [
        `<span class="mono">${num(r.payload_tokens)} tok</span>`, `<span class="mono">${num(r.baseline)}</span>`, `<span class="mono">${num(r.osiris_fixed)}</span>`, `<span class="mono" style="color:var(--cyan)">${num(r.osiris_adaptive)}</span>`,
        `<span class="mono" style="color:${r.fixed_pct >= 0 ? 'var(--emerald)' : 'var(--rose)'}">${r.fixed_pct > 0 ? '+' : ''}${num(r.fixed_pct)} %</span>`,
        `<span class="mono" style="color:${r.adaptive_pct >= 0 ? 'var(--emerald)' : 'var(--rose)'}">${r.adaptive_pct > 0 ? '+' : ''}${num(r.adaptive_pct)} %</span>`,
        `<span class="pill ${lvlCls(r.mode)}">${esc(r.mode)}</span>`, `<span class="mono" style="color:var(--amber)">${num(r.overhead_adaptive)}</span>`,
        `<span class="mono" style="color:${r.gain_tokens > 0 ? 'var(--emerald)' : 'var(--rose)'}">${sgn(r.gain_tokens)}</span>`, `<span class="mono">${r.payback_tasks === null ? '—' : num(r.payback_tasks) + ' task(s)'}</span>`]), 'baseline vs osiris')}
      <div style="margin-top:14px">${card('Method note', `<div class="mono-box">${esc(d.note || '—')}</div><div class="chiprow" style="margin-top:12px"><span class="pill ${g.passed ? 'ok' : 'bad'}">gate: ${g.passed ? 'pass' : 'fail'}</span><span class="pill muted">no_loss: ${g.no_loss === undefined ? '—' : g.no_loss}</span><span class="pill muted">success_equal: ${g.success_equal === undefined ? '—' : g.success_equal}</span></div>`, 'method')}</div>`;
  },

  async loopguard() {
    const d = await API('/api/loopguard'), fp = d.fingerprints || [], fl = d.failures || [], tu = d.tool_usage || [];
    const bars = fp.slice(0, 14).map((f) => ({ label: f.tool || '—', value: f.count, cls: f.count >= 3 ? 'rose' : '', note: num(f.count) + ' call(s)' }));
    el('view').innerHTML = `<div class="grid c4 mb">
        ${stat(num(fp.length), 'Fingerprints', 'call fingerprints', 'cyan')}${stat(num(fl.length), 'Failures', 'error signatures', fl.length ? 'rose' : 'emerald')}
        ${stat(num((d.blocked || []).length), 'Blocked signatures', 'count >= 3', (d.blocked || []).length ? 'rose' : 'emerald')}${stat(num(tu.length), 'Tools used', 'per task', 'violet')}</div>
      <div class="grid c2">${card('Call frequency', bars.length ? hbars(bars) : '<div class="empty">no fingerprints: no loop detected</div>', 'loop guard')}
      ${card('Failure signatures', table(['Task', 'Signature', 'Tool', 'Attempts', 'Last'], fl, (r) => [`<span class="mono">${esc(r.task_id)}</span>`, `<span class="mono">${esc((r.signature || '').slice(0, 22))}</span>`, `<span class="mono">${esc(r.tool || '—')}</span>`,
        `<span class="mono" style="color:${r.count >= 3 ? 'var(--rose)' : 'var(--amber)'}">${num(r.count)}</span>`, `<span class="mono muted">${ts(r.last_at)}</span>`]), num(fl.length) + ' signature(s)')}</div>`;
  },

  async invariants() {
    const rows = (await API('/api/invariants')).invariants || [];
    const body = rows.length ? table(['Id', 'Source', 'When', 'Require', 'Verdict', 'Message'], rows, (r) => [
      `<span class="mono">${esc(r.id || '—')}</span>`, `<span class="mono muted">${esc(r.source || '—')}</span>`, `<span class="mono">${esc(JSON.stringify(r.when || {}))}</span>`, `<span class="mono">${esc(JSON.stringify(r.require || {}))}</span>`,
      `<span class="pill ${r.verdict === 'block' ? 'bad' : 'info'}">${esc(r.verdict || 'warn')}</span>`, esc(r.message || '—')])
      : `<div class="empty">no invariant declared</div><div class="mono-box" style="margin-top:12px">Declare invariants in <b>.osiris/invariants.toml</b> (project) or <b>~/.osiris/invariants.toml</b> (global):\n\n[[invariant]]\nid = "tests-before-commit"\nwhen = { tool = "git.commit" }\nrequire = { state = "tests_passed" }\nmessage = "do not commit if tests fail"</div>`;
    el('view').innerHTML = card('Anti-breakage invariants', body, num(rows.length) + ' invariant(s)');
  },

  async audit() {
    const d = await API('/api/audit'), ok = d.lossless;
    el('view').innerHTML = `<div class="grid c4 mb">
        ${stat(ok ? 'LOSSLESS' : 'VIOLATION', 'Verdict', d.task_id || '—', ok ? 'emerald' : 'rose')}${stat(num(d.items_externalized), 'Externalized', 'moved, never deleted', 'cyan')}
        ${stat(num(d.items_verified), 'Verified', 'hash recomputed on read', 'violet')}${stat(num(d.items_dropped), 'Lost', 'must stay at 0', d.items_dropped ? 'rose' : 'emerald')}</div>
      <div class="grid c2">${card('Non-loss proof', `<div class="mono-box">${esc(JSON.stringify(d, null, 2))}</div>`, 'audit_task')}
      ${card('Mechanisms', `<dl class="kv"><dt>1. Refs</dt><dd>mem://sha256:&lt;hash&gt; — mismatch → integrity_error</dd><dt>2. Deletion</dt><dd>no code path deletes: prune moves</dd><dt>3. Audit</dt><dd>replayable from the append-only journal</dd></dl>
        ${code('python -m osiris audit --task ' + (d.task_id || '<id>'))}`, 'guarantees')}</div>`;
    wireCopy(el('view'));
  },

  async tools() {
    const d = await API('/api/tools'), tools = d.tools || [];
    const cards = tools.length ? tools.map((t) => `<div class="card tool-card"><h3>${esc(t.name)}</h3><div class="muted" style="font-size:11.5px;margin-bottom:9px;color:var(--muted)">${esc((t.description || '').slice(0, 220))}</div><div class="mono-box" style="max-height:160px">${esc(JSON.stringify(t.schema, null, 1))}</div></div>`).join('') : '<div class="empty">schemas not readable from the dashboard</div>';
    el('view').innerHTML = `<div class="grid c4 mb">${stat(num(d.count), 'Exposed tools', 'stable public surface', 'cyan')}${stat(num(d.access_tokens), 'Schema tokens', 'access cost per request', 'amber')}${stat(num(d.schema_chars), 'Characters', 'schemas + descriptions', 'violet')}${stat('6', 'Expected', 'plan / precheck / observe / recall / checkpoint / handoff', 'blue')}</div><div class="grid c2">${cards}</div>`;
  },

  async diagnostics() {
    const d = await API('/api/diagnostics'), items = d.items || [], ord = { critical: 0, high: 1, medium: 2, low: 3 };
    items.sort((a, b) => (ord[a.severity] ?? 9) - (ord[b.severity] ?? 9));
    const sev = {}; items.forEach((x) => { sev[x.severity] = (sev[x.severity] || 0) + 1; });
    const cards = items.map((x) => `<div class="diag ${esc(x.severity)}"><h4>${esc(x.title)}</h4><div class="meta">${esc(x.id)} · ${esc(x.component)} · <span class="pill ${x.status === 'fixed' ? 'ok' : 'warn'}">${esc(x.status)}</span> · <span class="pill muted">${esc(x.severity)}</span></div><dl><dt>Symptom</dt><dd>${esc(x.symptom)}</dd><dt>Cause</dt><dd>${esc(x.cause)}</dd><dt>Fix</dt><dd style="color:var(--txt)">${esc(x.fix)}</dd></dl></div>`).join('');
    el('view').innerHTML = `<div class="grid c3 mb">${stat(num(d.count), 'Bugs detected', 'code audit + tooling run', 'cyan')}${stat(num(d.by_status ? d.by_status.fixed : 0), 'Fixed', 'verified by pytest / ruff / bench', 'emerald')}${stat(num(d.by_status ? d.by_status.open : 0), 'Open', 'to handle', (d.by_status && d.by_status.open) ? 'rose' : 'emerald')}</div>
      <div class="mb">${card('Severity mix', donut(Object.entries(sev).map(([k, v]) => ({ label: k, value: v, color: { critical: '#fb7185', high: '#fbbf24', medium: '#60a5fa', low: '#34d399', info: '#22d3ee' }[k] })), num(d.count), 'findings'), 'by severity')}</div>
      <div class="grid c2">${cards}</div>`;
  },

  async config() {
    const d = await API('/api/config'), env = d.env || {}, eff = d.effective || {};
    const rows = Object.entries(env).map(([k, v]) => `<tr><td><span class="mono">${esc(k)}</span></td><td>${v === null || v === undefined || v === '' ? '<span class="pill muted">default</span>' : `<span class="mono" style="color:var(--cyan)">${esc(v)}</span>`}</td></tr>`).join('');
    el('view').innerHTML = `<div class="grid c2 mb">
        ${card('Environment variables', `<div class="scroll"><table><thead><tr><th>Variable</th><th>Value</th></tr></thead><tbody>${rows}</tbody></table></div>`, 'OSIRIS_*')}
        ${card('Effective configuration', `<dl class="kv"><dt>Version</dt><dd>${esc(eff.version || '—')}</dd><dt>Home</dt><dd>${esc(eff.home || '—')}</dd><dt>Database</dt><dd>${esc(eff.db_path || '—')}</dd><dt>Allowed roots</dt><dd>${esc(eff.allowed_roots ? (eff.allowed_roots || []).join(', ') : '—')}</dd><dt>Tokenizer</dt><dd>${esc(eff.tokenizer || '—')}</dd><dt>Project</dt><dd>${esc(d.project || '—')}</dd></dl>
          <div class="cfg-note">Read-only view. Change values through the OSIRIS_* environment variables, then restart the MCP server.</div>`, 'runtime')}</div>
      <div class="grid c2">
        ${card('Dashboard settings', `<dl class="kv"><dt>Auto-refresh</dt><dd><select id="cfg-every" class="btn" style="padding:5px 9px">${[[0, 'off'], [5, '5 s'], [15, '15 s'], [30, '30 s'], [60, '60 s']].map(([v, l]) => `<option value="${v}" ${S.every === v ? 'selected' : ''}>${l}</option>`).join('')}</select></dd><dt>Side panel</dt><dd><button class="btn" id="cfg-panel">${S.panelOpen ? 'Hide' : 'Show'}</button></dd></dl><div class="cfg-note">Settings apply instantly and are remembered in this browser.</div>`, 'local')}
        ${card('Run the dashboard', `${code('python dashboard\\server.py --home <OSIRIS_HOME> --port 8770')}<div class="cfg-note">Flags: --host (default 127.0.0.1), --port (default 8770), --home.</div>`, 'cli')}
      </div>`;
    el('cfg-every').addEventListener('change', (e) => { S.every = Number(e.target.value); try { localStorage.setItem('osiris.every', S.every); } catch (x) {} schedule(); toast('auto-refresh: ' + (S.every ? S.every + ' s' : 'off')); });
    el('cfg-panel').addEventListener('click', () => { togglePanel(); VIEWS.config(); });
    wireCopy(el('view'));
  },

  async quickstart() {
    const step = (n, t, p, c) => `<div class="step"><div class="num">${n}</div><div><h4>${esc(t)}</h4><p>${esc(p)}</p>${c || ''}</div></div>`;
    el('view').innerHTML = `
      <div class="card glass hero"><h2>Quickstart</h2><p>OSIRIS is a cache-aware context engine and state governor for AI agents. It moves bulky results out of the context into content-addressed refs, lets the agent re-read only what it needs, and proves nothing was lost.</p>
        <div class="chiprow"><span class="pill info">6 MCP tools</span><span class="pill ok">LOSSLESS audit</span><span class="pill violet">content-addressed refs</span></div></div>
      <div class="steps">
        ${step(1, 'Register the MCP server', 'Add OSIRIS to your MCP client using the template shipped in the repository, then restart the client.', code('mcp.example.json  (repo root)'))}
        ${step(2, 'Start a task', 'Call osiris.plan with mode=start, an objective and steps. You get a task_id and a sealed manifest.', code('osiris.plan { mode: "start", objective: "…", steps: ["…"] }'))}
        ${step(3, 'Externalize big results', 'Use osiris.observe with kind=payload (inline) or kind=file (path under an allowed root). You get a ref: mem://sha256:…', code('osiris.observe { kind: "file", path: "D:\\MCP-Osiris\\…", tool: "my-step" }'))}
        ${step(4, 'Recall only what you need', 'Re-read a targeted slice instead of the whole content: op = grep | count | range | outline | head | tail | excerpt (count = just the number of matches, ~3 tokens).', code('osiris.recall { ref: "mem://sha256:…", op: "grep", query: "ERROR", budget_tokens: 200 }'))}
        ${step(5, 'Drop it from context', 'Once the payload is out of your context, acknowledge it so savings are counted as proven.', code('osiris.observe { kind: "dropped", result: "mem://sha256:…" }'))}
        ${step(6, 'Close with a checkpoint', 'mode=final writes a report and returns the integrity verdict (lossless, information_perdue = 0).', code('osiris.checkpoint { mode: "final", task_id: "t_…" }'))}
        ${step(7, 'Watch it here', 'This dashboard reads the same database: tasks, journal, refs, ledger, audit and benchmark update live.', code('python -m osiris audit --task <id>'))}
      </div>`;
    wireCopy(el('view'));
  },

  async help() {
    const lang = S.lang || ((navigator.language || 'en').toLowerCase().startsWith('fr') ? 'fr' : 'en');
    S.lang = lang;
    const L = (fr, en) => (lang === 'fr' ? fr : en);
    const faq = (q, a) => `<details class="faq"><summary>${q}</summary><div>${a}</div></details>`;
    const sec = (id, title, body, tag) => `<div id="h-${id}" class="mb">${card(title, body, tag)}</div>`;
    const toc = [['what', L('Osiris, c’est quoi ?', 'What is Osiris?')], ['how', L('Comment ça marche', 'How it works')], ['pages', L('Les pages', 'The pages')], ['numbers', L('Les chiffres', 'The numbers')], ['recall', L('Relire sans tout relire', 'Re-reading cheaply')], ['tools', L('Les 6 outils', 'The 6 tools')], ['faq', 'FAQ']];
    const f = (n, t, d, s) => `<div class="f"><b>${n}. ${t}</b>${d}<small>${s}</small></div>`;
    const dl = (rows) => `<dl class="helplist">${rows.map(([a, b]) => `<dt>${a}</dt><dd>${b}</dd>`).join('')}</dl>`;
    el('view').innerHTML = `
      <div class="helptoc">
        <span class="lang"><button data-lang="fr" class="${lang === 'fr' ? 'on' : ''}">Français</button><button data-lang="en" class="${lang === 'en' ? 'on' : ''}">English</button></span>
        ${toc.map(([id, t]) => `<a href="#" data-goto="h-${id}">${t}</a>`).join('')}
      </div>
      ${sec('what', L('Osiris, c’est quoi ?', 'What is Osiris?'), `
        <p style="margin-top:0">${L(
          'Quand un agent IA travaille, tout ce qu’il lit (fichiers, logs, résultats d’outils) s’empile dans sa mémoire de travail, le <b>contexte</b>. Plus il est plein, plus l’agent coûte cher, ralentit et oublie.',
          'While an AI agent works, everything it reads (files, logs, tool results) piles up in its working memory, the <b>context</b>. The fuller it gets, the more it costs, the slower it is, and the more it forgets.')}</p>
        <p>${L(
          'Osiris est un <b>coffre-fort et un comptable</b> pour cette mémoire. Il range les gros résultats hors du contexte, laisse l’agent relire seulement la tranche utile, compte ce que ça économise, et prouve que rien n’a été perdu. L’œil de la page Overview, c’est lui : il veille.',
          'Osiris is a <b>vault and an accountant</b> for that memory. It stores big results outside the context, lets the agent re-read only the slice it needs, counts what that saves, and proves nothing was lost. The eye on the Overview page is Osiris keeping watch.')}</p>
        <p class="good-line" style="margin-bottom:0">${L('Ce dashboard ne fait que lire la base d’Osiris : il ne modifie rien.', 'This dashboard only reads Osiris’s database: it never changes anything.')}</p>`)}
      ${sec('how', L('Comment ça marche', 'How it works'), `
        <div class="flow">
          ${f(1, L('Planifier', 'Plan'), L('L’agent annonce son objectif et ses étapes.', 'The agent states its goal and steps.'), 'osiris.plan')}
          ${f(2, L('Ranger', 'Store'), L('Un gros résultat part dans le coffre et devient une référence <span class="mono">mem://sha256:…</span>.', 'A big result goes to the vault and becomes a reference <span class="mono">mem://sha256:…</span>.'), 'osiris.observe')}
          ${f(3, L('Relire', 'Re-read'), L('L’agent demande seulement la ligne, le compteur ou l’extrait utile.', 'The agent asks only for the line, count or excerpt it needs.'), 'osiris.recall')}
          ${f(4, L('Confirmer', 'Confirm'), L('Une relecture filtrée est comptée comme économie. Retirer le contenu du contexte la confirme.', 'A filtered read is counted as a saving. Removing the content from context confirms it.'), 'observe kind=dropped')}
          ${f(5, L('Clôturer', 'Close'), L('Un rapport final vérifie que rien n’a été perdu.', 'A final report checks that nothing was lost.'), 'osiris.checkpoint')}
        </div>
        <p class="muted" style="margin-bottom:0">${L('Les très petits résultats ne sont pas rangés : les stocker coûterait plus que les garder. C’est normal.', 'Very small results are not stored: storing them would cost more than keeping them. That is expected.')}</p>`)}
      ${sec('pages', L('Les pages du dashboard', 'The dashboard pages'), dl([
        ['Overview', L('L’état de santé en un coup d’œil : l’œil, les chiffres clés, les graphiques.', 'Health at a glance: the eye, key numbers, charts.')],
        ['Tasks', L('Chaque travail lancé par l’agent. Cliquez une ligne pour la suivre dans le panneau de droite.', 'Every job the agent started. Click a row to follow it in the right-hand panel.')],
        ['Journal', L('Tout ce qui s’est passé, dans l’ordre, sans jamais rien effacer.', 'Everything that happened, in order, never erased.')],
        ['Ledger', L('Les tokens économisés et dépensés, ligne par ligne, et le gain net par tâche.', 'Tokens saved and spent line by line, and net gain per task.')],
        ['Benchmark', L('À partir de quelle taille de résultat Osiris devient rentable.', 'From which result size Osiris starts paying off.')],
        [L('Stored items', 'Stored items'), L('Les gros résultats gardés dans le coffre, avec leur taille.', 'The big results kept in the vault, with their size.')],
        ['Memory', L('Notes et décisions qu’Osiris garde d’une session à l’autre.', 'Notes and decisions Osiris keeps between sessions.')],
        ['Manifest', L('Le résumé scellé de la tâche choisie ; un écart signale une dérive.', 'The sealed summary of the selected task; a mismatch signals drift.')],
        ['Integrity check', L('La preuve que rien n’a été perdu (verdict LOSSLESS).', 'Proof that nothing was lost (LOSSLESS verdict).')],
        ['Loop guard', L('Repère un agent qui répète la même action en boucle.', 'Spots an agent repeating the same action in a loop.')],
        ['Advanced', L('Handoffs, Rules, MCP tools, Diagnostics, Settings : utiles surtout pour le dépannage.', 'Handoffs, Rules, MCP tools, Diagnostics, Settings: mostly for troubleshooting.')]]))}
      ${sec('numbers', L('Les chiffres expliqués', 'The numbers explained'), dl([
        [L('Moved (déplacés)', 'Moved'), L('Tokens rangés dans le coffre. Ce n’est pas encore une économie.', 'Tokens stored in the vault. Not a saving yet.')],
        [L('Saved (économisés)', 'Saved'), L('Tokens que l’agent n’a pas eu à relire ou à garder dans son contexte. <span class="good-line">Plus haut = mieux.</span>', 'Tokens the agent did not have to re-read or keep in its context. <span class="good-line">Higher is better.</span>')],
        [L('Osiris cost (coût)', 'Osiris cost'), L('Ce que coûtent les réponses d’Osiris elles-mêmes. Plus bas = mieux.', 'What Osiris’s own replies cost. Lower is better.')],
        [L('Net gain', 'Net gain'), L('Économisé moins coût. Positif = Osiris est rentable.', 'Saved minus cost. Positive means Osiris is paying off.')],
        [L('Ratio', 'Ratio'), L('Combien de tokens économisés pour 1 token dépensé.', 'How many tokens saved per token spent.')],
        ['LOSSLESS', L('Verdict de l’audit : rien supprimé, chaque contenu vérifié par sa signature (hash).', 'Audit verdict: nothing deleted, every item verified by its hash.')]]))}
      ${sec('recall', L('Relire sans tout relire', 'Re-reading cheaply'), `
        <p style="margin-top:0">${L('Avec <span class="mono">osiris.recall</span> et une référence, le paramètre <span class="mono">op</span> choisit la tranche à relire :', 'With <span class="mono">osiris.recall</span> and a reference, the <span class="mono">op</span> parameter picks the slice to re-read:')}</p>
        ${dl([
          ['count', L('Combien de lignes contiennent un mot. Réponse : un nombre (~3 tokens). Le moins cher.', 'How many lines contain a word. Answer: one number (~3 tokens). The cheapest.')],
          ['grep', L('Les lignes qui contiennent un mot ou une regex.', 'The lines containing a word or regex.')],
          ['range', L('Les lignes de <span class="mono">start</span> à <span class="mono">end</span>.', 'Lines <span class="mono">start</span> to <span class="mono">end</span>.')],
          ['head / tail', L('Le début ou la fin.', 'The beginning or the end.')],
          ['outline', L('La structure générale, sans le détail.', 'The overall structure, without the detail.')],
          ['excerpt', L('Un extrait ciblé autour de <span class="mono">query</span>.', 'A targeted excerpt around <span class="mono">query</span>.')],
          ['aggregate / jsonl', L('Un résumé chiffré d’un log ou de lignes JSON.', 'A numeric summary of a log or JSON lines.')]])}
        ${code('osiris.recall { ref: "mem://sha256:…", op: "count", query: "ERROR" }')}`)}
      ${sec('tools', L('Les 6 outils', 'The 6 tools'), dl([
        ['osiris.plan', L('Démarre, met à jour ou reprend une tâche (manifeste scellé).', 'Starts, updates or resumes a task (sealed manifest).')],
        ['osiris.precheck', L('Vérifie une action avant de la faire : règles, doublons, budget.', 'Checks an action before it runs: rules, duplicates, budget.')],
        ['osiris.observe', L('Note une action ou range un gros résultat / fichier dans le coffre.', 'Logs an action or stores a big result / file in the vault.')],
        ['osiris.recall', L('Relit une référence, en entier ou seulement une tranche.', 'Reads a reference back, whole or just a slice.')],
        ['osiris.checkpoint', L('Photo de l’état, rapport final, compactage.', 'State snapshot, final report, compaction.')],
        ['osiris.handoff', L('Contrat de délégation pour un sous-agent.', 'Delegation contract for a sub-agent.')]]))}
      ${sec('faq', 'FAQ', `
        ${faq(L('Pourquoi « Saved » est à 0 alors que « Moved » ne l’est pas ?', 'Why is “Saved” 0 while “Moved” is not?'), L('Ranger un contenu ne vide pas encore le contexte. L’économie est comptée quand une relecture filtrée évite de tout relire, ou quand vous confirmez avec <span class="mono">observe kind=dropped</span>.', 'Storing content does not empty the context by itself. A saving is counted when a filtered read spares a full re-read, or when you confirm with <span class="mono">observe kind=dropped</span>.'))}
        ${faq(L('« Osiris cost » monte vite, c’est grave ?', 'Osiris cost rises fast, is that bad?'), L('Pas si le gain net reste positif. Sur de petites tâches le coût fixe pèse plus : voyez Benchmark.', 'Not while the net gain stays positive. On small tasks the fixed cost weighs more: see Benchmark.'))}
        ${faq(L('Le dashboard dit « database empty »', 'The dashboard says “database empty”'), L('Aucune tâche enregistrée, ou le dashboard pointe vers un autre dossier. Lancez-le avec <span class="mono">--home</span> identique à celui du serveur MCP.', 'No task recorded yet, or the dashboard points at another folder. Start it with the same <span class="mono">--home</span> as the MCP server.'))}
        ${faq(L('« path outside allowed root » avec kind=file', '“path outside allowed root” with kind=file'), L('L’accès aux fichiers est limité aux dossiers autorisés (Settings). Copiez le fichier dedans ou envoyez le texte avec <span class="mono">kind=payload</span>.', 'File access is limited to the allowed folders (Settings). Copy the file inside one or send the text with <span class="mono">kind=payload</span>.'))}
        ${faq(L('Comment vérifier que rien n’est perdu ?', 'How do I check nothing was lost?'), L('Ouvrez Integrity check, ou lancez <span class="mono">python -m osiris audit --task &lt;id&gt;</span>.', 'Open Integrity check, or run <span class="mono">python -m osiris audit --task &lt;id&gt;</span>.'))}
        ${faq(L('Les pages Handoffs ou Rules sont vides', 'Handoffs or Rules are empty'), L('Normal tant que vous n’avez pas créé de sous-agent ni de règle : ce sont des fonctions optionnelles.', 'Expected until you create a sub-agent or a rule: they are optional features.'))}`)}
      <div class="grid c3">
        ${card(L('Raccourcis', 'Shortcuts'), `<dl class="kv"><dt>R</dt><dd>${L('Rafraîchir', 'Refresh')}</dd><dt>P</dt><dd>${L('Panneau tâche', 'Task panel')}</dd><dt>H</dt><dd>Help</dd><dt>Q</dt><dd>Quickstart</dd></dl>`)}
        ${card('Links', `<div class="legend"><a href="${GH.repo}" target="_blank" rel="noopener">OSIRIS repository ↗</a><a href="${GH.issues}" target="_blank" rel="noopener">${L('Signaler un problème', 'Report an issue')} ↗</a><a href="${GH.user}" target="_blank" rel="noopener">GitHub ↗</a></div>`)}
        ${card(L('Auteur', 'Author'), `<b>mlkblk</b><div class="muted">${L('Créateur et mainteneur d’Osiris.', 'Creator and maintainer of Osiris.')}</div>`)}
      </div>`;
    el('view').querySelectorAll('[data-lang]').forEach((b) => b.addEventListener('click', () => { S.lang = b.dataset.lang; VIEWS.help(); }));
    el('view').querySelectorAll('[data-goto]').forEach((a) => a.addEventListener('click', (e) => { e.preventDefault(); el(a.dataset.goto).scrollIntoView({ behavior: 'smooth', block: 'start' }); }));
    wireCopy(el('view'));
  },
};

async function render() {
  loading();
  try { await (VIEWS[S.view] || VIEWS.overview)(); } catch (e) { el('view').innerHTML = `<div class="card"><div class="empty">render error: ${esc(e.message)}</div></div>`; }
}

/* ------------------------------------------------------------ task panel */
async function selectTask(taskId, silent) {
  S.taskId = taskId; S.task = await API('/api/task/' + taskId); paintPanel();
  if (S.view === 'prefix') render();
  if (!silent) toast('task ' + taskId);
}
function paintPanel() {
  const t = S.task; el('panel-task').textContent = t ? t.task_id : '—';
  if (!t) { el('panel-state').innerHTML = '<span class="panel-empty">No task selected.</span>'; el('panel-plan').innerHTML = '—'; el('panel-manifest').textContent = '—'; el('panel-budget').innerHTML = '—'; return; }
  const st = t.state || {}, flags = st.flags || {}, b = t.budget || {}, lvl = t.level || '—', p = t.prefix || {};
  const done = Number(t.plan_done || 0), tot = Number(t.plan_total || 0), pct = tot ? Math.round((done / tot) * 100) : 0;
  el('panel-state').innerHTML = `<dl class="kv"><dt>Objective</dt><dd style="font-family:var(--sans)">${esc(t.objective || '—')}</dd><dt>Level</dt><dd><span class="pill ${lvlCls(lvl)}">${esc(lvl)}</span></dd><dt>Volume</dt><dd>${num(t.volume)} tok</dd><dt>Files</dt><dd>${num(Object.keys(st.files || {}).length)}</dd><dt>Decisions</dt><dd>${num((st.decisions || []).length)}</dd></dl>`;
  el('panel-plan').innerHTML = `<div class="progress"><i style="width:${pct}%"></i></div><div class="mono">${done}/${tot} steps · ${pct}%</div>`;
  el('panel-manifest').innerHTML = `<b>OSIRIS/1</b> task=${esc(t.task_id)} mode=${esc(lvl)}\nhead  ${esc((p.head_hash || flags.head_hash || '—').slice(0, 26))}\nzoneB ${esc((p.zoneB_hash || flags.zoneB_hash || '—').slice(0, 26))}\ntail  ${esc((p.tail_hash || flags.tail_hash || '—').slice(0, 26))}\nSEAL  ${esc((p.prefix_hash || flags.prefix_hash || '—').slice(0, 26))}`;
  el('panel-budget').innerHTML = `<dl class="kv"><dt>Tokens</dt><dd>${num(b.tokens_used || b.tokens || b.tokens_estimated || 0)}</dd><dt>Budget</dt><dd>${b.ok === undefined ? '—' : b.ok ? '<span class="pill ok">ok</span>' : '<span class="pill bad">exceeded</span>'}</dd><dt>Saved</dt><dd style="color:var(--emerald)">${num(b.tokens_saved || 0)}</dd><dt>Journal</dt><dd>${num((t.events || []).length)} events</dd></dl>`;
}
async function paintFeed() {
  try {
    const rows = ((await API('/api/events')).items || []).slice(0, 40);
    el('panel-feed').innerHTML = rows.length ? rows.map((r) => `<div class="feed-item ${r.kind === 'checkpoint' ? 'ok' : r.action_state === 'failed' ? 'bad' : ''}"><div class="k">${esc(r.kind)}</div><div class="t">${esc(r.task_id)}</div><div class="ts">${ts(r.ts)}</div></div>`).join('') : '<span class="panel-empty">journal empty</span>';
  } catch (e) {}
}
function panelAction(a) {
  const go = (v) => { S.view = v; syncNav(); render(); };
  if (a === 'audit') go('audit'); else if (a === 'bench') go('bench'); else if (a === 'diag') go('diagnostics'); else if (a === 'refresh') { refresh(true); paintFeed(); }
}
async function refreshIntegrity() {
  try { const a = await API('/api/audit'); S.integrity = a.lossless === true ? 'LOSSLESS' : a.lossless === false ? 'VIOLATION' : '—'; el('k-integrity').textContent = S.integrity; el('k-integrity').parentElement.className = 'kpi ' + (S.integrity === 'LOSSLESS' ? 'good' : S.integrity === 'VIOLATION' ? 'bad' : ''); } catch (e) {}
}
async function paintExtraBadges() {
  for (const [id, path] of [['b-inv', '/api/invariants'], ['b-tools', '/api/tools'], ['b-diag', '/api/diagnostics']]) { try { const d = await API(path); setBadge(id, d.count); } catch (e) {} }
}
async function autoSelectTask() {
  if (S.taskId) return;
  try { const t = ((await API('/api/tasks')).tasks || [])[0]; if (t) await selectTask(t.task_id, true); } catch (e) {}
}

document.addEventListener('keydown', (e) => {
  if (e.target.matches('input,select,textarea') || e.ctrlKey || e.metaKey || e.altKey) return;
  const k = e.key.toLowerCase();
  if (k === 'r') refresh(true); else if (k === 'p') togglePanel(); else if (k === 'q') { S.view = 'quickstart'; syncNav(); render(); } else if (k === 'h') { S.view = 'help'; syncNav(); render(); }
});

boot().then(() => { paintFeed(); refreshIntegrity(); paintExtraBadges(); autoSelectTask(); });
setInterval(paintFeed, 20000);
setInterval(() => { refreshIntegrity(); paintExtraBadges(); }, 30000);
