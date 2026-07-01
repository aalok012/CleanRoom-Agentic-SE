"""Assemble isolated per-FR Spring controllers into a runnable Maven Spring Boot project.

The Code Agent emits one self-contained ``@RestController`` per functional requirement (a flat
``GeneratedCode`` with ``files``), each with NO package statement. This step lays them out as a
buildable Maven project and adds fixed scaffolding — a ``pom.xml``, an ``application.properties``,
and a ``@SpringBootApplication`` main class. Spring's classpath **component scanning** from the
base package then auto-registers every controller, so this step never writes per-feature wiring.

It is MECHANICAL only — it injects a ``package`` line, lays out files, and writes fixed
scaffolding, never program logic — so the Code/Test isolation of the pipeline is unaffected (the
exact analog of the FastAPI ``packager.build_runnable_package``).

Each FR's class is placed in its OWN sub-package (``...gen.g<fr_slug>``) so that classes that the
isolated generations happened to name identically never collide at compile time.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from src.cleanroom.utils.java_packager import java_class_name

BASE_PACKAGE = "com.cleanroom.app"
GEN_PACKAGE = BASE_PACKAGE + ".gen"

_PACKAGE_LINE = re.compile(r"^\s*package\s+[\w.]+\s*;\s*$", re.MULTILINE)

_POM_XML = f"""<?xml version="1.0" encoding="UTF-8"?>
<project xmlns="http://maven.apache.org/POM/4.0.0"
         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
         xsi:schemaLocation="http://maven.apache.org/POM/4.0.0 https://maven.apache.org/xsd/maven-4.0.0.xsd">
  <modelVersion>4.0.0</modelVersion>
  <parent>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-parent</artifactId>
    <version>3.3.4</version>
    <relativePath/>
  </parent>
  <groupId>com.cleanroom</groupId>
  <artifactId>generated-app</artifactId>
  <version>0.0.1-SNAPSHOT</version>
  <name>generated-app</name>
  <properties>
    <java.version>17</java.version>
  </properties>
  <dependencies>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-web</artifactId>
    </dependency>
    <dependency>
      <groupId>org.springframework.boot</groupId>
      <artifactId>spring-boot-starter-test</artifactId>
      <scope>test</scope>
    </dependency>
  </dependencies>
  <build>
    <plugins>
      <plugin>
        <groupId>org.springframework.boot</groupId>
        <artifactId>spring-boot-maven-plugin</artifactId>
      </plugin>
    </plugins>
  </build>
</project>
"""

_APPLICATION_JAVA = f"""package {BASE_PACKAGE};

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * Application entry point — generated mechanically by the pipeline's Spring packager.
 * {{@code @SpringBootApplication}} component-scans {BASE_PACKAGE}, so every generated
 * {{@code @RestController}} under {GEN_PACKAGE} is auto-registered. No business logic lives here.
 *
 * Run with:  mvn spring-boot:run
 */
