import os

import httpx
from google import genai
from google.genai import errors, types
from pydantic import ValidationError

from engine.errors import EngineError
from engine.schema import Brand, SlideDeck

API_KEY_VAR = "GEMINI_API_KEY"
SCHEMA_KEYS = {"type", "properties", "required", "items", "enum", "minimum", "maximum",
               "minItems", "maxItems", "anyOf", "description", "additionalProperties"}


class DeckRejected(Exception):
    """The model returned a deck that breaks the schema; the message is feedback for a retry."""

SYSTEM_PROMPT = """You write animated Instagram carousels for a brand.

Structure:
- Slide 1 is a cover_hero that states the hook.
- The last slide is an outro_cta with one clear call to action.
- Every slide in between is a word_stagger (one sharp idea) or a comparison_split (a before/after contrast). Pick whichever fits the point being made; do not force a contrast where there is none.

Writing:
- Every field has a hard character limit, given in its description. Stay well inside it; shorter lines read better on a phone.
- Each slide makes exactly one point. No filler, no hype words, no emoji.
- Use sentence case. Keep claims and numbers faithful to the source material; never invent statistics.
- Write in the brand's voice.

Return the full carousel as JSON that matches the response schema."""


def _gemini_schema(node, defs: dict):
    """Rewrite a Pydantic JSON schema into the subset Gemini documents: refs inlined, length limits as descriptions."""
    if isinstance(node, list):
        return [_gemini_schema(item, defs) for item in node]
    if not isinstance(node, dict):
        return node
    if "$ref" in node:
        return _gemini_schema(defs[node["$ref"].rsplit("/", 1)[-1]], defs)
    out, notes = {}, []
    for key, value in node.items():
        if key == "properties":
            out[key] = {name: _gemini_schema(prop, defs) for name, prop in value.items()}
        elif key == "oneOf":
            out["anyOf"] = _gemini_schema(value, defs)
        elif key == "const":
            out["enum"] = [value]
        elif key == "maxLength":
            notes.append(f"At most {value} characters.")
        elif key in SCHEMA_KEYS:
            out[key] = _gemini_schema(value, defs)
    if notes:
        out["description"] = " ".join(filter(None, [out.get("description"), *notes]))
    branches = out.get("anyOf", [])
    if len(branches) == 2 and {"type": "null"} in branches:
        value = next(b for b in branches if b != {"type": "null"})
        out = {**value, **{k: v for k, v in out.items() if k != "anyOf"}, "type": [value["type"], "null"]}
    return out


def response_schema() -> dict:
    schema = SlideDeck.model_json_schema()
    return _gemini_schema(schema, schema.get("$defs", {}))


def _prompt(source: str, brand: Brand, slide_count: int, feedback: str | None) -> str:
    parts = [
        f"Brand: {brand.name} ({brand.handle})",
        f"Voice: {brand.voice or 'clear and direct'}",
        f"Slides: exactly {slide_count}",
        f"Source material:\n<source>\n{source}\n</source>",
    ]
    if feedback:
        parts.append(f"Your previous attempt failed these checks. Fix every one and return the full carousel again:\n{feedback}")
    return "\n\n".join(parts)


def write_deck(source: str, brand: Brand, slide_count: int, model: str, feedback: str | None = None) -> SlideDeck:
    """Ask the model for a deck. Raises DeckRejected if the output breaks the schema."""
    api_key = os.environ.get(API_KEY_VAR)
    if not api_key:
        raise EngineError(f"Set the {API_KEY_VAR} environment variable to use generate")
    try:
        response = genai.Client(api_key=api_key).models.generate_content(
            model=model,
            contents=_prompt(source, brand, slide_count, feedback),
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                response_mime_type="application/json",
                response_json_schema=response_schema(),
            ),
        )
    except (errors.APIError, httpx.HTTPError) as e:
        raise EngineError(f"Gemini API request failed: {e}") from e

    if not response.text:
        raise EngineError("Gemini did not return a carousel")
    try:
        deck = SlideDeck.model_validate_json(response.text)
    except ValidationError as e:
        raise DeckRejected(str(e)) from e
    if len(deck.slides) != slide_count:
        raise DeckRejected(f"Expected exactly {slide_count} slides, got {len(deck.slides)}.")
    return deck
