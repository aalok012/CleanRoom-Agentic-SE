"""JS packager — lay generated JavaScript out as a runnable Node/Express + SQLite app.

Analog of `build_runnable_package` (FastAPI) / `write_java_sources` (Java). The Code Agent emits
one self-contained ES/CommonJS module per functional requirement, each exporting a PURE function
named exactly as the contract (stdlib-only, no side effects at import) — that is the certified core
the in-process oracle calls. On top of those we assemble a thin Express server + a SQLite-backed
key/value store (`better-sqlite3`) as the deliverable web app. The oracle never requires Express or
the DB (it loads the pure function files directly), so certification needs no `npm install`.
"""

from __future__ import annotations

from pathlib import Path


def js_file_path(path: str) -> str:
    """Map a planner contract path (``controllers/foo.py``) to its JS file (``controllers/foo.js``)."""
    return path[:-3] + ".js" if path.endswith(".py") else path


_DB_JS = """\
// Thin SQLite-backed key/value store (the project's "SQL DB"). Stores each feature's
// state blob as JSON in a single table — the JS analog of the Python adapter's AppState.
'use strict';
let _db = null;
function db() {
  if (_db) return _db;
  const Database = require('better-sqlite3');
  _db = new Database(process.env.APP_DB || 'app.db');
  _db.exec('CREATE TABLE IF NOT EXISTS app_state (key TEXT PRIMARY KEY, value TEXT NOT NULL)');
  return _db;
}
function load(key, fallback) {
  const row = db().prepare('SELECT value FROM app_state WHERE key = ?').get(key);
  return row ? JSON.parse(row.value) : fallback;
}
function save(key, value) {
  db().prepare('INSERT INTO app_state (key, value) VALUES (?, ?) '
    + 'ON CONFLICT(key) DO UPDATE SET value = excluded.value').run(key, JSON.stringify(value));
}
module.exports = { db, load, save };
"""

_APP_JS = """\
// Runnable Express server. Auto-discovers every feature module under controllers/ and views/
// and mounts each exported function as POST /{layer}/{module}. Mirrors FastAPI router
// auto-discovery so no per-feature wiring is written (Code/Test isolation preserved).
'use strict';
const express = require('express');
const fs = require('fs');
const path = require('path');

function createApp() {
  const app = express();
  app.use(express.json());
  app.get('/health', (_req, res) => res.json({ status: 'ok' }));
  for (const layer of ['controllers', 'views', 'models']) {
    const dir = path.join(__dirname, layer);
    if (!fs.existsSync(dir)) continue;
    for (const file of fs.readdirSync(dir).filter((f) => f.endsWith('.js'))) {
      const mod = require(path.join(dir, file));
      const fn = Object.values(mod).find((v) => typeof v === 'function');
      if (!fn) continue;
      const route = `/${layer}/${file.replace(/\\.js$/, '')}`;
      app.post(route, (req, res) => {
        try {
          res.json(fn(req.body));
        } catch (err) {
          res.status(400).json({ error: String(err && err.message || err) });
        }
      });
    }
  }
  return app;
}

if (require.main === module) {
  const port = process.env.PORT || 3000;
  createApp().listen(port, () => console.log(`listening on ${port}`));
}
module.exports = { createApp };
"""


def _package_json(project: str) -> str:
    name = (project or "app").lower().replace(" ", "-").replace("_", "-")
    return (
        '{\n'
        f'  "name": "{name}",\n'
        '  "version": "1.0.0",\n'
        '  "private": true,\n'
        '  "main": "app.js",\n'
        '  "scripts": {\n'
        '    "start": "node app.js",\n'
        '    "test": "jest"\n'
        '  },\n'
        '  "dependencies": {\n'
        '    "better-sqlite3": "^11.0.0",\n'
        '    "express": "^4.19.2"\n'
        '  },\n'
        '  "devDependencies": {\n'
        '    "jest": "^29.7.0"\n'
        '  }\n'
        '}\n'
    )


def write_js_sources(generated_code: dict, code_dir: Path, project: str = "app") -> Path:
    """Write each FR module (as .js) + the Express/SQLite scaffold. Returns the app dir."""
    code_dir = Path(code_dir)
    code_dir.mkdir(parents=True, exist_ok=True)
    for f in generated_code.get("files", []):
        dest = code_dir / js_file_path(f["path"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(f.get("content", ""), encoding="utf-8")
    (code_dir / "db.js").write_text(_DB_JS, encoding="utf-8")
    (code_dir / "app.js").write_text(_APP_JS, encoding="utf-8")
    (code_dir / "package.json").write_text(_package_json(project), encoding="utf-8")
    return code_dir
