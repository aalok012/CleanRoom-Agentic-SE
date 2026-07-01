from pydantic import BaseModel, Field


class FileImplementation(BaseModel):
    """The LLM's output for ONE contract: just the file body.

    Ids, paths, layer and feature ownership are NOT trusted to the LLM — they come from
    the planner's contract and are attached deterministically by the agent.
    """

    content: str = Field(
        description="Full Python source of the file: the function implemented exactly per its "
        "signature and docstring, plus any imports it needs. No prose outside the code."
    )


class GeneratedFile(BaseModel):
    fr_id: str = Field(description="Functional requirement this file implements (from the contract)")
    feature_id: str = Field(description="Owning feature id (from the contract)")
    path: str = Field(description="Deterministic file path from the planner's contract")
    mvc_layer: str = Field(description="The file's layer: 'model', 'view', or 'controller'")
    content: str = Field(description="Full source of the file")


class GeneratedCode(BaseModel):
    files: list[GeneratedFile] = Field(default_factory=list)
