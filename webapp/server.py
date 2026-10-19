import asyncio
import base64
import io
import json
import logging
import os
import re
import secrets
import shutil
import zipfile
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import get_args

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from engine import pipeline, renderer
from engine.compiler import slide_stem
from engine.config import DEFAULT_MODEL, FONTS_DIR, ROOT
from engine.errors import EngineError
from engine.schema import Brand, Carousel, Slide, load_model

BRANDS_DIR = ROOT / "brands"
CAROUSELS_DIR = ROOT / "output"
STATIC_DIR = Path(__file__).parent / "static"
REQUEST_NAME = "request.json"
QA_NAME = "qa.json"
ATTEMPTS = 2
RENDER_PARALLEL = 4
NAME = re.compile(r"[A-Za-z0-9_-]{1,64}")
FILE_NAME = re.compile(r"[A-Za-z0-9_-]{1,80}\.(html|mp4)")
FILE_KINDS = {"slides": ".html", "mp4": ".mp4"}

log = logging.getLogger("webapp")

Work = Callable[[Callable[[str], None]], Awaitable[None]]


@dataclass
class Job:
    kind: str
    status: str = "waiting"
    log: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def active(self) -> bool:
        return self.status in ("waiting", "running")


class CreateRequest(BaseModel):
    brand: str = Field(pattern=NAME.pattern)
    source: str = Field(min_length=1)
    slides: int = Field(6, ge=2, le=15)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.jobs = {}
    app.state.tasks = set()
    app.state.slot = asyncio.Semaphore(1)
    yield


app = FastAPI(title="Carousel Studio", lifespan=lifespan, docs_url=None, redoc_url=None)
app.mount("/fonts", StaticFiles(directory=FONTS_DIR), name="fonts")


@app.middleware("http")
async def require_password(request: Request, call_next):
    expected = os.environ.get("APP_PASSWORD", "")
    header = request.headers.get("authorization", "")
    password = ""
    if header.startswith("Basic "):
        try:
            password = base64.b64decode(header[6:]).decode().partition(":")[2]
        except (ValueError, UnicodeDecodeError):
            password = ""
    if not expected or not secrets.compare_digest(password.encode(), expected.encode()):
        return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="Carousel Studio"'})
    return await call_next(request)


