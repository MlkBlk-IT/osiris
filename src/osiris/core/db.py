"""Stockage SQLite local d'OSIRIS.

Un seul fichier : `~/.osiris/osiris.db`. Aucun service externe, aucun reseau.

Le schema est versionne par `PRAGMA user_version`. Chaque migration est
numerotee, transactionnelle, et n'est rejouee qu'une fois. Une migration qui
echoue laisse la base dans son etat anterieur : une base ne peut donc pas
demarrer avec un schema a moitie applique.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from osiris.config import settings

_LOCK = threading.RLock()
_CONN: sqlite3.Connection | None = None

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS tasks (
    task_id     TEXT PRIMARY KEY,
    created_at  REAL NOT NULL,
    updated_at  REAL NOT NULL,
    state_json  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS memory (
    mem_id     TEXT PRIMARY KEY,
    task_id    TEXT,
    scope      TEXT NOT NULL,
    kind       TEXT NOT NULL,
    body       TEXT NOT NULL,
    pinned     INTEGER NOT NULL DEFAULT 0,
    meta_json  TEXT,
    created_at REAL NOT NULL,
    seq        INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_memory_task ON memory(task_id, kind);

CREATE TABLE IF NOT EXISTS refs (
    ref          TEXT PRIMARY KEY,
    task_id      TEXT,
    content_hash TEXT NOT NULL,
    size_bytes   INTEGER NOT NULL,
    content      TEXT NOT NULL,
    meta_json    TEXT,
    redactions   INTEGER NOT NULL DEFAULT 0,
    created_at   REAL NOT NULL,
    expires_at   REAL
);

CREATE TABLE IF NOT EXISTS events (
    seq          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id      TEXT NOT NULL,
    ts           REAL NOT NULL,
    kind         TEXT NOT NULL,
    action_state TEXT,
    run_key      TEXT,
    payload_json TEXT
);
CREATE INDEX IF NOT EXISTS ix_events_task ON events(task_id, seq);

CREATE TABLE IF NOT EXISTS checkpoints (
    checkpoint_id  TEXT PRIMARY KEY,
    task_id        TEXT NOT NULL,
    journal_offset INTEGER NOT NULL,
    label          TEXT,
    state_json     TEXT,
    created_at     REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS handoffs (
    handoff_id     TEXT PRIMARY KEY,
    task_id        TEXT NOT NULL,
    parent_task_id TEXT,
    contract_json  TEXT NOT NULL,
    status         TEXT NOT NULL,
    result_json    TEXT,
    created_at     REAL NOT NULL,
    expires_at     REAL
);

CREATE TABLE IF NOT EXISTS fingerprints (
    task_id    TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    tool       TEXT,
    args_hash  TEXT,
    result_sig TEXT,
    count      INTEGER NOT NULL DEFAULT 0,
    first_at   REAL,
    last_at    REAL,
    PRIMARY KEY (task_id, fingerprint)
);

CREATE TABLE IF NOT EXISTS failures (
    task_id    TEXT NOT NULL,
    signature  TEXT NOT NULL,
    tool       TEXT,
    args_hash  TEXT,
    count      INTEGER NOT NULL DEFAULT 0,
    first_at   REAL,
    last_at    REAL,
    PRIMARY KEY (task_id, signature)
);

CREATE TABLE IF NOT EXISTS files (
    task_id      TEXT NOT NULL,
    path         TEXT NOT NULL,
    content_hash TEXT,
    mtime        REAL,
    last_read_at REAL,
    ref          TEXT,
    size_bytes   INTEGER,
    PRIMARY KEY (task_id, path)
);

CREATE TABLE IF NOT EXISTS tool_results (
    task_id    TEXT NOT NULL,
    cache_key  TEXT NOT NULL,
    ref        TEXT,
    size_bytes INTEGER,
    tokens     INTEGER,
    cost       REAL,
    ttl        REAL,
    reusable   INTEGER NOT NULL DEFAULT 1,
    created_at REAL,
    PRIMARY KEY (task_id, cache_key)
);

CREATE TABLE IF NOT EXISTS ledger (
    task_id        TEXT NOT NULL,
    seq            INTEGER NOT NULL,
    ts             REAL NOT NULL,
    kind           TEXT NOT NULL,
    tokens_in      INTEGER NOT NULL DEFAULT 0,
    tokens_out     INTEGER NOT NULL DEFAULT 0,
    tokens_cached  INTEGER NOT NULL DEFAULT 0,
    tokens_fresh   INTEGER NOT NULL DEFAULT 0,
    tokens_saved   INTEGER NOT NULL DEFAULT 0,
    tokens_moved   INTEGER NOT NULL DEFAULT 0,
    cost           REAL NOT NULL DEFAULT 0,
    note           TEXT,
    PRIMARY KEY (task_id, seq)
);

CREATE TABLE IF NOT EXISTS tool_usage (
    task_id     TEXT NOT NULL,
    tool        TEXT NOT NULL,
    calls       INTEGER NOT NULL DEFAULT 0,
    last_at     REAL,
    PRIMARY KEY (task_id, tool)
);
"""


class MigrationError(RuntimeError):
    """Une migration a echoue : la base est restee a sa version precedente."""


# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------
#
# Convention : le numero de migration est `PRAGMA user_version`. La migration
# N s'applique que si `user_version < N`, et elle est rejouee sur une base
# fraiche comme sur une base ancienne.
#
# Une migration doit :
#   - etre idempotente ou s'appuyer sur `user_version` pour ne jouer qu'une fois ;
#   - tolerer UNIQUEMENT les cas explicitement attendus (ici : la colonne
#     existe deja) ;
#   - laisser passer toute autre erreur, pour qu'une base ne demarre pas avec
#     un schema incomplet.

