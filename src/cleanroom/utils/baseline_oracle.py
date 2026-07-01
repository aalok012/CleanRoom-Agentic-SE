"""Baseline run-tests oracle — execute the LLM-written tests against the LLM-written code.

Unlike the full pipeline's structured pass@k (which binds spec-derived cases to a planning
contract), the baseline has no contract: it just RUNS the generated test file against the
generated code and counts pass/fail. Per language:
  - python:     `python -m pytest` over the tests dir; parse "N passed, M failed".
  - javascript: `node --test` (Node's built-in runner, no npm); parse the TAP "# pass/# fail".
  - java:       `javac` compile-check per feature pair (Feature_x.java + Feature_xTest.java);
                a clean compile counts as a pass (matches the full pipeline's Java oracle).
Returns (passed, total). Everything degrades gracefully (missing toolchain / no tests -> (0,0)).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


def _run(cmd, cwd, timeout, env=None):
    try:
        return subprocess.run(cmd, cwd=(str(cwd) if cwd else None), capture_output=True,
                              text=True, timeout=timeout, env=env)
    except (subprocess.TimeoutExpired, OSError, subprocess.SubprocessError) as exc:
        class _R:  # minimal stand-in
            returncode = 1
            stdout = ""
            stderr = f"{type(exc).__name__}: {str(exc)[:200]}"
        return _R()


def run_python_tests(app_dir: Path, timeout: float = 120.0) -> tuple[int, int]:
    import os
    app_dir = Path(app_dir).resolve()
    env = {**os.environ, "PYTHONPATH": str(app_dir)}
    proc = _run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(app_dir)],
                None, timeout, env)
    out = (proc.stdout or "") + (proc.stderr or "")
    passed = sum(int(m) for m in re.findall(r"(\d+) passed", out))
    failed = sum(int(m) for m in re.findall(r"(\d+) failed", out))
    errors = sum(int(m) for m in re.findall(r"(\d+) error", out))
    total = passed + failed + errors
    return passed, total


def run_js_tests(app_dir: Path, timeout: float = 120.0) -> tuple[int, int]:
    from src.cleanroom.utils.js_tooling import node_path
    node = node_path()
    if node is None:
        return 0, 0
    proc = _run([node, "--test"], app_dir, timeout)
    out = (proc.stdout or "") + (proc.stderr or "")
    pm = re.search(r"#\s*pass\s+(\d+)", out)
    fm = re.search(r"#\s*fail\s+(\d+)", out)
    passed = int(pm.group(1)) if pm else 0
    failed = int(fm.group(1)) if fm else 0
    return passed, passed + failed


def run_java_compile(app_dir: Path, feature_slugs: list[str], timeout: float = 120.0) -> tuple[int, int]:
    from src.cleanroom.utils.java_tooling import javac_path
    javac = javac_path()
    if javac is None:
        return 0, 0
    app_dir = Path(app_dir).resolve()
    classes = app_dir / "_classes"
    classes.mkdir(exist_ok=True)
    passed = 0
    total = 0
    for slug in feature_slugs:
        code = app_dir / f"Feature_{slug}.java"
        test = app_dir / f"Feature_{slug}Test.java"
        srcs = [str(p) for p in (code, test) if p.is_file()]
        if not srcs:
            continue
        total += 1
        proc = _run([javac, "-d", str(classes), *srcs], None, timeout)
        if proc.returncode == 0:
            passed += 1
    return passed, total


def run_oracle(language: str, app_dir: Path, feature_slugs: list[str],
               timeout: float = 120.0) -> tuple[int, int]:
    app_dir = Path(app_dir)
    if language == "python":
        return run_python_tests(app_dir, timeout)
    if language == "javascript":
        return run_js_tests(app_dir, timeout)
    if language == "java":
        return run_java_compile(app_dir, feature_slugs, timeout)
    return 0, 0
