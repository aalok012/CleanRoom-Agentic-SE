import json
from typing import ClassVar, Literal

from pydantic import BaseModel, Field, field_validator


class TestCase(BaseModel):
    __test__: ClassVar[bool] = False

    # Capable models often return real JSON (dict/list) for these JSON-as-string fields instead of
    # a string; coerce non-strings back to a JSON string so strict `str` validation doesn't fail
    # the whole structured call (which would surface as a None and crash the test stage).
    @field_validator("inputs_json", "expected_json", "setup_json", mode="before", check_fields=False)
    @classmethod
    def _coerce_json_to_str(cls, v):
        if isinstance(v, str):
            return v
        try:
            return json.dumps(v)
        except (TypeError, ValueError):
            return str(v)

    requirement_id: str = Field(description="The requirement this case verifies, e.g. '2.2.1'")
    description: str = Field(description="What behavior is being checked")
    inputs: str = Field(description="Human-readable summary of inputs")
    expected: str = Field(description="Human-readable summary of expected result")
    inputs_json: str = Field(
        description='JSON object of keyword arguments, e.g. {"query": "pizza"}'
    )
    expected_json: str = Field(
        description='JSON expected return, or {"raises": "<ExceptionType>"} for failure cases '
        '(e.g. ValueError in Python / HTTPException in FastAPI / IllegalArgumentException in Java)'
    )
    oracle: Literal["eq", "raises"] = Field(
        default="eq", description="eq = assert return equals expected_json; raises = expect exception"
    )
    setup_json: str = Field(
        default="",
        description=(
            "FastAPI stack only: a JSON array of Arrange calls that establish this case's "
            'precondition state before the main call, e.g. for "edit an existing staff member" '
            '[{"inputs": {"action": "add", "staff_member": {"id": 1, "name": "Ann"}}}]. Each '
            'item is {"inputs": <body-object>, "route"?: "<route>"} (route defaults to this '
            "requirement's own endpoint). Use the SAME identifiers the main inputs reference so "
            "the entity exists. Empty when the call needs no pre-existing state."
        ),
    )


class FeatureTests(BaseModel):
    feature_id: str = Field(description="Feature these cases belong to, e.g. '2.2'")
    cases: list[TestCase] = Field(default_factory=list)
    test_source: str = Field(
        default="",
        description="Runnable test module encoding the cases — a pytest module for Python "
        "(incl. FastAPI), or a JUnit5 test class for Java.",
    )


class TestSourceRepair(BaseModel):
    test_source: str = Field(
        description="Full repaired Java source for the same generated JUnit/Spring test class."
    )


class GeneratedTests(BaseModel):
    features: list[FeatureTests] = Field(default_factory=list)
