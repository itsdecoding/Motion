import pytest
from pydantic import ValidationError

from engine.compiler import mix
from engine.schema import Carousel


def test_example_is_valid(spec):
    carousel = Carousel.model_validate(spec)
    assert [s.type for s in carousel.slides] == ["cover_hero", "word_stagger", "comparison_split", "outro_cta"]


@pytest.mark.parametrize("change", [
    lambda s: s["slides"][0].update(type="spinning_cube"),
    lambda s: s["slides"][0].update(headline="x" * 49),
    lambda s: s["slides"][0].update(unknown_field="x"),
    lambda s: s["slides"][1].update(lines=[]),
    lambda s: s["brand"]["palette"].update(paper="cream"),
    lambda s: s.update(slides=s["slides"] * 4),
])
def test_rejects_invalid_specs(spec, change):
    change(spec)
    with pytest.raises(ValidationError):
        Carousel.model_validate(spec)


def test_duration_must_cover_the_animation(spec):
    spec["slides"][1].update(lines=["one two three four"] * 4, duration=3.0)
    with pytest.raises(ValidationError, match="settles at"):
        Carousel.model_validate(spec)


def test_mix():
    assert mix("#000000", "#ffffff", 0.5) == "#808080"
    assert mix("#123456", "#abcdef", 0) == "#123456"
