"""`QueryEngine` — filtrage **cote serveur** des payloads externalises.

Pourquoi ce module existe
-------------------------
Externaliser un payload (le sortir de la fenetre du modele) ne suffit pas :
si on le rappelle en entier, on a juste deplace le cout. Le vrai levier est
de **filtrer avant que le modele ne voie la donnee** — c'est le principe du
"code execution with MCP" (Anthropic : 150k -> 2k tokens, -98,7 %) : la
reduction se fait dans l'environnement d'execution, pas dans le prompt.

Jusqu'ici OSIRIS ne proposait qu'une fenetre de sous-chaine autour de termes
(`refs.excerpt`). C'est trop grossier : pas de regex, pas de plage de lignes,
pas d'agregation, pas d'ancrage symbolique.

Ce module ajoute des operations **cote serveur**, dont le resultat seul
entre dans le contexte :

    grep      lignes qui matchent (regex ou litteral) + numeros de ligne
    count     nombre de lignes qui matchent (meme regex que grep, ~3 tokens)
    range     plage de lignes (bornes inclusives, 1-based)
    head      N premieres lignes
    tail      N dernieres lignes
    outline   ancres symboliques (def/class/function/struct/...) : la liste
              des definitions d'un fichier, sans lire le fichier
    aggregate compteurs : lignes, caracteres, tokens, repartition par prefixe
    jsonl     agregation sur des lignes JSON (compte par cle/valeur)

Invariant : aucune operation ne modifie le ref. Le contenu reste integralement
recoverable ; seule la **selection** est economisee.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from typing import Any

from osiris.core import refs
from osiris.core.tokens import count_tokens

OPS = ("excerpt", "grep", "count", "range", "head", "tail", "outline", "aggregate", "jsonl")

#: Ancres symboliques (approximation lexicale, sans parseur).
_OUTLINE = re.compile(
    r"^\s*(?:"
    r"(?:async\s+)?def\s+\w+|"
    r"class\s+\w+|"
    r"(?:export\s+)?(?:async\s+)?function\s+\w+|"
    r"(?:export\s+)?(?:const|let|var)\s+\w+\s*=\s*(?:async\s*)?\(|"
    r"(?:pub\s+)?(?:struct|enum|trait|impl|interface|type|module|package)\s+\w+|"
    r"@[\w.]+|"
    r"#\s*include\b|"
    r"#\[|"
    r"</?\w+[^>]*>$"
    r")"
)

#: Prefixes de definitions pour l'outline multi-langages.
_SECTION = re.compile(
    r"^\s*(?:#{1,6}\s+\S|//\s*(?:TODO|NOTE|FIXME|class|func|def|type)\b|/\*\*?\s*@?\w+)"
)


def _lines(content: str) -> list[str]:
    return content.splitlines()


def _clip(text: str, budget_tokens: int) -> tuple[str, bool]:
    """Tronque un texte au budget, en caracteres (estimation 4 car/1 token)."""
    if not budget_tokens or budget_tokens <= 0:
        return text, False
    limit = budget_tokens * 4
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def _result(
    ref: str,
    op: str,
    text: str,
    *,
    total_lines: int,
    matches: int = 0,
    extra: dict[str, Any] | None = None,
    budget_tokens: int = 0,
) -> dict[str, Any]:
    clipped, truncated = _clip(text, budget_tokens)
    payload: dict[str, Any] = {
        "found": True,
        "ref": ref,
        "op": op,
        "text": clipped,
        "tokens": count_tokens(clipped),
        "total_lines": total_lines,
        "matches": matches,
        "truncated": truncated,
    }
    if extra:
        payload.update(extra)
    return payload


def run(
    ref: str,
    op: str = "excerpt",
    query: str = "",
    start: int = 0,
    end: int = 0,
    budget_tokens: int = 800,
    limit: int = 40,
) -> dict[str, Any]:
    """Execute une operation de filtrage sur un ref stocke.

    `op`   : une de `OPS`.
    `query`: motif (litteral ou regex selon l'operation), ou cle pour `jsonl`.
    `start`/`end` : bornes de lignes (1-based, inclusives) pour `range`.
    `limit` : nombre maximal de lignes renvoyees.
    """
    op = op if op in OPS else "excerpt"
    entry = refs.get(ref)
    if entry is None:
        return {"found": False, "ref": ref, "note": "ref inconnue"}
    content = entry["content"]
    rows = _lines(content)
    total = len(rows)

    if op == "excerpt":
        found = refs.excerpt(ref, query=query, budget_tokens=budget_tokens)
        if not found.get("found"):
            return {"found": False, "ref": ref}
        return {
            "found": True,
            "ref": ref,
            "op": op,
            "text": found["excerpt"],
            "offset": found["offset"],
            "complete": found["complete"],
            "tokens": found["tokens"],
            "total_lines": total,
            "matches": found.get("matches", 0),
            "truncated": not found.get("complete", False),
            "verified": found["verified"],
        }

    if op == "grep":
        pattern = query or ""
        if not pattern:
            return {"found": True, "ref": ref, "op": op, "text": "", "note": "query vide"}
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error:
            regex = re.compile(re.escape(pattern), re.IGNORECASE)
        hits = [
            f"{idx}: {line.rstrip()}"
            for idx, line in enumerate(rows, start=1)
            if regex.search(line)
        ]
        text = "\n".join(hits[: max(1, limit)])
        return _result(
            ref,
            op,
            text,
            total_lines=total,
            matches=len(hits),
            extra={"truncated_lines": max(0, len(hits) - limit)},
            budget_tokens=budget_tokens,
        )

    if op == "count":
        pattern = query or ""
        if not pattern:
            return {"found": True, "ref": ref, "op": op, "text": "", "note": "query vide"}
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error:
            regex = re.compile(re.escape(pattern), re.IGNORECASE)
        n = sum(1 for line in rows if regex.search(line))
        return _result(ref, op, str(n), total_lines=total, matches=n)

    if op == "range":
        first = max(1, int(start or 1))
        last = int(end or 0) or first + max(0, int(limit or 40)) - 1
        last = min(last, total)
        selected = rows[first - 1 : last]
        text = "\n".join(f"{first + i}: {line.rstrip()}" for i, line in enumerate(selected))
        return _result(
            ref,
            op,
            text,
            total_lines=total,
            matches=len(selected),
            extra={"start": first, "end": last},
            budget_tokens=budget_tokens,
        )

    if op in ("head", "tail"):
        n = max(1, int(limit or 40))
        chosen = rows[:n] if op == "head" else rows[-n:]
        offset = 0 if op == "head" else max(0, total - n)
        text = "\n".join(
            f"{offset + i + 1}: {line.rstrip()}" for i, line in enumerate(chosen)
        )
        return _result(ref, op, text, total_lines=total, matches=len(chosen))

    if op == "outline":
        anchors: list[str] = []
        for idx, line in enumerate(rows, start=1):
            if _OUTLINE.match(line) or _SECTION.match(line):
                anchors.append(f"{idx}: {line.rstrip()}")
        text = "\n".join(anchors[: max(1, limit)])
        return _result(
            ref,
            op,
            text,
            total_lines=total,
            matches=len(anchors),
            extra={"truncated_lines": max(0, len(anchors) - limit)},
            budget_tokens=budget_tokens,
        )

    if op == "aggregate":
        counter = Counter()
        for line in rows:
            stripped = line.strip()
            if not stripped:
                continue
            head = stripped.split()[0]
            counter[head[:24]] += 1
        top = counter.most_common(20)
        summary = [
            f"lignes: {total}",
            f"caracteres: {len(content)}",
            f"tokens: {entry['tokens']}",
            f"lignes non vides: {sum(counter.values())}",
            "prefixes les plus frequents:",
        ]
        summary += [f"  {token} x{count}" for token, count in top]
        return _result(
            ref,
            op,
            "\n".join(summary),
            total_lines=total,
            matches=len(top),
            extra={"stats": dict(top)},
        )

    if op == "jsonl":
        key = query or ""
        counter: Counter[str] = Counter()
        parsed = 0
        errors = 0
        for line in rows:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except ValueError:
                errors += 1
                continue
            parsed += 1
            if not isinstance(obj, dict):
                continue
            if key:
                value = obj.get(key)
                if value is None:
                    continue
                counter[str(value)[:48]] += 1
            else:
                counter[",".join(sorted(obj.keys()))[:48]] += 1
        top = counter.most_common(20)
        summary = [
            f"lignes json: {parsed}",
            f"lignes invalides: {errors}",
            (f"cle '{key}':") if key else "schemas:",
        ]
        summary += [f"  {value} x{count}" for value, count in top]
        return _result(
            ref,
            op,
            "\n".join(summary),
            total_lines=total,
            matches=len(top),
            extra={"stats": dict(top), "parsed": parsed, "invalid": errors},
        )

    return {"found": False, "ref": ref, "note": f"operation inconnue: {op}"}
