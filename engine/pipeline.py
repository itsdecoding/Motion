import asyncio
from collections.abc import Callable
from pathlib import Path

from engine import verifier
from engine.compiler import compile_carousel
from engine.errors import EngineError
from engine.schema import Brand, Carousel
from engine.synthesizer import DeckRejected, write_deck

SPEC_NAME = "carousel.json"


def save_spec(carousel: Carousel, folder: Path) -> Path:
    path = folder / SPEC_NAME
    try:
        folder.mkdir(parents=True, exist_ok=True)
        path.write_text(carousel.model_dump_json(indent=2), encoding="utf-8")
    except OSError as e:
        raise EngineError(f"Cannot write {path}: {e}") from e
    return path


async def build(carousel: Carousel, folder: Path) -> tuple[list[Path], list[verifier.Issue]]:
    html_paths = compile_carousel(carousel, folder / "slides")
    return html_paths, await verifier.verify(carousel, html_paths)


async def generate(
    source: str,
    brand: Brand,
    slide_count: int,
    model: str,
    attempts: int,
    folder: Path,
    log: Callable[[str], None],
) -> Carousel:
    """Write, save and QA a carousel, retrying with QA feedback. Raises EngineError if no attempt passes."""
    feedback = None
    for attempt in range(1, attempts + 1):
        log(f"Attempt {attempt}: writing slides")
        try:
            deck = await asyncio.to_thread(write_deck, source, brand, slide_count, model, feedback)
        except DeckRejected as e:
            feedback = str(e)
            log("  The slides broke the schema")
            continue
        carousel = Carousel(title=deck.title, slides=deck.slides, brand=brand)
        save_spec(carousel, folder)
        log("Checking slides")
        _, issues = await build(carousel, folder)
        if not issues:
            log("QA passed")
            return carousel
        for issue in issues:
            log(f"  {issue}")
        feedback = "\n".join(map(str, issues))
    raise EngineError(f"No carousel passed QA after {attempts} attempts. Edit {folder / SPEC_NAME} and run verify.\n{feedback}")
