from pydantic import BaseModel, Field


class FunctionalRequirement(BaseModel):
    """A requirement describing what the system DOES (behavior / input / output)."""

    id: str = Field(description="Section ID exactly as in the SRS, e.g. '2.2.1.1' — assigned by the parser, never the LLM")
    text: str = Field(description="Requirement text copied or closely paraphrased from the SRS")


class Feature(BaseModel):
    id: str = Field(default="", description="Feature/section ID from the SRS, e.g. '2.2'")
    name: str
    description: str = ""
    functional_requirements: list[FunctionalRequirement] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Behavioral contract — the formal, design-by-contract specification of ONE
# functional requirement. Written by the Spec Agent's LLM phase from the SPEC
# only (no code, no tests). Stack-agnostic: it captures WHAT must hold, not how.
# ---------------------------------------------------------------------------
class BehavioralContract(BaseModel):
    """A pre/post-condition contract for a single functional requirement."""

    fr_id: str = Field(description="Functional requirement id, from the parser — never invented")
    feature_id: str = Field(description="Owning feature id")
    stimulus: str = Field(description="Input: the event, data payload, or user action that triggers the operation")
    precondition: str = Field(description="Boolean condition that must hold before the operation runs; if violated the contract is broken")
    response: str = Field(description="Output: the deterministic result or action returned to the external environment")
    postcondition: str = Field(description="Guarantee true after execution, linking the response back to the inputs")


# ---------------------------------------------------------------------------
# Per-feature LLM contract result (used with with_structured_output()).
# The LLM only authors the contract fields; the id always comes from the parser.
# ---------------------------------------------------------------------------
class FRContract(BaseModel):
    id: str = Field(description="The requirement id, echoed VERBATIM from the input — never changed or invented")
    stimulus: str = Field(description="Input: the event, data payload, or user action that triggers the operation")
    precondition: str = Field(description="Boolean condition that must hold before the operation runs; 'none' if always callable")
    response: str = Field(description="Output: the deterministic result or action returned to the external environment")
    postcondition: str = Field(description="Guarantee true after execution, linking the response to the inputs")


class FeatureContractSet(BaseModel):
    contracts: list[FRContract] = Field(default_factory=list)


class IntermediateRepresentation(BaseModel):
    project_name: str
    source_file: str
    features: list[Feature] = Field(default_factory=list)
    contracts: list[BehavioralContract] = Field(default_factory=list)


class EnrichedIR(IntermediateRepresentation):
    """Pipeline IR after downstream stages — optional enrichment keys."""

    dependency_graph: dict | None = None
    planning: dict | None = None
    generated_code: dict | None = None
    generated_tests: dict | None = None
    verification: dict | None = None
    certification: dict | None = None
    metrics: dict | None = None
