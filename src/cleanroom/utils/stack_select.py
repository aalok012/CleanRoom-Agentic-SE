"""Deterministic target-stack selection from the specification.

The pipeline supports two delivered-artifact shapes:

  * ``python``  — plain, framework-free importable functions. Right for SRSs whose
    requirements are stateless computation/query (search, sort, rank, convert,
    validate): each FR is a pure function and the function oracle certifies it directly.

  * ``fastapi`` — a runnable FastAPI + SQLAlchemy web app with a shared persistence
    layer. Right for SRSs that create/read/update/delete records, authenticate users,
    or otherwise carry state ACROSS requests (orders, menus, staff, bookings): these
    cannot be honestly modelled as isolated pure functions (that is what produced the
    DineOut fake-in-memory-state and hardcoded data), so they target a real DB-backed app.

Selection is DETERMINISTIC — a keyword vote over the spec-derived requirement text and
contracts — so the choice is reproducible and explainable, and never an extra LLM call.
It reads ONLY the spec (features + behavioral contracts); it never touches tests or code,
so isolation is unaffected. ``run_pipeline`` calls this when ``--stack auto`` (the default)
and an explicit ``--stack python|fastapi`` always overrides it.
"""

from __future__ import annotations

import re

from src.cleanroom.utils.ir import feature_id_of, requirement_text

# Signals that an FR mutates/persists shared state or gates on an authenticated actor —
# i.e. behaviour that needs a real datastore that outlives a single call.
_STATEFUL = (
    "add", "create", "register", "edit", "update", "modify", "delete", "remove",
    "cancel", "submit", "save", "store", "record", "persist", "insert", "assign",
    "approve", "reject", "book", "reserve", "order", "checkout", "pay", "payment",
    "manage", "authenticate", "login", "log in", "sign in", "permission", "account",
    "profile", "database", "inventory", "menu", "staff", "notify", "notification",
    "mark", "schedule", "enroll", "upload",
)
# Signals that an FR is a stateless transform/query over its inputs.
_STATELESS = (
    "search", "sort", "filter", "rank", "match", "compute", "calculate", "convert",
    "parse", "validate", "format", "transform", "recommend", "analyze", "score",
    "compare", "translate", "summarize", "detect", "classify", "lookup", "query",
)


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z]+", (text or "").lower())


def _fr_is_stateful(text: str, precondition: str) -> bool:
    """One FR votes 'stateful' if its requirement text leans CRUD/persistence, or it has a
    real (authenticated/permission) precondition with no offsetting stateless signal."""
    words = set(_words(text))
    stateful_hits = sum(1 for kw in _STATEFUL if kw in words or kw in text.lower())
    stateless_hits = sum(1 for kw in _STATELESS if kw in words)
    if stateful_hits > stateless_hits:
        return True
    pre = (precondition or "").strip().lower()
    gated = pre not in ("", "none", "n/a", "na") and any(
        kw in pre for kw in ("authenticat", "permission", "logged in", "admin", "authoriz")
    )
    return gated and stateless_hits == 0


def select_stack(ir: dict, threshold: float = 0.34) -> tuple[str, str]:
    """Return (stack, human-readable reason) for the spec.

    fastapi when at least ``threshold`` of functional requirements look stateful/CRUD;
    otherwise python. The reason string is logged so the choice is auditable.
    """
    contracts_by_fr = {c.get("fr_id"): c for c in ir.get("contracts", [])}
    total = 0
    stateful = 0
    for feature in ir.get("features", []):
        for req in feature.get("functional_requirements", []):
            total += 1
            bc = contracts_by_fr.get(req["id"], {})
            if _fr_is_stateful(requirement_text(req), bc.get("precondition", "")):
                stateful += 1

    if total == 0:
        return "python", "no functional requirements found; defaulting to python"

    ratio = stateful / total
    if ratio >= threshold:
        return (
            "fastapi",
            f"{stateful}/{total} requirements ({ratio:.0%}) are stateful/CRUD "
            f"≥ {threshold:.0%} → DB-backed web app",
        )
    return (
        "python",
        f"only {stateful}/{total} requirements ({ratio:.0%}) are stateful "
        f"< {threshold:.0%} → stateless functions",
    )
