from pydantic import BaseModel, Field


class DependencyEdge(BaseModel):
    """A single dependency: `source` depends on `target` (target must be built first)."""

    source: str = Field(description="Feature id that has the dependency, e.g. '2.3'")
    target: str = Field(description="Feature id that is the prerequisite, e.g. '2.2'")
    reason: str = Field(description="Why this edge exists, for traceability")


class FRDependency(BaseModel):
    """One FR's inferred prerequisites WITHIN the same feature (semantic pass)."""

    id: str = Field(description="The requirement id (source), echoed verbatim — never invented")
    prerequisite_ids: list[str] = Field(
        default_factory=list,
        description="Ids of requirements in THIS feature that must be built first",
    )


class FeatureFRDeps(BaseModel):
    dependencies: list[FRDependency] = Field(default_factory=list)


class DependencyGraph(BaseModel):
    nodes: list[str] = Field(default_factory=list, description="All feature ids in the spec")
    edges: list[DependencyEdge] = Field(default_factory=list)
    build_order: list[str] = Field(
        default_factory=list,
        description="Topological order: prerequisites come before their dependents",
    )
    cycles: list[list[str]] = Field(
        default_factory=list,
        description="Groups of feature ids involved in circular dependencies, if any",
    )
