"""OSIRIS — serveur MCP (transport stdio).

Six outils, un seul but : reduire le contexte, proteger le cache, bloquer
les boucles, empecher les cassees, partager le travail, reprendre apres un
crash — sans jamais controller le LLM ni dependre d'un provider.

Regle de design : l'agent ne calcule **jamais** de hash. Il transmet les
arguments bruts ; OSIRIS canonicalise, digeste et decide.
"""

from __future__ import annotations

import json
import time
from typing import Any

from fastmcp import FastMCP

from osiris import audit as audit_mod
from osiris.config import settings
from osiris.core import (
    adaptive,
    compass,
    events,
    fileops,
    handoff,
    invariants,
    ledger,
    loopguard,
    memory,
    prefix,
    prune,
    refs,
    runtime,
)
from osiris.core.errors import AccessDenied, InvalidInput
from osiris.core.ids import hash_args, sha256_hex
from osiris.core.manifest import build_manifest
from osiris.core.task_state import FileEntry, ToolResultEntry
from osiris.core.tokens import count_tokens

mcp = FastMCP(
    name="osiris",
    instructions=(
        "OSIRIS — context engine cache-aware. Utilise osiris.plan au debut d'une "
        "tache, osiris.observe apres chaque appel d'outil, osiris.precheck avant "
        "une action risquee, osiris.recall pour rehydrater un ref, "
        "osiris.checkpoint pour materialiser l'etat, osiris.handoff pour deleguer."
    ),
)

#: Au-dela de ce nombre de tokens, un resultat d'outil est externalise.
#: En dessous, le garder dans le contexte coute moins cher (voir core/adaptive).
AUTO_EXTERNALIZE_TOKENS = 800

#: Kinds acceptes par osiris.observe.
OBSERVE_KINDS = (
    "tool_result",
    "payload",
    "file",
    "decision",
    "constraint",
    "lesson",
    "test_result",
    "failure",
    "note",
    "contract",
)


# --------------------------------------------------------------------------
# helpers internes
# --------------------------------------------------------------------------


def _zones(state) -> dict[str, Any]:
    """Calcule zones, drift et plan de prefill pour l'etat courant."""
    return prefix.analyze_prefix(
        objective=state.objective,
        constraints=state.constraints,
        decisions=state.decisions,
        plan_global=state.plan.steps,
        project_rules_digest=invariants.rules_digest(),
        client_contract_hash=state.hashes.get("client_contract_hash", ""),
        client_system_hash=state.hashes.get("client_system_hash", ""),
        previous=state.hashes,
    )


def _issue_manifest(state, analysis: dict[str, Any]) -> dict[str, str]:
    """Produit le manifeste + seal et memorise le seal emis."""
    zones = analysis["zones"]
    manifest = build_manifest(
        task_id=state.task_id,
        objective=state.objective,
        plan_current=state.plan.current,
        plan_total=state.total_steps,
        invariants_count=len(invariants.active_ids()),
        files_count=len(state.files),
        refs_count=len(state.tool_results),
        budget_ok=state.budget.ok,
        zones=zones,
        decisions_count=len(state.decisions),
    )
    state.hashes.update(zones)
    state.hashes["issued_seal"] = manifest["seal"]
    return manifest


def _restore_from_checkpoint(state, ck_state: dict[str, Any]) -> None:
    """Fusion checkpoint + etat courant.

    Les champs append-only (objectif, contraintes, decisions) gardent la
    version la plus recente ; les champs remplacables (plan, fichiers,
    resultats, echecs) viennent du checkpoint.
    """
    restored = type(state).from_json(ck_state)
    state.plan = restored.plan
    state.files = restored.files
    state.tool_results = restored.tool_results
    state.failures = restored.failures
    state.budget.tokens_estimated = restored.budget.tokens_estimated
    state.budget.cost_estimated = restored.budget.cost_estimated
    state.budget.tool_calls = restored.budget.tool_calls


def _budget_payload(state) -> dict[str, Any]:
    return {
        "tokens_estimated": state.budget.tokens_estimated,
        "tokens_saved": state.budget.tokens_saved,
        "tokens_remaining": state.budget.tokens_remaining,
        "cost_estimated_usd": round(state.budget.cost_estimated, 6),
        "cost_remaining_usd": state.budget.cost_remaining,
        "tool_calls": state.budget.tool_calls,
        "max_tokens": state.budget.max_tokens,
        "max_tool_calls": state.budget.max_tool_calls,
        "ok": state.budget.ok,
    }