@app.exception_handler(EngineError)
async def engine_error(request: Request, exc: EngineError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        raise EngineError(f"Cannot read {path.name}: {e}") from e


def _write_json(path: Path, data) -> None:
    try:
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except OSError as e:
        raise EngineError(f"Cannot write {path.name}: {e}") from e


def _folder(carousel_id: str) -> Path:
    path = CAROUSELS_DIR / carousel_id
    if not NAME.fullmatch(carousel_id) or not path.is_dir():
        raise HTTPException(404, "Carousel not found")
    return path


def _carousel(folder: Path) -> Carousel | None:
    spec = folder / pipeline.SPEC_NAME
    return load_model(Carousel, spec) if spec.exists() else None


def _brands() -> dict[str, Brand]:
    return {path.stem: load_model(Brand, path) for path in sorted(BRANDS_DIR.glob("*.json"))}


def _job(carousel_id: str) -> Job | None:
    return app.state.jobs.get(carousel_id)


def _ensure_idle(carousel_id: str) -> None:
    job = _job(carousel_id)
    if job and job.active:
        raise HTTPException(409, "This carousel is still being worked on. Wait for it to finish.")


def _clear_videos(folder: Path) -> None:
    shutil.rmtree(folder / "mp4", ignore_errors=True)


def _save_issues(folder: Path, issues: list) -> list[dict]:
    found = [asdict(issue) for issue in issues]
    _write_json(folder / QA_NAME, found)
    return found


async def _check(carousel: Carousel, folder: Path) -> list[dict]:
    _, issues = await pipeline.build(carousel, folder)
    return _save_issues(folder, issues)


async def _run(job: Job, work: Work) -> None:
    async with app.state.slot:
        job.status = "running"
        try:
            await work(job.log.append)
            job.status = "done"
        except EngineError as e:
            job.status, job.error = "failed", str(e)
        except Exception:
            log.exception("%s job failed", job.kind)
            job.status, job.error = "failed", "Something unexpected went wrong. The server log has the details."


def _start(carousel_id: str, kind: str, work: Work) -> Job:
    _ensure_idle(carousel_id)
    job = Job(kind)
    app.state.jobs[carousel_id] = job
    task = asyncio.create_task(_run(job, work))
    app.state.tasks.add(task)
    task.add_done_callback(app.state.tasks.discard)
    return job


def _generate_work(request: CreateRequest, brand: Brand, folder: Path) -> Work:
    async def work(say: Callable[[str], None]) -> None:
        _clear_videos(folder)
        try:
            await pipeline.generate(request.source, brand, request.slides, DEFAULT_MODEL, ATTEMPTS, folder, say)
        except EngineError:
            carousel = _carousel(folder)
            if carousel:
                await _check(carousel, folder)
            raise
        _save_issues(folder, [])
    return work


def _slides(carousel_id: str, folder: Path, carousel: Carousel, job: Job | None) -> list[dict]:
    rendering = job is not None and job.kind == "render" and job.active
    slides = []
    for index, slide in enumerate(carousel.slides, 1):
        stem = slide_stem(index, slide)
        video = folder / "mp4" / f"{stem}.mp4"
        html = folder / "slides" / f"{stem}.html"
        slides.append({
            "stem": stem,
            "html": f"/files/{carousel_id}/slides/{stem}.html" if html.exists() else None,
            "video": f"/files/{carousel_id}/mp4/{stem}.mp4" if video.exists() and not rendering else None,
        })
    return slides


@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/brands")
async def list_brands():
    return [{"id": key, **brand.model_dump()} for key, brand in _brands().items()]


@app.get("/api/slide-types")
async def slide_types():
    models = get_args(get_args(Slide)[0])
    return {model.model_json_schema()["properties"]["type"]["const"]: model.model_json_schema() for model in models}


@app.get("/api/carousels")
async def list_carousels():
    found = []
    for spec in CAROUSELS_DIR.glob(f"*/{pipeline.SPEC_NAME}"):
        try:
            carousel = load_model(Carousel, spec)
        except EngineError:
            log.warning("Skipping unreadable %s", spec)
            continue
        job = _job(spec.parent.name)
        found.append({
            "id": spec.parent.name,
            "title": carousel.title,
            "brand": carousel.brand.name,
            "slides": len(carousel.slides),
            "updated": spec.stat().st_mtime,
            "busy": bool(job and job.active),
        })
    return sorted(found, key=lambda c: c["updated"], reverse=True)


@app.post("/api/carousels", status_code=202)
async def create_carousel(request: CreateRequest):
    brand = _brands().get(request.brand)
    if brand is None:
        raise HTTPException(400, f"Unknown brand: {request.brand}")
    carousel_id = secrets.token_hex(4)
    folder = CAROUSELS_DIR / carousel_id
    try:
        folder.mkdir(parents=True)
    except OSError as e:
        raise EngineError(f"Cannot create a folder for the carousel: {e}") from e
    _write_json(folder / REQUEST_NAME, request.model_dump())
    _start(carousel_id, "generate", _generate_work(request, brand, folder))
    return {"id": carousel_id}


@app.get("/api/carousels/{carousel_id}")
async def get_carousel(carousel_id: str):
    folder = _folder(carousel_id)
    carousel = _carousel(folder)
    job = _job(carousel_id)
    return {
        "id": carousel_id,
        "carousel": carousel.model_dump() if carousel else None,
        "issues": _read_json(folder / QA_NAME),
        "can_rewrite": (folder / REQUEST_NAME).exists(),
        "job": asdict(job) if job else None,
        "slides": _slides(carousel_id, folder, carousel, job) if carousel else [],
    }


@app.put("/api/carousels/{carousel_id}")
async def save_carousel(carousel_id: str, carousel: Carousel):
    folder = _folder(carousel_id)
    _ensure_idle(carousel_id)
    pipeline.save_spec(carousel, folder)
    _clear_videos(folder)
    return {"issues": await _check(carousel, folder)}


@app.post("/api/carousels/{carousel_id}/rewrite", status_code=202)
async def rewrite_carousel(carousel_id: str):
    folder = _folder(carousel_id)
    saved = _read_json(folder / REQUEST_NAME)
    if saved is None:
        raise HTTPException(400, "This carousel wasn't created on the website, so there is no topic to rewrite from.")
    request = CreateRequest.model_validate(saved)
    brand = _brands().get(request.brand)
    if brand is None:
        raise HTTPException(400, f"Unknown brand: {request.brand}")
    _start(carousel_id, "generate", _generate_work(request, brand, folder))
    return {"id": carousel_id}


@app.post("/api/carousels/{carousel_id}/render", status_code=202)
async def render_carousel(carousel_id: str):
    folder = _folder(carousel_id)
    carousel = _carousel(folder)
    if carousel is None:
        raise HTTPException(400, "This carousel has no slides yet.")

    async def work(say: Callable[[str], None]) -> None:
        say("Checking slides")
        html_paths, issues = await pipeline.build(carousel, folder)
        if _save_issues(folder, issues):
            raise EngineError("Fix the quality problems on the review page before making videos.")
        _clear_videos(folder)
        say(f"Making {len(html_paths)} videos")
        await renderer.render(carousel, html_paths, folder / "mp4", RENDER_PARALLEL)

    _start(carousel_id, "render", work)
    return {"id": carousel_id}


@app.get("/api/carousels/{carousel_id}/videos.zip")
async def download_videos(carousel_id: str):
    folder = _folder(carousel_id)
    carousel = _carousel(folder)
    slides = _slides(carousel_id, folder, carousel, _job(carousel_id)) if carousel else []
    if not slides or any(s["video"] is None for s in slides):
        raise HTTPException(409, "The videos aren't ready yet.")
    buffer = io.BytesIO()
    try:
        with zipfile.ZipFile(buffer, "w") as archive:
            for slide in slides:
                archive.write(folder / "mp4" / f"{slide['stem']}.mp4", f"{slide['stem']}.mp4")
    except OSError as e:
        raise EngineError(f"Cannot pack the videos: {e}") from e
    return Response(
        buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{carousel_id}-videos.zip"'},
    )


@app.get("/files/{carousel_id}/{kind}/{name}")
async def carousel_file(carousel_id: str, kind: str, name: str):
    folder = _folder(carousel_id)
    path = folder / kind / name
    if kind not in FILE_KINDS or not FILE_NAME.fullmatch(name) or not name.endswith(FILE_KINDS[kind]) or not path.is_file():
        raise HTTPException(404, "File not found")
    return FileResponse(path)
