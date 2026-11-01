/* =============================================================================
   OSIRIS Control Plane — app
   Dashboard delta : shell QadGraph + vues OSIRIS (ledger, bench, diagnostics).
   ============================================================================= */
'use strict';

const API = (p) => fetch(p).then((r) => r.json());

const S = {
  view: 'overview',
  taskId: null,
  health: null,
  overview: null,
  task: null,
  feed: [],
  panelOpen: true,
};

const $ = (sel) => document.querySelector(sel);
const el = (id) => document.getElementById(id);

const esc = (v) =>
  String(v === null || v === undefined ? '' : v)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');

const num = (n) => {
  const v = Number(n || 0);
  if (!isFinite(v)) return '0';
  return v.toLocaleString('fr-FR');
};

const ts = (t) => {
  if (!t) return '—';
  const d = new Date(Number(t) * 1000);
  return isNaN(d) ? '—' : d.toLocaleString('fr-FR');
};

const dur = (s) => {
  const n = Math.max(0, Math.floor(Number(s || 0)));
  const h = Math.floor(n / 3600), m = Math.floor((n % 3600) / 60);
  return h ? `${h}h${String(m).padStart(2, '0')}` : `${m}m${String(n % 60).padStart(2, '0')}s`;
};

const bytes = (b) => {
  const v = Number(b || 0);
  if (v < 1024) return v + ' B';
  if (v < 1048576) return (v / 1024).toFixed(1) + ' Ko';
  return (v / 1048576).toFixed(2) + ' Mo';
};