def _finalize(task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Enregistre le surcout propre d'OSIRIS (tokens de la reponse d'outil).

    OSIRIS doit etre rentable : on mesure donc explicitement ce qu'il coute
    a l'agent, pour pouvoir comparer au gain.
    """
    overhead = count_tokens(json.dumps(payload, ensure_ascii=False, default=str))
    ledger.record(task_id, "overhead", tokens_in=overhead, note="tool_response")
    return payload


def _compass(state) -> dict[str, Any]:
    usage = runtime.tool_usage(state.task_id)
    failing = {f.tool for f in state.failures.values() if f.count >= 2 and f.tool}
    return compass.recommend(
        objective=state.objective,
        current_step=state.current_step,
        known_tools=list(usage.keys()),
        blocked_tools=loopguard.blocked_tools(state.task_id),
        failing_tools=failing,
        forbidden_tools=set(),
        used_tools=[t for t, n in usage.items() if n <= 2],
    )


# --------------------------------------------------------------------------
# osiris.plan
# --------------------------------------------------------------------------


@mcp.tool(name="osiris.plan")
def osiris_plan(
    objective: str = "",
    steps: tuple[str, ...] = (),
    constraints: tuple[str, ...] = (),
    mode: str = "start",
    task_id: str = "",
    context_tokens: int = 0,
) -> dict[str, Any]:
    """Tache : plan, manifeste scelle. start | update | resume.

    Args:
        objective: Objectif.
        steps: Etapes.
        constraints: Regles.
        mode: start | update | resume.
        task_id: Tache a reprendre.
        context_tokens: Tokens du contexte (0 = inconnu).

    Returns:
        task_id, manifest, seal, mode, budget, next_step, compass, drift.
    """
    if mode not in ("start", "update", "resume"):
        raise InvalidInput(f"mode invalide: {mode}")

    if mode == "start":
        state = runtime.create_task(objective, list(steps) or None, list(constraints) or None)
        events.append(state.task_id, "task_start", {"objective": objective})
    else:
        state = runtime.get_task(task_id) or runtime.ensure_task(task_id)
        if objective and objective != state.objective:
            state.objective = objective
        if steps:
            state.plan.steps = list(steps)
            state.plan.current = min(state.plan.current, max(0, len(steps) - 1))
        for constraint in constraints:
            state.add_constraint(constraint)
            memory.add(state.task_id, "constraint", constraint, scope="task")

    resume_info: dict[str, Any] = {}
    if mode == "resume":
        checkpoint = events.latest_checkpoint(state.task_id)
        if checkpoint:
            full = events.get_checkpoint(checkpoint["checkpoint_id"])
            if full:
                _restore_from_checkpoint(state, full["state"])
        unknown = events.open_actions(state.task_id)
        completed = events.completed_actions(state.task_id)
        resume_info = {
            "checkpoint": checkpoint["checkpoint_id"] if checkpoint else "",
            "done": list(state.plan.done),
            "current": state.current_step,
            "unknown_actions": [{"tool": a["tool"], "run_key": a["run_key"]} for a in unknown],
            "completed_actions": len(completed),
            "note": "verifie les actions inconnues avant de rejouer",
        }
        events.append(state.task_id, "resume", {"unknown": len(unknown)})

    analysis = _zones(state)
    if context_tokens > 0:
        payload_hint = context_tokens
        level = adaptive.level_for(payload_hint)
    else:
        # taille inconnue : on ne degrade pas le niveau sur une ignorance
        payload_hint = state.budget.tokens_estimated
        level = adaptive.LEVEL_STANDARD
    state.flags["osiris_volume"] = payload_hint
    state.flags["osiris_level"] = level

    if adaptive.wants_full_manifest(payload_hint):
        manifest = _issue_manifest(state, analysis)
    else:
        # tache petite : une ligne de manifeste suffit (le seal reste exact)
        seal = analysis["zones"]["prefix_hash"]
        state.hashes.update(analysis["zones"])
        state.hashes["issued_seal"] = f"sha256:{seal}"
        manifest = {
            "manifest": f"OSIRIS/1 {level}",
            "seal": f"sha256:{seal}",
        }

    compass_out = _compass(state)
    runtime.save_task(state)

    # OSIRIS doit etre rentable : si son surcout depasse son gain, on le dit.
    net = ledger.net_saving(state.task_id)
    warning = ""
    if net < 0:
        warning = (
            "surcout OSIRIS > gain sur cette tache : "
            "appelle osiris moins souvent (un observe par action utile, "
            "pas par action triviale)"
        )

    if level == adaptive.LEVEL_LIGHT:
        # mode leger : pas de compass, pas de budget detaille, pas de resume
        return _finalize(
            state.task_id,
            {
                "task_id": state.task_id,
                "mode": level,
                "manifest": manifest["manifest"],
            },
        )

    return _finalize(
        state.task_id,
        {
            "task_id": state.task_id,
            "mode": level,
            "manifest": manifest["manifest"],
            "seal": manifest["seal"],
            "budget": {
                "ok": state.budget.ok,
                "remaining": state.budget.tokens_remaining,
                "calls": state.budget.tool_calls,
            },
            "next_step": state.current_step,
            "compass": {
                "rec": compass_out["recommended_tools"],
                "avoid": compass_out["avoid_tools"],
            },
            "drift": analysis["drift"]["verdict"],
            **({"hint": warning} if warning else {}),
            **({"resume": resume_info} if resume_info else {}),
        },
    )


# --------------------------------------------------------------------------
# osiris.precheck
# --------------------------------------------------------------------------


@mcp.tool(name="osiris.precheck")
def osiris_precheck(action: str = "", args: str = "", reason: str = "") -> dict[str, Any]:
    """Verifie une action avant qu'elle parte : invariant, doublon, budget.

    Args:
        action: Action (ex: git.commit).
        args: Arguments (JSON).
        reason: Pourquoi.

    Returns:
        verdict (allow|warn|block|suggest_alternative), reasons, required_action.
    """
    state = runtime.ensure_task()
    reasons: list[str] = []
    required_action = ""
    alternative = ""
    invariant_id = ""

    violations = invariants.evaluate(
        action=action,
        args=args,
        flags=state.flags,
        budget_ok=state.budget.ok,
    )
    for violation in violations:
        reasons.append(f"{violation['id']}: {violation['message']}")
        invariant_id = invariant_id or violation["id"]
        required_action = required_action or violation.get("required_action", "")

    if not state.budget.ok:
        reasons.append("budget: budget de tache epuise")
        required_action = required_action or "reduce_scope"

    # action destructive deja executee ?
    duplicate = False
    if action:
        row = (
            runtime.get_conn()
            .execute(
                "SELECT COALESCE(SUM(count), 0) AS n FROM fingerprints"
                " WHERE task_id = ? AND tool = ? AND args_hash = ?",
                (state.task_id, action, hash_args(args)),
            )
            .fetchone()
        )
        duplicate = int(row["n"]) >= 1

    if duplicate:
        reasons.append("duplicate: appel identique deja journalise")
        alternative = "utilise le ref deja stocke au lieu de rejouer"

    verdict = "allow"
    if any(v["verdict"] == "block" for v in violations) or not state.budget.ok:
        verdict = "block"
    elif reasons or any(v["verdict"] == "warn" for v in violations):
        verdict = "warn"
    elif duplicate:
        verdict = "suggest_alternative"

    if verdict == "block" and not required_action:
        required_action = "resolve_violation"

    ledger.record(
        state.task_id,
        "precheck",
        tokens_in=count_tokens(f"{action} {args}"),
        note=f"{verdict}:{action}",
    )
    runtime.save_task(state)

    return _finalize(
        state.task_id,
        {
            "verdict": verdict,
            "reason": "invariant_violation"
            if invariant_id
            else ("budget" if not state.budget.ok else ""),
            "invariant": invariant_id,
            "reasons": reasons,
            "required_action": required_action,
            "alternative": alternative,
            "budget_ok": state.budget.ok,
        },
    )


# --------------------------------------------------------------------------
# osiris.observe
# --------------------------------------------------------------------------


@mcp.tool(name="osiris.observe")
def osiris_observe(
    kind: str = "tool_result",
    tool: str = "",
    args: str = "",
    result: str = "",
    status: str = "ok",
    path: str = "",
    seal: str = "",
) -> dict[str, Any]:
    """Consigne une action : doublons, boucles, externalisation.

    Args:
        kind: tool_result | payload | file | decision | constraint | lesson |
            test_result | failure | note | contract.
        tool: Outil.
        args: Arguments (JSON).
        result: Resultat.
        status: ok | error | skipped.
        path: Chemin (kind=file).
        seal: Seal (ecart = derive).

    Returns:
        ok, ref, tokens_saved, dup, loop, hint, seal, drift.
    """
    if kind not in OBSERVE_KINDS:
        kind = "note"

    state = runtime.ensure_task()
    ref_out = ""
    tokens_saved = 0
    hint = ""
    dup = False
    volume_hint = 0

    events.append(
        state.task_id,
        "observe",
        {"kind": kind, "tool": tool, "args": args, "status": status, "path": path},
    )

    # -- cas speciaux ------------------------------------------------------
    if kind == "file" and path:
        try:
            info = fileops.read_text(path)
        except AccessDenied as exc:
            return _finalize(
                state.task_id,
                {
                    "ok": False,
                    "ref": "",
                    "saved": 0,
                    "dup": False,
                    "loop": "allow",
                    "hint": f"acces refuse: {exc}",
                    "drift": "none",
                },
            )
        file_tokens = count_tokens(str(info["content"]))
        volume_hint = file_tokens
        previous = state.files.get(info["path"])
        dup = bool(previous and previous.content_hash == info["sha256"])
        if adaptive.should_externalize(file_tokens):
            entry = refs.put(state.task_id, str(info["content"]), meta={"path": info["path"]})
            ref_out = entry["ref"]
            tokens_saved = entry["tokens"]
            events.append(
                state.task_id,
                "externalize",
                {"ref": ref_out, "kind": "file", "path": info["path"], "tokens": tokens_saved},
            )
        # sinon : hash seul. La detection de doublon reste possible, sans le
        # cout d'une ref (~30 tokens) ni d'un stockage.
        state.files[info["path"]] = FileEntry(
            path=info["path"],
            content_hash=info["sha256"],
            mtime=info["mtime"],
            last_read_at=time.time(),
            ref=ref_out or None,
            size_bytes=int(info["size_bytes"]),
        )
        if dup:
            hint = (
                "deja lu, hash inchange : ne relis pas"
                if not ref_out
                else "deja lu, hash inchange : utilise le ref au lieu de relire"
            )

    elif kind == "payload" and result:
        payload_tokens = count_tokens(result)
        volume_hint = payload_tokens
        if adaptive.should_externalize(payload_tokens):
            entry = refs.put(state.task_id, result, meta={"tool": tool})
            ref_out = entry["ref"]
            tokens_saved = entry["tokens"]
            events.append(
                state.task_id,
                "externalize",
                {"ref": ref_out, "kind": "payload", "tokens": tokens_saved},
            )
        else:
            hint = "payload trop petit pour etre externalise : garde-le en contexte"

    elif kind == "decision" and result:
        state.add_decision(result)
        memory.add(state.task_id, "decision", result, scope="task", pinned=True)
        events.append(state.task_id, "decision", {"text": result})

    elif kind == "constraint" and result:
        state.add_constraint(result)
        memory.add(state.task_id, "constraint", result, scope="task", pinned=True)
        events.append(state.task_id, "constraint", {"text": result})

    elif kind == "lesson" and result:
        state.lessons.append(result)
        memory.add(state.task_id, "lesson", result, scope="project")
        events.append(state.task_id, "lesson", {"text": result})

    elif kind == "test_result":
        passed = status == "ok"
        state.set_flag("tests_passed", passed)
        state.set_flag("tests_failed", not passed)
        memory.add(
            state.task_id,
            "note",
            f"tests {'PASS' if passed else 'FAIL'}",
            scope="task",
        )
        events.append(state.task_id, "test_result", {"passed": passed, "tool": tool})

    elif kind == "failure" and result:
        sig = loopguard.error_signature(result)
        state.failures.setdefault(sig, None)
        from osiris.core.task_state import FailureEntry

        entry = state.failures.get(sig)
        if entry is None:
            entry = FailureEntry(
                signature=sig,
                tool=tool,
                args_hash=hash_args(args),
                count=1,
                first_at=time.time(),
                last_at=time.time(),
            )
        else:
            entry.count += 1
            entry.last_at = time.time()
        state.failures[sig] = entry
        memory.add(state.task_id, "failure", result[:400], scope="task")
        events.append(state.task_id, "failure", {"signature": sig})

    elif kind == "contract" and result:
        state.hashes["client_contract_hash"] = sha256_hex(result)
        events.append(state.task_id, "contract", {"hash": state.hashes["client_contract_hash"]})
        hint = "contract outil enregistre : un changement ici casse le prefix cache"

    elif kind == "note" and result:
        memory.add(state.task_id, "note", result, scope="task")
        events.append(state.task_id, "note", {"text": result[:400]})

    # -- cas general : resultat d'outil ------------------------------------
    if kind == "tool_result" or (tool and kind not in ("file", "decision", "constraint")):
        runtime.bump_tool_usage(state.task_id, tool)
        state.budget.tool_calls += 1
        verdict = loopguard.record(state.task_id, tool, args, result or "", status)
        loop_verdict = verdict["verdict"]
        if verdict.get("detail"):
            hint = f"{verdict['reason']}: {verdict['detail']}"
        if verdict["verdict"] == "suggest_alternative":
            dup = True
        events.append(
            state.task_id,
            "action",
            {"tool": tool, "args": args, "status": status},
            run_key=events.make_run_key(tool, args),
            action_state=events.STATE_SUCCEEDED if status == "ok" else events.STATE_FAILED,
        )
        # externalisation automatique d'un gros resultat
        result_tokens = count_tokens(result) if result else 0
        volume_hint = max(volume_hint, result_tokens)
        if (
            result
            and result_tokens > AUTO_EXTERNALIZE_TOKENS
            and adaptive.should_externalize(result_tokens)
        ):
            entry = refs.put(state.task_id, result, meta={"tool": tool})
            ref_out = ref_out or entry["ref"]
            tokens_saved += entry["tokens"]
            events.append(
                state.task_id,
                "externalize",
                {"ref": entry["ref"], "kind": "tool_result", "tokens": entry["tokens"]},
            )
            cache_key = sha256_hex(f"{tool}|{hash_args(args)}")
            state.tool_results[cache_key] = ToolResultEntry(
                cache_key=cache_key,
                ref=entry["ref"],
                size_bytes=entry["size_bytes"],
                tokens=entry["tokens"],
                created_at=time.time(),
            )
    else:
        loop_verdict = "allow"

    # -- comptabilite des tokens ------------------------------------------
    observed = count_tokens(result) if kind in ("tool_result", "payload") else 0
    state.budget.tokens_estimated += observed
    state.budget.tokens_saved += tokens_saved
    ledger.record(
        state.task_id,
        "observe",
        tokens_in=observed,
        tokens_saved=tokens_saved,
        note=kind,
    )

    # -- drift + prune automatique ------------------------------------------
    analysis = _zones(state)
    drift = analysis["drift"]
    issued = state.hashes.get("issued_seal", "")
    if seal and issued and seal != issued:
        drift = {
            "verdict": "critical",
            "changed": ["client_head"],
            "cache_broken": True,
            "cache_hit_estimate": 0.0,
            "action": "restore_head_and_alert",
        }
        hint = hint or "seal porte par l'agent different de l'etat OSIRIS : head derive"

    events.append(
        state.task_id,
        "prefix",
        {"prefix_hash": analysis["zones"]["prefix_hash"], "drift": drift["verdict"]},
    )

    prune_info = prune.evaluate(
        current_tokens=state.budget.tokens_estimated,
        mode="cache_ttl",
        elapsed_since_last_turn_s=0.0,
        ttl_s=settings.cache_ttl_s,
        threshold_tokens=settings.prune_threshold_tokens,
    )
    if prune_info["should_prune"]:
        for candidate in prune.select_candidates(state):
            if candidate.get("ref"):
                state.budget.tokens_saved += 0  # deja comptabilise a l'externalisation
                break

    # -- niveau adaptatif ----------------------------------------------------
    # Le volume = plus gros payload vu par la tache. C'est lui qui decide
    # si OSIRIS externalise, manifeste en detail, ou se contente du minimum.
    known_volume = int(state.flags.get("osiris_volume") or 0)
    volume = max(known_volume, volume_hint, observed)
    state.flags["osiris_volume"] = volume
    level = (
        adaptive.level_for(volume)
        if volume > 0
        else (state.flags.get("osiris_level") or adaptive.LEVEL_STANDARD)
    )
    state.flags["osiris_level"] = level
    compact = level == adaptive.LEVEL_LIGHT

    runtime.save_task(state)

    if compact:
        # Mode leger : on ne renvoie que ce qui porte une decision.
        # "mode" est deja connu (plan), "loop" n'interesse que s'il signale
        # un probleme. Le reste est du bruit pour l'agent.
        response: dict[str, Any] = {
            "ok": True,
            "dup": dup,
        }
        if loop_verdict != "allow":
            response["loop"] = loop_verdict
        if ref_out:
            response["ref"] = ref_out
        if hint:
            response["hint"] = hint
        return _finalize(state.task_id, response)

    return _finalize(
        state.task_id,
        {
            "ok": True,
            "ref": ref_out,
            "saved": tokens_saved,
            "dup": dup,
            "loop": loop_verdict,
            "hint": hint,
            "drift": drift["verdict"],
            "mode": level,
        },
    )


# --------------------------------------------------------------------------
# osiris.recall
# --------------------------------------------------------------------------


@mcp.tool(name="osiris.recall")
def osiris_recall(
    ref: str = "",
    task_id: str = "",
    scope: str = "",
    query: str = "",
    kind: str = "",
    budget_tokens: int = 800,
) -> dict[str, Any]:
    """Rehydrate un ref, ou restitue l'etat / la memoire d'une tache.

    Args:
        ref: Ref (mem://...).
        task_id: Tache.
        scope: task | project | agent | global.
        query: Filtre texte (extrait cible si un ref est fourni).
        kind: Type de memoire.
        budget_tokens: Budget tokens.

    Returns:
        items, found, state, budget, open_actions.
    """
    state = runtime.get_task(task_id) or runtime.ensure_task(task_id)

    if ref:
        excerpt = refs.excerpt(ref, query=query, budget_tokens=budget_tokens)
        if not excerpt.get("found"):
            return _finalize(
                state.task_id,
                {
                    "found": False,
                    "items": [],
                    "note": "ref inconnue",
                },
            )
        return _finalize(
            state.task_id,
            {
                "found": True,
                "items": [
                    {
                        "ref": excerpt["ref"],
                        "excerpt": excerpt["excerpt"],
                        "offset": excerpt["offset"],
                        "complete": excerpt["complete"],
                        "tokens": excerpt["tokens"],
                        "verified": excerpt["verified"],
                    }
                ],
                "total_chars": excerpt.get("total_chars", 0),
            },
        )

    entries = memory.list_entries(
        task_id=state.task_id,
        scope=scope or None,
        kind=kind or None,
        query=query or None,
        limit=50,
    )
    items: list[dict[str, Any]] = []
    spent = 0
    for entry in entries:
        cost = count_tokens(entry["body"])
        if spent + cost > budget_tokens and items:
            break
        spent += cost
        items.append(
            {
                "mem_id": entry["mem_id"],
                "kind": entry["kind"],
                "scope": entry["scope"],
                "pinned": entry["pinned"],
                "body": entry["body"],
            }
        )

    return _finalize(
        state.task_id,
        {
            "found": True,
            "items": items,
            "task_id": state.task_id,
            "state": {
                "objective": state.objective,
                "plan_current": state.plan.current,
                "plan_total": state.total_steps,
                "current_step": state.current_step,
                "done": list(state.plan.done),
                "decisions": list(state.decisions),
                "constraints": list(state.constraints),
                "flags": dict(state.flags),
            },
            "budget": {
                "ok": state.budget.ok,
                "remaining": state.budget.tokens_remaining,
                "saved": state.budget.tokens_saved,
            },
            "open_actions": [
                {"tool": a["tool"], "run_key": a["run_key"]}
                for a in events.open_actions(state.task_id)
            ],
        },
    )


# --------------------------------------------------------------------------
# osiris.checkpoint
# --------------------------------------------------------------------------


@mcp.tool(name="osiris.checkpoint")
def osiris_checkpoint(label: str = "", mode: str = "snapshot", task_id: str = "") -> dict[str, Any]:
    """Snapshot d'etat, ou cloture avec rapport.

    Args:
        label: Etiquette.
        mode: snapshot | final.
        task_id: Tache.

    Returns:
        checkpoint_id, journal_offset, integrity, report (en mode final).
    """
    state = runtime.get_task(task_id) or runtime.ensure_task(task_id)
    checkpoint = events.save_checkpoint(state.task_id, label, state.to_json())
    events.append(state.task_id, "checkpoint", {"label": label, "mode": mode})

    integrity = audit_mod.audit_task(state.task_id)
    runtime.save_task(state)

    # En mode `light`, la charge utile doit rester minimale : on ne renvoie que
    # ce qui porte une decision (l'identifiant du checkpoint, le verdict
    # d'integrite et la preuve de non-perte). Les compteurs et le chemin du
    # rapport restent sur disque — ils ne coutent rien au contexte.
    compact = (state.flags.get("osiris_level") or adaptive.LEVEL_STANDARD) == adaptive.LEVEL_LIGHT

    payload: dict[str, Any] = {
        "checkpoint_id": checkpoint["checkpoint_id"],
        "integrity": "lossless" if integrity["lossless"] else "violation",
        "information_perdue": integrity["items_dropped"],
    }
    if not compact:
        payload["journal_offset"] = checkpoint["journal_offset"]
        payload["items_verified"] = integrity["items_verified"]
        payload["items_externalized"] = integrity["items_externalized"]

    if mode == "final":
        report = audit_mod.write_report(state.task_id)
        # Un rapport est un artefact sur disque, pas du contexte : on renvoie
        # un seul chemin (le markdown) + son digest. Les 3 rapports (md, json,
        # html) partagent la meme base : md/json/html sont derivables.
        if not compact:
            payload["report"] = report["markdown"]
            payload["report_digest"] = report["report_digest"]

    return _finalize(state.task_id, payload)


# --------------------------------------------------------------------------
# osiris.handoff
# --------------------------------------------------------------------------


@mcp.tool(name="osiris.handoff")
def osiris_handoff(
    mission: str = "",
    must_know: tuple[str, ...] = (),
    allowed_tools: tuple[str, ...] = (),
    forbidden_actions: tuple[str, ...] = (),
    files: tuple[str, ...] = (),
    budget_tokens: int = 0,
    mode: str = "create",
    handoff_id: str = "",
    result: str = "",
) -> dict[str, Any]:
    """Contrat de delegation (create), ou son resultat (complete/collect).

    Args:
        mission: Mission du sous-agent.
        must_know: Faits indispensables (remplacent le contexte parent).
        allowed_tools: Outils.
        forbidden_actions: Interdits.
        files: Fichiers.
        budget_tokens: Budget tokens.
        mode: create | complete | collect.
        handoff_id: Handoff vise.
        result: Resultat (JSON).

    Returns:
        handoff_id, contract, context_refs, estimated_tokens (create) ;
        status, result (complete / collect).
    """
    state = runtime.ensure_task()

    if mode == "complete":
        if not handoff_id:
            raise InvalidInput("handoff_id requis en mode complete")
        payload: dict[str, Any] = {}
        if result:
            try:
                payload = json.loads(result)
            except (ValueError, TypeError):
                payload = {"summary": result}
        ok = handoff.complete(handoff_id, payload)
        events.append(state.task_id, "handoff_complete", {"handoff_id": handoff_id})
        return _finalize(
            state.task_id,
            {"handoff_id": handoff_id, "status": "completed" if ok else "unknown"},
        )

    if mode == "collect":
        if not handoff_id:
            raise InvalidInput("handoff_id requis en mode collect")
        entry = handoff.get(handoff_id)
        if entry is None:
            return {"handoff_id": handoff_id, "status": "unknown"}
        return _finalize(
            state.task_id,
            {
                "handoff_id": handoff_id,
                "status": entry["status"],
                "result": entry["result"],
            },
        )

    created = handoff.create(
        parent_task_id=state.task_id,
        mission=mission,
        must_know=must_know,
        allowed_tools=allowed_tools,
        forbidden_actions=forbidden_actions,
        files=files,
        budget_tokens=budget_tokens,
        context_refs=None,
        state=state,
    )
    state.handoffs[created["handoff_id"]] = {
        "mission": mission,
        "status": "open",
        "estimated_tokens": created["estimated_tokens"],
    }
    events.append(
        state.task_id,
        "handoff",
        {"handoff_id": created["handoff_id"], "tokens": created["estimated_tokens"]},
    )
    ledger.record(
        state.task_id,
        "handoff",
        tokens_in=created["estimated_tokens"],
        note=created["handoff_id"],
    )
    runtime.save_task(state)

    return _finalize(
        state.task_id,
        {
            "handoff_id": created["handoff_id"],
            "contract": created["contract_text"],
            "estimated_tokens": created["estimated_tokens"],
        },
    )


def main() -> None:
    """Lance le serveur MCP en stdio."""
    settings.ensure_dirs()
    mcp.run()


if __name__ == "__main__":
    main()
