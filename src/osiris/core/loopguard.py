"""`LoopGuard` — detection des boucles d'appels d'outils.

Fingerprint : sha256(tool ‖ canonical_args ‖ result_signature).

Cinq detections :
1. doublon exact      — meme outil, memes arguments
2. echec repete       — meme signature d'erreur
3. pattern de boucle  — meme erreur, arguments variables
4. oscillation        — alternance A/B sans progression
5. runaway            — trop d'appels sans changement d'etat utile

Verdicts : allow | warn | block | suggest_alternative.

Principe : le blocage est **logique et explique**. On ne bloque que ce qui
est objectivement demontre (meme hash de fichier, meme signature d'erreur).
"""

from __future__ import annotations

import re
import time
from typing import Any

from osiris.core.db import get_conn
from osiris.core.ids import canonical_args, hash_args, sha256_hex
from osiris.core.policy import load_policy
from osiris.core.tokens import count_tokens

#: Evenements qui prouvent un progres (mutation reelle de l'etat).
PROGRESS_KINDS = frozenset(
    {"externalize", "decision", "constraint", "payload", "file_write", "test_result", "lesson"}
)

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_DIGITS = re.compile(r"\d+")
_PATH = re.compile(r"[A-Za-z]:[\\/][^\s\"']+|/(?:[\w.-]+/)+[\w.-]+")
_QUOTED = re.compile(r"\"[^\"]*\"|'[^']*'")


def normalize_error(text: str) -> str:
    """Normalise un message d'erreur pour en extraire une signature stable."""
    if not text:
        return ""
    cleaned = _ANSI.sub("", text)
    lines = [ln.strip() for ln in cleaned.splitlines() if ln.strip()]
    head = " | ".join(lines[:2])
    head = _PATH.sub("PATH", head)
    head = _QUOTED.sub("Q", head)
    head = _DIGITS.sub("#", head)
    return head[:200]


def error_signature(text: str) -> str:
    """Signature courte et stable d'une erreur."""
    normalized = normalize_error(text)
    if not normalized:
        return ""
    return f"{sha256_hex(normalized)[:10]}"


def result_signature(result: str, status: str) -> str:
    """Signature du resultat : contenu si succes, erreur si echec."""
    if status == "error":
        return f"err:{error_signature(result)}"
    return f"ok:{sha256_hex(result or '')[:12]}"


def fingerprint(tool: str, args: str | None, result_sig: str) -> str:
    """Triple fingerprint."""
    return sha256_hex(f"{tool}|{canonical_args(args)}|{result_sig}")[:20]


def _upsert_fingerprint(
    task_id: str,
    fp: str,
    tool: str,
    result_sig: str,
    args_hash: str,
    result_tokens: int = 0,
) -> int:
    conn = get_conn()
    now = time.time()
    row = conn.execute(
        "SELECT count FROM fingerprints WHERE task_id = ? AND fingerprint = ?", (task_id, fp)
    ).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO fingerprints (task_id, fingerprint, tool, args_hash, result_sig,"
            " count, first_at, last_at, result_tokens) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)",
            (task_id, fp, tool, args_hash, result_sig, now, now, int(result_tokens)),
        )
        return 1
    count = int(row["count"]) + 1
    conn.execute(
        "UPDATE fingerprints SET count = ?, last_at = ?, result_tokens = ?"
        " WHERE task_id = ? AND fingerprint = ?",
        (count, now, int(result_tokens), task_id, fp),
    )
    return count


def _record_failure(task_id: str, signature: str, tool: str, args: str) -> int:
    conn = get_conn()
    now = time.time()
    row = conn.execute(
        "SELECT count FROM failures WHERE task_id = ? AND signature = ?", (task_id, signature)
    ).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO failures (task_id, signature, tool, args_hash, count, first_at, last_at)"
            " VALUES (?, ?, ?, ?, 1, ?, ?)",
            (task_id, signature, tool, hash_args(args), now, now),
        )
        return 1
    count = int(row["count"]) + 1
    conn.execute(
        "UPDATE failures SET count = ?, last_at = ? WHERE task_id = ? AND signature = ?",
        (count, now, task_id, signature),
    )
    return count


def _recent_tools(task_id: str, limit: int) -> list[tuple[str, str]]:
    rows = (
        get_conn()
        .execute(
            "SELECT payload_json FROM events WHERE task_id = ? AND kind = 'action'"
            " ORDER BY seq DESC LIMIT ?",
            (task_id, limit),
        )
        .fetchall()
    )
    out: list[tuple[str, str]] = []
    for row in rows:
        import json

        try:
            payload = json.loads(row["payload_json"] or "{}")
        except ValueError:
            payload = {}
        out.append((payload.get("tool", ""), payload.get("args", "")))
    return out


def _calls_since_progress(task_id: str) -> int:
    rows = (
        get_conn()
        .execute(
            "SELECT kind FROM events WHERE task_id = ? ORDER BY seq DESC LIMIT 200", (task_id,)
        )
        .fetchall()
    )
    count = 0
    for row in rows:
        if row["kind"] in PROGRESS_KINDS:
            return count
        if row["kind"] == "action":
            count += 1
    return count


