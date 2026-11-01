"""Fixtures de test.

L'environnement OSIRIS est redirige vers un repertoire temporaire AVANT toute
import de `osiris.config` (les settings sont figes a l'import).
"""

from __future__ import annotations

import os
import pathlib
import sys
import tempfile

_TMP = pathlib.Path(tempfile.mkdtemp(prefix="osiris-test-"))

os.environ["OSIRIS_HOME"] = str(_TMP)
os.environ["OSIRIS_DATA_DIR"] = str(_TMP / "data")
os.environ["OSIRIS_ROOTS"] = str(_TMP)
os.environ["OSIRIS_LOG_LEVEL"] = "WARNING"

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import pytest  # noqa: E402

from osiris.config import settings  # noqa: E402
from osiris.core import db  # noqa: E402


@pytest.fixture(autouse=True)
def clean_state():
    """Base propre avant et apres chaque test."""
    db.reset_conn()
    for suffix in ("", "-wal", "-shm"):
        candidate = pathlib.Path(str(settings.db_path) + suffix)
        if candidate.exists():
            candidate.unlink()
    settings.ensure_dirs()
    yield
    db.reset_conn()


@pytest.fixture
def tmp_root() -> pathlib.Path:
    """Repertoire de travail pour les fixtures de fichiers."""
    root = _TMP / "work"
    root.mkdir(parents=True, exist_ok=True)
    return root


@pytest.fixture
def sample_file(tmp_root: pathlib.Path) -> pathlib.Path:
    """Un fichier source typique."""
    path = tmp_root / "Profile.psm1"
    path.write_text(
        "function Get-Profile {\n"
        "    param($Name)\n"
        "    $p = Join-Path $env:PROFILE $Name\n"
        "    if (Test-Path $p) { return Get-Content $p }\n"
        "    return $null\n"
        "}\n",
        encoding="utf-8",
    )
    return path
