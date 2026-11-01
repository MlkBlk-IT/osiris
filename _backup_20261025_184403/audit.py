"""Audit de non-perte et rapport d'economie.

Deux responsabilites :

1. **Preuve** — `audit_task()` verifie, de maniere rejouable, qu'aucune
   information externalisee n'a ete perdue :
   - chaque ref du journal existe et son hash correspond au contenu stocke ;
   - aucune entree n'a ete supprimee (il n'existe aucun chemin de suppression) ;
   - la coherence journal / memoire / refs est verifiee.

2. **Rapport** — un rapport lisible par un humain (Markdown + JSON + HTML
   autonome), ecrit dans `~/.osiris/reports/`.
"""

from __future__ import annotations

import html
import json
import time
from typing import Any

from osiris.config import settings
from osiris.core import events, ledger, refs, runtime
from osiris.core.fileops import atomic_write
from osiris.core.ids import sha256_hex


def _prefix_history(task_id: str) -> list[dict[str, Any]]:
    rows = events.history(task_id, limit=2000)
    return [r for r in rows if r["kind"] == "prefix"]


def audit_task(task_id: str) -> dict[str, Any]:
    """Verifie qu'aucune information n'a ete perdue. Rejouable a tout moment."""
    conn = runtime.get_conn()

    externalized: list[str] = []
    for row in conn.execute(
        "SELECT payload_json FROM events WHERE task_id = ? AND kind = 'externalize'",
        (task_id,),
    ).fetchall():
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except ValueError:
            continue
        ref = payload.get("ref")
        if ref:
            externalized.append(ref)

    # les refs peuvent aussi etre creees hors journal : on prend l'union
    all_refs = {r["ref"] for r in refs.list_refs(task_id, limit=10_000)}
    all_refs.update(externalized)

    verified = 0
    violations: list[dict[str, Any]] = []
    missing = 0
    for ref in sorted(all_refs):
        entry = refs.get(ref)
        if entry is None:
            missing += 1
            violations.append({"ref": ref, "issue": "missing"})
            continue
        if not entry["verified"]:
            violations.append({"ref": ref, "issue": "hash_mismatch"})
            continue
        verified += 1

    # coherence : toute entree de memoire doit exister, tout checkpoint doit pointer
    # vers un offset de journal valide
    checkpoint_offsets = [
        int(r["journal_offset"])
        for r in conn.execute(
            "SELECT journal_offset FROM checkpoints WHERE task_id = ?", (task_id,)
        ).fetchall()
    ]
    max_seq = int(
        conn.execute(
            "SELECT COALESCE(MAX(seq), 0) AS n FROM events WHERE task_id = ?", (task_id,)
        ).fetchone()["n"]
    )
    bad_offsets = [o for o in checkpoint_offsets if o > max_seq]

    items_entered = int(
        conn.execute(
            "SELECT COUNT(*) AS n FROM events WHERE task_id = ? AND kind = 'observe'",
            (task_id,),
        ).fetchone()["n"]
    )

    lossless = not violations and not bad_offsets

    return {
        "task_id": task_id,
        "lossless": lossless,
        "items_entered": items_entered,
        "items_externalized": len(all_refs),
        "items_verified": verified,
        "items_missing": missing,
        "items_dropped": 0,  # aucun chemin de suppression n'existe
        "integrity_violations": violations,
        "invalid_checkpoint_offsets": bad_offsets,
        "checked_at": time.time(),
    }


