/* OSIRIS live layer — real-time charts + command palette + cursor-follow specular. Loaded AFTER app.js. Reads only existing /api endpoints. */
(() => {
  'use strict';
  const $ = (s, r = document) => r.querySelector(s);
  const N = 90, TICK = 2000;
  const B = { t: [], saved: [], over: [], net: [], ev: [], rate: [], lat: [] };
  let lastSeq = 0, first = true, n = 0, online = true;
  const num = (x) => (x == null || Number.isNaN(+x)) ? '\u2014' : Math.abs(x) >= 1e6 ? (x / 1e6).toFixed(2) + 'M' : Math.abs(x) >= 1e4 ? (x / 1e3).toFixed(1) + 'k' : Math.round(x).toLocaleString('en-US');
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const col = (name, fb) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fb;
  const push = (a, x) => { a.push(x); if (a.length > N) a.shift(); };
  const store = { get: (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } }, set: (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* ignore */ } } };
  /* Jeton d'authentification : partage avec app.js (charge avant live.js). */
  const AUTH = (() => { try { const t = sessionStorage.getItem('osiris.token'); return t ? { Authorization: 'Bearer ' + t } : {}; } catch (e) { return {}; } })();
  const api = (p, opts) => fetch(p, Object.assign({ headers: AUTH }, opts || {}));

  /* ---------- build strip ---------- */
  const ws = $('#workspace'), view = $('#view');
  if (!ws || !view) return;
  const strip = document.createElement('section');
  strip.id = 'live'; strip.className = 'glass live';
  strip.innerHTML = `
    <div class="live-head">
      <span class="live-pill" id="lv-pill"><i></i><span>LIVE</span></span>
      <span class="live-meta" id="lv-meta">connecting\u2026</span><span class="spacer"></span>
      <button class="btn ghost sm" id="lv-k" title="Ctrl+K">\u2318K Search</button>
      <button class="btn ghost sm" id="lv-toggle">Collapse</button>
    </div>
    <div class="live-body">
      <div class="tiles">
        <div class="tile" data-k="saved"><span class="tl">Tokens saved</span><b class="tv" data-v="0">\u2014</b><span class="ts" id="ts-saved"></span><svg class="spark" viewBox="0 0 120 36" preserveAspectRatio="none"></svg></div>
        <div class="tile" data-k="net"><span class="tl">Net gain</span><b class="tv" data-v="0">\u2014</b><span class="ts" id="ts-net"></span><svg class="spark" viewBox="0 0 120 36" preserveAspectRatio="none"></svg></div>
        <div class="tile" data-k="ev"><span class="tl">Journal events</span><b class="tv" data-v="0">\u2014</b><span class="ts" id="ts-ev"></span><svg class="spark" viewBox="0 0 120 36" preserveAspectRatio="none"></svg></div>
        <div class="tile" data-k="lat"><span class="tl">API latency</span><b class="tv" data-v="0">\u2014</b><span class="ts" id="ts-lat"></span><svg class="spark" viewBox="0 0 120 36" preserveAspectRatio="none"></svg></div>
      </div>
      <div class="live-chart" id="lv-chart">
        <div class="lc-legend"><span><b style="background:var(--turq)"></b>saved</span><span><b style="background:var(--lapis)"></b>overhead</span><span><b style="background:var(--gold)"></b>net</span></div>
        <span class="lc-axis" id="lc-max" style="top:8px"></span><span class="lc-axis" id="lc-min" style="bottom:6px">0</span>
        <svg viewBox="0 0 640 156" preserveAspectRatio="none"></svg>
        <i class="lc-dot" id="lc-dot"></i><i class="lc-cross" id="lc-cross"></i><div class="lc-tip" id="lc-tip"></div>
      </div>
      <div class="live-feed" id="lv-feed"></div>
    </div>`;
  ws.insertBefore(strip, view);
  if (store.get('osiris.live') === '0') { strip.classList.add('collapsed'); $('#lv-toggle').textContent = 'Expand'; }
  $('#lv-toggle').onclick = () => { const c = strip.classList.toggle('collapsed'); $('#lv-toggle').textContent = c ? 'Expand' : 'Collapse'; store.set('osiris.live', c ? '0' : '1'); };

  /* ---------- drawing ---------- */
  const xs = (i, len, w, p) => p + (w - 2 * p) * (i + (N - len)) / (N - 1);
  const smooth = (P) => P.reduce((d, a, i) => i ? d + ` C${(P[i - 1][0] + a[0]) / 2},${P[i - 1][1]} ${(P[i - 1][0] + a[0]) / 2},${a[1]} ${a[0]},${a[1]}` : `M${a[0]},${a[1]}`, '');

  function spark(svg, arr, color, id) {
    if (!svg || arr.length < 2) return;
    const W = 120, H = 36, p = 3, hi = Math.max(...arr), lo = Math.min(...arr), span = hi - lo;
    const P = arr.map((y, i) => [xs(i, arr.length, W, p), span ? H - p - (y - lo) / span * (H - 2 * p) : H / 2]);
    const d = smooth(P), l = P[P.length - 1];
    svg.innerHTML = `<defs><linearGradient id="${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${color}" stop-opacity=".38"/><stop offset="1" stop-color="${color}" stop-opacity="0"/></linearGradient></defs>
      <path d="${d} L${l[0]},${H} L${P[0][0]},${H} Z" fill="url(#${id})"/><path d="${d}" fill="none" stroke="${color}" stroke-width="1.8" stroke-linecap="round" vector-effect="non-scaling-stroke"/>`;
  }

  let geo = null;
  function chart() {
    const svg = $('#lv-chart svg'), len = B.saved.length;
    if (!svg || len < 2) return;
    const W = 640, H = 156, p = 8, top = 30, bot = 26;
    const max = Math.max(1, ...B.saved, ...B.over, ...B.net), sy = (v) => H - bot - (v / max) * (H - top - bot);
    const line = (arr) => arr.map((y, i) => [xs(i, len, W, p), sy(y)]);
    const S = line(B.saved), O = line(B.over), G = line(B.net);
    const rmax = Math.max(1, ...B.rate), bw = (W - 2 * p) / N * .62;
    const bars = B.rate.map((r, i) => { const h = r / rmax * 20; return r ? `<rect x="${xs(i, len, W, p) - bw / 2}" y="${H - 4 - h}" width="${bw}" height="${h}" rx="2" fill="${col('--lapis', '#2456c8')}" opacity=".28"/>` : ''; }).join('');
    const grid = [0, .5, 1].map((f) => `<line x1="${p}" x2="${W - p}" y1="${sy(max * f)}" y2="${sy(max * f)}" stroke="rgba(31,64,120,.12)" stroke-dasharray="3 5" vector-effect="non-scaling-stroke"/>`).join('');
    const ds = smooth(S);
    svg.innerHTML = `<defs><linearGradient id="lvg-s" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${col('--turq', '#12a594')}" stop-opacity=".45"/><stop offset="1" stop-color="${col('--turq', '#12a594')}" stop-opacity="0"/></linearGradient></defs>
      ${grid}${bars}<path d="${ds} L${S[len - 1][0]},${H - bot} L${S[0][0]},${H - bot} Z" fill="url(#lvg-s)"/>
      <path d="${smooth(O)}" fill="none" stroke="${col('--lapis', '#2456c8')}" stroke-width="2" stroke-linecap="round" vector-effect="non-scaling-stroke"/>
      <path d="${smooth(G)}" fill="none" stroke="${col('--gold', '#b9790a')}" stroke-width="2" stroke-linecap="round" vector-effect="non-scaling-stroke"/>
      <path d="${ds}" fill="none" stroke="${col('--turq', '#12a594')}" stroke-width="2.6" stroke-linecap="round" vector-effect="non-scaling-stroke"/>`;
    const l = S[len - 1], dot = $('#lc-dot');
    dot.style.left = (l[0] / W * 100) + '%'; dot.style.top = (l[1] / H * 100) + '%';
    $('#lc-max').textContent = num(max);
    geo = { W, p, len };
  }

  /* hover crosshair + tooltip */
  const cw = $('#lv-chart');
  cw.addEventListener('pointermove', (e) => {
    if (!geo) return;
    const r = cw.getBoundingClientRect(), f = (e.clientX - r.left) / r.width;
    let i = Math.round((f * geo.W - geo.p) / (geo.W - 2 * geo.p) * (N - 1)) - (N - geo.len);
    i = Math.max(0, Math.min(geo.len - 1, i));
    const cx = (xs(i, geo.len, geo.W, geo.p) / geo.W) * r.width, tip = $('#lc-tip'), cr = $('#lc-cross');
    cr.style.display = tip.style.display = 'block'; cr.style.left = cx + 'px';
    tip.innerHTML = `${new Date(B.t[i]).toLocaleTimeString('en-US')}<br>saved <b>${num(B.saved[i])}</b> \u00b7 overhead <b>${num(B.over[i])}</b><br>net <b>${num(B.net[i])}</b> \u00b7 +${B.rate[i]} ev`;
    tip.style.left = Math.min(cx + 12, r.width - tip.offsetWidth - 8) + 'px';
  });
  cw.addEventListener('pointerleave', () => { $('#lc-tip').style.display = $('#lc-cross').style.display = 'none'; });

  function tween(el, to) {
    const from = +el.dataset.v || 0; if (from === to) { el.textContent = num(to); return; }
    el.dataset.v = to; const t0 = performance.now(), d = 700;
    const step = (t) => { const k = Math.min(1, (t - t0) / d), e = 1 - Math.pow(1 - k, 3); el.textContent = num(from + (to - from) * e); if (k < 1) requestAnimationFrame(step); };
    requestAnimationFrame(step);
  }
  const tile = (k) => $(`.tile[data-k="${k}"]`);

  /* ---------- polling ---------- */
  async function poll() {
    if (document.hidden) return;
    const t0 = performance.now(); n++;
    try {
      const r = await api('/api/overview', { cache: 'no-store' }); const o = await r.json();
      const lat = performance.now() - t0, T = o.totals || {}, C = o.counts || {};
      online = r.ok;
      push(B.t, Date.now()); push(B.saved, T.tokens_saved || 0); push(B.over, T.overhead || 0); push(B.net, T.net_gain || 0);
      push(B.ev, C.events || 0); push(B.rate, B.ev.length > 1 ? Math.max(0, B.ev[B.ev.length - 1] - B.ev[B.ev.length - 2]) : 0); push(B.lat, lat);
      tween(tile('saved').querySelector('.tv'), T.tokens_saved || 0); tween(tile('net').querySelector('.tv'), T.net_gain || 0); tween(tile('ev').querySelector('.tv'), C.events || 0);
      tile('lat').querySelector('.tv').textContent = lat.toFixed(0) + ' ms';
      const moved = T.tokens_moved || 0, ratio = (T.tokens_saved && T.overhead) ? (T.tokens_saved / T.overhead).toFixed(1) + '\u00d7 return' : '';
      $('#ts-saved').textContent = moved ? `of ${num(moved)} moved` : ''; $('#ts-net').textContent = ratio;
      const per = B.rate.slice(-30).reduce((a, b) => a + b, 0); $('#ts-ev').textContent = `+${per} / min`;
      $('#ts-lat').textContent = `avg ${(B.lat.reduce((a, b) => a + b, 0) / B.lat.length).toFixed(0)} ms`;
      spark(tile('saved').querySelector('svg'), B.saved, col('--emerald', '#0f7d56'), 'sp-a'); spark(tile('net').querySelector('svg'), B.net, col('--lapis', '#2456c8'), 'sp-b');
      spark(tile('ev').querySelector('svg'), B.ev, col('--violet', '#5b41d1'), 'sp-c'); spark(tile('lat').querySelector('svg'), B.lat, col('--cyan', '#0b8a96'), 'sp-d');
      chart();
      $('#lv-meta').textContent = `${C.tasks || 0} tasks \u00b7 ${num(C.ledger || 0)} ledger \u00b7 integrity ${o.integrity || '\u2014'} \u00b7 ${new Date().toLocaleTimeString('en-US')}`;
    } catch (e) { online = false; $('#lv-meta').textContent = 'api unreachable \u2014 retrying\u2026'; }
    const pill = $('#lv-pill'); pill.classList.toggle('bad', !online); pill.lastChild.textContent = online ? 'LIVE' : 'OFFLINE';
    if (n % 2 === 1) feed();
  }

  const KIND = { checkpoint: ['ok', 'ckpt'], saving: ['ok', 'save'], decision: ['vio', 'decide'], lesson: ['vio', 'lesson'], note: ['', 'note'], task_start: ['gold', 'task'], externalize: ['', 'store'], action: ['ok', 'act'], resume: ['gold', 'resume'], observe: ['', 'obs'] };
  const ago = (ts) => { const s = Math.max(0, Date.now() / 1000 - ts); return s < 60 ? Math.floor(s) + 's' : s < 3600 ? Math.floor(s / 60) + 'm' : s < 86400 ? Math.floor(s / 3600) + 'h' : Math.floor(s / 86400) + 'd'; };
  async function feed() {
    try {
      const d = (await api('/api/events', { cache: 'no-store' })).json(), items = (d.items || []).filter((e) => e.kind !== 'prefix');
      if (!items.length) return;
      const box = $('#lv-feed'), fresh = items.filter((e) => e.seq > lastSeq).slice(0, first ? 6 : 4).reverse();
      lastSeq = Math.max(lastSeq, ...items.map((e) => e.seq));
      for (const e of fresh) {
        const p = e.payload || {}, k = KIND[e.kind] || ['', e.kind], bad = e.action_state === 'failed' || p.status === 'error';
        const row = document.createElement('div');
        row.className = 'lf in ' + (bad ? 'bad' : k[0]);
        row.innerHTML = `<span class="k">${esc(k[1])}</span><span class="x">${esc(p.objective || p.text || p.label || p.tool || p.path || e.task_id)}</span><span class="a" data-ts="${e.ts}">${ago(e.ts)}</span>`;
        box.prepend(row);
      }
      while (box.children.length > 6) box.lastChild.remove();
      first = false;
    } catch (e) { /* ignore */ }
  }
  setInterval(() => document.querySelectorAll('#lv-feed .a').forEach((a) => { a.textContent = ago(+a.dataset.ts); }), 5000);
  async function seed() {
    try {
      const d = (await api('/api/ledger', { cache: 'no-store' })).json();
      const it = (d.items || []).slice().sort((a, b) => a.ts - b.ts);
      if (it.length < 2) return;
      let s = 0, o = 0;
      const cum = it.map((r) => { s += r.tokens_saved || 0; if (r.kind === 'overhead') o += r.tokens_in || 0; return [r.ts * 1000, s, o]; });
      const k = Math.min(60, cum.length);
      for (let i = 0; i < k; i++) { const c = cum[Math.round(i * (cum.length - 1) / (k - 1))]; B.t.push(c[0]); B.saved.push(c[1]); B.over.push(c[2]); B.net.push(c[1] - c[2]); B.rate.push(0); }
    } catch (e) { /* ignore */ }
  }
  seed().then(() => { poll(); setInterval(poll, TICK); });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(); });

  /* ---------- cursor-follow specular ---------- */
  let raf = 0;
  document.addEventListener('pointermove', (e) => {
    if (raf) return; raf = requestAnimationFrame(() => {
      raf = 0; const g = e.target.closest && e.target.closest('.glass,.card'); if (!g) return;
      const r = g.getBoundingClientRect(); g.style.setProperty('--mx', ((e.clientX - r.left) / r.width * 100).toFixed(1) + '%'); g.style.setProperty('--my', ((e.clientY - r.top) / r.height * 100).toFixed(1) + '%');
    });
  }, { passive: true });

  /* ---------- command palette (Ctrl/Cmd+K) ---------- */
  const pal = document.createElement('div');
  pal.id = 'cmdk';
  pal.innerHTML = '<div class="cmdk-box glass"><input placeholder="Jump to a view or run an action\u2026" autocomplete="off" spellcheck="false"/><ul></ul><div class="cmdk-foot">\u2191\u2193 navigate \u00b7 \u21b5 open \u00b7 esc close</div></div>';
  document.body.appendChild(pal);
  const inp = $('input', pal), ul = $('ul', pal); let items = [], sel = 0;
  const click = (s) => { const e = $(s); if (e) e.click(); };
  function build() {
    items = [...document.querySelectorAll('.nav-item[data-view]')].map((el) => ({ t: el.textContent.replace(/\d+$/, '').trim(), g: 'view', run: () => el.click() }));
    items.push({ t: 'Refresh data', g: 'action', run: () => click('#btn-refresh') }, { t: 'Toggle task panel', g: 'action', run: () => click('#btn-panel') },
      { t: 'Toggle live strip', g: 'action', run: () => click('#lv-toggle') }, { t: 'Run integrity check', g: 'action', run: () => click('[data-act="audit"]') },
      { t: 'Run benchmark', g: 'action', run: () => click('[data-act="bench"]') }, { t: 'Open diagnostics', g: 'action', run: () => click('[data-act="diag"]') });
  }
  function paint() {
    const q = inp.value.trim().toLowerCase(), list = items.filter((i) => !q || i.t.toLowerCase().includes(q) || i.g.includes(q)); sel = Math.min(sel, Math.max(0, list.length - 1));
    ul.innerHTML = list.map((i, k) => `<li class="${k === sel ? 'on' : ''}" data-i="${items.indexOf(i)}"><span>${esc(i.t)}</span><span class="g">${i.g}</span></li>`).join('') || '<li>No match</li>';
    ul.querySelectorAll('li[data-i]').forEach((li) => { li.onclick = () => { close(); items[+li.dataset.i].run(); }; });
    pal._list = list;
  }
  function open() { build(); inp.value = ''; sel = 0; paint(); pal.classList.add('open'); inp.focus(); }
  function close() { pal.classList.remove('open'); }
  pal.addEventListener('mousedown', (e) => { if (e.target === pal) close(); });
  inp.addEventListener('input', () => { sel = 0; paint(); });
  inp.addEventListener('keydown', (e) => {
    e.stopPropagation();
    if (e.key === 'Escape') close();
    else if (e.key === 'ArrowDown') { sel = Math.min(sel + 1, pal._list.length - 1); paint(); e.preventDefault(); }
    else if (e.key === 'ArrowUp') { sel = Math.max(sel - 1, 0); paint(); e.preventDefault(); }
    else if (e.key === 'Enter' && pal._list[sel]) { const it = pal._list[sel]; close(); it.run(); }
  });
  document.addEventListener('keydown', (e) => { if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); pal.classList.contains('open') ? close() : open(); } });
  $('#lv-k').onclick = open;
})();
