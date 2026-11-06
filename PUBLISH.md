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
uv pip install --python "$env:TEMP\osiris-install-test\Scripts\python.exe" dist\mcp_osiris-0.1.2-py3-none-any.whl

# CLI
& "$env:TEMP\osiris-install-test\Scripts\python.exe" -m osiris health
& "$env:TEMP\osiris-install-test\Scripts\osiris.exe" --help

# verification complete de l'artefact installe (ressources + gate du bench)
& "$env:TEMP\osiris-install-test\Scripts\python.exe" scripts\check_wheel_install.py

# dashboard installe (assets web inclus dans le wheel)
& "$env:TEMP\osiris-install-test\Scripts\osiris-dashboard.exe" --port 8780
```

## 3. Publication PyPI

### 3a. Via la CI (Trusted Publishing — recommande)

Le job `pypi` du workflow utilise l'OIDC : aucun jeton a stocker.

Prerequis (une seule fois, dans le navigateur) :
<https://pypi.org/manage/project/mcp-osiris/settings/publishing/>

| Champ | Valeur |
|---|---|
| Provider | GitHub Actions |
| Organization / user | `MlkBlk-IT` |
| Repository | `osiris` |
| Workflow filename | `publish.yml` |
| Environment name | `pypi` |

> L'environnement GitHub `pypi` existe deja sur le repo. Sans cette
> declaration cote PyPI, la publication echoue avec
> `invalid-publisher: valid token, but no corresponding publisher`.

### 3b. Manuelle (jeton API)

```powershell
# 1) recuperer un jeton : https://pypi.org/manage/account/token/ (scope "PyPI")
$env:TWINE_USERNAME = "__token__"
$env:TWINE_PASSWORD = "<JETON_PYPI>"      # jamais dans un fichier

twine upload dist\*
```

Vérification : <https://pypi.org/project/mcp-osiris/>

## 4. Publication npm

### 4a. Via la CI (Trusted Publishing — recommande)

Le workflow `.github/workflows/publish.yml` publie automatiquement a la sortie
d'une GitHub Release. **Aucun secret npm n'est necessaire** : l'authentification
repose sur l'echange OIDC (trusted publishing).

Prerequis (une seule fois, dans le navigateur) :
<https://www.npmjs.com/package/osiris-mcp/settings/access>

| Champ | Valeur |
|---|---|
| Provider | GitHub Actions |
| Organization / user | `MlkBlk-IT` |
| Repository | `osiris` |
| Workflow filename | `publish.yml` |
| Environment name | *(vide)* |

> **Pourquoi le workflow echouait avec `E404`.** `actions/setup-node` ecrit
> `//registry.npmjs.org/:_authToken=${NODE_AUTH_TOKEN}` dans le `.npmrc` des
> que `registry-url` est renseigne. Sans secret `NPM_TOKEN`, cette ligne
> s'expande en token **vide** : npm croit avoir des credentials, **saute
> l'echange OIDC**, et fait un `PUT` anonyme -> `404 Not Found`.
> Le workflow retire donc `registry-url`, pinne `npm@11` (le trusted
> publishing exige npm >= 11.5.1) et **verifie l'echange OIDC avant de
> publier** : si le Trusted Publisher manque, l'erreur le dit explicitement
> au lieu d'afficher un 404 trompeur.

Le workflow verifie aussi que la version du tag correspond a `pyproject.toml`
et a `npm/package.json`, et que la version n'est pas deja publiee.

Rejouer une publication sans nouvelle release :
<https://github.com/MlkBlk-IT/osiris/actions/workflows/publish.yml> -> *Run
workflow* (cocher `dry_run` pour verifier sans publier).

### 4b. Manuelle (depuis la machine)

```powershell
Set-Location 'D:\MCP-Osiris\npm'

npm whoami                                   # doit afficher mlkblkit
npm publish --access public --otp <CODE_2FA>

npm view osiris-mcp                         # verification
npx -y osiris-mcp                           # test de lancement
```

> Le token npm local est actuellement **expire** (`npm whoami` -> `401`) :
> regenerer un token sur <https://www.npmjs.com/settings/tokens> (type
> *Automation*) avant d'utiliser cette voie.

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
- `twine upload` : `invalid-publisher` → le publisher Trusted Publishing PyPI
  n'est pas declare (voir 3a). La declaration se fait dans le navigateur.
- `npm publish` : `E404` → le Trusted Publisher npm ne correspond pas (voir 4a :
  repo / workflow / environment), ou un token npm vide est present dans le
  `.npmrc` et fait sauter l'echange OIDC.
- `npm publish` : `E409 Cannot publish over previously staged version` → la
  version est deja occupee par un run precedent (mode *staged* de npm 12).
  Attendre la promotion par le scan npm, **ne pas** bumper la version.
- `npm publish` : `E403` → 2FA ( `--otp` ) ou nom de paquet deja pris.
- Registre MCP : `server.json` invalide → schema <https://static.modelcontextprotocol.io/schemas/2025-09-29/server.schema.json>