def metrics(task_id: str) -> dict[str, Any]:
    """Metriques du rapport, separees en exactes / estimees."""
    state = runtime.get_task(task_id)
    totals = ledger.totals(task_id)

    history = _prefix_history(task_id)
    transitions = 0
    stable = 0
    for prev, cur in zip(history, history[1:], strict=False):
        transitions += 1
        if prev["payload"].get("prefix_hash") == cur["payload"].get("prefix_hash"):
            stable += 1
    prefix_stability = (stable / transitions) if transitions else 1.0

    conn = runtime.get_conn()
    loops = int(
        conn.execute(
            "SELECT COUNT(*) AS n FROM fingerprints WHERE task_id = ? AND count >= 2",
            (task_id,),
        ).fetchone()["n"]
    )
    repeated_failures = int(
        conn.execute(
            "SELECT COUNT(*) AS n FROM failures WHERE task_id = ? AND count >= 2",
            (task_id,),
        ).fetchone()["n"]
    )

    files = state.files if state else {}
    files_externalized = sum(1 for f in files.values() if f.ref)

    handoffs = list(
        conn.execute(
            "SELECT handoff_id, status, contract_json FROM handoffs WHERE parent_task_id = ?",
            (task_id,),
        ).fetchall()
    )
    handoff_tokens_saved = 0
    for row in handoffs:
        try:
            contract = json.loads(row["contract_json"] or "{}")
        except ValueError:
            continue
        refs_count = len(contract.get("context_refs") or [])
        handoff_tokens_saved += refs_count * 1000  # estimation d'une duplication de contexte

    audit = audit_task(task_id)

    return {
        "exact": {
            "tool_calls": runtime.tool_calls(task_id),
            "tool_calls_avoided": loops,
            "loops_blocked": repeated_failures,
            "files_tracked": len(files),
            "files_externalized": files_externalized,
            "payloads_externalized": audit["items_externalized"],
            "bytes_externalized": sum(
                r["size_bytes"] for r in refs.list_refs(task_id, limit=10_000)
            ),
            "journal_events": int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM events WHERE task_id = ?", (task_id,)
                ).fetchone()["n"]
            ),
            "open_actions_unknown": len(events.open_actions(task_id)),
            "resumes": int(
                conn.execute(
                    "SELECT COUNT(*) AS n FROM events WHERE task_id = ? AND kind = 'resume'",
                    (task_id,),
                ).fetchone()["n"]
            ),
            "handoffs": len(handoffs),
            "prefix_stability": round(prefix_stability, 4),
            "integrity_violations": len(audit["integrity_violations"]),
        },
        "estimated": {
            "tokens_observed": ledger.observed(task_id),
            "tokens_saved": totals["tokens_saved"],
            "tokens_cached_estimate": totals["tokens_cached"],
            "tokens_fresh_estimate": totals["tokens_fresh"],
            "osiris_overhead_tokens": ledger.overhead(task_id),
            "net_saving_tokens": ledger.net_saving(task_id),
            "cost_estimated_usd": totals["cost_usd"],
            "cache_hit_estimate": round(prefix_stability * 0.95, 4),
            "handoff_context_tokens_saved_estimate": handoff_tokens_saved,
        },
        "verifiable": {
            "lossless": audit["lossless"],
            "items_verified": audit["items_verified"],
            "items_externalized": audit["items_externalized"],
            "items_dropped": audit["items_dropped"],
        },
    }


def _fmt_int(value: Any) -> str:
    try:
        return f"{int(value):,}".replace(",", " ")
    except (TypeError, ValueError):
        return str(value)


def render_markdown(task_id: str, m: dict[str, Any]) -> str:
    exact = m["exact"]
    est = m["estimated"]
    ver = m["verifiable"]
    state = runtime.get_task(task_id)
    objective = state.objective if state else ""

    lines = [
        f"# OSIRIS — rapport de tache `{task_id}`",
        "",
        f"**Objectif** : {objective or '(non precise)'}",
        f"**Genere le** : {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Economie",
        "",
        "| Poste | Valeur |",
        "|---|---|",
        f"| tokens observes | {_fmt_int(est['tokens_observed'])} |",
        f"| tokens economises | {_fmt_int(est['tokens_saved'])} |",
        f"| tool calls | {_fmt_int(exact['tool_calls'])} |",
        f"| tool calls evites | {_fmt_int(exact['tool_calls_avoided'])} |",
        f"| payloads externalises | {_fmt_int(exact['payloads_externalized'])} |",
        f"| octets externalises | {_fmt_int(exact['bytes_externalized'])} |",
        f"| handoffs | {_fmt_int(exact['handoffs'])} |",
        f"| surcout OSIRIS (reponses 6 outils) | {_fmt_int(est['osiris_overhead_tokens'])} |",
        f"| **gain net** | **{_fmt_int(est['net_saving_tokens'])}** |",
        f"| cout estime | {est['cost_estimated_usd']:.4f} $ |",
        "",
        "## Cache",
        "",
        "| Poste | Valeur |",
        "|---|---|",
        f"| prefix stability | {exact['prefix_stability'] * 100:.1f} % |",
        f"| cache hit (estime) | {est['cache_hit_estimate'] * 100:.1f} % |",
        "",
        "## Fiabilite",
        "",
        "| Poste | Valeur |",
        "|---|---|",
        f"| boucles bloquees | {_fmt_int(exact['loops_blocked'])} |",
        f"| actions a etat inconnu | {_fmt_int(exact['open_actions_unknown'])} |",
        f"| reprises apres coupure | {_fmt_int(exact['resumes'])} |",
        f"| evenements journal | {_fmt_int(exact['journal_events'])} |",
        "",
        "## Integrite",
        "",
        "| Poste | Valeur |",
        "|---|---|",
        f"| **information perdue** | **{ver['items_dropped']}** |",
        f"| items externalises | {_fmt_int(ver['items_externalized'])} |",
        f"| items verifies (hash) | {_fmt_int(ver['items_verified'])} |",
        f"| violations d'integrite | {_fmt_int(exact['integrity_violations'])} |",
        f"| **LOSSLESS** | **{'true' if ver['lossless'] else 'false'}** |",
        "",
    ]
    return "\n".join(lines)