function toast(msg, ms = 2600) {
  const t = el('toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(t._t);
  t._t = setTimeout(() => t.classList.remove('show'), ms);
}

function loading() {
  el('view').innerHTML = '<div class="loading"><span class="spin">◌</span> chargement…</div>';
}

/* ---------------------------------------------------------------- helpers */
function card(title, body, tag) {
  return `<div class="card"><h3>${esc(title)}${tag ? `<span class="tag">${esc(tag)}</span>` : ''}</h3>${body}</div>`;
}

function stat(n, t, s, cls) {
  return `<div class="card"><div class="stat"><span class="n ${cls || ''}">${esc(n)}</span><span class="t">${esc(t)}</span>${
    s ? `<span class="s">${esc(s)}</span>` : ''
  }</div></div>`;
}

function table(cols, rows, render) {
  if (!rows || !rows.length) return '<div class="empty">aucune donnee</div>';
  return `<div class="scroll"><table><thead><tr>${cols
    .map((c) => `<th>${esc(c)}</th>`)
    .join('')}</tr></thead><tbody>${rows
    .map((r) => `<tr>${render(r).map((c) => `<td>${c}</td>`).join('')}</tr>`)
    .join('')}</tbody></table></div>`;
}

/* ------------------------------------------------------------------ boot */
async function boot() {
  document.querySelectorAll('.nav-item').forEach((n) => {
    n.addEventListener('click', () => {
      document.querySelectorAll('.nav-item').forEach((x) => x.classList.remove('active'));
      n.classList.add('active');
      S.view = n.dataset.view;
      render();
    });
  });
  el('btn-refresh').addEventListener('click', () => refresh(true));
  el('btn-panel').addEventListener('click', togglePanel);
  el('btn-close-panel').addEventListener('click', togglePanel);
  document.querySelectorAll('#panel .actions .btn').forEach((b) => {
    b.addEventListener('click', () => panelAction(b.dataset.act));
  });
  await refresh(false);
  setInterval(() => refresh(false, true), 15000);
}

function togglePanel() {
  S.panelOpen = !S.panelOpen;
  el('app').classList.toggle('no-panel', !S.panelOpen);
}

/* --------------------------------------------------------------- refresh */
async function refresh(manual, silent) {
  try {
    const h = await API('/api/health');
    S.health = h;
    el('db-dot').className = 'dot ' + (h.db_exists ? (h.empty ? 'warn' : 'ok') : 'bad');
    el('db-state').textContent = h.db_exists ? (h.empty ? 'base vide' : 'connecte') : 'base introuvable';
    el('db-path').textContent = h.db;
  } catch (e) {
    el('db-dot').className = 'dot bad';
    el('db-state').textContent = 'serveur injoignable';
  }
  if (silent) {
    // refresh silencieux : uniquement les KPI du topbar
    try {
      const o = await API('/api/overview');
      S.overview = o;
      paintKpis(o);
    } catch (e) {}
    return;
  }
  const o = await API('/api/overview');
  S.overview = o;
  paintKpis(o);
  paintBadges();
  await render();
  if (manual) toast('actualise');
}

function paintKpis(o) {
  const t = o.totals || {};
  const c = o.counts || {};
  el('k-tasks').textContent = num(c.tasks);
  el('k-refs').textContent = num(c.refs);
  el('k-events').textContent = num(c.events);
  el('k-saved').textContent = num(t.tokens_saved);
  el('k-overhead').textContent = num(t.overhead);
  const net = el('k-net');
  net.textContent = (t.net_gain > 0 ? '+' : '') + num(t.net_gain);
  net.parentElement.className = 'kpi ' + (t.net_gain > 0 ? 'good' : t.net_gain < 0 ? 'bad' : '');
  el('k-integrity').textContent = o.integrity || S.integrity || '—';
  el('k-integrity').parentElement.className = 'kpi ' + ((o.integrity || S.integrity) === 'LOSSLESS' ? 'good' : '');
}

function paintBadges() {
  const c = (S.overview && S.overview.counts) || {};
  const map = {
    'b-tasks': c.tasks, 'b-events': c.events, 'b-memory': c.memory,
    'b-refs': c.refs, 'b-handoffs': c.handoffs, 'b-ledger': c.ledger,
    'b-fp': (S.overview && S.overview.fingerprints) || 0,
  };
  Object.entries(map).forEach(([id, v]) => { if (el(id)) el(id).textContent = num(v); });
}

/* ---------------------------------------------------------------- render */
const VIEWS = {
  async overview() {
    const o = S.overview;
    const t = o.totals || {};
    const c = o.counts || {};
    const led = o.ledger || [];
    const maxK = Math.max(1, ...led.map((r) => Number(r.n || 0)));
    const bars = led.length
      ? led
          .map((r) => {
            const pct = Math.round((Number(r.n || 0) / maxK) * 100);
            return `<div style="margin-bottom:9px">
              <div style="display:flex;justify-content:space-between;font-size:11px;margin-bottom:4px">
                <span class="mono">${esc(r.kind)}</span>
                <span class="mono" style="color:var(--dim)">${num(r.n)} entree(s) · ${num(r.tin)} tok</span>
              </div>
              <div class="bar cyan"><i style="width:${pct}%"></i></div>
            </div>`;
          })
          .join('')
      : '<div class="empty">le ledger est vide : aucun outil n a encore ete appele</div>';

    el('view').innerHTML = `
      <div class="grid c4" style="margin-bottom:14px">
        ${stat(num(c.tasks), 'Taches', 'enregistrees en base', 'cyan')}
        ${stat(num(c.memory), 'Memoire typee', 'task / project / agent / global', 'violet')}
        ${stat(num(c.refs), 'Refs', 'store content-addressed', 'blue')}
        ${stat(num(c.checkpoints), 'Checkpoints', 'journal append-only', 'emerald')}
      </div>
      <div class="grid c4" style="margin-bottom:14px">
        ${stat(num(t.tokens_saved), 'Tokens economises', 'cumul du ledger', 'emerald')}
        ${stat(num(t.overhead), 'Surcout OSIRIS', 'cout de reponse des outils', 'amber')}
        ${stat((t.net_gain > 0 ? '+' : '') + num(t.net_gain), 'Gain net', 'economies − surcout', t.net_gain > 0 ? 'emerald' : 'rose')}
        ${stat(num(c.ledger), 'Ecritures ledger', 'trace complete', 'cyan')}
      </div>
      <div class="grid c2">
        ${card('Repartition du ledger', bars, 'par kind')}
        ${card('Etat du serveur', `<dl class="kv">
          <dt>Version</dt><dd>${esc(S.health && S.health.db ? '0.1.0' : '—')}</dd>
          <dt>Base</dt><dd>${esc(S.health ? S.health.db : '—')}</dd>
          <dt>Home</dt><dd>${esc(S.health ? S.health.home : '—')}</dd>
          <dt>Python</dt><dd>${esc(S.health ? S.health.python : '—')}</dd>
          <dt>Lignes</dt><dd>${num(S.health ? S.health.total_rows : 0)}</dd>
          <dt>Derniere activite</dt><dd>${ts(o.last_activity)}</dd>
        </dl>`, 'runtime')}
      </div>`;
  },

  async tasks() {
    const d = await API('/api/tasks');
    const rows = d.tasks || [];
    const body = rows.length
      ? `<div class="scroll"><table><thead><tr>
          <th>Tache</th><th>Objectif</th><th>Niveau</th><th>Volume</th><th>Plan</th><th>Decisions</th><th>Mis a jour</th>
        </tr></thead><tbody>${rows
          .map(
            (r) => `<tr data-task="${esc(r.task_id)}" style="cursor:pointer">
              <td class="mono">${esc(r.task_id)}</td>
              <td>${esc((r.objective || '—').slice(0, 90))}</td>
              <td><span class="pill ${r.level === 'light' ? 'info' : r.level === 'full' ? 'violet' : 'muted'}">${esc(r.level || '—')}</span></td>
              <td class="mono">${num(r.volume)} tok</td>
              <td class="mono">${r.plan_done}/${r.plan_total}</td>
              <td class="mono">${num(r.decisions)}</td>
              <td class="mono" style="color:var(--dim)">${ts(r.updated_at)}</td>
            </tr>`
          )
          .join('')}</tbody></table></div>`
      : '<div class="empty">aucune tache en base</div>';
    el('view').innerHTML = card('Taches', body, num(rows.length) + ' tache(s)');
    el('view').querySelectorAll('[data-task]').forEach((tr) => {
      tr.addEventListener('click', () => selectTask(tr.dataset.task));
    });
  },

  async events() {
    const d = await API('/api/events');
    const rows = d.items || [];
    el('view').innerHTML = card(
      'Journal append-only',
      table(['Seq', 'Tache', 'Kind', 'Etat', 'Run key', 'Horodatage'], rows, (r) => [
        `<span class="mono">${num(r.seq)}</span>`,
        `<span class="mono">${esc(r.task_id)}</span>`,
        `<span class="pill info">${esc(r.kind)}</span>`,
        r.action_state ? `<span class="pill ${r.action_state === 'succeeded' ? 'ok' : r.action_state === 'failed' ? 'bad' : 'muted'}">${esc(r.action_state)}</span>` : '<span class="muted">—</span>',
        `<span class="mono" style="font-size:10px;color:var(--dim)">${esc((r.run_key || '—').slice(0, 14))}</span>`,
        `<span class="mono" style="color:var(--dim)">${ts(r.ts)}</span>`,
      ]),
      num(rows.length) + ' evenement(s)'
    );
  },

  async prefix() {
    const t = S.taskId ? await API('/api/task/' + S.taskId) : null;
    const st = t ? t.state || {} : {};
    const flags = st.flags || {};
    const p = t ? t.prefix || {} : {};
    const b = t ? t.budget || {} : {};
    const head = p.head_hash || flags.head_hash || '';
    const zoneB = p.zoneB_hash || flags.zoneB_hash || '';
    const tail = p.tail_hash || flags.tail_hash || '';
    const prefixHash = p.prefix_hash || flags.prefix_hash || '';

    const zone = (name, hash, verdict, note) => `<div style="margin-bottom:14px">
      <div style="display:flex;align-items:center;gap:9px;margin-bottom:5px">
        <span class="mono" style="font-size:11px;color:var(--cyan)">${esc(name)}</span>
        <span class="pill ${verdict}">${esc(verdict)}</span>
      </div>
      <div class="mono-box" style="font-size:10.5px">${esc(hash || '—')}</div>
      <div style="font-size:10.5px;color:var(--dim);margin-top:4px">${esc(note)}</div>
    </div>`;

    el('view').innerHTML = `
      <div class="grid c2">
        ${card(
          'Zones du prefixe',
          (t ? '' : '<div class="empty" style="margin-bottom:12px">selectionnez une tache pour afficher son prefixe</div>') +
            zone('head_hash', head, head ? 'ok' : 'muted', 'system + regles + contraintes · immuable · un changement = DRIFT CRITIQUE') +
            zone('zoneB_hash', zoneB, zoneB ? 'warn' : 'muted', 'objectif + plan global + tool contract · quasi stable') +
            zone('tail_hash', tail, tail ? 'info' : 'muted', 'decisions epinglees · append-only · croissance normale') +
            zone('prefix_hash', prefixHash, prefixHash ? 'ok' : 'muted', 'sha256(head ‖ zoneB) · ce qui est reellement cache'),
          t ? esc(t.task_id) : 'aucune tache'
        )}
        ${card(
          'Etat & budget',
          `<dl class="kv">
            <dt>Objectif</dt><dd>${esc(t ? t.objective || '—' : '—')}</dd>
            <dt>Niveau</dt><dd>${esc(t ? t.level || '—' : '—')}</dd>
            <dt>Volume</dt><dd>${num(t ? t.volume : 0)} tokens</dd>
            <dt>Tokens</dt><dd>${num(b.tokens_used || b.tokens || b.tokens_estimated || 0)}</dd>
            <dt>Budget</dt><dd>${esc(b.ok === undefined ? '—' : b.ok ? 'ok' : 'depasse')}</dd>
            <dt>Fichiers</dt><dd>${num(Object.keys(st.files || {}).length)}</dd>
            <dt>Decisions</dt><dd>${num((st.decisions || []).length)}</dd>
            <dt>Memoire</dt><dd>${num(Object.keys(st.memory || {}).length)}</dd>
          </dl>`,
          'task state'
        )}
      </div>`;
  },

  async memory() {
    const d = await API('/api/memory');
    const rows = d.items || [];
    const scopes = Object.entries(d.by_scope || {}).map(([k, v]) => `<span class="pill muted">${esc(k)} ${v}</span>`).join(' ');
    const kinds = Object.entries(d.by_kind || {}).map(([k, v]) => `<span class="pill info">${esc(k)} ${v}</span>`).join(' ');
    el('view').innerHTML = `
      <div class="grid c2" style="margin-bottom:14px">
        ${card('Par scope', scopes || '<span class="empty">vide</span>', 'task / project / agent / global')}
        ${card('Par kind', kinds || '<span class="empty">vide</span>', 'semantic / decision / workflow…')}
      </div>
      ${card('Memoire typee', table(['Id', 'Scope', 'Kind', 'Corps', 'Epingle', 'Seq'], rows, (r) => [
        `<span class="mono" style="font-size:10px">${esc(r.mem_id)}</span>`,
        `<span class="pill muted">${esc(r.scope)}</span>`,
        `<span class="pill violet">${esc(r.kind)}</span>`,
        `<div style="max-height:130px;overflow:auto;white-space:pre-wrap">${esc(r.body)}</div>`,
        r.pinned ? '<span class="pill ok">oui</span>' : '<span class="pill muted">non</span>',
        `<span class="mono">${num(r.seq)}</span>`,
      ]), num(rows.length) + ' entree(s)')}`;
  },

  async refs() {
    const d = await API('/api/refs');
    const rows = d.items || [];
    el('view').innerHTML = `
      <div class="grid c4" style="margin-bottom:14px">
        ${stat(num(d.count), 'Refs', 'adressees par contenu', 'cyan')}
        ${stat(bytes(d.total_bytes), 'Volume', 'contenu externalise', 'violet')}
        ${stat(num(d.redactions), 'Redactions', 'secrets masques avant hash', 'amber')}
        ${stat('sha256', 'Algorithme', 'integrite verifiee a la lecture', 'emerald')}
      </div>
      ${card('Store content-addressed', table(['Ref', 'Tache', 'Hash', 'Taille', 'Redactions', 'Expire', 'Cree'], rows, (r) => [
        `<span class="mono" style="font-size:10px">${esc(r.ref)}</span>`,
        `<span class="mono" style="font-size:10px">${esc(r.task_id || '—')}</span>`,
        `<span class="mono" style="font-size:10px;color:var(--dim)">${esc((r.content_hash || '').slice(0, 20))}</span>`,
        `<span class="mono">${bytes(r.size_bytes)}</span>`,
        `<span class="mono">${num(r.redactions)}</span>`,
        `<span class="mono" style="color:var(--dim)">${r.expires_at ? ts(r.expires_at) : '—'}</span>`,
        `<span class="mono" style="color:var(--dim)">${ts(r.created_at)}</span>`,
      ]), num(rows.length) + ' ref(s)')}`;
  },

  async handoffs() {
    const d = await API('/api/handoffs');
    const rows = d.items || [];
    el('view').innerHTML = card(
      'Contrats de delegation',
      table(['Id', 'Statut', 'Mission', 'Budget', 'Parent', 'Cree', 'Expire'], rows, (r) => {
        const c = r.contract || {};
        return [
          `<span class="mono" style="font-size:10px">${esc(r.handoff_id)}</span>`,
          `<span class="pill ${r.status === 'open' ? 'info' : r.status === 'completed' ? 'ok' : 'muted'}">${esc(r.status)}</span>`,
          esc((c.mission || '—').slice(0, 80)),
          `<span class="mono">${num((c.budget || {}).tokens || 0)}</span>`,
          `<span class="mono" style="font-size:10px">${esc(r.parent_task_id || '—')}</span>`,
          `<span class="mono" style="color:var(--dim)">${ts(r.created_at)}</span>`,
          `<span class="mono" style="color:var(--dim)">${r.expires_at ? ts(r.expires_at) : '—'}</span>`,
        ];
      }),
      num(rows.length) + ' contrat(s)'
    );
  },

  async ledger() {
    const d = await API('/api/ledger');
    const rows = d.items || [];
    const per = Object.entries(d.per_task || {});
    const perTask = per.length
      ? table(['Tache', 'Entrees', 'Tokens in', 'Out', 'Cached', 'Saved', 'Surcout', 'Gain net'], per, ([tid, a]) => [
          `<span class="mono" style="font-size:10px">${esc(tid)}</span>`,
          `<span class="mono">${num(a.entries)}</span>`,
          `<span class="mono">${num(a.tokens_in)}</span>`,
          `<span class="mono">${num(a.tokens_out)}</span>`,
          `<span class="mono" style="color:var(--cyan)">${num(a.tokens_cached)}</span>`,
          `<span class="mono" style="color:var(--emerald)">${num(a.tokens_saved)}</span>`,
          `<span class="mono" style="color:var(--amber)">${num(a.overhead)}</span>`,
          `<span class="mono" style="color:${a.net_gain > 0 ? 'var(--emerald)' : 'var(--rose)'}">${a.net_gain > 0 ? '+' : ''}${num(a.net_gain)}</span>`,
        ])
      : '<div class="empty">aucune ecriture</div>';

    el('view').innerHTML = `
      <div class="grid c2">
        ${card('Cumul par tache', perTask, 'economie vs surcout')}
        ${card('Journal du ledger', table(['Tache', 'Kind', 'In', 'Out', 'Cached', 'Fresh', 'Saved', 'Note'], rows.slice(0, 120), (r) => [
          `<span class="mono" style="font-size:10px">${esc(r.task_id)}</span>`,
          `<span class="pill ${r.kind === 'overhead' ? 'warn' : 'info'}">${esc(r.kind)}</span>`,
          `<span class="mono">${num(r.tokens_in)}</span>`,
          `<span class="mono">${num(r.tokens_out)}</span>`,
          `<span class="mono" style="color:var(--cyan)">${num(r.tokens_cached)}</span>`,
          `<span class="mono">${num(r.tokens_fresh)}</span>`,
          `<span class="mono" style="color:var(--emerald)">${num(r.tokens_saved)}</span>`,
          `<span class="mono" style="font-size:10px;color:var(--dim)">${esc((r.note || '').slice(0, 30))}</span>`,
        ]), num(rows.length) + ' ecriture(s)')}
      </div>`;
  },

  async bench() {
    const d = await API('/api/bench');
    if (d.running) {
      el('view').innerHTML = '<div class="loading"><span class="spin">◌</span> benchmark en cours (isolated)…</div>';
      setTimeout(() => VIEWS.bench(), 4000);
      return;
    }
    const rows = d.rows || [];
    const g = d.gate || {};
    const gateCls = g.passed ? 'ok' : 'bad';
    el('view').innerHTML = `
      <div class="grid c3" style="margin-bottom:14px">
        ${stat(g.passed ? 'VERTE' : 'ROUGE', 'Gate du benchmark', g.criterion || '', g.passed ? 'emerald' : 'rose')}
        ${stat(num(d.access_tokens), 'Cout d acces', 'tokens de schemas par requete', 'cyan')}
        ${stat((g.worst_adaptive_pct > 0 ? '+' : '') + num(g.worst_adaptive_pct) + ' %', 'Pire ecart', 'mode adaptatif vs baseline', g.worst_adaptive_pct >= 0 ? 'emerald' : 'rose')}
      </div>
      ${card(
        'Rentabilite par taille de payload',
        table(['Payload', 'Baseline', 'OSIRIS fixe', 'OSIRIS adaptatif', 'Fixe %', 'Adaptatif %', 'Mode', 'Surcout', 'Gain net', 'Amorti'], rows, (r) => [
          `<span class="mono">${num(r.payload_tokens)} tok</span>`,
          `<span class="mono">${num(r.baseline)}</span>`,
          `<span class="mono">${num(r.osiris_fixed)}</span>`,
          `<span class="mono" style="color:var(--cyan)">${num(r.osiris_adaptive)}</span>`,
          `<span class="mono" style="color:${r.fixed_pct >= 0 ? 'var(--emerald)' : 'var(--rose)'}">${r.fixed_pct > 0 ? '+' : ''}${num(r.fixed_pct)} %</span>`,
          `<span class="mono" style="color:${r.adaptive_pct >= 0 ? 'var(--emerald)' : 'var(--rose)'}">${r.adaptive_pct > 0 ? '+' : ''}${num(r.adaptive_pct)} %</span>`,
          `<span class="pill ${r.mode === 'light' ? 'info' : r.mode === 'full' ? 'violet' : 'muted'}">${esc(r.mode)}</span>`,
          `<span class="mono" style="color:var(--amber)">${num(r.overhead_adaptive)}</span>`,
          `<span class="mono" style="color:${r.gain_tokens > 0 ? 'var(--emerald)' : 'var(--rose)'}">${r.gain_tokens > 0 ? '+' : ''}${num(r.gain_tokens)}</span>`,
          `<span class="mono">${r.payback_tasks === null ? '—' : num(r.payback_tasks) + ' tache(s)'}</span>`,
        ]),
        'baseline vs osiris'
      )}
      <div style="margin-top:14px">${card(
        'Note de methode',
        `<div class="mono-box">${esc(d.note || '—')}</div>
         <div class="chiprow" style="margin-top:12px">
           <span class="pill ${gateCls}">gate : ${g.passed ? 'pass' : 'fail'}</span>
           <span class="pill muted">no_loss : ${g.no_loss === undefined ? '—' : g.no_loss}</span>
           <span class="pill muted">success_equal : ${g.success_equal === undefined ? '—' : g.success_equal}</span>
         </div>`,
        'methode'
      )}</div>`;
  },

  async loopguard() {
    const d = await API('/api/loopguard');
    const fp = d.fingerprints || [];
    const fl = d.failures || [];
    const tu = d.tool_usage || [];
    const max = Math.max(1, ...fp.map((f) => Number(f.count || 0)));
    const bars = fp.length
      ? fp
          .slice(0, 14)
          .map(
            (f) => `<div style="margin-bottom:8px">
              <div style="display:flex;justify-content:space-between;font-size:11px;margin-bottom:3px">
                <span class="mono" style="font-size:10px">${esc(f.tool || '—')}</span>
                <span class="mono" style="color:var(--dim)">${num(f.count)} appel(s)</span>
              </div>
              <div class="bar ${f.count >= 3 ? 'rose' : 'cyan'}"><i style="width:${Math.round((f.count / max) * 100)}%"></i></div>
            </div>`
          )
          .join('')
      : '<div class="empty">aucune empreinte : aucune boucle detectee</div>';

    el('view').innerHTML = `
      <div class="grid c4" style="margin-bottom:14px">
        ${stat(num(fp.length), 'Empreintes', 'appels fingerprints', 'cyan')}
        ${stat(num(fl.length), 'Echecs', 'signatures d erreur', fl.length ? 'rose' : 'emerald')}
        ${stat(num((d.blocked || []).length), 'Signatures bloquees', 'count >= 3', (d.blocked || []).length ? 'rose' : 'emerald')}
        ${stat(num(tu.length), 'Outils utilises', 'par tache', 'violet')}
      </div>
      <div class="grid c2">
        ${card('Frequence des appels', bars, 'anti-boucle')}
        ${card('Signatures d echec', table(['Tache', 'Signature', 'Outil', 'Essais', 'Dernier'], fl, (r) => [
          `<span class="mono" style="font-size:10px">${esc(r.task_id)}</span>`,
          `<span class="mono" style="font-size:10px">${esc((r.signature || '').slice(0, 22))}</span>`,
          `<span class="mono">${esc(r.tool || '—')}</span>`,
          `<span class="mono" style="color:${r.count >= 3 ? 'var(--rose)' : 'var(--amber)'}">${num(r.count)}</span>`,
          `<span class="mono" style="color:var(--dim)">${ts(r.last_at)}</span>`,
        ]), num(fl.length) + ' signature(s)')}
      </div>`;
  },

  async invariants() {
    const d = await API('/api/invariants');
    const rows = d.invariants || [];
    const body = rows.length
      ? table(['Id', 'Source', 'Quand', 'Exige', 'Verdict', 'Message'], rows, (r) => [
          `<span class="mono" style="font-size:10px">${esc(r.id || '—')}</span>`,
          `<span class="mono" style="font-size:9.5px;color:var(--dim)">${esc(r.source || '—')}</span>`,
          `<span class="mono" style="font-size:10px">${esc(JSON.stringify(r.when || {}))}</span>`,
          `<span class="mono" style="font-size:10px">${esc(JSON.stringify(r.require || {}))}</span>`,
          `<span class="pill ${r.verdict === 'block' ? 'bad' : 'info'}">${esc(r.verdict || 'warn')}</span>`,
          esc(r.message || '—'),
        ])
      : `<div class="empty">aucun invariant declare</div>
         <div class="mono-box" style="margin-top:12px">Les invariants se declarent dans <b>.osiris/invariants.toml</b> (projet)
ou <b>~/.osiris/invariants.toml</b> (global) :

[[invariant]]
id = "tests-before-commit"
when   = { tool = "git.commit" }
require = { state = "tests_passed" }
message = "ne pas committer si les tests echouent"</div>`;
    el('view').innerHTML = card('Invariants anti-casse', body, num(rows.length) + ' invariant(s)');
  },

  async audit() {
    const d = await API('/api/audit');
    const lossy = d.lossless;
    el('view').innerHTML = `
      <div class="grid c4" style="margin-bottom:14px">
        ${stat(lossy ? 'LOSSLESS' : 'VIOLATION', 'Verdict', d.task_id || '—', lossy ? 'emerald' : 'rose')}
        ${stat(num(d.items_externalized), 'Externalises', 'deplaces, jamais supprimes', 'cyan')}
        ${stat(num(d.items_verified), 'Verifies', 'hash recalcule a la lecture', 'violet')}
        ${stat(num(d.items_dropped), 'Perdus', 'doit rester a 0', d.items_dropped ? 'rose' : 'emerald')}
      </div>
      <div class="grid c2">
        ${card('Preuve de non-perte', `<div class="mono-box">${esc(JSON.stringify(d, null, 2))}</div>`, 'audit_task')}
        ${card('Mecanismes', `<dl class="kv">
          <dt>1. Refs</dt><dd>mem://sha256:&lt;hash&gt; — divergence → integrity_error</dd>
          <dt>2. Suppression</dt><dd>aucun chemin de code ne supprime : le prune deplace</dd>
          <dt>3. Audit</dt><dd>rejouable depuis le journal append-only</dd>
        </dl>
        <div class="mono-box" style="margin-top:12px">python -m osiris audit --task ${esc(d.task_id || '<id>')}</div>`, 'garanties')}
      </div>`;
  },

  async tools() {
    const d = await API('/api/tools');
    const tools = d.tools || [];
    const cards = tools.length
      ? tools
          .map(
            (t) => `<div class="card" style="padding:13px 15px">
              <h3 style="margin-bottom:8px">${esc(t.name)}</h3>
              <div style="font-size:11.5px;color:var(--muted);margin-bottom:9px">${esc((t.description || '').slice(0, 220))}</div>
              <div class="mono-box" style="font-size:10px;max-height:160px;overflow:auto">${esc(JSON.stringify(t.schema, null, 1))}</div>
            </div>`
          )
          .join('')
      : '<div class="empty">les schemas ne sont pas lisibles depuis le dashboard</div>';
    el('view').innerHTML = `
      <div class="grid c4" style="margin-bottom:14px">
        ${stat(num(d.count), 'Outils exposes', 'surface publique stable', 'cyan')}
        ${stat(num(d.access_tokens), 'Tokens de schemas', 'cout d acces par requete', 'amber')}
        ${stat(num(d.schema_chars), 'Caracteres', 'schemas + descriptions', 'violet')}
        ${stat('6', 'Attendu', 'plan / precheck / observe / recall / checkpoint / handoff', 'blue')}
      </div>
      <div class="grid c2">${cards}</div>`;
  },

  async diagnostics() {
    const d = await API('/api/diagnostics');
    const items = d.items || [];
    const sevOrder = { critical: 0, high: 1, medium: 2, low: 3 };
    items.sort((a, b) => (sevOrder[a.severity] || 9) - (sevOrder[b.severity] || 9));
    const cards = items
      .map(
        (x) => `<div class="diag ${esc(x.severity)}">
          <h4>${esc(x.title)}</h4>
          <div class="meta">${esc(x.id)} · ${esc(x.component)} · <span class="pill ${x.status === 'fixed' ? 'ok' : 'warn'}">${esc(x.status)}</span></div>
          <dl>
            <dt>Symptome</dt><dd>${esc(x.symptom)}</dd>
            <dt>Cause</dt><dd>${esc(x.cause)}</dd>
            <dt>Correctif</dt><dd style="color:var(--txt)">${esc(x.fix)}</dd>
          </dl>
        </div>`
      )
      .join('');
    el('view').innerHTML = `
      <div class="grid c3" style="margin-bottom:14px">
        ${stat(num(d.count), 'Bugs detectes', 'audit du code + execution de l outillage', 'cyan')}
        ${stat(num(d.by_status ? d.by_status.fixed : 0), 'Correctes', 'verifies par pytest / ruff / bench', 'emerald')}
        ${stat(num(d.by_status ? d.by_status.open : 0), 'Ouverts', 'a traiter', (d.by_status && d.by_status.open) ? 'rose' : 'emerald')}
      </div>
      <div class="grid c2">${cards}</div>`;
  },

  async config() {
    const d = await API('/api/config');
    const env = d.env || {};
    const rows = Object.entries(env).map(([k, v]) => [
      `<span class="mono" style="font-size:10.5px">${esc(k)}</span>`,
      v === null || v === undefined || v === ''
        ? '<span class="pill muted">defaut</span>'
        : `<span class="mono" style="color:var(--cyan)">${esc(v)}</span>`,
    ]);
    el('view').innerHTML = `
      <div class="grid c2">
        ${card(
          'Variables d environnement',
          `<div class="scroll"><table><thead><tr><th>Variable</th><th>Valeur</th></tr></thead><tbody>${rows
            .map((r) => `<tr><td>${r[0]}</td><td>${r[1]}</td></tr>`)
            .join('')}</tbody></table></div>`,
          'OSIRIS_*'
        )}
        ${card(
          'Configuration effective',
          `<dl class="kv">
            <dt>Version</dt><dd>${esc((d.effective || {}).version || '—')}</dd>
            <dt>Home</dt><dd>${esc((d.effective || {}).home || '—')}</dd>
            <dt>Base</dt><dd>${esc((d.effective || {}).db_path || '—')}</dd>
            <dt>Racines</dt><dd>${esc((d.effective || {}).allowed_roots ? (d.effective.allowed_roots || []).join(', ') : '—')}</dd>
            <dt>Tokenizer</dt><dd>${esc((d.effective || {}).tokenizer || '—')}</dd>
            <dt>Projet</dt><dd>${esc(d.project || '—')}</dd>
          </dl>`,
          'runtime'
        )}
      </div>`;
  },
};

async function render() {
  loading();
  const fn = VIEWS[S.view] || VIEWS.overview;
  try {
    await fn();
  } catch (e) {
    el('view').innerHTML = `<div class="card"><div class="empty">erreur de rendu : ${esc(e.message)}</div></div>`;
  }
}

/* ------------------------------------------------------------ task panel */
async function selectTask(taskId, silent) {
  S.taskId = taskId;
  S.task = await API('/api/task/' + taskId);
  paintPanel();
  if (S.view === 'prefix') render();
  if (!silent) toast('tache ' + taskId);
}

function paintPanel() {
  const t = S.task;
  el('panel-task').textContent = t ? t.task_id : '—';
  if (!t) {
    el('panel-state').innerHTML = '<span class="panel-empty">Aucune tache selectionnee.</span>';
    el('panel-manifest').textContent = '—';
    el('panel-budget').innerHTML = '—';
    return;
  }
  const st = t.state || {};
  const flags = st.flags || {};
  const b = t.budget || {};
  const lvl = t.level || '—';
  el('panel-state').innerHTML = `<dl class="kv">
    <dt>Objectif</dt><dd style="font-family:var(--sans)">${esc(t.objective || '—')}</dd>
    <dt>Niveau</dt><dd><span class="pill ${lvl === 'light' ? 'info' : lvl === 'full' ? 'violet' : 'muted'}">${esc(lvl)}</span></dd>
    <dt>Volume</dt><dd>${num(t.volume)} tok</dd>
    <dt>Plan</dt><dd>${num(t.plan_done)}/${num(t.plan_total)}</dd>
    <dt>Fichiers</dt><dd>${num(Object.keys(st.files || {}).length)}</dd>
    <dt>Decisions</dt><dd>${num((st.decisions || []).length)}</dd>
  </dl>`;

  const p = t.prefix || {};
  el('panel-manifest').innerHTML =
    `<b>OSIRIS/1</b> task=${esc(t.task_id)} mode=${esc(lvl)}\n` +
    `head  ${esc((p.head_hash || flags.head_hash || '—').slice(0, 26))}\n` +
    `zoneB ${esc((p.zoneB_hash || flags.zoneB_hash || '—').slice(0, 26))}\n` +
    `tail  ${esc((p.tail_hash || flags.tail_hash || '—').slice(0, 26))}\n` +
    `SEAL  ${esc((p.prefix_hash || flags.prefix_hash || '—').slice(0, 26))}`;

  el('panel-budget').innerHTML = `<dl class="kv">
    <dt>Tokens</dt><dd>${num(b.tokens_used || b.tokens || b.tokens_estimated || 0)}</dd>
    <dt>Budget</dt><dd>${b.ok === undefined ? '—' : b.ok ? '<span class="pill ok">ok</span>' : '<span class="pill bad">depasse</span>'}</dd>
    <dt>Economise</dt><dd style="color:var(--emerald)">${num(b.tokens_saved || 0)}</dd>
    <dt>Journal</dt><dd>${num((t.events || []).length)} evenements</dd>
  </dl>`;
}

async function paintFeed() {
  const d = await API('/api/events');
  const rows = (d.items || []).slice(0, 40);
  el('panel-feed').innerHTML = rows.length
    ? rows
        .map((r) => {
          const cls = r.kind === 'checkpoint' ? 'ok' : r.action_state === 'failed' ? 'bad' : '';
          return `<div class="feed-item ${cls}">
            <div class="k">${esc(r.kind)}</div>
            <div class="t">${esc(r.task_id)}</div>
            <div class="ts">${ts(r.ts)}</div>
          </div>`;
        })
        .join('')
    : '<span class="panel-empty">journal vide</span>';
}

function panelAction(act) {
  if (act === 'audit') { S.view = 'audit'; syncNav(); render(); }
  else if (act === 'bench') { S.view = 'bench'; syncNav(); render(); }
  else if (act === 'diag') { S.view = 'diagnostics'; syncNav(); render(); }
  else if (act === 'refresh') { refresh(true); paintFeed(); }
}

async function refreshIntegrity() {
  try {
    const a = await API('/api/audit');
    S.integrity = a.lossless === true ? 'LOSSLESS' : a.lossless === false ? 'VIOLATION' : '—';
    el('k-integrity').textContent = S.integrity;
    el('k-integrity').parentElement.className = 'kpi ' + (S.integrity === 'LOSSLESS' ? 'good' : S.integrity === 'VIOLATION' ? 'bad' : '');
  } catch (e) {}
}

async function paintExtraBadges() {
  const defs = [['b-inv', '/api/invariants'], ['b-tools', '/api/tools'], ['b-diag', '/api/diagnostics']];
  for (const [id, path] of defs) {
    try {
      const d = await API(path);
      if (el(id)) el(id).textContent = num(d.count);
    } catch (e) {}
  }
}

async function autoSelectTask() {
  if (S.taskId) return;
  try {
    const d = await API('/api/tasks');
    const t = (d.tasks || [])[0];
    if (t) await selectTask(t.task_id, true);
  } catch (e) {}
}

function syncNav() {
  document.querySelectorAll('.nav-item').forEach((n) => n.classList.toggle('active', n.dataset.view === S.view));
}

boot().then(() => { paintFeed(); refreshIntegrity(); paintExtraBadges(); autoSelectTask(); });
setInterval(paintFeed, 20000);
setInterval(() => { refreshIntegrity(); paintExtraBadges(); }, 30000);
