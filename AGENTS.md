# AGENTS.md — OSIRIS

## ⛔ Règle de périmètre — PRIORITÉ ABSOLUE

**Ce projet est 100% AUTONOME. Ne jamais toucher aux autres projets de l'utilisateur.**

Interdits absolus, sans exception ni autorisation implicite :

- ❌ Modifier, refactorer, restructurer, migrer, renommer ou supprimer un autre projet
- ❌ `pip install` d'un autre projet de l'utilisateur (ex. `loom-mcp`) ou dépendance par chemin
- ❌ `import` d'un module d'un autre projet
- ❌ Référencer un chemin absolu vers un autre dossier de projet
- ❌ Partager une base de données, un schéma ou un fichier avec un autre projet
- ❌ Proposer ou appliquer une « absorption », « fusion » ou « migration » d'un autre projet
- ❌ Modifier la configuration MCP globale (`C:\Users\Tech\.minimax\mcp.json`) sans accord explicite

Projets existants protégés : `D:\Loom`, `D:\AI-Stack` (SuperLocalMemory),
`D:\CacheForge`, `D:\IcyCache`, `D:\MCP`, `D:\MCP_TEST` — et tout autre dossier
du disque hors de `D:\MCP-Osiris`.

**Zone d'écriture autorisée : `D:\MCP-Osiris` uniquement.**

L'inspection **en lecture seule** d'un projet existant doit être **demandée**,
jamais présumée. En cas de doute, demander avant de lire.

---

## Ce qui est autonome ici

Tout le code est écrit from scratch dans `src/osiris/`. Les seules dépendances
autorisées sont des **paquets PyPI publics** : `mcp`, `fastmcp`, `pydantic`,
`httpx`, `PyYAML`, `rich`, `tiktoken`.

| Besoin | Implémentation locale |
|---|---|
| Comptage de tokens | `core/tokens.py` (tiktoken, repli heuristique) |
| Stockage des refs | `core/refs.py` (SQLite local, content-addressed) |
| Masquage des secrets | `core/redact.py` (avant le hash) |
| Lecture de fichiers | `core/fileops.py` (sandbox, racines autorisées) |
| Mémoire typée | `core/memory.py` + `core/task_state.py` |
| Journal / checkpoints | `core/events.py` |
| Coût / économies | `core/ledger.py` |
| Cache / drift | `core/prefix.py` |
| Filtrage serveur des payloads | `core/query.py` (grep, range, outline, aggregate, jsonl) |
| Compaction (trim/compact/clear) | `core/compaction.py` |
| Pression contexte | `core/pressure.py` |
| Anti-boucle | `core/loopguard.py` |
| Invariants | `core/invariants.py` |
| Handoff | `core/handoff.py` |

---

## Invariants du produit (à ne pas casser)

1. **Le prune déplace, il ne supprime jamais.** Il n'existe aucun chemin de code
   qui supprime un payload. C'est ce qui rend la preuve LOSSLESS possible.
2. **Les décisions et les contraintes sont append-only, et leur réécriture est
   détectée.** Elles vivent dans la queue (`tail_hash`), pas dans le head :
   les ajouter ne doit **jamais** déclencher un drift critique (le prefixe
   cache est intact). Réécrire un élément épinglé est détecté par comparaison
   des collections elles-mêmes (`core/prefix.py::rewritten_pins`) et signalé
   comme rupture **sémantique** (`verdict: critical`, `cause: pinned_rewrite`,
   `semantic_break: true`). Le cache n'est pas invalidé, l'état de la tâche si.
   *Avant correction, les contraintes étaient dans le head et la réécriture
   d'une décision n'était pas détectée du tout : l'invariant n°2 était
   documentaire, pas implémenté.*
3. **L'agent ne calcule jamais de hash.** Il transmet les arguments bruts ;
   OSIRIS canonicalise et digeste.
4. **Les réponses des outils restent courtes.** Garde-fou dans
   `tests/test_mcp_tools.py` : `plan` < 260 tokens, `observe` < 110,
   `checkpoint` < 110. OSIRIS ne doit pas devenir un consommateur de contexte.
5. **Le surcoût d'OSIRIS est mesuré** (ledger kind `overhead`) et le gain net
   est exposé dans le rapport. Si le net est négatif, `osiris.plan` prévient
   l'agent.
6. **Aucun prix provider n'est codé en dur** : la table de prix vient de
   `~/.osiris/pricing.json`.
7. **Le TTL du cache est un paramètre**, pas une dépendance provider. Le TTL
   est **déterministe** : `P(cache_mort)` est un seuil (0 avant, 1 après), pas
   une rampe `Δt/TTL`.
8. **Déplacé ≠ gagné.** `tokens_moved` = payload déplacé vers un ref ;
   `tokens_saved` = tokens dont la sortie du contexte est **prouvée** par
   l'accusé de réception de l'agent (`observe(kind="dropped")`). Invariant
   garanti par un test : `tokens_saved ≤ tokens_in`.
9. **Le tableau `tools` exposé ne change pas** (6 outils, ou 1 en mode
   `OSIRIS_DISPATCH_ONLY=1`) : il fait partie du prefixe mis en cache.
10. **Un serveur MCP ne peut pas compacter la fenêtre de l'hôte** : OSIRIS
    fournit les artefacts (`compact`/`trim`/`clear`, resources), la réduction
    reste une décision de l'hôte.

---

## Environnement

- Venv : `D:\MCP-Osiris\.venv` (CPython 3.12.10, via `uv`)
- Interpréteur : `.venv\Scripts\python.exe`
- Ne jamais installer dans le Python système.
- `OSIRIS_HOME` par défaut : `~/.osiris`. Pour un essai isolé :
  `OSIRIS_HOME=D:\MCP-Osiris\data\home`.

## Commandes

```powershell
.venv\Scripts\python.exe -m pytest tests -q         # 77 tests
.venv\Scripts\python.exe -m ruff check src tests bench scripts
.venv\Scripts\python.exe -m osiris health
.venv\Scripts\python.exe scripts\smoke_stdio.py     # E2E stdio
.venv\Scripts\python.exe bench\run_bench.py         # benchmark + rentabilité
```

## Cycle de développement

1. Modifier dans `src/osiris/`.
2. `pytest` doit rester vert (77 tests) et `ruff check` propre.
3. Si le comportement des outils change : mettre à jour `README.md` (section
   correspondante) et `tests/test_mcp_tools.py`.
4. Ne jamais casser la preuve LOSSLESS (`tests/test_audit.py`).
5. Ne jamais publier un chiffre qui ne sort pas de `bench/run_bench.py` : le
   README §12 est regénéré depuis la sortie réelle, pas recopié.
