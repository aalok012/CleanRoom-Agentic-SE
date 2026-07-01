"""Java toolchain discovery — mirrors `dafny_available()` so the Java oracle degrades gracefully.

`java_available()` gates the Java executable oracle: if there is no `javac`, certification skips
(rather than failing the run), exactly like the proof tier skips without a `dafny` binary.
`junit_jar()` finds an optional JUnit console-standalone jar (env `JUNIT_JAR` or a known path);
when present the plain-Java oracle can compile generated JUnit tests.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def javac_path() -> str | None:
    return os.getenv("JAVAC") or shutil.which("javac")


def java_path() -> str | None:
    return os.getenv("JAVA") or shutil.which("java")


def java_available() -> bool:
    """True iff a Java compiler is on PATH/$JAVAC (the minimum for the compile-check oracle)."""
    return javac_path() is not None


def junit_jar() -> Path | None:
    """Locate a junit-platform-console-standalone jar, if the user provided one.

    Looked up via $JUNIT_JAR, then ~/.cleanroom/. Returns None when absent."""
    env = os.getenv("JUNIT_JAR")
    if env and Path(env).is_file():
        return Path(env)
    for cand in (Path.home() / ".cleanroom").glob("junit-platform-console-standalone*.jar"):
        return cand
    return None
