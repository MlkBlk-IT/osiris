"""Ledger de cout et d'economies (`CostLedger`).

Les prix ne sont jamais codes en dur : ils viennent du fichier de tarification
de l'utilisateur. Sans ce fichier, les montants sont des estimations basees
sur une table neutre, explicitement etiquetees.
"""

from __future__ import annotations

import json
import time
from typing import Any

from osiris.core.db import get_conn
from osiris.core.policy import load_pricing
from osiris.core.tokens import count_tokens


def _pricing() -> dict[str, float]:
    raw = load_pricing()
    return {
        "input_per_mtok": float(raw.get("input_per_mtok", 3.0)),
        "output_per_mtok": float(raw.get("output_per_mtok", 15.0)),
        "cache_read_per_mtok": float(raw.get("cache_read_per_mtok", 0.30)),
        "cache_write_per_mtok": float(raw.get("cache_write_per_mtok", 3.75)),
    }


def estimate_cost(
    tokens_in: int = 0,
    tokens_out: int = 0,
    tokens_cached: int = 0,
    tokens_fresh: int = 0,
) -> float:
    """Estime un cout en USD a partir de la table de prix utilisateur."""
    p = _pricing()
    fresh_in = max(0, (tokens_in or 0) - (tokens_cached or 0))
    cost = 0.0
    cost += fresh_in / 1_000_000 * p["input_per_mtok"]
    cost += max(0, tokens_fresh) / 1_000_000 * p["input_per_mtok"]
    cost += max(0, tokens_cached) / 1_000_000 * p["cache_read_per_mtok"]
    cost += max(0, tokens_out) / 1_000_000 * p["output_per_mtok"]
    return round(cost, 8)


def record(
    task_id: str,
    kind: str,
    tokens_in: int = 0,
    tokens_out: int = 0,
    tokens_cached: int = 0,
    tokens_fresh: int = 0,
    tokens_saved: int = 0,
    tokens_moved: int = 0,
    cost: float | None = None,
    note: str = "",
) -> int:
    """Enregistre une entree de ledger.

    `tokens_saved` est reserve aux economies **prouvees** (kind `saving`) :
    l'agent a accuse reception de la suppression d'un payload, donc les
    tokens ont reellement quitté sa fenetre.

    `tokens_moved` compte les tokens **deplaces** vers un ref : ils sont
    stockes, mais leur presence dans le contexte du modele n'est pas etablie.
    Les confondre donnait un gain net fictif.
    """
    if cost is None:
        cost = estimate_cost(tokens_in, tokens_out, tokens_cached, tokens_fresh)
    conn = get_conn()
    row = conn.execute(
        "SELECT COALESCE(MAX(seq), 0) + 1 AS n FROM ledger WHERE task_id = ?", (task_id,)
    ).fetchone()
    seq = int(row["n"])
    conn.execute(
        "INSERT INTO ledger (task_id, seq, ts, kind, tokens_in, tokens_out, tokens_cached,"
        " tokens_fresh, tokens_saved, tokens_moved, cost, note)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            task_id,
            seq,
            time.time(),
            kind,
            int(tokens_in),
            int(tokens_out),
            int(tokens_cached),
            int(tokens_fresh),
            int(tokens_saved),
            int(tokens_moved),
            float(cost),
            note,
        ),
    )
    return seq


def record_text(
    task_id: str,
    kind: str,
    text: str,
    tokens_cached: int = 0,
    tokens_saved: int = 0,
    note: str = "",
) -> int:
    """Enregistre une entree en estimant les tokens a partir d'un texte."""
    tokens = count_tokens(text)
    return record(
        task_id,
        kind,
        tokens_in=tokens,
        tokens_cached=tokens_cached,
        tokens_fresh=max(0, tokens - tokens_cached),
        tokens_saved=tokens_saved,
        note=note,
    )


