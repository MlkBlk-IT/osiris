"""Met a jour le profil GitHub MlkBlk-IT/MlkBlk-IT apres une release.

Met a jour la ligne "What's new", le tableau "By the numbers" et le badge
tests, sans toucher au bloc `<!-- releases:start/end -->` (genere par le
workflow "Update releases").

    python scripts/update_profile.py --project osiris --version 0.1.2 \
        --date 2026-11-06 --summary "..." --url https://... --tests 146
"""

from __future__ import annotations

import argparse
import base64
import json
import pathlib
import subprocess
import sys

PROFILE_REPO = "MlkBlk-IT/MlkBlk-IT"
PROFILE_README = "README.md"
PROFILE_BRANCH = "main"


def _gh(*args: str) -> str:
    result = subprocess.run(
        ["gh", *args], capture_output=True, text=True, encoding="utf-8", check=True
    )
    return result.stdout


def _get_readme() -> tuple[str, str]:
    raw = _gh("api", f"repos/{PROFILE_REPO}/contents/{PROFILE_README}")
    payload = json.loads(raw)
    text = base64.b64decode(payload["content"]).decode("utf-8")
    return text, payload["sha"]


def _put_readme(text: str, sha: str, message: str) -> None:
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    _gh(
        "api",
        "--method",
        "PUT",
        f"repos/{PROFILE_REPO}/contents/{PROFILE_README}",
        "-f",
        f"message={message}",
        "-f",
        f"content={encoded}",
        "-f",
        f"sha={sha}",
        "-f",
        f"branch={PROFILE_BRANCH}",
    )


def add_whats_new(text: str, date: str, project: str, version: str, summary: str, url: str) -> str:
    """Insere la ligne de release juste apres l'entete du tableau."""
    marker = "|---|---|---|\n"
    if marker not in text:
        raise SystemExit("tableau 'What's new' introuvable")
    row = (
        f"| **{date}** | **[Osiris](https://github.com/MlkBlk-IT/osiris) {version}** | "
        f"{summary} [Release]({url}) |\n"
    )
    return text.replace(marker, marker + row, 1)


def update_osiris_figures(text: str, tests: int) -> str:
    """Met a jour le nombre de tests d'OSIRIS dans le paragraphe 'By the numbers'.

    Le badge `tests-<N>` et la colonne du tableau renvoient a ICYLOOM
    (251 tests collectes) : ils ne doivent PAS etre touches par une release
    OSIRIS. Seul le paragraphe de texte mentionne Osiris.
    """
    import re

    pattern = re.compile(r"(Osiris: \*\*\+[^*]+\*\* net prompt savings at [^*]+, )([^.]*?)(\.)")
    return pattern.sub(lambda m: f"{m.group(1)}{m.group(2)} — {tests} tests{m.group(3)}", text, count=1)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--tests", type=int, required=True)
    parser.add_argument("--commit", default="")
    args = parser.parse_args()

    text, sha = _get_readme()
    updated = add_whats_new(text, args.date, args.project, args.version, args.summary, args.url)
    updated = update_osiris_figures(updated, args.tests)

    if updated == text:
        print("profil inchange")
        return 0

    _put_readme(
        updated,
        sha,
        f"docs: profile update — {args.project} {args.version} ({args.tests} tests)",
    )
    print(f"profil mis a jour : {args.project} {args.version}, badge tests-{args.tests}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
