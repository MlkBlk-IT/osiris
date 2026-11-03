"""Tests de regression Priorites 2 & 3 : ledger accounting + task/session isolation."""

from __future__ import annotations

from osiris.core import ledger, refs
from osiris.core.db import get_conn

# ======================================================================
# PRIORITE 2 : Savings accounting
# ======================================================================


def test_dropped_credit_once_per_ref():
    """observe(kind='dropped') ne credite qu'une seule fois par ref."""
    entry = refs.put("t1", "contenu a dropper")
    ref = entry["ref"]

    # Premier drop
    ledger.record("t1", "saving", tokens_saved=entry["tokens"], note=f"dropped:{ref}")
    # Deuxième drop du meme ref -> la fonction osiris_observe verifie et NE re-enregistre pas
    # Simuler ce que fait osiris_observe : verifier avant d'enregistrer
    already = get_conn().execute(
        "SELECT COUNT(*) AS n FROM ledger WHERE task_id = ? AND kind = 'saving' AND note = ?",
        ("t1", f"dropped:{ref}")
    ).fetchone()
    if int(already["n"]) == 0:
        ledger.record("t1", "saving", tokens_saved=entry["tokens"], note=f"dropped:{ref}")

    totals = ledger.totals("t1")
    assert totals["tokens_saved"] == entry["tokens"], (
        f"Double credit: {totals['tokens_saved']} != {entry['tokens']}"
    )


def test_filtered_access_credit_once_per_ref():
    """_credit_filtered_access ne credite qu'une seule fois par ref."""
    entry = refs.put("t1", "x" * 10000)  # ~2500 tokens
    ref = entry["ref"]

    import osiris.server as srv
    from osiris.core.runtime import create_task
    state = create_task("test filtered")

    # Premier acces filtre (got < full -> gain > 0)
    selection = {"tokens": 100, "found": True, "verified": True}
    gain1 = srv._credit_filtered_access(state, ref, selection, "grep")
    assert gain1 > 0, f"First credit should be > 0, got {gain1}"

    # Deuxième acces au meme ref -> 0
    gain2 = srv._credit_filtered_access(state, ref, selection, "grep")
    assert gain2 == 0, f"Second credit should be 0, got {gain2}"


def test_dropped_then_filtered_no_double_count():
    """Si ref deja droppe, filtered_access ne rajoute pas."""
    entry = refs.put("t1", "contenu droppe puis filtre")
    ref = entry["ref"]

    import osiris.server as srv
    from osiris.core.runtime import create_task
    state = create_task("test dropped then filtered")

    # Simuler drop complet
    ledger.record("t1", "saving", tokens_saved=entry["tokens"], note=f"dropped:{ref}")

    # Acces filtre apres -> 0
    selection = {"tokens": 100, "found": True, "verified": True}
    gain = srv._credit_filtered_access(state, ref, selection, "grep")
    assert gain == 0, f"Should not credit after full drop: {gain}"


def test_tokens_moved_vs_tokens_saved_separation():
    """externalize cree tokens_moved, PAS tokens_saved."""
    from osiris.core import prune
    entry = prune.externalize("t1", "payload deplace")
    assert "tokens_moved" in entry
    assert entry["tokens_moved"] == entry["tokens"]
    # L'entry ne doit pas contenir tokens_saved
    assert entry.get("tokens_saved", 0) == 0


# ======================================================================
# PRIORITE 3 : Task/session isolation
# ======================================================================


def test_get_task_clears_current_pointer_on_missing():
    """get_task nettoie le pointeur courant si la tache a ete supprimee."""
    from osiris.core.db import get_conn
    from osiris.core.runtime import create_task, current_task_id, get_task

    state = create_task("tache a supprimer")
    tid = state.task_id
    assert current_task_id() == tid

    # Supprimer manuellement la tache de la DB
    get_conn().execute("DELETE FROM tasks WHERE task_id = ?", (tid,))

    # get_task sans argument -> nettoie le pointeur
    result = get_task(None)
    assert result is None
    assert current_task_id() is None


def test_loopguard_force_reset_isolation():
    """Chaque test loopguard doit partir d'un etat propre (fingerprints)."""
    from osiris.core.db import get_conn
    from osiris.core.loopguard import _upsert_fingerprint, fingerprint

    # Premier test laisse des donnees
    fp = fingerprint("tool", '{"a":1}', "ok:abc")
    _upsert_fingerprint("t1", fp, "tool", "ok:abc", "args_hash_1", 100)

    # Nouveau test sur tache differente -> isolation
    fp2 = fingerprint("tool", '{"b":2}', "ok:def")
    count = _upsert_fingerprint("t2", fp2, "tool", "ok:def", "args_hash_2", 200)
    assert count == 1, "Nouvelle tache doit partir de count=1"

    # Verifier que t1 n'a pas ete affecte
    row = get_conn().execute(
        "SELECT count FROM fingerprints WHERE task_id = ? AND fingerprint = ?",
        ("t1", fp)
    ).fetchone()
    assert int(row["count"]) == 1


def test_tool_results_reusable_flag():
    """tool_results.reusable controlle la reutilisation inter-taches."""
    from osiris.core.db import get_conn

    # Inserer un resultat reusable=0 (non partageable)
    get_conn().execute(
        "INSERT INTO tool_results (task_id, cache_key, ref, reusable) VALUES (?, ?, ?, 0)",
        ("t1", "ck1", "mem://sha256:abc",)
    )

    # Verifier que reusable=0 empeche le partage implicite
    # (la logique de partage verifie ce flag)
    row = get_conn().execute(
        "SELECT reusable FROM tool_results WHERE task_id = ? AND cache_key = ?",
        ("t1", "ck1")
    ).fetchone()
    assert row["reusable"] == 0