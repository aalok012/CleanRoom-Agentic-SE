"""Shared planning-contract helpers — single source for field names across agents."""

from __future__ import annotations

from src.cleanroom.utils.ir import (
    feature_id_of,
    normalize_generated_tests,
    normalize_ir,
    normalize_ir_features,
    requirement_text,
)


def planning_by_fr(ir: dict) -> dict[str, dict]:
    """Map fr_id -> planning contract dict."""
    return {c["fr_id"]: c for c in (ir.get("planning") or {}).get("contracts", [])}


def route_for(file_path: str) -> str:
    """Deterministic HTTP route for a generated module on the FastAPI stack.

    The packager mounts each router under ``/{layer}/{module_stem}`` and the Code Agent
    decorates with ``@router.post("")``, so the route is exactly the prefix:
    ``controllers/manage_staff_records.py`` -> ``/controllers/manage_staff_records``.
    Mirrors evaluation.runner.route_from_file_path so tests and the cert oracle agree.
    """
    p = file_path[:-3] if file_path.endswith(".py") else file_path
    return "/" + p.strip("/") if p else ""


def requirement_for_prompt(fr: dict, plan: dict | None = None) -> dict:
    """Merge an FR with its planning contract for Jinja prompts (test/planning).

    Also surfaces the spec-derived behavioral-contract fields (stimulus/precondition/
    response/postcondition) carried on ``plan['contract']`` so the test prompt can design
    branch/edge cases from them. All inputs are spec-derived — never code — so isolation holds.
    """
    plan = plan or {}
    file_path = plan.get("file_path", "")
    bc = plan.get("contract") or {}
    return {
        "id": fr["id"],
        "text": requirement_text(fr),
        "signature": plan.get("signature", ""),
        "file_path": file_path,
        "route": route_for(file_path),
        "example_inputs_json": plan.get("example_inputs_json", "{}"),
        "expected_return_json": plan.get("expected_return_json", "null"),
        "failure_inputs_json": plan.get("failure_inputs_json", ""),
        "error_mode": plan.get("error_mode", "raise"),
        "entity_identifier": plan.get("entity_identifier", ""),
        "stimulus": bc.get("stimulus", ""),
        "precondition": bc.get("precondition", ""),
        "response": bc.get("response", ""),
        "postcondition": bc.get("postcondition", ""),
    }


def prereq_ifaces(contract: dict, by_fr: dict) -> list[dict]:
    """Prerequisite metadata for code/verification prompts (spec-derived only)."""
    return [
        {
            "fr_id": pid,
            "layer": by_fr[pid]["mvc_layer"],
            "signature": by_fr[pid]["signature"],
            "file_path": by_fr[pid]["file_path"],
            "example_inputs_json": by_fr[pid].get("example_inputs_json", "{}"),
        }
        for pid in contract.get("prerequisite_fr_ids", [])
        if pid in by_fr
    ]
