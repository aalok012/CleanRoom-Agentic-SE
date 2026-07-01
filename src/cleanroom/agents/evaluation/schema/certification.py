from typing import ClassVar, Literal

from pydantic import BaseModel, Field


class TestVerdict(BaseModel):
    # Keep pytest from collecting this model as a test (its name starts with "Test").
    __test__: ClassVar[bool] = False

    requirement_id: str = Field(description="The requirement/test case this verdict is for, e.g. '2.2.1'")
    verdict: Literal["pass", "fail"] = Field(description="Whether the code satisfies this test case")
    reason: str = Field(default="", description="Brief justification for the verdict")


class FeatureJudgement(BaseModel):
    """The LLM judge's output for one (code sample, feature): one verdict per test case."""

    verdicts: list[TestVerdict] = Field(default_factory=list)


class FRCertification(BaseModel):
    """pass@k results for a single functional requirement (HumanEval-style task unit)."""

    fr_id: str
    feature_id: str = ""
    n_samples: int = 0
    n_test_cases: int = 0
    passing_samples: int = 0
    pass_at: dict[str, float] = Field(default_factory=dict)
    cases_passed: int = 0
    cases_total: int = 0
    case_pass_rate: float = 0.0


class FeatureCertification(BaseModel):
    """pass@k results for a single feature."""

    feature_id: str
    name: str = ""
    n_samples: int = Field(description="n: code samples generated for this feature")
    n_test_cases: int = Field(description="number of spec-derived test cases used as the oracle")
    passing_samples: int = Field(description="c: samples that passed ALL of the feature's test cases")
    pass_at: dict[str, float] = Field(default_factory=dict, description="e.g. {'pass@1': 0.4, 'pass@5': 1.0}")
    cases_passed: int = 0
    cases_total: int = 0
    case_pass_rate: float = 0.0


class CertificationResult(BaseModel):
    model: str = ""
    oracle: str = Field(default="executable", description="executable subprocess runner or llm_judge fallback")
    n: int = Field(description="samples generated per FR")
    k_values: list[int] = Field(default_factory=list)
    frs: list[FRCertification] = Field(default_factory=list)
    features: list[FeatureCertification] = Field(default_factory=list)
    aggregate_pass_at: dict[str, float] = Field(
        default_factory=dict, description="mean pass@k across features"
    )
    aggregate_case_pass_rate: float = Field(
        default=0.0, description="fraction of individual test case executions that passed"
    )
    failures: list[dict] = Field(
        default_factory=list,
        description="Per-case failure diagnostics (fr_id/feature_id/inputs/expected/reason). "
        "Consumed ONLY by the opt-in recovery loop to feed failing cases back into "
        "regeneration — never read by the clean-room Code/Test agents.",
    )
    notes: list[str] = Field(default_factory=list)
