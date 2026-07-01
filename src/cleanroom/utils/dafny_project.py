"""Scaffold a Dafny verification project and compile verified Dafny to native code.

No npm / external toolchain dependency: ``scaffold_dafny_project`` just makes a directory and drops
in our vendored ``Replay.dfy`` kernel (the abstract Domain/Kernel that feature modules refine).
``compile_dafny`` turns each VERIFIED feature module into native source via the stock
``dafny translate <target>`` backend (default Python). Compilation is best-effort — the verified
Dafny is the primary, formally-guaranteed artifact; native emission is a convenience on top.

Project layout:
    <project_dir>/
      dafny/   Replay.dfy (vendored)  +  F<feat>.dfy (generated, one per feature)
      out/     dafny translate output for the verified modules
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from src.cleanroom.agents.dafny.schema.dafny import GeneratedDafny
from src.cleanroom.utils.dafny_verify import dafny_binary

# Our vendored kernel, owned in-repo (no external install needed).
KERNEL_SRC = Path(__file__).resolve().parents[1] / "agents" / "dafny" / "kernel" / "Replay.dfy"


def scaffold_dafny_project(project_dir: Path) -> Path:
    """Create a fresh Dafny project at ``project_dir``: a ``dafny/`` dir + the vendored kernel.

    Verification and ``dafny translate`` use only the ``dafny`` binary, so no node project is needed.
    """
    project_dir = Path(project_dir)
    if project_dir.exists():
        shutil.rmtree(project_dir)
    dafny_dir = project_dir / "dafny"
    dafny_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(KERNEL_SRC, dafny_dir / "Replay.dfy")
    return project_dir


def stage_dafny_cores(app_dir: Path, project_dir: Path, modules: list[str]) -> dict:
    """Copy compiled cores + the marshalling shim into a runnable app under ``app_dir/dafny_cores``.

    For each proved feature ``module`` (e.g. ``F4_1``) the compiled ``out/<module>-py/`` dir is
    copied to ``app_dir/dafny_cores/<module>-py/`` (it bundles its own ``_dafny`` runtime), and the
    shared ``dafny_marshal.py`` shim lands at ``app_dir/dafny_cores/dafny_marshal.py``. The generated
    adapters discover this dir by searching upward for ``dafny_cores`` (see generate_adapter.j2).
    """
    app_dir, project_dir = Path(app_dir), Path(project_dir)
    cores_dir = app_dir / "dafny_cores"
    cores_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(Path(__file__).resolve().parent / "dafny_marshal.py", cores_dir / "dafny_marshal.py")
    staged, missing = [], []
    for module in modules:
        src = project_dir / "out" / f"{module}-py"
        if not src.is_dir():
            missing.append(module)
            continue
        dst = cores_dir / f"{module}-py"
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        staged.append(module)
    return {"cores_dir": str(cores_dir), "staged": staged, "missing": missing}


def stage_dafny_cores_java(maven_dir: Path, project_dir: Path, modules: list[str]) -> dict:
    """Copy translated Dafny Java cores into a Maven project's ``src/main/java`` so it compiles.

    For each proved feature ``module`` (e.g. ``F4_1``) ``dafny translate java --include-runtime``
    produced ``out/<module>-java/`` — a package tree of ``.java`` sources that bundles its OWN copy
    of the ``dafny`` runtime. We replicate each file at its package-relative path under
    ``src/main/java``, but SKIP a destination that already exists: that dedupes the shared
    ``dafny`` runtime across multiple staged cores (first writer wins — every core bundles the same
    runtime), so javac never sees a duplicate class. Returns staged/missing module lists.
    """
    src_root = Path(maven_dir) / "src" / "main" / "java"
    src_root.mkdir(parents=True, exist_ok=True)
    staged, missing = [], []
    for module in modules:
        core_dir = Path(project_dir) / "out" / f"{module}-java"
        if not core_dir.is_dir():
            missing.append(module)
            continue
        for jf in core_dir.rglob("*.java"):
            dst = src_root / jf.relative_to(core_dir)
            if dst.exists():          # shared DafnyRuntime already staged by an earlier core
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(jf, dst)
        staged.append(module)
    return {"java_src": str(src_root), "staged": staged, "missing": missing}


_PACKAGE_RE = re.compile(r"(?m)^\s*package\s+([\w.]+)\s*;")
_CLASS_RE = re.compile(r"(?m)^\s*public\s+(?:abstract\s+)?class\s+(\w+)\b")
_PUBLIC_STATIC_RE = re.compile(
    r"(?m)^\s*public\s+static\s+(?:<[^>\n]+>\s+)?(.+?)\s+(\w+)\(([^()]*)\)\s*(?:\{|$)"
)
_PUBLIC_METHOD_RE = re.compile(r"(?m)^\s*public\s+(.+?)\s+(dtor_\w+|is_\w+)\(([^()]*)\)\s*(?:\{|$)")
_PUBLIC_FIELD_RE = re.compile(r"(?m)^\s*public\s+(.+?)\s+_(\w+)\s*;")


def _one_line(text: str) -> str:
    return " ".join((text or "").split())


def summarize_dafny_java_api(project_dir: Path, module: str) -> dict:
    """Extract the actual Java API emitted by ``dafny translate java`` for one module.

    The Spring adapter generator must call the translated API, not infer Java names from the Dafny
    source. Dafny mangles package names (``F3_1Domain`` -> ``F3__1Domain``), exposes fields through
    ``dtor_*`` accessors, and sometimes gives ``Apply`` a request-record parameter rather than an
    ``Action`` parameter. This summary is deterministic and prompt-sized: package names, public
    class names, factories, destructors, and ``__default`` state-machine method signatures.
    """
    project_dir = Path(project_dir)
    core_dir = project_dir / "out" / f"{module}-java"
    domain_package = f"{module}Domain".replace("_", "__")
    kernel_package = f"{module}Kernel".replace("_", "__")
    out: dict = {
        "module": module,
        "core_dir": str(core_dir),
        "exists": core_dir.is_dir(),
        "domain_package": domain_package,
        "kernel_package": kernel_package,
        "default_methods": [],
        "classes": [],
        "summary": "",
    }
    if not core_dir.is_dir():
        out["summary"] = f"No translated Java core found at {core_dir}"
        return out

    domain_dir = core_dir / domain_package
    java_files = sorted(domain_dir.glob("*.java")) if domain_dir.is_dir() else []
    for path in java_files:
        text = path.read_text(encoding="utf-8", errors="ignore")
        pkg = (_PACKAGE_RE.search(text) or [None, domain_package])[1]
        cls_match = _CLASS_RE.search(text)
        if not cls_match:
            continue
        cls = cls_match.group(1)
        factories = []
        destructors = []
        predicates = []
        fields = []
        for ret, name, args in _PUBLIC_STATIC_RE.findall(text):
            if name.startswith("create") or name in {"Default", "_typeDescriptor"}:
                factories.append(f"{_one_line(ret)} {name}({_one_line(args)})")
        for ret, name, args in _PUBLIC_METHOD_RE.findall(text):
            sig = f"{_one_line(ret)} {name}({_one_line(args)})"
            if name.startswith("dtor_"):
                destructors.append(sig)
            elif name.startswith("is_"):
                predicates.append(sig)
        for typ, name in _PUBLIC_FIELD_RE.findall(text):
            fields.append(f"{_one_line(typ)} _{name}")

        item = {
            "package": pkg,
            "class": cls,
            "factories": factories,
            "destructors": destructors,
            "predicates": predicates,
            "fields": fields,
        }
        if cls == "__default":
            methods = []
            for ret, name, args in _PUBLIC_STATIC_RE.findall(text):
                if name not in {"Default", "_typeDescriptor"} and not name.startswith("create"):
                    methods.append(f"{_one_line(ret)} {name}({_one_line(args)})")
            item["methods"] = methods
            out["default_methods"] = methods
        out["classes"].append(item)

    lines = [
        f"Translated Java core directory: {core_dir}",
        f"Domain package: {domain_package}",
        f"Kernel package: {kernel_package}",
        "State-machine methods on domain __default:",
    ]
    if out["default_methods"]:
        lines.extend(f"- {domain_package}.__default.{sig}" for sig in out["default_methods"])
    else:
        lines.append("- (none found)")
    lines.append("Domain classes:")
    for item in out["classes"]:
        cls = item["class"]
        if cls == "__default":
            continue
        lines.append(f"- {item['package']}.{cls}")
        if item["factories"]:
            lines.append("  factories: " + "; ".join(item["factories"][:8]))
        if item["destructors"]:
            lines.append("  accessors: " + "; ".join(item["destructors"][:12]))
        if item["predicates"]:
            lines.append("  predicates: " + "; ".join(item["predicates"][:8]))
    out["summary"] = "\n".join(lines)
    return out


def compile_dafny(project_dir: Path, gen: GeneratedDafny, target: str = "py",
                  timeout: float = 240.0) -> dict:
    """Compile each VERIFIED feature module to native source via ``dafny translate`` (best-effort).

    ``target`` is any stock Dafny backend: py | cs | js | go | java | cpp | rs. Returns
    {"target", "compiled": [...], "failed": [...]}. Unverified modules are skipped (a feature
    only compiles from a discharged proof — never from unproved code).
    """
    dafny = dafny_binary()
    if dafny is None:
        return {"target": target, "compiled": [], "failed": [],
                "note": "dafny binary not found; skipped"}

    project_dir = Path(project_dir).resolve()
    dafny_dir = project_dir / "dafny"
    out_dir = project_dir / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    compiled: list[dict] = []
    failed: list[dict] = []

    for f in gen.features:
        if not f.verified:
            failed.append({"feature_id": f.feature_id, "reason": "dafny not verified"})
            continue
        src = (dafny_dir / f"{f.module}.dfy").resolve()
        if not src.exists():
            failed.append({"feature_id": f.feature_id, "reason": "missing .dfy"})
            continue
        out_base = (out_dir / f.module).resolve()
        try:
            # --no-verify: already proved.  --allow-warnings: Dafny exits non-zero on STYLE
            # warnings even when translation succeeds, so we must not let those fail it.
            proc = subprocess.run(
                [dafny, "translate", target, "--no-verify", "--allow-warnings",
                 "--include-runtime", "-o", str(out_base), str(src)],
                capture_output=True, text=True, timeout=timeout, cwd=str(project_dir),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            failed.append({"feature_id": f.feature_id, "reason": str(exc)[:160]})
            continue
        # dafny writes either <base>.<ext> or a <base>-<target>/ directory depending on backend.
        produced = sorted(p for p in out_dir.glob(f"{f.module}*") if p != src)
        if proc.returncode == 0 and produced:
            compiled.append({"feature_id": f.feature_id, "target": target,
                             "output": str(produced[0])})
        else:
            failed.append({"feature_id": f.feature_id,
                           "reason": ("dafny translate: " + (proc.stderr or proc.stdout or "failed")).strip()[:160]})
    return {"target": target, "compiled": compiled, "failed": failed}
