"""Verifie que le dashboard installe demarre et repond.

S'execute avec l'interpreteur du venv qui a recu le wheel :

    python scripts/check_dashboard_serve.py

Le dashboard est lance dans un processus, `/api/health` est interroge, puis le
processus est arrete. Un dashboard qui ne demarre pas (ressource manquante,
import casse, port occupe) est detecte ici et non chez l'utilisateur.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _dashboard_command() -> list[str]:
    """La commande `osiris-dashboard` installee, ou le module en secours."""
    scripts = pathlib_scripts()
    if scripts is not None:
        return scripts
    return [sys.executable, "-m", "osiris.dashboard.server"]


def pathlib_scripts() -> list[str] | None:
    import pathlib

    exe = "osiris-dashboard.exe" if os.name == "nt" else "osiris-dashboard"
    candidates = [
        pathlib.Path(sys.executable).parent / exe,
        pathlib.Path(sys.prefix) / "bin" / exe,
        pathlib.Path(sys.prefix) / "Scripts" / exe,
    ]
    for candidate in candidates:
        if candidate.is_file():
            return [str(candidate)]
    return None


def main() -> int:
    port = _free_port()
    home = tempfile.mkdtemp(prefix="osiris-wheel-dash-")
    env = dict(os.environ)
    env["OSIRIS_HOME"] = home
    env["OSIRIS_DATA_DIR"] = tempfile.mkdtemp(prefix="osiris-wheel-dash-data-")

    command = _dashboard_command() + ["--port", str(port)]
    print("lancement :", " ".join(command))
    process = subprocess.Popen(
        command,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    payload = None
    try:
        for _ in range(45):
            if process.poll() is not None:
                break
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/api/health", timeout=3
                ) as response:
                    payload = response.read().decode("utf-8", "replace")
                    break
            except (urllib.error.URLError, OSError):
                time.sleep(1)

        if payload is None:
            process.terminate()
            output = ""
            if process.stdout is not None:
                output = process.stdout.read()[-2000:]
            print("ECHEC : le dashboard installe n'a pas repondu sur /api/health")
            print(output)
            return 1

        data = json.loads(payload)
        print("OK /api/health :", json.dumps(data)[:300])
    finally:
        process.terminate()
        try:
            process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.kill()

    print("OK : le dashboard installe demarre et repond")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
