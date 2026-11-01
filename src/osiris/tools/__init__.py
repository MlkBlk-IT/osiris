"""Point d'extension pour les outils utilisateur.

Les 6 outils noyau d'OSIRIS (`osiris.plan`, `osiris.precheck`,
`osiris.observe`, `osiris.recall`, `osiris.checkpoint`, `osiris.handoff`)
sont definis dans `osiris.server` — ils sont la surface publique stable du
produit et leur schema est verifie par les tests.

Ce package existe pour **ajouter tes propres outils** sans modifier le
noyau. Chaque module y expose une fonction `register(mcp)` qui recoit
l'instance FastMCP et y depose ses outils :

    # src/osiris/tools/mon_outil.py
    from fastmcp import FastMCP


    def register(mcp: FastMCP) -> None:
        @mcp.tool(name="mon.outil")
        def mon_outil(chemin: str) -> str:
            \"\"\"Ce que fait l'outil.\"\"\"
            return "..."


Puis, dans `osiris/server.py` :

    from osiris.tools import mon_outil
    ...
    mon_outil.register(mcp)

Regles :
- les descriptions doivent etre **courtes** : un schema coute des tokens a
  chaque tour, et OSIRIS s'auto-limite volontairement ;
- les outils utilisateur ne doivent pas **supprimer** d'information : ils
  externalisent via `osiris.core.refs` s'ils ont besoin de garder un payload ;
- ils ne doivent pas modifier la base OSIRIS en dehors des API `core.*`.
"""

from __future__ import annotations

__all__: list[str] = []