#: Colonnes ajoutees apres la creation initiale des tables.
#: (version, nom, table, colonne, instruction)
_COLUMN_MIGRATIONS: tuple[tuple[int, str, str, str, str], ...] = (
    (
        1,
        "fingerprints_args_hash",
        "fingerprints",
        "args_hash",
        "ALTER TABLE fingerprints ADD COLUMN args_hash TEXT",
    ),
    (
        2,
        "fingerprints_result_tokens",
        "fingerprints",
        "result_tokens",
        # Taille du resultat enregistre : permet de crediter un blocage de
        # boucle par le cout reellement evite (0 = inconnu, jamais devine).
        "ALTER TABLE fingerprints ADD COLUMN result_tokens INTEGER NOT NULL DEFAULT 0",
    ),
    (
        3,
        "ledger_tokens_moved",
        "ledger",
        "tokens_moved",
        # Tokens DEPLACES vers un ref : distincts des tokens SAUVES (prouves
        # comme ayant quitté le contexte du modele). Sans cette separation,
        # le ledger comptait des economies qui n'en etaient pas.
        "ALTER TABLE ledger ADD COLUMN tokens_moved INTEGER NOT NULL DEFAULT 0",
    ),
)

#: Version de la migration de donnees (reclassement de l'historique).
#: Distincte des migrations de colonnes : une base ancienne doit la subir
#: meme si ses colonnes sont deja a jour.
_DATA_MIGRATION_VERSION = 4

#: Version du schema apres application de toutes les migrations connues.
SCHEMA_VERSION = 4


def _has_column(conn: sqlite3.Connection, table: str, column: str) -> bool:
    """La colonne existe-t-elle deja ? (source de verite, pas d'exception)"""
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(str(r[1]) == column for r in rows)


def _apply_column_migration(
    conn: sqlite3.Connection, table: str, column: str, statement: str
) -> None:
    """Applique un `ALTER TABLE ADD COLUMN`, si la colonne manque.

    Seule la colonne deja presente est toleree. Toute autre erreur
    (`OperationalError`) est propagee : elle signale un schema incoherent,
    pas un cas anodin.
    """
    if _has_column(conn, table, column):
        return
    try:
        conn.execute(statement)
    except sqlite3.OperationalError as exc:
        raise MigrationError(
            f"migration ADD COLUMN {table}.{column} : {exc}"
        ) from exc


def _reclassify_ledger_history(conn: sqlite3.Connection) -> None:
    """Reclassement de l'historique : `tokens_saved` -> `tokens_moved`.

    Avant la separation, toute externalisation etait comptee comme une
    economie. Ces tokens etaient **deplaces**, pas prouves sortis du
    contexte du modele : ils redeviennent donc `tokens_moved`.

    Idempotent : seules les lignes porteuses d'un `tokens_saved` non nul
    hors kind `saving` sont touchees.
    """
    try:
        conn.execute(
            "UPDATE ledger SET tokens_moved = tokens_moved + tokens_saved,"
            " tokens_saved = 0 WHERE kind <> 'saving' AND tokens_saved > 0"
        )
    except sqlite3.OperationalError as exc:
        raise MigrationError(f"migration reclassement du ledger : {exc}") from exc


def _user_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("PRAGMA user_version").fetchone()
    return int(row[0]) if row else 0


def migrate(conn: sqlite3.Connection) -> int:
    """Applique les migrations manquantes. Retourne la version du schema.

    Chaque migration est transactionnelle : en cas d'echec, la transaction
    est annulee et `user_version` reste sur la version precedente. La base
    n'est donc jamais laissee dans un etat a moitie migre, et l'erreur
    remonte a l'appelant au lieu d'etre silencieusement ignoree.
    """
    current = _user_version(conn)

    for version, _name, table, column, statement in _COLUMN_MIGRATIONS:
        if version <= current:
            continue
        try:
            conn.execute("BEGIN")
            _apply_column_migration(conn, table, column, statement)
            conn.execute(f"PRAGMA user_version = {version}")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        current = version

    # Migration de donnees : reclassement de l'historique du ledger.
    # Version propre : elle doit s'executer sur une base ancienne meme si
    # ses colonnes sont deja a jour (c'est le cas d'une base creee par une
    # version anterieure au versionnage).
    if current < _DATA_MIGRATION_VERSION:
        try:
            conn.execute("BEGIN")
            _reclassify_ledger_history(conn)
            conn.execute(f"PRAGMA user_version = {_DATA_MIGRATION_VERSION}")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        current = _DATA_MIGRATION_VERSION

    return current


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    migrate(conn)
    return conn


def get_conn() -> sqlite3.Connection:
    """Connexion process unique, initialisee au premier appel."""
    global _CONN
    with _LOCK:
        if _CONN is None:
            settings.ensure_dirs()
            _CONN = _connect(settings.db_path)
        return _CONN


def reset_conn() -> None:
    """Ferme et recree la connexion (tests, changement de OSIRIS_HOME)."""
    global _CONN
    with _LOCK:
        if _CONN is not None:
            try:
                _CONN.close()
            finally:
                _CONN = None


def use_memory_db() -> sqlite3.Connection:
    """Connexion jetable en memoire (tests)."""
    conn = sqlite3.connect(":memory:", check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    migrate(conn)
    return conn
