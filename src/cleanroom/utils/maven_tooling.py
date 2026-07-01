"""Maven/JDK toolchain discovery for the Spring Boot oracle.

Mirrors `java_tooling.java_available()` / `dafny_available()` so the Spring build-check oracle
degrades gracefully: if there is no `mvn` (or no `javac`), certification SKIPS rather than failing
the run, exactly like the proof tier skips without a `dafny` binary. The Spring oracle builds a
real Maven project, so it needs both a JDK and Maven on PATH.
"""

from __future__ import annotations

import os
import shutil


def mvn_path() -> str | None:
    return os.getenv("MVN") or shutil.which("mvn")


def spring_oracle_available() -> bool:
    """True iff both Maven and a JDK compiler are available (the minimum to build a Spring app)."""
    from src.cleanroom.utils.java_tooling import java_available

    return mvn_path() is not None and java_available()
