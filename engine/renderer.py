import asyncio
import shutil
from pathlib import Path

from playwright.async_api import Browser

from engine.browser import launch, open_slide, seek
from engine.config import FPS
from engine.errors import EngineError
from engine.schema import Carousel, SlideBase


def _ffmpeg_cmd(out_mp4: Path) -> list[str]:
    return [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "image2pipe", "-framerate", str(FPS), "-c:v", "png", "-i", "-",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "18",
        "-movflags", "+faststart", str(out_mp4),
    ]


async def _render_slide(browser: Browser, slide: SlideBase, html: Path, out_mp4: Path) -> Path:
    proc = await asyncio.create_subprocess_exec(
        *_ffmpeg_cmd(out_mp4), stdin=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        async with open_slide(browser, html) as page:
            for frame in range(round(slide.duration * FPS)):
                await seek(page, frame / FPS)
                proc.stdin.write(await page.screenshot(type="png"))
                await proc.stdin.drain()
        proc.stdin.close()
    except (BrokenPipeError, ConnectionResetError):
        pass
    except BaseException:
        proc.kill()
        await proc.wait()
        raise
    stderr = await proc.stderr.read()
    if await proc.wait() != 0:
        raise EngineError(f"FFmpeg failed for {html.name}: {stderr.decode(errors='replace').strip()}")
    return out_mp4


async def render(carousel: Carousel, html_paths: list[Path], out_dir: Path, parallel: int) -> list[Path]:
    if shutil.which("ffmpeg") is None:
        raise EngineError("FFmpeg is not installed or not on PATH")
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise EngineError(f"Cannot create {out_dir}: {e}") from e

    limit = asyncio.Semaphore(parallel)

    async def bounded(slide: SlideBase, html: Path) -> Path:
        async with limit:
            return await _render_slide(browser, slide, html, out_dir / f"{html.stem}.mp4")

    async with launch() as browser:
        return list(await asyncio.gather(*(bounded(s, h) for s, h in zip(carousel.slides, html_paths))))
