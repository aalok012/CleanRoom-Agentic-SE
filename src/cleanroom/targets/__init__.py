"""Language targets — per-language knobs (codegen/test templates, packaging, oracle).

`get_target(language, stack)` returns the `LanguageTarget` the agents dispatch through, so adding a
language (or a web stack under one) is a new subclass + its prompts, not edits scattered across the
agents. `stack` distinguishes web stacks that share a language: under `java`, `spring` selects the
Spring Boot stack, anything else the plain-Java stack (the python stacks are handled inside the
base target's stack-taking methods).
"""

from src.cleanroom.targets.base import LanguageTarget
from src.cleanroom.targets.java import JavaTarget
from src.cleanroom.targets.js import JsTarget
from src.cleanroom.targets.spring import SpringBootTarget

_PY = LanguageTarget()
_JAVA = JavaTarget()
_SPRING = SpringBootTarget()
_JS = JsTarget()


def get_target(language: str, stack: str | None = None) -> LanguageTarget:
    if language == "java":
        return _SPRING if stack == "spring" else _JAVA
    if language == "javascript":
        return _JS
    return _PY


__all__ = ["LanguageTarget", "JavaTarget", "JsTarget", "SpringBootTarget", "get_target"]
