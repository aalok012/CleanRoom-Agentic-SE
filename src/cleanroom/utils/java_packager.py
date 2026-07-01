"""Lay out generated Java sources so `javac` can compile them.

Each generated file's public class name is read from its content and written as `<Class>.java`
under `<code_dir>/src` (default package, flat) — javac requires the file name to match the public
class. v1 keeps features self-contained (no cross-class calls, no build system).
"""

from __future__ import annotations

import re
from pathlib import Path

_PUBLIC_CLASS = re.compile(r"public\s+(?:final\s+)?class\s+([A-Za-z_]\w*)")


def java_class_name(content: str, fallback: str) -> str:
    m = _PUBLIC_CLASS.search(content or "")
    return m.group(1) if m else fallback


def write_java_sources(generated_code: dict, code_dir: Path) -> list[Path]:
    """Write every Java file under code_dir/src as <PublicClass>.java. Returns the paths."""
    src = Path(code_dir) / "src"
    src.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    used: set[str] = set()
    for i, f in enumerate(generated_code.get("files", [])):
        content = f.get("content", "")
        fallback = "Gen" + re.sub(r"\W", "_", str(f.get("fr_id", i)))
        name = java_class_name(content, fallback)
        if name in used:                      # avoid clobbering on a duplicated class name
            name = f"{name}_{i}"
        used.add(name)
        dest = src / f"{name}.java"
        dest.write_text(content)
        written.append(dest)
    return written


def write_java_test_sources(generated_tests: dict, code_dir: Path) -> list[Path]:
    """Write generated JUnit tests under code_dir/src so the javac oracle compiles them.

    Plain Java has no build tool in v1; production and test classes both live in the default
    package, so the compiler-visible tree is the flat ``src`` directory.
    """
    src = Path(code_dir) / "src"
    src.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    used: set[str] = set()
    for i, feature in enumerate(generated_tests.get("features", [])):
        slug = str(feature.get("feature_id", i)).replace(".", "_")
        source = (feature.get("test_source") or "").strip()
        if not source:
            source = (f"// No JUnit source generated for feature {feature.get('feature_id', slug)}; "
                      f"{len(feature.get('cases', []))} case(s) recorded in the IR.\n")
        name = java_class_name(source, f"Feature_{slug}Test")
        dest_name = name if name not in used else f"{name}_{i}"
        used.add(dest_name)
        dest = src / f"{dest_name}.java"
        dest.write_text(source + "\n")
        written.append(dest)
    return written
