from contextlib import asynccontextmanager
from pathlib import Path

from playwright.async_api import Browser, Error as PlaywrightError, Page, async_playwright

from engine.config import HEIGHT, WIDTH
from engine.errors import EngineError


@asynccontextmanager
async def launch():
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            try:
                yield browser
            finally:
                await browser.close()
    except PlaywrightError as e:
        raise EngineError(f"Browser failed: {e}. If Chromium is missing, run: playwright install chromium") from e


@asynccontextmanager
async def open_slide(browser: Browser, html: Path):
    page = await browser.new_page(viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=1)
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    try:
        await page.goto(html.resolve().as_uri())
        missing = await page.evaluate("window.__ready()")
        if missing:
            raise EngineError(f"{html.name}: fonts failed to load: {', '.join(missing)}")
        if errors:
            raise EngineError(f"{html.name}: script error: {errors[0]}")
        yield page
    finally:
        await page.close()


async def seek(page: Page, t: float) -> None:
    await page.evaluate("(t) => window.seek(t)", t)
