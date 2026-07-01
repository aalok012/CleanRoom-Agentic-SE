"""Execute spec-derived test cases against generated code in an isolated subprocess."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import textwrap
from pathlib import Path

_RUNNER_SCRIPT = textwrap.dedent(
    '''
    import importlib.util
    import json
    import sys
    from pathlib import Path

    code_root = Path(sys.argv[1])
    file_path = sys.argv[2]
    func_name = sys.argv[3]
    inputs_json = sys.argv[4]
    expected_json = sys.argv[5]
    oracle = sys.argv[6]

    sys.path.insert(0, str(code_root))
    module_path = code_root / file_path
    spec = importlib.util.spec_from_file_location("candidate_mod", module_path)
    if spec is None or spec.loader is None:
        print(json.dumps({"pass": False, "reason": f"cannot load {file_path}"}))
        raise SystemExit(0)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fn = getattr(mod, func_name, None)
    if fn is None:
        print(json.dumps({"pass": False, "reason": f"function {func_name} not found in {file_path}"}))
        raise SystemExit(0)

    inputs = json.loads(inputs_json)

    def normalize(value):
        if isinstance(value, dict):
            return {str(k): normalize(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [normalize(v) for v in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if hasattr(value, "__dict__"):
            return normalize(vars(value))
        return str(value)

    try:
        if oracle == "raises":
            expected = json.loads(expected_json)
            exc_name = expected.get("raises", "ValueError")
            try:
                fn(**inputs)
                print(json.dumps({"pass": False, "reason": f"expected {exc_name} but no exception raised"}))
            except Exception as exc:
                ok = type(exc).__name__ == exc_name
                reason = type(exc).__name__ if ok else f"got {type(exc).__name__}, expected {exc_name}"
                print(json.dumps({"pass": ok, "reason": reason}))
        else:
            result = normalize(fn(**inputs))
            expected = normalize(json.loads(expected_json))
            ok = result == expected
            reason = "match" if ok else f"got {result!r}, expected {expected!r}"
            print(json.dumps({"pass": ok, "reason": reason}))
    except Exception as exc:
        print(json.dumps({"pass": False, "reason": f"execution error: {type(exc).__name__}: {exc}"}))
    '''
)


_HTTP_RUNNER_SCRIPT = textwrap.dedent(
    '''
    import json
    import os
    import sys
    from pathlib import Path

    out_dir = Path(sys.argv[1])   # dir containing the assembled app/ package
    route = sys.argv[2]
    inputs_json = sys.argv[3]
    expected_json = sys.argv[4]
    oracle = sys.argv[5]
    setup_json = sys.argv[6] if len(sys.argv) > 6 else "[]"

    # cwd = the package dir so the app's sqlite:///./app.db is private to this sample.
    os.chdir(out_dir)
    sys.path.insert(0, str(out_dir))

    def normalize(value):
        if isinstance(value, dict):
            return {str(k): normalize(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [normalize(v) for v in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    try:
        from app import create_app
        from fastapi.testclient import TestClient
        client = TestClient(create_app())
        # Arrange: replay the spec-derived setup calls so the precondition state exists
        # (the shared sqlite file persists across these calls and the main call below).
        for i, step in enumerate(json.loads(setup_json or "[]")):
            step_route = step.get("route") or route
            step_resp = client.post(step_route, json=step.get("inputs", {}))
            if step_resp.status_code >= 400:
                print(json.dumps({"pass": False, "reason":
                    f"setup step {i} ({step_route}) failed: HTTP {step_resp.status_code}: {step_resp.text[:120]}"}))
                raise SystemExit(0)
        # Act: the call under test.
        inputs = json.loads(inputs_json)
        resp = client.post(route, json=inputs)
    except SystemExit:
        raise
    except Exception as exc:
        print(json.dumps({"pass": False, "reason": f"app boot/request error: {type(exc).__name__}: {exc}"}))
        raise SystemExit(0)

    if oracle == "raises":
        # An HTTP error status is the web equivalent of a raised precondition failure.
        ok = resp.status_code >= 400
        print(json.dumps({"pass": ok, "reason": f"HTTP {resp.status_code}"}))
    elif resp.status_code != 200:
        print(json.dumps({"pass": False, "reason": f"HTTP {resp.status_code}: {resp.text[:160]}"}))
    else:
        try:
            body = normalize(resp.json())
        except Exception:
            print(json.dumps({"pass": False, "reason": f"non-JSON response: {resp.text[:160]}"}))
            raise SystemExit(0)
        expected = normalize(json.loads(expected_json))
        ok = body == expected
        reason = "match" if ok else f"got {body!r}, expected {expected!r}"
        print(json.dumps({"pass": ok, "reason": reason}))
    '''
)


_JS_RUNNER_SCRIPT = textwrap.dedent(
    """
    'use strict';
    const path = require('path');
    const codeRoot = process.argv[1];
    const filePath = process.argv[2];
    const funcName = process.argv[3];
    const inputsJson = process.argv[4];
    const expectedJson = process.argv[5];
    const oracle = process.argv[6];

    function canon(v) {
      if (Array.isArray(v)) return v.map(canon);
      if (v && typeof v === 'object') {
        const o = {};
        for (const k of Object.keys(v).sort()) o[k] = canon(v[k]);
        return o;
      }
      return v;
    }
    function eq(a, b) { return JSON.stringify(canon(a)) === JSON.stringify(canon(b)); }
    function out(pass, reason) {
      console.log(JSON.stringify({ pass: pass, reason: String(reason) }));
      process.exit(0);
    }

    let mod;
    try {
      mod = require(path.resolve(codeRoot, filePath));
    } catch (e) {
      out(false, 'cannot load ' + filePath + ': ' + ((e && e.message) || e));
    }
    let fn = mod && mod[funcName];
    if (typeof fn !== 'function') {
      fn = mod && Object.values(mod).find((x) => typeof x === 'function');
    }
    if (typeof fn !== 'function') {
      out(false, 'function ' + funcName + ' not found in ' + filePath);
    }

    let inputs;
    try { inputs = JSON.parse(inputsJson); } catch (e) { out(false, 'bad inputs json'); }

    try {
      if (oracle === 'raises') {
        let threw = false;
        try { fn(inputs); } catch (e) { threw = true; }
        out(threw, threw ? 'threw' : 'expected throw but none');
      } else {
        const result = fn(inputs);
        const expected = JSON.parse(expectedJson);
        const ok = eq(result, expected);
        out(ok, ok ? 'match'
          : ('got ' + JSON.stringify(canon(result)) + ', expected ' + JSON.stringify(canon(expected))));
      }
    } catch (e) {
      out(false, 'execution error: ' + ((e && e.message) || e));
    }
    """
)


def run_case_js(code_dir: Path, plan: dict, case: dict, timeout: float = 30.0) -> tuple[bool, str]:
    """In-process JS oracle: load the generated module under Node and call the contract function.

    Mirrors the Python ``run_case`` executable oracle — the generated FR module exports a PURE,
    stdlib-only function named per the contract, so Node can ``require`` it and call it directly
    (no Express, no DB, no ``npm install``). The function takes a single object argument (the
    inputs JSON). Gracefully reports when Node is absent.
    """
    from src.cleanroom.utils.js_tooling import node_path
    from src.cleanroom.utils.js_packager import js_file_path

    node = node_path()
    if node is None:
        return False, "node not found (install Node.js or set $NODE)"

    func_name = func_name_from_signature(plan.get("signature", ""))
    if not func_name:
        return False, "no function name in signature"

    file_path = js_file_path(plan.get("file_path", ""))
    inputs_json = case.get("inputs_json") or "{}"
    expected_json = case.get("expected_json") or "null"
    oracle = case.get("oracle") or "eq"

    try:
        json.loads(inputs_json)
        json.loads(expected_json)
    except json.JSONDecodeError as exc:
        return False, f"invalid test JSON: {exc}"

    try:
        proc = subprocess.run(
            [node, "-e", _JS_RUNNER_SCRIPT, str(code_dir), file_path, func_name,
             inputs_json, expected_json, oracle],
            capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return False, f"node timed out after {timeout:.0f}s"
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"node error: {str(exc)[:200]}"

    line = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return False, (proc.stderr or proc.stdout or "no result")[:300]
    return bool(payload.get("pass")), str(payload.get("reason", ""))


def route_from_file_path(file_path: str) -> str:
    """The HTTP route the packager registers for a generated module.

    build_runnable_package() mounts each router under prefix ``/{layer}/{module_stem}`` and
    the Code Agent decorates with ``@router.post("")``, so the full route is deterministic:
    ``controllers/manage_menu_items.py`` -> ``/controllers/manage_menu_items``.
    """
    p = file_path[:-3] if file_path.endswith(".py") else file_path
    return "/" + p.strip("/")


def run_case_http(out_dir: Path, file_path: str, case: dict, timeout: float = 30.0) -> tuple[bool, str]:
    """Run one structured test case against the assembled FastAPI app via TestClient.

    Posts the case's canonical inputs to the module's route and checks the JSON response
    (oracle ``eq``) or that the call returns a 4xx error status (oracle ``raises``).
    """
    route = route_from_file_path(file_path)
    inputs_json = case.get("inputs_json") or "{}"
    expected_json = case.get("expected_json") or "null"
    oracle = case.get("oracle") or "eq"
    setup_json = (case.get("setup_json") or "").strip() or "[]"

    try:
        json.loads(inputs_json)
        json.loads(expected_json)
        json.loads(setup_json)
    except json.JSONDecodeError as exc:
        return False, f"invalid test JSON: {exc}"

    proc = subprocess.run(
        [sys.executable, "-c", _HTTP_RUNNER_SCRIPT,
         str(out_dir), route, inputs_json, expected_json, oracle, setup_json],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0 and not proc.stdout.strip():
        err = (proc.stderr or proc.stdout or "subprocess failed").strip()
        return False, err[:300]

    line = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return False, (proc.stdout or proc.stderr or "no result")[:300]
    return bool(payload.get("pass")), str(payload.get("reason", ""))


def func_name_from_signature(signature: str) -> str | None:
    match = re.search(r"def\s+([A-Za-z_]\w*)", signature or "")
    return match.group(1) if match else None


def run_case(
    code_dir: Path,
    file_path: str,
    signature: str,
    case: dict,
    timeout: float = 10.0,
) -> tuple[bool, str]:
    """Run one structured test case. Returns (passed, reason)."""
    func_name = func_name_from_signature(signature)
    if not func_name:
        return False, "no function name in signature"

    inputs_json = case.get("inputs_json") or "{}"
    expected_json = case.get("expected_json") or "null"
    oracle = case.get("oracle") or "eq"

    try:
        json.loads(inputs_json)
        json.loads(expected_json)
    except json.JSONDecodeError as exc:
        return False, f"invalid test JSON: {exc}"

    proc = subprocess.run(
        [sys.executable, "-c", _RUNNER_SCRIPT, str(code_dir), file_path, func_name, inputs_json, expected_json, oracle],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0 and not proc.stdout.strip():
        err = (proc.stderr or proc.stdout or "subprocess failed").strip()
        return False, err[:300]

    line = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return False, (proc.stdout or proc.stderr or "no result")[:300]

    return bool(payload.get("pass")), str(payload.get("reason", ""))


def run_case_java(code_dir: Path, plan: dict, case: dict, timeout: float = 30.0) -> tuple[bool, str]:
    """v1 Java oracle: compile-check candidate Java and generated JUnit tests → (passed, reason).

    Generated Java must be stdlib-only (java.util), so a clean compile means the codegen produced
    well-typed Java for this FR. Generated JUnit test sources are compiled too when present. Full
    per-case JUnit *execution* remains a documented follow-up.
    """
    from src.cleanroom.utils.java_tooling import javac_path, junit_jar

    javac = javac_path()
    if javac is None:
        return False, "javac not found (set $JAVAC or install a JDK)"

    src = Path(code_dir) / "src"
    java_paths = sorted(src.glob("*.java"))
    java_files = [str(p) for p in java_paths]
    if not java_files:
        return False, "no Java sources to compile"
    test_files = [p for p in java_paths if p.name.endswith("Test.java")]

    classes = Path(code_dir) / "classes"
    classes.mkdir(parents=True, exist_ok=True)
    cmd = [javac, "-d", str(classes)]
    jar = junit_jar()
    if test_files and jar is None:
        return False, "JUnit test sources present but JUNIT_JAR was not found"
    if jar is not None:
        cmd += ["-cp", str(jar)]
    cmd += java_files
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"javac error: {str(exc)[:200]}"

    if proc.returncode != 0:
        return False, "javac: " + (proc.stderr or proc.stdout or "compile failed").strip()[:300]
    if test_files:
        return True, "compiled OK (v1 oracle: javac + JUnit test compile-check; execution deferred)"
    return True, "compiled OK (v1 oracle: javac compile-check; no JUnit tests found)"


# Cache the build verdict per assembled project dir: the build outcome is independent of the
# individual test case, so we compile each sample's Spring project once and reuse the verdict for
# all of its cases (mirrors how run_case_java's compile-check is identical across cases).
_SPRING_BUILD_CACHE: dict[str, tuple[bool, str]] = {}


def run_case_spring(code_dir: Path, plan: dict, case: dict, timeout: float = 180.0) -> tuple[bool, str]:
    """v1 Spring oracle: test-compile the assembled Maven Spring Boot project → (passed, reason).

    A clean ``mvn test-compile`` means the isolated controllers and generated MockMvc/JUnit tests
    assembled into a well-typed Spring app. The build outcome is the same for every case of a
    sample, so it is computed once per project dir and cached. In-process MockMvc execution of each
    case remains deferred; this is a static compile check.
    """
    from src.cleanroom.utils.maven_tooling import mvn_path

    key = str(Path(code_dir).resolve())
    if key in _SPRING_BUILD_CACHE:
        return _SPRING_BUILD_CACHE[key]

    mvn = mvn_path()
    if mvn is None:
        return False, "mvn not found (set $MVN or install Maven)"
    if not (Path(code_dir) / "pom.xml").is_file():
        return False, "no pom.xml — Spring project was not assembled"

    cmd = [mvn, "-B", "-q", "-Dstyle.color=never", "test-compile"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(code_dir))
    except subprocess.TimeoutExpired:
        result = (False, f"mvn test-compile timed out after {timeout:.0f}s")
        _SPRING_BUILD_CACHE[key] = result
        return result
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"mvn error: {str(exc)[:200]}"

    if proc.returncode != 0:
        tail = (proc.stdout or "") + (proc.stderr or "")
        result = (False, "mvn test-compile: " + tail.strip()[-300:])
    else:
        result = (True, "built OK (v1 oracle: mvn test-compile; MockMvc execution deferred)")
    _SPRING_BUILD_CACHE[key] = result
    return result


def run_pytest_module(code_dir: Path, test_file: Path, timeout: float = 60.0) -> tuple[bool, str]:
    """Optional: run a pytest module with PYTHONPATH=code_dir."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(test_file), "-q", "--tb=line"],
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=test_file.parent,
        env={**__import__("os").environ, "PYTHONPATH": str(code_dir)},
    )
    ok = proc.returncode == 0
    summary = (proc.stdout or proc.stderr or "").strip().splitlines()
    reason = summary[-1] if summary else ("passed" if ok else "pytest failed")
    return ok, reason[:300]
