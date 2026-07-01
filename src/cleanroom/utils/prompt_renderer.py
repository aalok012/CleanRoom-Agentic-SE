from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

_PROMPTS_ROOT = Path(__file__).parent.parent / "agents"


def cot_template(template_name: str, prompt_strategy: str) -> str:
    """Map a base template name to its parallel reasoning variant for the active prompt strategy.

    - ``cot``  -> ``<base>_cot.j2`` when that variant exists on disk, else the base name.
    - ``mot``  -> ``<base>_mot.j2`` if present, else ``<base>_cot.j2`` if present, else the base
      name. This is the ``_mot`` -> ``_cot`` -> baseline fallback chain: a stage only gets the
      Module-of-Thought prompt when a ``_mot`` file was authored for it (Planning, Code, Test);
      every other stage (Spec, Dependency, Dafny proof track, adapters, feedback, compile-repair)
      transparently falls back to its CoT prompt, then to the original.
    - any other value (``baseline``, …) -> the base name unchanged (byte-for-byte identical path).

    Variants are parallel files resolved by the same rglob lookup as the originals; nothing is
    overwritten and the rendered context (template variables) is identical across strategies.
    """
    if not template_name.endswith(".j2"):
        return template_name
    base = template_name[:-3]
    if prompt_strategy == "mot":
        candidates = (base + "_mot.j2", base + "_cot.j2")
    elif prompt_strategy == "cot":
        candidates = (base + "_cot.j2",)
    else:
        return template_name
    for candidate in candidates:
        if next(_PROMPTS_ROOT.rglob(candidate), None) is not None:
            return candidate
    return template_name


class PromptRenderer:
    def __init__(self) -> None:
        self.env = Environment(
            loader=FileSystemLoader(str(_PROMPTS_ROOT)),
            undefined=StrictUndefined,
            autoescape=False,
        )

    def render(self, template_name: str, context: dict) -> str:
        # searches recursively under agents/ for the template filename
        matches = list(_PROMPTS_ROOT.rglob(template_name))
        if not matches:
            raise FileNotFoundError(f"Prompt template '{template_name}' not found under {_PROMPTS_ROOT}")
        relative = matches[0].relative_to(_PROMPTS_ROOT)
        template = self.env.get_template(str(relative))
        return template.render(**context)
