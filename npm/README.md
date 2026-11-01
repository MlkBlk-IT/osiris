# osiris-mcp

> OSIRIS — context engine cache-aware pour agents IA. Serveur MCP local et provider-agnostic.

Ce paquet npm est le **lanceur stdio** du serveur MCP OSIRIS. Le serveur lui-même
est distribué sur PyPI (`mcp-osiris`).

## Installation

```bash
npx -y osiris-mcp
```

Pour l'installer globalement :

```bash
npm install -g osiris-mcp
```

## Runtime Python

Le lanceur cherche un runtime dans cet ordre :

1. `OSIRIS_PYTHON` (chemin vers l'interpréteur, prioritaire)
2. `uvx` / `uv` → `uvx --from mcp-osiris mcp-osiris` (aucune installation requise)
3. `python3` → `python3 -m osiris`
4. `python` → `python -m osiris`

Si aucun runtime n'est trouvé, installez [Python 3.12+](https://www.python.org/downloads/)
ou [uv](https://docs.astral.sh/uv/).

## Configuration MCP

```json
{
  "mcpServers": {
    "osiris": {
      "command": "npx",
      "args": ["-y", "osiris-mcp"],
      "env": {
        "OSIRIS_HOME": "~/.osiris",
        "OSIRIS_ROOTS": "/chemin/du/projet"
      }
    }
  }
}
```

| Variable | Défaut | Rôle |
|---|---|---|
| `OSIRIS_HOME` | `~/.osiris` | Base SQLite, rapports, caches |
| `OSIRIS_ROOTS` | *(vide)* | Racines autorisées pour la lecture de fichiers (séparées par `;`) |
| `OSIRIS_CACHE_TTL_S` | `300` | TTL du cache (secondes) |
| `OSIRIS_PRUNE_THRESHOLD_TOKENS` | `40000` | Seuil de prune |
| `OSIRIS_DISPATCH_ONLY` | `0` | `1` → n'expose que l'outil `osiris.call` |

## Ce que ça fait

- **Filtrage serveur** : le gros contenu ne rentre jamais dans le contexte de
  l'agent, seule la slice demandée estinjectée (`grep`, `range`, `outline`…).
- **Ledger honnête** : `tokens_moved` (déplacé) et `tokens_saved` (prouvé) sont
  comptés séparément, invariant `tokens_saved ≤ tokens_in + tokens_moved`.
- **Décisions append-only** avec détection de réécriture.
- **Garde-fous** : anti-boucle, budget par phase, invariants.

## Documentation complète

<https://github.com/MlkBlk-IT/osiris>

## Licence

MIT © 2026 Malik Belkacemi (MLKBLK-IT)
