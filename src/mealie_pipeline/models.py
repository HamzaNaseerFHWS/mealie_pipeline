"""Data shapes shared by the stages. The LLM output schema is generated from `ExtractedRecipe`."""

from typing import Any, Literal

from pydantic import BaseModel, Field

SourceKind = Literal["web", "desc", "cmt", "asr", "ocr"]


class Evidence(BaseModel):
    source: SourceKind
    quote: str = Field(description="Verbatim substring of the cited source, in its original language.")


class ExtractedIngredient(BaseModel):
    line: str = Field(description="One ingredient, in English, e.g. '2 tbsp olive oil'.")
    original_line: str = Field(description="The same ingredient exactly as the source wrote it.")
    section: str | None = Field(default=None, description="Section heading such as 'For the sauce'.")
    quantity_stated: bool = Field(description="False when the source never gave an amount.")
    evidence: list[Evidence]


class ExtractedStep(BaseModel):
    section: str | None = None
    text: str
    evidence: list[Evidence]


class TagChoice(BaseModel):
    tag: str = Field(description="Exactly one of the existing Mealie tag names.")
    reason: str


class ExtractedRecipe(BaseModel):
    is_recipe: bool
    name: str
    description: str = ""
    language: Literal["en", "de", "ur", "hi"] = "en"
    servings: float | None = None
    yield_text: str | None = None
    prep_minutes: int | None = None
    cook_minutes: int | None = None
    total_minutes: int | None = None
    ingredients: list[ExtractedIngredient] = Field(default_factory=list)
    instructions: list[ExtractedStep] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    tag_choices: list[TagChoice] = Field(default_factory=list)
    missing_info: list[str] = Field(default_factory=list)


def extraction_schema(tag_names: list[str]) -> dict[str, Any]:
    """The JSON Schema for `ExtractedRecipe` with `tag_choices[].tag` restricted to existing tags."""
    schema = ExtractedRecipe.model_json_schema()
    if tag_names:
        schema["$defs"]["TagChoice"]["properties"]["tag"]["enum"] = list(tag_names)
    return schema


class VideoMeta(BaseModel):
    """What the pipeline keeps from yt-dlp's metadata."""

    title: str
    description: str = ""
    uploader: str = ""
    uploader_id: str = ""
    duration_s: float | None = None
    upload_date: str | None = None
    thumbnail: str | None = None
    webpage_url: str = ""


class ParsedIngredient(BaseModel):
    """One ingredient line after parsing and catalog matching (ids are None only in a dry run)."""

    original_text: str
    section: str | None = None
    quantity: float = 0
    quantity_stated: bool = True
    unit_id: str | None = None
    unit_name: str | None = None
    food_id: str | None = None
    food_name: str
    note: str = ""
    food_match: Literal["exact", "plural", "alias", "singular", "fuzzy", "new"] = "exact"
    unit_match: Literal["exact", "plural", "alias", "none", "new"] = "none"


class JudgeProblem(BaseModel):
    severity: Literal["blocker", "major", "minor"]
    field: str = Field(description="Which part of the recipe: ingredients, steps, times, name, ...")
    description: str


class Judge(BaseModel):
    """What the independent LLM review answers to "what is missing or wrong?"."""

    problems: list[JudgeProblem] = Field(default_factory=list)