def totals(task_id: str) -> dict[str, Any]:
    """Totaux du ledger pour une tache."""
    row = (
        get_conn()
        .execute(
            "SELECT COALESCE(SUM(tokens_in),0) AS ti, COALESCE(SUM(tokens_out),0) AS to_,"
            " COALESCE(SUM(tokens_cached),0) AS tc, COALESCE(SUM(tokens_fresh),0) AS tf,"
            " COALESCE(SUM(tokens_saved),0) AS ts, COALESCE(SUM(tokens_moved),0) AS tm,"
            " COALESCE(SUM(cost),0) AS cost,"
            " COUNT(*) AS n FROM ledger WHERE task_id = ?",
            (task_id,),
        )
        .fetchone()
    )
    return {
        "entries": int(row["n"]),
        "tokens_in": int(row["ti"]),
        "tokens_out": int(row["to_"]),
        "tokens_cached": int(row["tc"]),
        "tokens_fresh": int(row["tf"]),
        "tokens_saved": int(row["ts"]),
        "tokens_moved": int(row["tm"]),
        "cost_usd": round(float(row["cost"]), 6),
    }


def breakdown(task_id: str) -> list[dict[str, Any]]:
    """Ventilation du ledger par kind."""
    rows = (
        get_conn()
        .execute(
            "SELECT kind, COUNT(*) AS n, COALESCE(SUM(tokens_in),0) AS ti,"
            " COALESCE(SUM(tokens_saved),0) AS ts, COALESCE(SUM(tokens_moved),0) AS tm,"
            " COALESCE(SUM(cost),0) AS cost"
            " FROM ledger WHERE task_id = ? GROUP BY kind ORDER BY ts DESC",
            (task_id,),
        )
        .fetchall()
    )
    return [
        {
            "kind": r["kind"],
            "entries": int(r["n"]),
            "tokens_in": int(r["ti"]),
            "tokens_saved": int(r["ts"]),
            "tokens_moved": int(r["tm"]),
            "cost_usd": round(float(r["cost"]), 6),
        }
        for r in rows
    ]


def entries(task_id: str, limit: int = 200) -> list[dict[str, Any]]:
    rows = (
        get_conn()
        .execute(
            "SELECT seq, ts, kind, tokens_in, tokens_out, tokens_cached, tokens_fresh,"
            " tokens_saved, tokens_moved, cost, note FROM ledger WHERE task_id = ?"
            " ORDER BY seq ASC LIMIT ?",
            (task_id, limit),
        )
        .fetchall()
    )
    return [
        {
            "seq": r["seq"],
            "ts": r["ts"],
            "kind": r["kind"],
            "tokens_in": r["tokens_in"],
            "tokens_out": r["tokens_out"],
            "tokens_cached": r["tokens_cached"],
            "tokens_fresh": r["tokens_fresh"],
            "tokens_saved": r["tokens_saved"],
            "tokens_moved": r["tokens_moved"],
            "cost_usd": round(float(r["cost"]), 6),
            "note": r["note"],
        }
        for r in rows
    ]


def overhead(task_id: str) -> int:
    """Tokens consommes par OSIRIS lui-meme.

    Inclut deux postes, tous deux payes par l'agent :
    - `overhead` : la taille reelle de chaque reponse d'outil ;
    - `schema_access` : les schemas d'outils OSIRIS charges dans le prompt
      (comptabilises une fois par tache, cf. `server._record_schema_access`).

    Exclure les schemas rendait le net optimiste de ~1086 tokens par tache.
    """
    row = (
        get_conn()
        .execute(
            "SELECT COALESCE(SUM(tokens_in), 0) AS n FROM ledger"
            " WHERE task_id = ? AND kind IN ('overhead', 'schema_access')",
            (task_id,),
        )
        .fetchone()
    )
    return int(row["n"])


