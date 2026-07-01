"""Static stats over generated code: language, size, MVC layers, tech stack.

Deterministic, no LLM. Reads a GeneratedCode dump (the 'generated_code' IR key)
and reports file/line counts, the MVC-layer breakdown, and the libraries the code
imports (third-party = any imported top-level module not in the Python standard
library and not a relative/intra-project import).
"""

import ast
import sys
from collections import Counter
from pathlib import Path

_STDLIB = set(sys.stdlib_module_names)
# Conventional intra-project package/layer names the generated code imports from
# its own siblings — these are NOT third-party libraries.
_INTRA_PROJECT = {"model", "models", "controller", "controllers", "view", "views", "schema", "schemas"}


def code_stats(generated_code: dict) -> dict:
    # Current schema is a flat {"files": [...]}; tolerate the legacy {"increments": [{"files": ...}]}.
    files = generated_code.get("files") or [
        f for inc in generated_code.get("increments", []) for f in inc.get("files", [])
    ]
    loc = sum((f.get("content", "").count("\n") + 1) for f in files if f.get("content"))
    layers = Counter((f.get("mvc_layer") or "unknown") for f in files)

    # The project's own modules (generated file stems) plus conventional layer names —
    # imports of these are intra-project, not external dependencies.
    own_modules = {Path(f.get("path", "")).stem for f in files if f.get("path")} | _INTRA_PROJECT

    imports: set[str] = set()
    for f in files:
        try:
            tree = ast.parse(f.get("content", ""))
        except SyntaxError:
            continue  # malformed generated file — skip its imports, don't crash
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                imports.add(node.module.split(".")[0])

    third_party = sorted(i for i in imports if i not in _STDLIB and i not in own_modules)
    return {
        "language": "Python",
        "files": len(files),
        "lines_of_code": loc,
        "files_per_layer": dict(layers),
        "imports": sorted(imports),
        "third_party_libraries": third_party,
    }
