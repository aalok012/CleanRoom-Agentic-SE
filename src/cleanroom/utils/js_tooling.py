"""Node.js toolchain discovery — mirrors `java_available()` so the JS oracle degrades gracefully.

`node_available()` gates the JavaScript executable oracle: with no `node` on PATH, certification
skips (rather than failing the run), exactly like the proof tier skips without a `dafny` binary and
the Java oracle skips without `javac`.
"""

from __future__ import annotations

import os
import shutil


def node_path() -> str | None:
    return os.getenv("NODE") or shutil.which("node")


def npm_path() -> str | None:
    return os.getenv("NPM") or shutil.which("npm")


def node_available() -> bool:
    """True iff a Node.js runtime is on PATH/$NODE (the minimum for the in-process JS oracle)."""
    return node_path() is not None
