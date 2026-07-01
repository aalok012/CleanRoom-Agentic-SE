"""Schemas for the Dafny proof tier."""

from pydantic import BaseModel, Field


class FeatureDafny(BaseModel):
    """The verified (or best-effort) Dafny state machine for one feature."""

    feature_id: str
    module: str = Field(description="Dafny module base name, e.g. 'F4_10' (module <base>Domain)")
    dafny_source: str = Field(description="Full .dfy source of the feature's Domain + Kernel modules")
    verified: bool = Field(description="True iff `dafny verify` reported 0 errors")
    rounds: int = Field(default=0, description="Generate/revise rounds used")
    residual_errors: list[dict] = Field(
        default_factory=list, description="Remaining proof errors if not verified (line/message)"
    )
    axioms: list[dict] = Field(
        default_factory=list,
        description="`assume {:axiom}` escape hatches — obligations ASSUMED, not proved (line/content)",
    )

    @property
    def proved_clean(self) -> bool:
        """Verified with NO assumed axioms — a fully discharged proof."""
        return self.verified and not self.axioms


class GeneratedDafny(BaseModel):
    """All per-feature Dafny modules."""

    features: list[FeatureDafny] = Field(default_factory=list)

    @property
    def n_verified(self) -> int:
        return sum(1 for f in self.features if f.verified)
