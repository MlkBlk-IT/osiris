"""Stockage SQLite local d'OSIRIS.

Un seul fichier : `~/.osiris/osiris.db`. Aucun service externe, aucun reseau.
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


def _connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA)
    # migrations tolerantes (colonnes ajoutees apres coup)
    for statement in (
        "ALTER TABLE fingerprints ADD COLUMN args_hash TEXT",
        # Taille du resultat enregistre : permet de crediter un blocage de
        # boucle par le cout reellement evite (0 = inconnu, jamais devine).
        "ALTER TABLE fingerprints ADD COLUMN result_tokens INTEGER NOT NULL DEFAULT 0",
        # Tokens DEPLACES vers un ref : distincts des tokens SAUVES (prouves
        # comme ayant quitte le contexte du modele). Sans cette separation,
        # le ledger comptait des economies qui n'en etaient pas.
        "ALTER TABLE ledger ADD COLUMN tokens_moved INTEGER NOT NULL DEFAULT 0",
    ):
        try:
            conn.execute(statement)
        except sqlite3.OperationalError:
            pass
    # Reclassement de l'historique : avant la separation, toute externalisation
    # etait comptee comme une economie. Ces tokens etaient **deplaces**, pas
    # prouves sortis du contexte du modele : ils redeviennent donc
    # `tokens_moved`. Idempotent : seules les lignes porteuses d'un
    # `tokens_saved` non nul hors kind `saving` sont touchees.
    try:
        conn.execute(
            "UPDATE ledger SET tokens_moved = tokens_moved + tokens_saved,"
            " tokens_saved = 0 WHERE kind <> 'saving' AND tokens_saved > 0"
        )
    except sqlite3.OperationalError:
        pass
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
    return conn
