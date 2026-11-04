# Publier OSIRIS — checklist complète

Repo public : <https://github.com/MlkBlk-IT/osiris> · PyPI : `mcp-osiris` ·
npm : `osiris-mcp` · Registre MCP : `io.github.MlkBlk-IT/osiris`

> Les jetons (PyPI `pypi-…`, npm `npm_…`) ne doivent **jamais** être écrits dans
> un fichier versionné ni dans un log. Passe-les via l'environnement ou le
> prompt interactif.

---

## 0. Pré-requis (déjà vérifiés)

| Outil | Présent |
|---|---|
| `uv` | ✔ `C:\Users\Tech\AppData\Local\Programs\Python\Python312\Scripts\uv.exe` |
| `npm` | ✔ (Node 27 alpha — npm 12 signale un avertissement de version) |
| `twine` | ✔ (Python système) |
| `git` | ✔ remote `https://github.com/MlkBlk-IT/osiris.git` |

## 1. Build + validation (local)

```powershell
Set-Location 'D:\MCP-Osiris'

# tests + lint doivent rester verts
& '.\.venv\Scripts\python.exe' -m pytest -q --no-header --tb=line
& '.\.venv\Scripts\python.exe' -m ruff check src tests bench scripts

# build sdist + wheel (hatchling, isole automatiquement)
uv build

# métadonnées PyPI valides
twine check dist\*

# contenu du wheel : le dashboard et le bench doivent etre presents
& '.\.venv\Scripts\python.exe' -c "import zipfile,glob;z=zipfile.ZipFile(glob.glob('dist/*.whl')[0]);print([n for n in z.namelist() if 'dashboard' in n or 'bench' in n])"
```

## 2. Test d'installation isolée (avant publication)

```powershell
uv venv "$env:TEMP\osiris-install-test"
uv pip install --python "$env:TEMP\osiris-install-test\Scripts\python.exe" dist\mcp_osiris-0.1.1-py3-none-any.whl

# CLI
& "$env:TEMP\osiris-install-test\Scripts\python.exe" -m osiris health
& "$env:TEMP\osiris-install-test\Scripts\osiris.exe" --help

# dashboard installe (assets web inclus dans le wheel)
& "$env:TEMP\osiris-install-test\Scripts\osiris-dashboard.exe" --port 8780
```

## 3. Publication PyPI

```powershell
# 1) recuperer un jeton : https://pypi.org/manage/account/token/ (scope "PyPI")
$env:TWINE_USERNAME = "__token__"
$env:TWINE_PASSWORD = "<JETON_PYPI>"      # jamais dans un fichier

twine upload dist\*
```

Vérification : <https://pypi.org/project/mcp-osiris/>

## 4. Publication npm

```powershell
Set-Location 'D:\MCP-Osiris\npm'

# compte : npm whoami   (doit etre en conflit avec un 2FA : npm token create)
npm publish --access public --otp <CODE_2FA>

npm view osiris-mcp          # verification
npx -y osiris-mcp            # test de lancement
```

## 5. Soumission au registre MCP officiel

Le paquet npm doit etre publie **avant** la soumission (le registre verifie
l'identifiant du paquet).

```powershell
# CLI officielle : https://github.com/modelcontextprotocol/registry
uvx mcp-publisher publish    # lit server.json, demande un token de session
```

Puis : <https://registry.modelcontextprotocol.io/>

## 6. Glama

<https://glama.ai/mcp/servers> → formulaire **Submit a server** :

| Champ | Valeur |
|---|---|
| Name | OSIRIS |
| Description | context engine cache-aware pour agents IA (filtrage serveur, ledger honnete) |
| GitHub repo | <https://github.com/MlkBlk-IT/osiris> |
| NPM package | `osiris-mcp` |
| Type | stdio |
| License | MIT |

## 7. Smithery

Le dépôt contient `smithery.yaml`. Après publication npm :

```powershell
npx @smithery/cli publish
```

Puis : <https://smithery.ai/server/@mlkblk/osiris>

## 8. Listes communautaires

- `punkpeye/awesome-mcp-servers` — PR d'une ligne dans la section *Knowledge & Memory*.
- `wong2/awesome-mcp-servers` (moved), `appcypher/awesome-mcp-servers`.
- `modelcontextprotocol/registry` — via la CLI (etape 5).

## 9. Page GitHub

- `LICENSE` present → detection MIT automatique ✔
- `CHANGELOG.md` present ✔
- Section **Installation** du README a jour ✔
- Badge PyPI / npm a ajouter dans le README (URL ci-dessous) :
  - `https://img.shields.io/pypi/v/mcp-osiris`
  - `https://img.shields.io/npm/v/osiris-mcp`

## 10. Ordre de publication (important)

1. `uv build` + `twine check` + test d'installation isole
2. **PyPI** (le lanceur npm utilise `uvx --from mcp-osiris`)
3. **npm** (`osiris-mcp`)
4. Registre MCP officiel (exige le paquet npm publie)
5. Glama + Smithery + awesome-mcp-servers

---

### En cas de blocage

- `twine upload` : `403` → le nom `mcp-osiris` est deja pris ou le jeton est invalide.
- `npm publish` : `E403` → 2FA ( `--otp` ) ou nom de paquet deja pris.
- Registre MCP : `server.json` invalide → schema <https://static.modelcontextprotocol.io/schemas/2025-09-29/server.schema.json>