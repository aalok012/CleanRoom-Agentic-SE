import json
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from src.cleanroom.agents.spec_agent.schema.ir import BehavioralContract


class _JsonStrFields(BaseModel):
    """Mixin: coerce the `*_json` fields that hold JSON-as-a-string.

    These fields are typed `str` (they carry serialized JSON), but capable models — Sonnet,
    GPT-5, etc. — naturally return *real* JSON for them (e.g. the list ``[{"id": 1}]`` instead
    of the string ``'[{"id": 1}]'``). That fails strict `str` validation and the whole structured
    call comes back unparsed (a None that then crashes the agent). We json.dumps any non-string
    value back into a string so validation passes regardless of how the model formatted it.
    """

    @field_validator(
        "example_inputs_json", "expected_return_json", "failure_inputs_json",
        mode="before", check_fields=False,
    )
    @classmethod
    def _coerce_json_to_str(cls, v):
        if isinstance(v, str):
            return v
        try:
            return json.dumps(v)
        except (TypeError, ValueError):
            return str(v)


class Contract(_JsonStrFields):
    """An implementation contract for ONE functional requirement.

    Built by attaching implementation metadata to the spec-derived behavioral contract.
    Signature and the MVC layer come from LLM interpretation; the docstring is composed
    deterministically (Google style) from the behavioral contract; file_path is derived
    from the layer, and prerequisite_fr_ids come from the FR-level dependency edges.
    """

    fr_id: str = Field(description="Functional requirement id, from the parser — never invented")
    feature_id: str = Field(description="Owning feature id")
    signature: str = Field(description="Concrete function signature: name, typed params, return type")
    docstring: str = Field(description="Google-style docstring composed from the behavioral contract")
    mvc_layer: Literal["model", "view", "controller"] = Field(description="'model' | 'view' | 'controller'")
    file_path: str = Field(description="Deterministic path derived from the MVC layer")
    prerequisite_fr_ids: list[str] = Field(
        default_factory=list, description="FRs (same feature) that must be built first — from fr_edges"
    )
    contract: BehavioralContract | None = Field(
        default=None, description="The spec-derived behavioral contract this implementation realizes"
    )
    example_inputs_json: str = Field(
        default="{}",
        description="JSON object of keyword arguments for a canonical happy-path call",
    )
    expected_return_json: str = Field(
        default="null",
        description="JSON value the function should return on the happy path",
    )
    error_mode: Literal["raise", "return"] = Field(
        default="raise",
        description="How precondition violations are signaled: raise ValueError or return an error dict",
    )
    failure_inputs_json: str = Field(
        default="",
        description="JSON kwargs for a precondition-violation call, or empty if none",
    )
    entity_identifier: str = Field(
        default="",
        description=(
            "For a stateful CRUD requirement (create/edit/delete/look up a PERSISTED entity), "
            "the single field that uniquely keys that entity for lookup — e.g. 'id' or 'name'. "
            "Both the code (lookup key) and the tests (seed-then-reference) use it, so they agree. "
            "Empty for stateless requirements or pure computations with no persisted entity."
        ),
    )


class PlanningOutput(BaseModel):
    contracts: list[Contract] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Per-feature LLM design result (used with with_structured_output()).
# The LLM designs the implementation surface (signature, layer, per-arg/return
# docs) from the behavioral contract; ids always come from the parser/spec stages.
# ---------------------------------------------------------------------------
class ArgDoc(BaseModel):
    """One parameter's documentation, for the docstring's Args section."""

    name: str = Field(description="Parameter name — must match a parameter in the signature exactly")
    description: str = Field(description="What this parameter is and any constraints on it")


class FRPlan(_JsonStrFields):
    id: str = Field(description="The requirement id, echoed VERBATIM from the input — never changed or invented")
    signature: str = Field(description="One-line function signature in Python syntax: name, typed params, "
                           "return type. Canonical, language-neutral interface — codegen realizes it in the "
                           "run's target language (e.g. translated to Java).")
    args: list[ArgDoc] = Field(
        default_factory=list, description="One entry per signature parameter (omit if the signature takes none)"
    )
    returns: str = Field(default="", description="What the function returns (leave empty for a None return)")
    mvc_layer: Literal["model", "view", "controller"] = Field(description="EXACTLY one of: model, view, controller")
    example_inputs_json: str = Field(
        description='JSON object mapping parameter names to JSON-serializable values, e.g. {"query": "pizza"}'
    )
    expected_return_json: str = Field(
        description='JSON value returned on the happy path, e.g. {"status": "ok"} or a JSON list'
    )
    error_mode: Literal["raise", "return"] = Field(
        default="raise",
        description='Precondition failure style: "raise" (ValueError) or "return" (error dict)',
    )
    failure_inputs_json: str = Field(
        default="",
        description='Empty if no failure test; else JSON kwargs that must raise ValueError',
    )
    entity_identifier: str = Field(
        default="",
        description=(
            "For a stateful CRUD requirement (create/edit/delete/look up a PERSISTED entity), the "
            "ONE field that uniquely keys that entity for lookup — e.g. 'id' or 'name'. It MUST be "
            "a key present in example_inputs_json (possibly nested inside an entity object). Use "
            '"" for stateless requirements or pure computations with no persisted entity.'
        ),
    )


class FeaturePlan(BaseModel):
    plans: list[FRPlan] = Field(default_factory=list)
