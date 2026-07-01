"""Compile-informed Java repair loop.

This module runs a static Java build after code/test generation, maps compiler diagnostics back to
generated artifacts, asks the relevant agent to repair only the broken source, and retries. The
loop consumes compiler output only: no test cases, expected outputs, or runtime verdicts are fed to
the Code Agent.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from src.cleanroom.utils.java_packager import java_class_name
from src.cleanroom.utils.java_tooling import javac_path, junit_jar
from src.cleanroom.utils.maven_tooling import mvn_path

if TYPE_CHECKING:
    from src.cleanroom.agents.code.agent import CodeAgent
    from src.cleanroom.agents.test.agent import TestAgent


@dataclass(frozen=True)
class CompileError:
    path: Path
    line: int | None
    col: int | None
    message: str
    raw: str

    def as_dict(self) -> dict:
        return {
            "path": str(self.path),
            "line": self.line,
            "col": self.col,
            "message": self.message,
        }


@dataclass(frozen=True)
class CompileCheck:
    ok: bool
    skipped: bool
    command: str
    reason: str
    diagnostics: str = ""


_JAVAC_ERROR = re.compile(
    r"^(?P<path>.+?\.java):(?P<line>\d+):\s+error:\s+(?P<msg>.*)$",
    re.MULTILINE,
)
_MAVEN_ERROR = re.compile(
    r"^\[ERROR\]\s+(?P<path>.+?\.java):\[(?P<line>\d+),(?P<col>\d+)\]\s+(?P<msg>.*)$",
    re.MULTILINE,
)


def run_java_compile_repair(
    *,
    code_agent: "CodeAgent",
    ir: dict,
    code_dir: Path,
    stack: str,
    generated_tests: dict | None = None,
    test_agent: "TestAgent | None" = None,
    dafny_proj: Path | None = None,
    adapter_modules: dict[str, str] | None = None,
    max_rounds: int = 2,
    timeout: float = 240.0,
) -> dict:
    """Repair Java/Spring compile failures in-place on ``ir``.

    Returns a JSON-serializable metrics dict. ``ir["generated_code"]`` and, when test repair is
    available, ``ir["generated_tests"]`` are updated after each successful LLM repair.
    """
    adapter_modules = adapter_modules or {}
    adapter_java_apis: dict[str, dict] = {}
    if dafny_proj is not None and adapter_modules:
        from src.cleanroom.utils.dafny_project import summarize_dafny_java_api

        adapter_java_apis = {
            fid: summarize_dafny_java_api(Path(dafny_proj), module)
            for fid, module in adapter_modules.items()
        }
    generated_tests = generated_tests if generated_tests is not None else (ir.get("generated_tests") or {})
    if generated_tests and "generated_tests" not in ir:
        ir["generated_tests"] = generated_tests

    metrics = {
        "max_rounds": max(0, int(max_rounds)),
        "attempts": [],
        "repaired_files": [],
        "ok": False,
        "skipped": False,
        "reason": "",
        "unmapped_errors": [],
    }
    if metrics["max_rounds"] <= 0:
        metrics["skipped"] = True
        metrics["reason"] = "disabled"
        return metrics
    if not ir.get("generated_code"):
        metrics["skipped"] = True
        metrics["reason"] = "no generated_code"
        return metrics

    project_dir = Path(code_dir)
    for round_idx in range(metrics["max_rounds"] + 1):
        project_dir = _rebuild_project(
            code_agent=code_agent,
            ir=ir,
            code_dir=Path(code_dir),
            stack=stack,
            generated_tests=generated_tests,
            dafny_proj=dafny_proj,
            adapter_modules=adapter_modules,
        )
        check = _run_compile_check(project_dir, stack, timeout=timeout)
        errors = _parse_compile_errors(check.diagnostics, project_dir)
        source_map = _generated_source_map(ir.get("generated_code") or {}, project_dir, stack)
        test_map = _generated_test_map(generated_tests or {}, project_dir, stack)
        mapped_code, mapped_tests, unmapped = _map_errors(errors, source_map, test_map)
        attempt = {
            "round": round_idx,
            "ok": check.ok,
            "skipped": check.skipped,
            "command": check.command,
            "reason": check.reason,
            "error_count": len(errors),
            "code_files": len(mapped_code),
            "test_files": len(mapped_tests),
            "unmapped_errors": [e.as_dict() for e in unmapped[:8]],
        }
        metrics["attempts"].append(attempt)

        if check.ok or check.skipped:
            metrics["ok"] = check.ok
            metrics["skipped"] = check.skipped
            metrics["reason"] = check.reason
            return metrics
        if round_idx >= metrics["max_rounds"]:
            metrics["reason"] = check.reason
            metrics["unmapped_errors"] = [e.as_dict() for e in unmapped[:20]]
            return metrics
        if not mapped_code and not mapped_tests:
            metrics["reason"] = "compile failed, but no generated Java source could be mapped"
            metrics["unmapped_errors"] = [e.as_dict() for e in unmapped[:20]]
            return metrics

        for file_index, file_errors in sorted(mapped_code.items()):
            files = (ir.get("generated_code") or {}).get("files") or []
            if file_index >= len(files):
                continue
            prior = files[file_index]
            diagnostics = _diagnostics_for_file(check.diagnostics, file_errors, project_dir)
            repaired = code_agent.repair_compile_error(
                ir,
                prior,
                diagnostics,
                proved_modules=adapter_modules,
                proved_java_apis=adapter_java_apis,
            )
            files[file_index] = repaired.model_dump()
            metrics["repaired_files"].append({
                "round": round_idx + 1,
                "kind": "code",
                "fr_id": repaired.fr_id,
                "feature_id": repaired.feature_id,
                "path": repaired.path,
            })

        if mapped_tests and test_agent is None:
            metrics["reason"] = "compile failed in generated tests, but no test repair agent was provided"
            metrics["unmapped_errors"] = [e.as_dict() for errors_ in mapped_tests.values() for e in errors_][:20]
            return metrics

        for feature_index, file_errors in sorted(mapped_tests.items()):
            features = (generated_tests or {}).get("features") or []
            if feature_index >= len(features) or test_agent is None:
                continue
            prior = features[feature_index]
            diagnostics = _diagnostics_for_file(check.diagnostics, file_errors, project_dir)
            repaired = test_agent.repair_compile_error(ir, prior, diagnostics)
            features[feature_index] = repaired.model_dump()
            if "generated_tests" in ir:
                ir["generated_tests"] = generated_tests
            metrics["repaired_files"].append({
                "round": round_idx + 1,
                "kind": "test",
                "feature_id": repaired.feature_id,
                "path": "test_source",
            })

    metrics["reason"] = "max rounds exhausted"
    return metrics


def _rebuild_project(
    *,
    code_agent: "CodeAgent",
    ir: dict,
    code_dir: Path,
    stack: str,
    generated_tests: dict,
    dafny_proj: Path | None,
    adapter_modules: dict[str, str],
) -> Path:
    if stack == "spring":
        project_dir = code_agent.target.package_sample(ir["generated_code"], code_dir, stack) or code_dir
        if dafny_proj is not None and adapter_modules:
            code_agent.target.stage_cores(
                Path(project_dir),
                Path(dafny_proj),
                [adapter_modules[fid] for fid in sorted(adapter_modules)],
            )
        code_agent.target.package_tests(generated_tests or {}, Path(project_dir), stack)
        return Path(project_dir)

    src = Path(code_dir) / "src"
    classes = Path(code_dir) / "classes"
    if src.exists():
        shutil.rmtree(src)
    if classes.exists():
        shutil.rmtree(classes)
    code_agent.target.package_sample(ir["generated_code"], code_dir, stack)
    code_agent.target.package_tests(generated_tests or {}, code_dir, stack)
    return Path(code_dir)


def _run_compile_check(project_dir: Path, stack: str, timeout: float) -> CompileCheck:
    if stack == "spring":
        mvn = mvn_path()
        if mvn is None:
            return CompileCheck(
                ok=False,
                skipped=True,
                command="mvn -B -q -Dstyle.color=never clean test-compile",
                reason="mvn not found",
            )
        if not (project_dir / "pom.xml").is_file():
            return CompileCheck(
                ok=False,
                skipped=True,
                command="mvn -B -q -Dstyle.color=never clean test-compile",
                reason="no pom.xml",
            )
        cmd = [mvn, "-B", "-q", "-Dstyle.color=never", "clean", "test-compile"]
        display_cmd = "mvn -B -q -Dstyle.color=never clean test-compile"
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=str(project_dir),
            )
        except subprocess.TimeoutExpired:
            return CompileCheck(False, False, display_cmd, f"mvn timed out after {timeout:.0f}s")
        except (OSError, subprocess.SubprocessError) as exc:
            return CompileCheck(False, False, display_cmd, f"mvn error: {str(exc)[:200]}")
        output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        if proc.returncode == 0:
            return CompileCheck(True, False, display_cmd, "mvn clean test-compile passed", output)
        return CompileCheck(False, False, display_cmd, "mvn clean test-compile failed", output)

    javac = javac_path()
    if javac is None:
        return CompileCheck(False, True, "javac -d classes src/*.java", "javac not found")
    src = project_dir / "src"
    java_files = sorted(src.glob("*.java"))
    if not java_files:
        return CompileCheck(False, True, "javac -d classes src/*.java", "no Java sources")
    tests = [p for p in java_files if p.name.endswith("Test.java")]
    jar = junit_jar()
    skipped_test_compile = False
    if tests and jar is None:
        java_files = [p for p in java_files if not p.name.endswith("Test.java")]
        skipped_test_compile = True
        if not java_files:
            return CompileCheck(
                False,
                True,
                "javac -cp $JUNIT_JAR -d classes src/*.java",
                "JUnit test sources present but JUNIT_JAR was not found",
            )
    classes = project_dir / "classes"
    classes.mkdir(parents=True, exist_ok=True)
    cmd = [javac, "-d", str(classes)]
    if jar is not None:
        cmd += ["-cp", str(jar)]
    cmd += [str(p) for p in java_files]
    display_cmd = "javac -d classes" + (" -cp $JUNIT_JAR" if jar is not None else "") + " src/*.java"
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return CompileCheck(False, False, display_cmd, f"javac timed out after {timeout:.0f}s")
    except (OSError, subprocess.SubprocessError) as exc:
        return CompileCheck(False, False, display_cmd, f"javac error: {str(exc)[:200]}")
    output = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    if proc.returncode == 0:
        if skipped_test_compile:
            return CompileCheck(
                True,
                True,
                display_cmd,
                "main sources compile; JUnit test compile skipped because JUNIT_JAR was not found",
                output,
            )
        return CompileCheck(True, False, display_cmd, "javac compile-check passed", output)
    return CompileCheck(False, False, display_cmd, "javac compile-check failed", output)


def _parse_compile_errors(diagnostics: str, project_dir: Path) -> list[CompileError]:
    out: list[CompileError] = []
    for m in _MAVEN_ERROR.finditer(diagnostics or ""):
        out.append(CompileError(
            path=_resolve_error_path(m.group("path"), project_dir),
            line=int(m.group("line")),
            col=int(m.group("col")),
            message=m.group("msg").strip(),
            raw=m.group(0),
        ))
    for m in _JAVAC_ERROR.finditer(diagnostics or ""):
        out.append(CompileError(
            path=_resolve_error_path(m.group("path"), project_dir),
            line=int(m.group("line")),
            col=None,
            message=m.group("msg").strip(),
            raw=m.group(0),
        ))
    return _dedupe_errors(out)


def _resolve_error_path(path_text: str, project_dir: Path) -> Path:
    p = Path(path_text.strip())
    if not p.is_absolute():
        p = Path(project_dir) / p
    try:
        return p.resolve()
    except OSError:
        return p.absolute()


def _dedupe_errors(errors: list[CompileError]) -> list[CompileError]:
    seen: set[tuple[str, int | None, int | None, str]] = set()
    out: list[CompileError] = []
    for error in errors:
        key = (str(error.path), error.line, error.col, error.message)
        if key in seen:
            continue
        seen.add(key)
        out.append(error)
    return out


def _generated_source_map(generated_code: dict, project_dir: Path, stack: str) -> dict[Path, int]:
    files = generated_code.get("files") or []
    out: dict[Path, int] = {}
    if stack == "spring":
        from src.cleanroom.utils.spring_packager import GEN_PACKAGE, _fr_slug

        gen_root = project_dir / "src" / "main" / "java" / Path(*GEN_PACKAGE.split("."))
        for i, f in enumerate(files):
            fallback = "Gen" + re.sub(r"\W", "_", str(f.get("fr_id", i)))
            cls = java_class_name(f.get("content", ""), fallback)
            out[(gen_root / _fr_slug(f.get("fr_id", ""), i) / f"{cls}.java").resolve()] = i
        return out

    src = project_dir / "src"
    used: set[str] = set()
    for i, f in enumerate(files):
        fallback = "Gen" + re.sub(r"\W", "_", str(f.get("fr_id", i)))
        name = java_class_name(f.get("content", ""), fallback)
        if name in used:
            name = f"{name}_{i}"
        used.add(name)
        out[(src / f"{name}.java").resolve()] = i
    return out


def _generated_test_map(generated_tests: dict, project_dir: Path, stack: str) -> dict[Path, int]:
    features = (generated_tests or {}).get("features") or []
    out: dict[Path, int] = {}
    used: set[str] = set()
    if stack == "spring":
        from src.cleanroom.utils.spring_packager import BASE_PACKAGE

        root = project_dir / "src" / "test" / "java" / Path(*BASE_PACKAGE.split("."))
    else:
        root = project_dir / "src"
    for i, feature in enumerate(features):
        slug = str(feature.get("feature_id", i)).replace(".", "_")
        source = (feature.get("test_source") or "").strip()
        name = java_class_name(source, f"Feature_{slug}Test")
        dest_name = name if name not in used else f"{name}_{i}"
        used.add(dest_name)
        out[(root / f"{dest_name}.java").resolve()] = i
    return out


def _map_errors(
    errors: list[CompileError],
    source_map: dict[Path, int],
    test_map: dict[Path, int],
) -> tuple[dict[int, list[CompileError]], dict[int, list[CompileError]], list[CompileError]]:
    code_by_file: dict[int, list[CompileError]] = {}
    test_by_file: dict[int, list[CompileError]] = {}
    unmapped: list[CompileError] = []
    for error in errors:
        path = error.path.resolve()
        if path in source_map:
            code_by_file.setdefault(source_map[path], []).append(error)
        elif path in test_map:
            test_by_file.setdefault(test_map[path], []).append(error)
        else:
            unmapped.append(error)
    return code_by_file, test_by_file, unmapped


def _diagnostics_for_file(diagnostics: str, errors: list[CompileError], project_dir: Path) -> str:
    project_dir = project_dir.resolve()
    anchors = {str(e.path) for e in errors}
    anchors.update(str(e.path.relative_to(project_dir)) for e in errors if _is_relative_to(e.path, project_dir))
    anchors.update(e.path.name for e in errors)
    lines = (diagnostics or "").splitlines()
    selected: list[str] = []
    for i, line in enumerate(lines):
        if any(anchor and anchor in line for anchor in anchors):
            start = max(0, i - 1)
            end = min(len(lines), i + 5)
            selected.extend(lines[start:end])
    if not selected:
        selected = [e.raw for e in errors]
    text = "\n".join(dict.fromkeys(selected))
    tail = "\n".join(lines[-80:])
    combined = (text + "\n\nCompiler output tail:\n" + tail).strip()
    return combined[-12000:]


def _is_relative_to(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False
