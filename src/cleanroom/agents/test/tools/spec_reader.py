"""Spec reader for the Test Agent.

Deterministic, no LLM. Reads spec-stage IR slices only — never generated code:

  * ir['features']  — functional requirements (WHAT)
  * ir['planning']  — planned interface + canonical I/O (same source the Code Agent uses)

Planning is spec-derived (authored before code exists), so anchoring tests to
planning I/O preserves clean-room isolation while keeping tests aligned with code contracts.
"""

from src.cleanroom.utils.contracts import planning_by_fr, requirement_for_prompt
from src.cleanroom.utils.ir import feature_id_of


def feature_of(req_id: str) -> str:
    """Feature id is the first two dot-segments of a requirement id: '2.2.6.6' -> '2.2'."""
    return ".".join(req_id.split(".")[:2])


def feature_units(ir: dict) -> list[dict]:
    """Slice the IR into one scoped unit per feature for test generation."""
    plans = planning_by_fr(ir)
    units: list[dict] = []
    for feature in ir.get("features", []):
        requirements = feature.get("functional_requirements", [])
        if not requirements:
            continue
        reqs_out = [
            requirement_for_prompt(r, plans.get(r["id"]))
            for r in requirements
        ]
        units.append(
            {
                "feature_id": feature_id_of(feature) or feature_of(requirements[0]["id"]),
                "name": feature.get("name", ""),
                "description": feature.get("description", ""),
                "requirements": reqs_out,
            }
        )
    return units
