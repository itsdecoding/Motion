from pathlib import Path
from typing import Annotated, ClassVar, Literal, TypeVar, Union

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, model_validator

from engine.config import FPS, QA_STEP, SPRING_SETTLE
from engine.errors import EngineError

HexColor = Annotated[str, StringConstraints(pattern=r"^#[0-9A-Fa-f]{6}$")]
WORD_STEP = 4 / FPS


def Text(max_length: int):
    return Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=max_length)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Palette(Strict):
    paper: HexColor
    carbon: HexColor
    ink: HexColor
    muted: HexColor
    highlight: HexColor
    glow: HexColor
    negative: HexColor


class Brand(Strict):
    name: Text(40)
    handle: Text(40)
    url: Text(60) | None = None
    voice: str = Field("", max_length=600)
    palette: Palette


class SlideBase(Strict):
    duration: float = Field(8.0, ge=3.0, le=15.0)
    dark: ClassVar[bool] = False

    def starts(self) -> dict[str, float | list[float]]:
        raise NotImplementedError

    @property
    def settle_time(self) -> float:
        times = [t for v in self.starts().values() for t in (v if isinstance(v, list) else [v])]
        return round(max(times) + SPRING_SETTLE, 3)

    @model_validator(mode="after")
    def _settles_before_end(self):
        minimum = self.settle_time + QA_STEP
        if self.duration < minimum:
            raise ValueError(f"animation settles at {self.settle_time:.2f}s, so duration must be at least {minimum:.2f}s")
        return self


def _stagger(start: float, count: int, step: float) -> list[float]:
    return [round(start + i * step, 3) for i in range(count)]


class CoverHero(SlideBase):
    """Opening hook on a dark background: a small badge, a bold headline, a serif accent line and an optional subline."""

    type: Literal["cover_hero"]
    dark: ClassVar[bool] = True
    badge: Text(28)
    headline: Text(48)
    headline_accent: Text(36)
    subline: Text(110) | None = None

    def starts(self):
        return {"orbit": 0.0, "badge": 0.1, "headline": 0.25, "accent": 0.45, "subline": 0.65}


class WordStagger(SlideBase):
    """A punchy statement revealed word by word. With several lines, the last one is set as a serif accent."""

    type: Literal["word_stagger"]
    lines: list[Text(26)] = Field(min_length=1, max_length=4)
    body: Text(170) | None = None

    def starts(self):
        words = _stagger(0.3, sum(len(line.split()) for line in self.lines), WORD_STEP)
        return {"words": words, "body": round(words[-1] + 0.15, 3)}


class ComparisonSplit(SlideBase):
    """A before/after contrast: what people usually do versus the better approach."""

    type: Literal["comparison_split"]
    title: Text(56)
    old_label: Text(24) = "The old way"
    new_label: Text(24) = "The new way"
    old_points: list[Text(56)] = Field(min_length=1, max_length=3)
    new_points: list[Text(56)] = Field(min_length=1, max_length=3)

    def starts(self):
        old_points = _stagger(0.5, len(self.old_points), 0.12)
        new_card = round(old_points[-1] + 0.3, 3)
        return {
            "title": 0.1,
            "old_card": 0.3,
            "old_points": old_points,
            "new_card": new_card,
            "new_points": _stagger(new_card + 0.2, len(self.new_points), 0.12),
        }


class OutroCta(SlideBase):
    """Closing slide on a dark background with a headline, a serif accent line, a call-to-action pill and an optional note."""

    type: Literal["outro_cta"]
    dark: ClassVar[bool] = True
    headline: Text(40)
    headline_accent: Text(36)
    cta: Text(32)
    note: Text(90) | None = None

    def starts(self):
        return {"orbit": 0.0, "headline": 0.2, "accent": 0.4, "cta": 0.7, "note": 0.9}


Slide = Annotated[Union[CoverHero, WordStagger, ComparisonSplit, OutroCta], Field(discriminator="type")]


class SlideDeck(Strict):
    title: Text(80)
    slides: list[Slide] = Field(min_length=1, max_length=15)


class Carousel(SlideDeck):
    brand: Brand


M = TypeVar("M", bound=BaseModel)


def load_model(model: type[M], path: Path) -> M:
    try:
        return model.model_validate_json(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise EngineError(f"Cannot read {path}: {e}") from e
    except ValidationError as e:
        raise EngineError(f"{path} is invalid:\n{e}") from e
