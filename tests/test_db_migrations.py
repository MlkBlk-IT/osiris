"""Garde-fous sur les migrations SQLite.

Le schema est versionne par `PRAGMA user_version`. Une migration qui echoue
doit laisser la base dans son etat anterieur : une base ne peut pas demarrer
avec un schema a moitie applique, et l'erreur doit remonter a l'appelant
au lieu d'etre silencieusement ignoree.
"""

from __future__ import annotations

import sqlite3

import pytest

from osiris.core import db


def _user_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})")]


# ======================================================================
# Schema cible
# ======================================================================


def test_fresh_database_reaches_the_latest_version():
    conn = db.use_memory_db()
    assert _user_version(conn) == db.SCHEMA_VERSION


def test_fresh_database_has_every_migrated_column():
    conn = db.use_memory_db()
    assert "tokens_moved" in _columns(conn, "ledger")
    assert "result_tokens" in _columns(conn, "fingerprints")
    assert "args_hash" in _columns(conn, "fingerprints")


def test_migrations_are_idempotent():
    """Rejouer les migrations ne doit rien changer ni lever."""
    conn = db.use_memory_db()
    before = _user_version(conn)
    assert db.migrate(conn) == before
    assert _user_version(conn) == before


# ======================================================================
# Base ancienne (schema d'avant le versionnage)
# ======================================================================


def _legacy_db() -> sqlite3.Connection:
    """Une base creee par une version anterieure : pas de `user_version`,
    colonnes recentes absentes."""
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE fingerprints (task_id TEXT NOT NULL, fingerprint TEXT NOT NULL,"
        " tool TEXT, args_hash TEXT, result_sig TEXT, count INTEGER NOT NULL DEFAULT 0,"
        " first_at REAL, last_at REAL, PRIMARY KEY (task_id, fingerprint))"
    )
    conn.execute(
        "CREATE TABLE ledger (task_id TEXT NOT NULL, seq INTEGER NOT NULL, ts REAL NOT NULL,"
        " kind TEXT NOT NULL, tokens_in INTEGER NOT NULL DEFAULT 0,"
        " tokens_out INTEGER NOT NULL DEFAULT 0, tokens_cached INTEGER NOT NULL DEFAULT 0,"
        " tokens_fresh INTEGER NOT NULL DEFAULT 0, tokens_saved INTEGER NOT NULL DEFAULT 0,"
        " cost REAL NOT NULL DEFAULT 0, note TEXT, PRIMARY KEY (task_id, seq))"
    )
    return conn


def test_legacy_database_is_migrated():
    conn = _legacy_db()
    assert _user_version(conn) == 0
    assert "result_tokens" not in _columns(conn, "fingerprints")
    assert "tokens_moved" not in _columns(conn, "ledger")

    assert db.migrate(conn) == db.SCHEMA_VERSION

    assert "result_tokens" in _columns(conn, "fingerprints")
    assert "tokens_moved" in _columns(conn, "ledger")


def test_legacy_database_with_existing_columns_is_migrated():
    """Une base ou la colonne existe deja ne doit pas faire echouer la migration."""
    conn = _legacy_db()
    conn.execute("ALTER TABLE fingerprints ADD COLUMN result_tokens INTEGER NOT NULL DEFAULT 0")
    conn.execute("ALTER TABLE ledger ADD COLUMN tokens_moved INTEGER NOT NULL DEFAULT 0")
    assert db.migrate(conn) == db.SCHEMA_VERSION


def test_ledger_history_is_reclassified_once():
    """Avant la separation, toute externalisation etait comptee comme une
    economie : ces tokens sont *deplaces*, pas *prouves* sortis."""
    conn = _legacy_db()
    conn.execute(
        "INSERT INTO ledger (task_id, seq, ts, kind, tokens_in, tokens_saved)"
        " VALUES ('t1', 1, 0.0, 'observe', 100, 40)"
    )
    conn.execute(
        "INSERT INTO ledger (task_id, seq, ts, kind, tokens_in, tokens_saved)"
        " VALUES ('t1', 2, 0.0, 'saving', 100, 25)"
    )
    db.migrate(conn)

    rows = {
        r["kind"]: (int(r["tokens_saved"]), int(r["tokens_moved"]))
        for r in conn.execute("SELECT kind, tokens_saved, tokens_moved FROM ledger")
    }
    # `observe` : les tokens sont deplaces, pas prouves.
    assert rows["observe"] == (0, 40)
    # `saving` : economie prouvee, elle reste.
    assert rows["saving"] == (25, 0)


# ======================================================================
# Echec : rollback et propagation
# ======================================================================


def test_failed_migration_rolls_back_and_keeps_version(monkeypatch):
    """Une migration en echec ne doit ni incrementer `user_version`,
    ni laisser la base a moitie migree, ni etre silenciee."""
    conn = _legacy_db()
    before = _user_version(conn)

    def boom(conn_, table, column, statement):
        raise sqlite3.OperationalError("boom")

    monkeypatch.setattr(db, "_apply_column_migration", boom)

    with pytest.raises(sqlite3.OperationalError):
        db.migrate(conn)

    assert _user_version(conn) == before
    # La colonne de la migration en echec n'a pas ete ajoutee.
    assert "result_tokens" not in _columns(conn, "fingerprints")


def test_unexpected_operational_error_is_not_swallowed():
    """Une erreur SQL reelle doit remonter : c'est elle qui distingue une
    colonne deja presente d'un schema casse."""
    conn = db.use_memory_db()
    with pytest.raises(db.MigrationError):
        db._apply_column_migration(
            conn, "table_inexistante", "col", "ALTER TABLE table_inexistante ADD COLUMN col TEXT"
        )