def record(
    task_id: str,
    tool: str,
    args: str | None,
    result: str,
    status: str = "ok",
) -> dict[str, Any]:
    """Analyse un appel d'outil et renvoie un verdict.

    Returns:
        {"verdict": ..., "reason": ..., "detail": ..., "alternative": ...}
    """
    policy = load_policy()
    dup_limit = int(policy.get("loop.duplicate_limit", 2))
    dup_warn = int(policy.get("loop.duplicate_warn", 3))
    dup_block = int(policy.get("loop.duplicate_block", 5))
    failure_limit = int(policy.get("loop.failure_limit", 3))
    osc_window = int(policy.get("loop.oscillation_window", 8))
    runaway_calls = int(policy.get("loop.runaway_calls", 25))

    sig = result_signature(result or "", status)
    fp = fingerprint(tool, args, sig)
    count = _upsert_fingerprint(
        task_id, fp, tool, sig, hash_args(args), count_tokens(result or "")
    )

    if status == "error":
        esig = error_signature(result or "")
        failures = _record_failure(task_id, esig, tool, args or "")
        if failures >= failure_limit:
            return {
                "verdict": "block",
                "reason": "repeated_failure",
                "signature": esig,
                "seen": failures,
                "limit": failure_limit,
                "detail": f"meme signature d'erreur {failures} fois",
                "alternative": "corrige la cause avant de rejouer ; "
                "un nouvel essai identique n'est pas autorise",
                "required_action": "fix_then_retry",
            }
        if failures >= failure_limit - 1:
            return {
                "verdict": "warn",
                "reason": "failure_repeating",
                "signature": esig,
                "seen": failures,
                "detail": "cette erreur se repete",
                "alternative": "change d'approche avant le prochain essai",
            }

    if count >= dup_limit:
        if count >= dup_block:
            return {
                "verdict": "block",
                "reason": "exact_duplicate",
                "fingerprint": fp,
                "seen": count,
                "limit": dup_block,
                "detail": f"appel identique repete {count} fois (seuil block={dup_block})",
                "alternative": "arrefe : rejouer cet appel n'est plus autorise, "
                "change d'approche ou utilise le ref deja stocke",
                "required_action": "stop_and_change_approach",
            }
        if count >= dup_warn:
            return {
                "verdict": "warn",
                "reason": "exact_duplicate",
                "fingerprint": fp,
                "seen": count,
                "detail": f"appel identique repete {count} fois (seuil warn={dup_warn})",
                "alternative": "utilise le ref deja stocke au lieu de rejouer l'appel",
            }
        return {
            "verdict": "suggest_alternative",
            "reason": "exact_duplicate",
            "fingerprint": fp,
            "seen": count,
            "detail": "appel identique repete",
            "alternative": "utilise le ref deja stocke au lieu de rejouer l'appel",
        }

    # pattern de boucle : meme signature de resultat, mais arguments differents
    same_sig = (
        get_conn()
        .execute(
            "SELECT COUNT(*) AS n FROM fingerprints WHERE task_id = ? AND result_sig = ?",
            (task_id, sig),
        )
        .fetchone()
    )
    if int(same_sig["n"]) >= 2 and status == "error":
        return {
            "verdict": "warn",
            "reason": "loop_pattern",
            "signature": sig,
            "seen": int(same_sig["n"]),
            "detail": "meme resultat avec des arguments differents",
            "alternative": "varie l'approche, pas les arguments",
        }

    # oscillation : alternance de deux outils sans progression
    recent = _recent_tools(task_id, osc_window)
    if len(recent) >= 4:
        tools = [t for t, _ in recent]
        if len(set(tools)) == 2 and tools[0] == tools[2] and tools[1] == tools[3]:
            if _calls_since_progress(task_id) >= 4:
                return {
                    "verdict": "warn",
                    "reason": "oscillation",
                    "detail": f"alternance {tools[0]} / {tools[1]} sans progression",
                    "alternative": "change d'outil ou applique une correction avant de continuer",
                }

    # runaway : beaucoup d'appels sans mutation utile
    since_progress = _calls_since_progress(task_id)
    if since_progress >= runaway_calls:
        return {
            "verdict": "warn",
            "reason": "runaway",
            "detail": f"{since_progress} appels sans changement d'etat utile",
            "alternative": "produis un changement concret "
            "(ecriture, decision, correctif) avant de continuer",
        }

    return {"verdict": "allow", "reason": "no_loop_detected", "fingerprint": fp, "seen": count}


def blocked_tools(task_id: str) -> set[str]:
    """Outils qui ont recemment declenche un blocage (pour le Tool Compass)."""
    rows = (
        get_conn()
        .execute("SELECT tool, count FROM fingerprints WHERE task_id = ?", (task_id,))
        .fetchall()
    )
    policy = load_policy()
    limit = int(policy.get("loop.duplicate_limit", 2))
    return {r["tool"] for r in rows if r["tool"] and int(r["count"]) >= limit}