def loop_credits(task_id: str) -> int:
    """Tokens reellement evites par les boucles bloquees (auditable).

    Methode explicite, verifiable en DB : une boucle est bloquee quand un
    meme (tool, args) a ete observe au moins 2 fois (table `fingerprints`).
    Le 2e appel et les suivants auraient rejoue un resultat identique : le
    credit est la taille du resultat deja en cache, soit le cout evite.

    On ne credite **que** ce qui est prouvable : le nombre d'appels repetes
    (count - 1) multiplie par la taille du payload enregistre. Aucun credit
    forfaitaire, aucune constante inventee.
    """
    conn = get_conn()
    rows = conn.execute(
        "SELECT f.count AS count, f.result_tokens AS tokens"
        " FROM fingerprints f WHERE f.task_id = ? AND f.count >= 2",
        (task_id,),
    ).fetchall()
    return int(sum(max(0, int(r["count"]) - 1) * max(0, int(r["tokens"] or 0)) for r in rows))


def observed(task_id: str) -> int:
    """Tokens de contexte observes par l'agent (hors surcout OSIRIS)."""
    row = (
        get_conn()
        .execute(
            "SELECT COALESCE(SUM(tokens_in), 0) AS n FROM ledger"
            " WHERE task_id = ? AND kind NOT IN ('overhead', 'schema_access')",
            (task_id,),
        )
        .fetchone()
    )
    return int(row["n"])


def tokens_saved_exact(task_id: str) -> int:
    """Economies prouvees par une entree de ledger dediee (`kind='saving'`).

    Contrairement a `totals()['tokens_saved']`, qui agrege aussi des
    estimations, ce montant ne compte que ce qu'un chemin de code a mesure
    et journalise explicitement.
    """
    row = (
        get_conn()
        .execute(
            "SELECT COALESCE(SUM(tokens_saved), 0) AS n FROM ledger"
            " WHERE task_id = ? AND kind = 'saving'",
            (task_id,),
        )
        .fetchone()
    )
    return int(row["n"])


def tokens_moved_exact(task_id: str) -> int:
    """Tokens deplaces vers un ref (stockes, pas forcement retires du contexte)."""
    row = (
        get_conn()
        .execute(
            "SELECT COALESCE(SUM(tokens_moved), 0) AS n FROM ledger WHERE task_id = ?",
            (task_id,),
        )
        .fetchone()
    )
    return int(row["n"])


def storage_cost(task_id: str | None = None) -> dict[str, Any]:
    """Cout de stockage des refs (taille totale en bytes et nombre)."""
    conn = get_conn()
    if task_id:
        row = conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(size_bytes), 0) AS bytes"
            " FROM refs WHERE task_id = ?",
            (task_id,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(size_bytes), 0) AS bytes FROM refs"
        ).fetchone()
    return {
        "refs": int(row["n"]),
        "bytes": int(row["bytes"]),
    }


def credit_loop_savings(task_id: str, budget_state=None) -> int:
    """Credite les economies des boucles bloquees (doublons evites).

    Preuve : le 2e appel etait identique au 1er (meme fingerprint). Le
    resultat etait deja en cache. L'agent a evite de re-executer.
    Idempotent : ne recredite pas ce qui l'a deja ete.
    """
    row = (
        get_conn()
        .execute(
            "SELECT COALESCE(SUM(tokens_saved), 0) AS n FROM ledger"
            " WHERE task_id = ? AND kind = 'saving' AND note = 'loop_credit'",
            (task_id,),
        )
        .fetchone()
    )
    already = int(row["n"])
    if already > 0:
        return already

    avoided = loop_credits(task_id)
    if avoided <= 0:
        return 0

    record(task_id, "saving", tokens_saved=avoided, note="loop_credit")
    if budget_state is not None:
        budget_state.tokens_saved += avoided
    return avoided


def net_saving(task_id: str) -> int:
    """Gain net = tokens economises - surcout propre d'OSIRIS.

    Les deux termes sont mesures : les economies par le ledger, le surcout
    par `overhead()` (qui inclut desormais le cout des schemas).
    """
    totals_ = totals(task_id)
    return int(totals_["tokens_saved"]) - overhead(task_id)


def dump(task_id: str) -> str:
    return json.dumps(
        {"totals": totals(task_id), "breakdown": breakdown(task_id)},
        ensure_ascii=False,
        indent=2,
    )
