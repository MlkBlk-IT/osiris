"""Verifie le wheel installe : ressources, commandes et benchmark.

S'execute avec l'interpreteur du venv qui a recu le wheel :

    python scripts/check_wheel_install.py

Sortie non nulle si l'artefact distribue est incomplet ou casse. Ce script
est le meme que celui execute par le job `wheel` de la CI : la verification
de l'artefact vit donc dans le depot, pas dans le workflow.
"""

from __future__ import annotations

import importlib.util
import os
import pathlib
import sys
import tempfile


def _fail(message: str) -> None:
    print("ECHEC :", message)
    raise SystemExit(1)


def check_resources() -> pathlib.Path:
    """Toutes les ressources force-includees doivent etre dans le paquet."""
    import osiris

    root = pathlib.Path(osiris.__file__).parent
    required = [
        "dashboard/server.py",
        "dashboard/web/index.html",
        "dashboard/web/app.js",
        "dashboard/web/styles.css",
        "dashboard/web/liquid.css",
        "dashboard/web/live.js",
        "dashboard/web/logo.svg",
        "bench/run_bench.py",
        "bench/fixtures/src/Profile.psm1",
        "bench/fixtures/tests/Profile.Tests.ps1",
    ]
    missing = [r for r in required if not (root / r).is_file()]
    if missing:
        _fail(f"ressources manquantes dans le wheel : {', '.join(missing)}")
    print(f"OK ressources : {len(required)} fichiers dans {root}")
    return root


def check_dashboard_import() -> None:
    """Le dashboard doit etre importable depuis le paquet installe."""
    spec = importlib.util.find_spec("osiris.dashboard.server")
    if spec is None:
        _fail("osiris.dashboard.server introuvable")
    print("OK import dashboard :", spec.origin)


def check_exposure_policy() -> None:
    """Le dashboard installe doit refuser une exposition reseau non protegee."""
    from osiris.dashboard import server as dash

    try:
        dash.check_exposure("0.0.0.0", False, "")
    except SystemExit:
        print("OK exposition reseau refusee sans --allow-remote")
    else:
        _fail("une exposition reseau sans --allow-remote a ete acceptee")

    try:
        dash.check_exposure("0.0.0.0", True, "")
    except SystemExit:
        print("OK --allow-remote refuse sans jeton")
    else:
        _fail("--allow-remote sans jeton a ete accepte")


def check_version(expected: str | None) -> None:
    import osiris

    if expected is None:
        print("OK version installee :", osiris.__version__)
        return
    if osiris.__version__ != expected:
        _fail(f"version installee {osiris.__version__}, attendue {expected}")
    print("OK version installee :", osiris.__version__)


def check_bench(root: pathlib.Path) -> None:
    """Le bench inclus doit tourner et passer sa gate de rentabilite."""
    bench = root / "bench" / "run_bench.py"
    namespace = {"__file__": str(bench), "__name__": "bench_installed"}
    exec(compile(bench.read_text(encoding="utf-8"), str(bench), "exec"), namespace)
    result = namespace["run"]()
    if not result["gate"]["passed"]:
        _fail(f"gate du bench installe en echec : {result['gate']}")
    print("OK bench installe : gate PASS")


def main() -> int:
    # La version attendue est deduite des manifestes du depot : le controle
    # ne doit pas dependre d'une constante a mettre a jour a la main.
    expected: str | None = sys.argv[1] if len(sys.argv) > 1 else None
    if expected is None:
        pyproject = pathlib.Path(__file__).resolve().parents[1] / "pyproject.toml"
        if pyproject.is_file():
            import tomllib

            expected = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]

    # Isole la base AVANT tout import de `osiris.config` (les settings sont
    # figes a l'import) : le test ne doit toucher ni la base ni les rapports
    # de l'utilisateur.
    os.environ["OSIRIS_HOME"] = tempfile.mkdtemp(prefix="osiris-wheel-")
    os.environ["OSIRIS_DATA_DIR"] = tempfile.mkdtemp(prefix="osiris-wheel-data-")

    root = check_resources()
    check_dashboard_import()
    check_exposure_policy()
    check_version(expected)
    check_bench(root)
    print("OK : le wheel installe est complet et fonctionnel")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
