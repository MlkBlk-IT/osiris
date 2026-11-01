#!/usr/bin/env node
'use strict';

/*
 * osiris-mcp — lanceur MCP stdio pour OSIRIS.
 *
 * Ce paquet npm est un simple lanceur : le serveur MCP est ecrit en Python
 * (paquet PyPI `mcp-osiris`). Resolution du runtime, dans cet ordre :
 *
 *   1. OSIRIS_PYTHON  -> interpreteur Python explicite (chemin complet)
 *   2. uvx / uv       -> `uvx --from mcp-osiris mcp-osiris` (aucune install requise)
 *   3. python3        -> `python3 -m osiris`
 *   4. python         -> `python -m osiris`
 *
 * Contrat MCP : stdout ne porte QUE le protocole JSON-RPC. Les logs vont
 * systematiquement sur stderr.
 */

const { spawn, spawnSync } = require('node:child_process');
const fs = require('node:fs');

function has(cmd) {
  const probe = process.platform === 'win32' ? 'where' : 'which';
  const r = spawnSync(probe, [cmd], { stdio: 'ignore', windowsHide: true });
  return r.status === 0;
}

function pickRuntime() {
  const explicit = process.env.OSIRIS_PYTHON;
  if (explicit) {
    const usable =
      process.platform === 'win32' ? fs.existsSync(explicit) : has(explicit);
    if (usable) return { cmd: explicit, args: ['-m', 'osiris'] };
  }
  if (has('uvx')) {
    return { cmd: 'uvx', args: ['--from', 'mcp-osiris', 'mcp-osiris'] };
  }
  if (has('uv')) {
    return { cmd: 'uv', args: ['tool', 'run', '--from', 'mcp-osiris', 'mcp-osiris'] };
  }
  if (has('python3')) return { cmd: 'python3', args: ['-m', 'osiris'] };
  if (has('python')) return { cmd: 'python', args: ['-m', 'osiris'] };
  return null;
}

const runtime = pickRuntime();
if (!runtime) {
  process.stderr.write(
    '[osiris-mcp] Aucun runtime Python trouve.\n' +
      '[osiris-mcp]   - installez Python 3.12+ (https://www.python.org/downloads/)\n' +
      '[osiris-mcp]   - ou installez uv (https://docs.astral.sh/uv/) pour utiliser uvx\n' +
      '[osiris-mcp]   - ou fixez OSIRIS_PYTHON=/chemin/vers/python.exe\n'
  );
  process.exit(1);
}

const child = spawn(runtime.cmd, runtime.args, {
  // stdin DOIT etre herite : le serveur MCP lit les requetes JSON-RPC sur
  // stdin. stdout ne porte que le protocole, stderr recoit les logs.
  stdio: ['inherit', 'inherit', 'inherit'],
  windowsHide: true,
  env: Object.assign({}, process.env, {
    PYTHONUNBUFFERED: '1',
    PYTHONIOENCODING: 'utf-8',
  }),
});

for (const signal of ['SIGINT', 'SIGTERM']) {
  process.on(signal, () => {
    try {
      child.kill(signal);
    } catch (_) {
      /* le process est deja parti */
    }
  });
}

child.on('error', (err) => {
  process.stderr.write('[osiris-mcp] ' + err.message + '\n');
  process.exit(1);
});

child.on('exit', (code, signal) => {
  process.exit(signal ? 1 : code === null ? 1 : code);
});