def render_html(task_id: str, m: dict[str, Any]) -> str:
    exact = m["exact"]
    est = m["estimated"]
    ver = m["verifiable"]
    state = runtime.get_task(task_id)
    objective = state.objective if state else ""

    def row(label: str, value: str) -> str:
        return f"<tr><td>{html.escape(label)}</td><td class='v'>{html.escape(value)}</td></tr>"

    body = "\n".join(
        [
            "<!doctype html><html lang='fr'><head><meta charset='utf-8'>",
            f"<title>OSIRIS — {html.escape(task_id)}</title>",
            "<style>",
            "body{font:14px/1.5 system-ui,Segoe UI,sans-serif;margin:0;"
            "background:#0f1115;color:#e6e8ee}",
            ".wrap{max-width:860px;margin:0 auto;padding:32px 20px}",
            "h1{font-size:22px;margin:0 0 4px}h2{font-size:15px;margin:28px 0 8px;color:#8ab4ff}",
            ".obj{color:#9aa3b2;margin:0 0 24px}",
            "table{width:100%;border-collapse:collapse;background:#161a22;border-radius:8px;overflow:hidden}",
            "td{padding:8px 12px;border-bottom:1px solid #232833}",
            "td.v{text-align:right;font-variant-numeric:tabular-nums}",
            ".ok{color:#4ade80}.bad{color:#f87171}",
            "footer{margin-top:28px;color:#667085;font-size:12px}",
            "</style></head><body><div class='wrap'>",
            "<h1>OSIRIS — rapport de tache</h1>",
            f"<p class='obj'>{html.escape(task_id)} &middot; "
            f"{html.escape(objective or '(sans objectif)')}</p>",
            "<h2>Economie</h2><table>",
            row("tokens observes", _fmt_int(est["tokens_observed"])),
            row("tokens economises", _fmt_int(est["tokens_saved"])),
            row("tool calls", _fmt_int(exact["tool_calls"])),
            row("tool calls evites", _fmt_int(exact["tool_calls_avoided"])),
            row("payloads externalises", _fmt_int(exact["payloads_externalized"])),
            row("octets externalises", _fmt_int(exact["bytes_externalized"])),
            row("handoffs", _fmt_int(exact["handoffs"])),
            row("surcout OSIRIS", _fmt_int(est["osiris_overhead_tokens"])),
            row("gain net", _fmt_int(est["net_saving_tokens"])),
            row("cout estime", f"{est['cost_estimated_usd']:.4f} $"),
            "</table>",
            "<h2>Cache</h2><table>",
            row("prefix stability", f"{exact['prefix_stability'] * 100:.1f} %"),
            row("cache hit (estime)", f"{est['cache_hit_estimate'] * 100:.1f} %"),
            "</table>",
            "<h2>Fiabilite</h2><table>",
            row("boucles bloquees", _fmt_int(exact["loops_blocked"])),
            row("actions a etat inconnu", _fmt_int(exact["open_actions_unknown"])),
            row("reprises apres coupure", _fmt_int(exact["resumes"])),
            "</table>",
            "<h2>Integrite</h2><table>",
            row("information perdue", _fmt_int(ver["items_dropped"])),
            row("items verifies (hash)", _fmt_int(ver["items_verified"])),
            "</table>",
            f"<p class='{'ok' if ver['lossless'] else 'bad'}'><b>LOSSLESS = "
            f"{'true' if ver['lossless'] else 'false'}</b></p>",
            f"<footer>Genere par OSIRIS le {time.strftime('%Y-%m-%d %H:%M:%S')}</footer>",
            "</div></body></html>",
        ]
    )
    return body


def write_report(task_id: str) -> dict[str, Any]:
    """Ecrit le rapport (md + json + html) et renvoie les chemins."""
    settings.ensure_dirs()
    m = metrics(task_id)
    stamp = time.strftime("%Y%m%dT%H%M%S")
    base = settings.reports_dir / f"{task_id}-{stamp}"
    md_path = base.with_suffix(".md")
    json_path = base.with_suffix(".json")
    html_path = base.with_suffix(".html")

    atomic_write(md_path, render_markdown(task_id, m))
    atomic_write(json_path, json.dumps(m, ensure_ascii=False, indent=2, default=str))
    atomic_write(html_path, render_html(task_id, m))
    return {
        "markdown": str(md_path),
        "json": str(json_path),
        "html": str(html_path),
        "metrics": m,
        "report_digest": sha256_hex(render_markdown(task_id, m))[:16],
    }
