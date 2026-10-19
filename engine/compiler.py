import base64
from functools import cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateError

from engine.config import FONT_FACES, FONTS_DIR, HEIGHT, TEMPLATES_DIR, WIDTH
from engine.errors import EngineError
from engine.schema import Carousel, Palette, SlideBase


def mix(a: str, b: str, amount: float) -> str:
    """Blend hex color a toward b by amount (0 = a, 1 = b)."""
    ca, cb = (int(a[i:i + 2], 16) for i in (1, 3, 5)), (int(b[i:i + 2], 16) for i in (1, 3, 5))
    return "#" + "".join(f"{round(x + (y - x) * amount):02x}" for x, y in zip(ca, cb))


def slide_stem(index: int, slide: SlideBase) -> str:
    return f"{index:02d}_{slide.type}"


@cache
def _font_css() -> str:
    rules = []
    for family, file, weight, style in FONT_FACES:
        path = FONTS_DIR / file
        try:
            data = base64.b64encode(path.read_bytes()).decode()
        except OSError as e:
            raise EngineError(f"Missing font file {path}") from e
        rules.append(
            f'@font-face {{ font-family: "{family}"; src: url(data:font/woff2;base64,{data}) format("woff2"); '
            f"font-weight: {weight}; font-style: {style}; font-display: block; }}"
        )
    return "\n".join(rules)


@cache
def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=True,
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def _theme(palette: Palette, dark: bool) -> dict[str, str]:
    bg, fg = (palette.carbon, palette.paper) if dark else (palette.paper, palette.ink)
    return {
        "bg": bg,
        "fg": fg,
        "soft": mix(fg, bg, 0.3) if dark else palette.muted,
        "line": mix(fg, bg, 0.8),
        "surface": mix(palette.ink, palette.paper, 0.94),
        "halo": mix(palette.glow, bg, 0.72),
    }


def compile_carousel(carousel: Carousel, out_dir: Path) -> list[Path]:
    template = _env().get_template("slide.html.j2")
    total = len(carousel.slides)
    paths = []
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        for index, slide in enumerate(carousel.slides, 1):
            html = template.render(
                carousel=carousel,
                brand=carousel.brand,
                palette=carousel.brand.palette,
                theme=_theme(carousel.brand.palette, slide.dark),
                slide=slide,
                starts=slide.starts(),
                index=index,
                total=total,
                font_css=_font_css(),
                width=WIDTH,
                height=HEIGHT,
            )
            path = out_dir / f"{slide_stem(index, slide)}.html"
            path.write_text(html, encoding="utf-8")
            paths.append(path)
    except TemplateError as e:
        raise EngineError(f"Template error: {e}") from e
    except OSError as e:
        raise EngineError(f"Cannot write slides to {out_dir}: {e}") from e
    return paths
