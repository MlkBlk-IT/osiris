"""Configuration centralisée d'OSIRIS.

Tout est piloté par variables d'environnement, avec des défauts sûrs.
Aucun chemin ne pointe vers un autre projet : OSIRIS est autonome.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

#: Racine du projet (src/osiris/config.py -> racine en remontant 3 niveaux).
PROJECT_ROOT = Path(__file__).resolve().parents[2]

#: Racines autorisées par défaut : le répertoire courant du processus.
DEFAULT_ROOT = Path.cwd()

#: Taille maximale d'un fichier qu'OSIRIS est autorisé à lire/externaliser.
DEFAULT_MAX_FILE_BYTES = 2 * 1024 * 1024

#: TTL par defaut du prefix cache provider (parametre, pas une dependance).
DEFAULT_CACHE_TTL_S = 300.0


def _env_path(name: str, default: Path) -> Path:
    raw = os.getenv(name)
    return Path(raw).expanduser().resolve() if raw else default


def _env_roots() -> tuple[Path, ...]:
    raw = os.getenv("OSIRIS_ROOTS", "")
    roots: list[Path] = []
    for part in raw.split(os.pathsep):
        part = part.strip()
        if part:
            roots.append(Path(part).expanduser().resolve())
    roots.append(DEFAULT_ROOT.resolve())
    # dedup conserve l'ordre
    seen: set[Path] = set()
    unique: list[Path] = []
    for r in roots:
        if r not in seen:
            seen.add(r)
            unique.append(r)
    return tuple(unique)


#: Budgets par phase du cycle agent (tokens). `0` = pas de limite.
#:
#: Un budget global ne suffit pas : la phase d'observation (qui encaisse les
#: resultats d'outils) peut affamer la phase de generation. Ces plafonds
#: arbitrent entre les phases ; ils sont surchargeables par
#: `OSIRIS_PHASE_BUDGETS='{"observation": 40000}'`.
DEFAULT_PHASE_BUDGETS: dict[str, int] = {
    "planning": 4_000,
    "observation": 40_000,
    "generation": 20_000,
    "verification": 10_000,
}


def _env_phase_budgets() -> dict[str, int]:
    raw = os.getenv("OSIRIS_PHASE_BUDGETS", "").strip()
    if not raw:
        return dict(DEFAULT_PHASE_BUDGETS)
    try:
        data = json.loads(raw)
    except ValueError:
        return dict(DEFAULT_PHASE_BUDGETS)
    if not isinstance(data, dict):
        return dict(DEFAULT_PHASE_BUDGETS)
    out = dict(DEFAULT_PHASE_BUDGETS)
    for key, value in data.items():
        try:
            out[str(key)] = int(value)
        except (TypeError, ValueError):
            continue
    return out


@dataclass(frozen=True)
class Settings:
    """Parametres runtime immuables."""

    server_name: str = "osiris"
    version: str = "0.1.0"
    log_level: str = field(default_factory=lambda: os.getenv("OSIRIS_LOG_LEVEL", "INFO"))

    #: Repertoire d'etat OSIRIS (base, rapports, caches).
    home: Path = field(default_factory=lambda: _env_path("OSIRIS_HOME", Path.home() / ".osiris"))
    #: Repertoire de travail du projet (artefacts de bench, dumps).
    data_dir: Path = field(
        default_factory=lambda: _env_path("OSIRIS_DATA_DIR", PROJECT_ROOT / "data")
    )

    #: Racines filesystem autorisees.
    allowed_roots: tuple[Path, ...] = field(default_factory=_env_roots)
    max_file_bytes: int = int(os.getenv("OSIRIS_MAX_FILE_BYTES", DEFAULT_MAX_FILE_BYTES))

    #: TTL du prefix cache provider, en secondes (parametre de l'utilisateur).
    cache_ttl_s: float = float(os.getenv("OSIRIS_CACHE_TTL_S", DEFAULT_CACHE_TTL_S))

    #: Seuil au-dessus duquel le pruning automatique se declenche.
    prune_threshold_tokens: int = int(os.getenv("OSIRIS_PRUNE_THRESHOLD_TOKENS", "40000"))

    #: Mode de pruning : cache_ttl | conservative | balanced | aggressive.
    prune_mode: str = os.getenv("OSIRIS_PRUNE_MODE", "cache_ttl")

    #: Budgets par phase (tokens). `0` = pas de limite.
    phase_budgets: dict[str, int] = field(default_factory=_env_phase_budgets)

    #: Mode « un seul schema d'outil » : n'expose que `osiris.call`.
    #:
    #: Le tableau `tools` du client fait partie du prefixe mis en cache :
    #: le modifier invalide le cache. Certains clients (ou transports) preferent
    #: donc un point d'entree unique, stable dans le temps.
    dispatch_only: bool = os.getenv("OSIRIS_DISPATCH_ONLY", "0") in ("1", "true", "True")

    #: Fichiers de configuration optionnels.
    policy_path: Path = field(
        default_factory=lambda: _env_path("OSIRIS_POLICY", Path.home() / ".osiris" / "policy.json")
    )
    pricing_path: Path = field(
        default_factory=lambda: _env_path(
            "OSIRIS_PRICING", Path.home() / ".osiris" / "pricing.json"
        )
    )

    # -- proprietes derivees ------------------------------------------------

    @property
    def db_path(self) -> Path:
        return self.home / "osiris.db"

    @property
    def reports_dir(self) -> Path:
        return self.home / "reports"

    @property
    def python_version(self) -> str:
        return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

    @property
    def venv_python(self) -> str:
        return sys.executable

    def ensure_dirs(self) -> None:
        """Cree les repertoires necessaires (idempotent)."""
        self.home.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def is_path_allowed(self, path: Path) -> bool:
        """Vrai si `path` est sous une racine autorisee."""
        try:
            resolved = path.resolve()
        except OSError:
            return False
        for root in self.allowed_roots:
            try:
                resolved.relative_to(root)
                return True
            except ValueError:
                continue
        return False


settings = Settings()
