# STATUS — Intégration Hermes × Osiris

Dernière mise à jour : 2026-11-01

## État

Osiris MCP tourne comme **task engine continu** de la session Hermes.

- Dossier : `D:\mcp-osiris`
- Base : `D:\MCP-Osiris\data\home\osiris.db` (unifiée — MCP + dashboard lisent la même DB)
- Serveur MCP déclaré dans Hermes (`mcp_servers`)

## Règle dure (Malik)

> Osiris + IcyLoom actifs **en tout temps**. Pas optionnel.

Chaque tour :
1. Avant une tâche non triviale → `osiris_plan` (start/resume)
2. Payload > 100 tokens → `osiris_observe` (externalise en `mem://sha256:...`)
3. Relire → `osiris_recall` (grep/range/excerpt) avec budget
4. Jalons → `osiris_checkpoint`

## Modes d'engagement (auto)

| Niveau | Payload | Comportement |
|---|---|---|
| bystander | < 600 tok | opt-out |
| light | 600–800 tok | manifeste minimal |
| standard | 800–8000 tok | externalisation active |
| full | ≥ 8000 tok | compaction + KV routing |

## Outils

- `osiris_plan` : start / update / resume / status
- `osiris_observe` : tool_result, payload, file, decision, constraint, lesson, test_result, failure, note, contract
- `osiris_recall` : grep / range / outline / excerpt
- `osiris_checkpoint` : snapshot / final / compact / trim / clear

## Tâches actives

- `t_508935610764` — Finaliser intégration IcyLoom+Osiris (4/4 étapes complétées)

## Documentation Dashboards

- Guide & Quickstart : `D:\mcp-osiris\DASHBOARDS-GUIDE.md` (et `D:\Icy-Loom\DASHBOARDS-GUIDE.md`)
- Dashboard Osiris : `http://127.0.0.1:8770/` (auto-refresh 2s, `app.js?v=202611010212`)
- Dashboard IcyLoom : `http://127.0.0.1:8153/` (auto-refresh 2s)

## Vérification

- [x] `osiris_plan` appelé
- [x] Payloads > 100 tok → `osiris_observe`
- [x] Lecture gros contexte via `osiris_recall`
- [x] `osiris_checkpoint` aux jalons
