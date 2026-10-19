import asyncio
from functools import wraps
from pathlib import Path

import typer

from engine import pipeline, renderer, verifier
from engine.config import DEFAULT_MODEL
from engine.errors import EngineError
from engine.schema import Brand, Carousel, load_model

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Build animated carousels from a spec or a script.")


def reports_errors(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except EngineError as e:
            typer.secho(str(e), err=True, fg="red")
            raise typer.Exit(1)
    return wrapper


def _report(issues: list[verifier.Issue]) -> None:
    if not issues:
        typer.secho("QA passed", fg="green")
    for issue in issues:
        typer.secho(f"  {issue}", fg="yellow")


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as e:
        raise EngineError(f"Cannot read {path}: {e}") from e


@app.command()
@reports_errors
def generate(
    brand: Path = typer.Option(..., help="Brand JSON file."),
    script: Path = typer.Option(None, help="Script or outline file."),
    topic: str = typer.Option(None, help="Topic to write about, instead of a script."),
    slides: int = typer.Option(6, min=2, max=15, help="Number of slides."),
    out: Path = typer.Option(Path("output"), help="Output folder."),
    model: str = typer.Option(DEFAULT_MODEL, help="Gemini model."),
    attempts: int = typer.Option(2, min=1, max=5, help="Tries before giving up on QA failures."),
):
    """Write a carousel from a script or topic, then compile and QA it."""
    if (script is None) == (topic is None):
        raise EngineError("Pass exactly one of --script or --topic")
    source = _read(script) if script else topic
    brand_config = load_model(Brand, brand)
    asyncio.run(pipeline.generate(source, brand_config, slides, model, attempts, out, typer.echo))
    spec = out / pipeline.SPEC_NAME
    typer.echo(f"Saved {spec}. Render it with: python -m engine render {spec}")


@app.command()
@reports_errors
def verify(spec: Path = typer.Argument(..., help="carousel.json to check.")):
    """Compile a spec to HTML slides and run the QA checks."""
    carousel = load_model(Carousel, spec)
    html_paths, issues = asyncio.run(pipeline.build(carousel, spec.parent))
    typer.echo(f"Compiled {len(html_paths)} slides into {spec.parent / 'slides'}")
    _report(issues)
    if issues:
        raise typer.Exit(1)


@app.command()
@reports_errors
def render(
    spec: Path = typer.Argument(..., help="carousel.json to render."),
    parallel: int = typer.Option(4, min=1, max=16, help="Slides rendered at the same time."),
    skip_qa: bool = typer.Option(False, help="Render even if QA finds problems."),
):
    """Compile, QA, and render every slide to a 1080x1350 30 fps MP4."""
    carousel = load_model(Carousel, spec)
    html_paths, issues = asyncio.run(pipeline.build(carousel, spec.parent))
    _report(issues)
    if issues and not skip_qa:
        raise EngineError("Fix the QA problems above, or pass --skip-qa to render anyway")
    for path in asyncio.run(renderer.render(carousel, html_paths, spec.parent / "mp4", parallel)):
        typer.echo(f"Rendered {path}")
