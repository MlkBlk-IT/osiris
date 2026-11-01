"""`Tool Compass` — recommandation d'outils minimaux.

Limite honnete : un serveur MCP **ne peut pas masquer** les schemas d'un
autre serveur MCP — le client decide de la liste exposee au modele. Ce que le
Compass fait, en revanche, est real : reduire les **appels** inutiles.

Signalisation :
- categorie d'outil attendue par l'etape courante du plan ;
- outils deja utilisees sans changement d'etat (read-only) ;
- outils bloques par le LoopGuard ;
- outils en echec repete ;
- outils interdits par les invariants.
"""

from __future__ import annotations

from typing import Any

#: Categories d'outils et motifs de nom.
TOOL_KINDS: dict[str, tuple[str, ...]] = {
    "read": ("fs.read", "read", "cat", "view", "get_file", "open"),
    "write": ("fs.write", "write", "edit", "patch", "create", "apply"),
    "exec": ("shell", "exec", "run", "pester", "pytest", "npm", "git"),
    "net": ("fetch", "search", "web", "http", "browse"),
    "vcs": ("git.commit", "git.diff", "git.status", "git.push"),
}

#: Mots-cles d'etape -> categorie d'outil attendue.
STEP_KEYWORDS: dict[str, str] = {
    "lire": "read",
    "read": "read",
    "analys": "read",
    "explor": "read",
    "voir": "read",
    "corrig": "write",
    "fix": "write",
    "edit": "write",
    "modif": "write",
    "impl": "write",
    "test": "exec",
    "pester": "exec",
    "pytest": "exec",
    "verif": "exec",
    "run": "exec",
    "build": "exec",
    "lint": "exec",
    "commit": "vcs",
    "push": "vcs",
    "diff": "vcs",
    "status": "vcs",
    "recherch": "net",
    "fetch": "net",
    "web": "net",
    "consult": "net",
}


def tool_kind(tool: str) -> str:
    """categorie d'un outil, d'apres son nom."""
    name = (tool or "").lower()
    for kind, patterns in TOOL_KINDS.items():
        for pattern in patterns:
            if pattern in name:
                return kind
    return "other"


def expected_kind(step: str) -> str:
    """Categorie attendue pour une etape de plan."""
    text = (step or "").lower()
    for keyword, kind in STEP_KEYWORDS.items():
        if keyword in text:
            return kind
    return "read"


def recommend(
    objective: str,
    current_step: str,
    known_tools: list[str],
    blocked_tools: set[str] | None = None,
    failing_tools: set[str] | None = None,
    forbidden_tools: set[str] | None = None,
    used_tools: list[str] | None = None,
    max_tools: int = 5,
) -> dict[str, Any]:
    """Recommande 3 a 5 outils et signale ceux a eviter.

    Returns:
        {"recommended_tools": [...], "avoid_tools": [...], "reason": str,
         "cache_impact": str}
    """
    blocked = blocked_tools or set()
    failing = failing_tools or set()
    forbidden = forbidden_tools or set()
    used = used_tools or []

    want = expected_kind(current_step)
    known = list(dict.fromkeys(known_tools))
    by_kind: dict[str, list[str]] = {}
    for tool in known:
        by_kind.setdefault(tool_kind(tool), []).append(tool)

    recommended: list[str] = []
    reason_bits: list[str] = []

    for tool in by_kind.get(want, []):
        if tool not in blocked and tool not in failing and tool not in forbidden:
            recommended.append(tool)
    if recommended:
        reason_bits.append(f"etape '{current_step or objective}' -> outils {want}")

    # outils deja proofs utiles (succes, non bloques)
    for tool in used:
        if tool in known and tool not in recommended:
            if tool not in blocked and tool not in failing and tool not in forbidden:
                recommended.append(tool)
    if len(recommended) > max_tools:
        recommended = recommended[:max_tools]

    avoid: list[str] = []
    avoid_reasons: list[str] = []
    for tool in known:
        if tool in forbidden:
            avoid.append(tool)
            avoid_reasons.append(f"{tool}: interdit par invariant")
        elif tool in blocked:
            avoid.append(tool)
            avoid_reasons.append(f"{tool}: bloque par le LoopGuard")
        elif tool in failing:
            avoid.append(tool)
            avoid_reasons.append(f"{tool}: echec repete")

    if not recommended and known:
        # rien de recommendable : on renvoie les outils connus, sans eviter
        recommended = known[:max_tools]
        reason_bits.append("aucune categorie d'outil ne correspond a l'etape")

    if avoid_reasons:
        reason_bits.append("; ".join(avoid_reasons[:3]))

    return {
        "recommended_tools": recommended,
        "avoid_tools": avoid,
        "reason": " ; ".join(reason_bits) or "rien de specifique",
        "cache_impact": "none (la liste d'outils du client reste hors de controle)",
    }