@SpringBootApplication
public class Application {{
    public static void main(String[] args) {{
        SpringApplication.run(Application.class, args);
    }}
}}
"""

_APPLICATION_PROPERTIES = (
    "# Generated mechanically by the Spring packager.\n"
    "spring.application.name=generated-app\n"
    "server.port=8080\n"
)


def _fr_slug(fr_id: str, index: int) -> str:
    """A valid Java package segment for an FR id (e.g. '2.2.1' -> 'g2_2_1')."""
    raw = re.sub(r"\W", "_", str(fr_id) if fr_id not in (None, "") else f"i{index}")
    return "g" + raw


def _strip_package(content: str) -> str:
    """Remove any leading ``package ...;`` line the model may have emitted (we inject our own)."""
    return _PACKAGE_LINE.sub("", content, count=1).lstrip("\n")


def _files_of(generated_code: dict) -> list[dict]:
    """The flat ``files`` list, tolerating the legacy ``increments`` shape."""
    return generated_code.get("files") or [
        f for inc in generated_code.get("increments", []) for f in inc.get("files", [])
    ]


def write_spring_sources(generated_code: dict, project_dir: Path) -> list[Path]:
    """Write each generated controller under src/main/java/com/cleanroom/app/gen/g<fr>/<Class>.java.

    Each file gets its own sub-package so identically-named classes from isolated generations do
    not collide. Returns the written paths.
    """
    gen_root = project_dir / "src" / "main" / "java" / Path(*GEN_PACKAGE.split("."))
    if gen_root.exists():
        shutil.rmtree(gen_root)
    written: list[Path] = []
    for i, f in enumerate(_files_of(generated_code)):
        content = _strip_package(f.get("content", ""))
        fallback = "Gen" + re.sub(r"\W", "_", str(f.get("fr_id", i)))
        cls = java_class_name(content, fallback)
        slug = _fr_slug(f.get("fr_id", ""), i)
        pkg = f"{GEN_PACKAGE}.{slug}"
        pkg_dir = gen_root / slug
        pkg_dir.mkdir(parents=True, exist_ok=True)
        dest = pkg_dir / f"{cls}.java"
        dest.write_text(f"package {pkg};\n\n{content}\n")
        written.append(dest)
    return written


def write_spring_tests(generated_tests: dict, project_dir: Path) -> list[Path]:
    """Write generated MockMvc/JUnit tests under src/test/java so Maven compiles them.

    The Test Agent emits no package statement by design. Spring tests are placed in the app's base
    package so ``@SpringBootTest`` can discover ``Application`` through normal package scanning.
    """
    test_root = (Path(project_dir) / "src" / "test" / "java" /
                 Path(*BASE_PACKAGE.split(".")))
    if test_root.exists():
        shutil.rmtree(test_root)
    test_root.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    used: set[str] = set()
    for i, feature in enumerate(generated_tests.get("features", [])):
        slug = str(feature.get("feature_id", i)).replace(".", "_")
        source = _strip_package((feature.get("test_source") or "").strip())
        if not source:
            source = (f"// No Spring/JUnit source generated for feature "
                      f"{feature.get('feature_id', slug)}; "
                      f"{len(feature.get('cases', []))} case(s) recorded in the IR.\n")
        cls = java_class_name(source, f"Feature_{slug}Test")
        dest_name = cls if cls not in used else f"{cls}_{i}"
        used.add(dest_name)
        dest = test_root / f"{dest_name}.java"
        dest.write_text(f"package {BASE_PACKAGE};\n\n{source}\n")
        written.append(dest)
    return written


def build_spring_project(generated_code: dict, out_dir: Path) -> Path:
    """Assemble generated_code into out_dir as a runnable Maven Spring Boot project. Returns out_dir.

    Lays out the fixed scaffolding (pom.xml, application main, properties) plus every generated
    controller. Mechanical only — never touches program logic — so isolation holds.
    """
    out = Path(out_dir)
    app_pkg_dir = out / "src" / "main" / "java" / Path(*BASE_PACKAGE.split("."))
    app_pkg_dir.mkdir(parents=True, exist_ok=True)
    resources = out / "src" / "main" / "resources"
    resources.mkdir(parents=True, exist_ok=True)

    (out / "pom.xml").write_text(_POM_XML)
    (app_pkg_dir / "Application.java").write_text(_APPLICATION_JAVA)
    (resources / "application.properties").write_text(_APPLICATION_PROPERTIES)

    write_spring_sources(generated_code, out)
    return out


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) != 2:
        print("usage: python -m src.cleanroom.utils.spring_packager <full_ir.json>")
        sys.exit(1)

    with open(sys.argv[1], encoding="utf-8") as fh:
        ir = json.load(fh)
    if "generated_code" not in ir:
        print("IR has no 'generated_code' — run the pipeline (with the LLM stages) first.")
        sys.exit(1)

    out_dir = Path("outputs/generated") / ir.get("project_name", "project") / "spring"
    project = build_spring_project(ir["generated_code"], out_dir)
    print(f"Runnable Spring Boot project written to: {project}")
    print("Build/run it with:")
    print(f'  cd "{project}"')
    print("  mvn spring-boot:run")
