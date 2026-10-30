"""Data shapes shared by the stages. The LLM output schema is generated from `ExtractedRecipe`."""

from typing import Any, Literal

from pydantic import BaseModel, Field

SourceKind = Literal["web", "desc", "cmt", "asr", "ocr"]
ParseStatus = Literal["agreed", "nlp_preferred", "conflict", "unparsed", "nlp_only"]


class Evidence(BaseModel):
    source: SourceKind
    quote: str = Field(description="Verbatim substring of the cited source, in its original language.")


class LlmParse(BaseModel):
    """Engine B of the Ingredient Parser: the extraction call's own reading of the English line."""

    quantity: float | None = Field(default=None, description="The amount; null when none is given.")
    quantity_max: float | None = Field(default=None, description="Upper end of a range ('1-2' gives 2).")
    unit: str | None = Field(default=None, description="One of the known unit names, or null.")
    food: str | None = Field(default=None, description="The plain English food name, e.g. 'onion'.")
    note: str | None = Field(default=None, description="Size, preparation and comments: 'large, diced'.")


class ExtractedIngredient(BaseModel):
    line: str = Field(description="One ingredient, in English, e.g. '2 tbsp olive oil'.")
    original_line: str = Field(description="The same ingredient exactly as the source wrote it.")
    food_original: str = Field(
        default="",
        description="Only when the source is not English: the food's name as the source wrote it, "
        "without amount, unit or preparation, e.g. 'Muschelnudeln'. Empty for English sources.",
    )
    section: str | None = Field(default=None, description="Section heading such as 'For the sauce'.")
    quantity_stated: bool = Field(description="False when the source never gave an amount.")
    evidence: list[Evidence]
    llm_parse: LlmParse | None = Field(default=None, description="`line` split into its parts.")


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
    channel: str = ""  # Instagram: the username (its uploader_id is a number)
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
    food_original: str = ""
    note: str = ""
    food_match: Literal["exact", "plural", "alias", "singular", "fuzzy", "new"] = "exact"
    unit_match: Literal["exact", "plural", "alias", "none", "new"] = "none"
    # How the two parse engines compared (`nlp_only`: the extraction had no LLM parse, e.g. older data).
    parse_status: ParseStatus = "nlp_only"
    suspicious: list[str] = Field(default_factory=list)  # Sanity Check findings for this line
    food_aliases: list[str] = Field(default_factory=list)  # the Food's plural and aliases, for step links


class JudgeProblem(BaseModel):
    severity: Literal["blocker", "major", "minor"]
    field: str = Field(description="Which part of the recipe: ingredients, steps, times, name, ...")
    description: str


class Judge(BaseModel):
    """What the independent LLM review answers to "what is missing or wrong?"."""

    problems: list[JudgeProblem] = Field(default_factory=list)
