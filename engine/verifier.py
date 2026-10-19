import asyncio
from dataclasses import dataclass
from pathlib import Path

from playwright.async_api import Browser

from engine.browser import launch, open_slide, seek
from engine.config import QA_STEP
from engine.schema import Carousel, SlideBase

QA_JS = """
() => {
  const W = innerWidth, H = innerHeight, issues = [];
  const rgb = (s) => { const m = s.match(/[\\d.]+/g); return m && m.length >= 3 ? m.map(Number) : null; };
  const lum = ([r, g, b]) => {
    const f = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  const background = (el) => {
    for (let e = el; e; e = e.parentElement) {
      const c = rgb(getComputedStyle(e).backgroundColor);
      if (c && (c[3] ?? 1) > 0) return c;
    }
    return [255, 255, 255];
  };
  const hasText = (el) => [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim())
    || el.querySelector(".word") !== null;
  const els = [...document.querySelectorAll("[data-qa]")];
  const texts = els.filter(hasText);

  for (const el of els) {
    const name = el.dataset.qa, r = el.getBoundingClientRect();
    const clips = getComputedStyle(el).overflow !== "visible";
    if (el.scrollWidth > el.clientWidth + 1 || (clips && el.scrollHeight > el.clientHeight + 1))
      issues.push({ check: "overflow", element: name, detail: `content ${el.scrollWidth}x${el.scrollHeight} exceeds box ${el.clientWidth}x${el.clientHeight}` });
    if (r.left < -0.5 || r.top < -0.5 || r.right > W + 0.5 || r.bottom > H + 0.5)
      issues.push({ check: "bounds", element: name, detail: "extends past the canvas edge" });
  }
  for (const el of texts) {
    const style = getComputedStyle(el), size = parseFloat(style.fontSize);
    const [a, b] = [lum(rgb(style.color)), lum(background(el))];
    const ratio = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05), min = size >= 24 ? 3 : 4.5;
    if (ratio < min) issues.push({ check: "contrast", element: el.dataset.qa, detail: `ratio ${ratio.toFixed(2)} is below ${min}` });
  }
  for (let i = 0; i < texts.length; i++) for (let j = i + 1; j < texts.length; j++) {
    const [a, b] = [texts[i], texts[j]];
    if (a.contains(b) || b.contains(a)) continue;
    const ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
    const w = Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left);
    const h = Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top);
    if (w > 1 && h > 1) issues.push({ check: "overlap", element: `${a.dataset.qa} + ${b.dataset.qa}`, detail: `overlap ${Math.round(w)}x${Math.round(h)}px` });
  }
  return issues;
}
"""


@dataclass(frozen=True)
class Issue:
    slide: int
    time: float
    check: str
    element: str
    detail: str

    def __str__(self) -> str:
        return f"slide {self.slide} at {self.time:.2f}s: {self.check} on {self.element} ({self.detail})"


def sample_times(slide: SlideBase) -> list[float]:
    times, t = [], slide.settle_time
    while t < slide.duration:
        times.append(round(t, 3))
        t += QA_STEP
    return times


async def _verify_slide(browser: Browser, index: int, slide: SlideBase, html: Path) -> list[Issue]:
    found: dict[tuple[str, str], Issue] = {}
    async with open_slide(browser, html) as page:
        for t in sample_times(slide):
            await seek(page, t)
            for raw in await page.evaluate(QA_JS):
                found.setdefault((raw["check"], raw["element"]), Issue(index, t, **raw))

        t = slide.settle_time
        await seek(page, t)
        first = await page.screenshot(type="png")
        await seek(page, 0)
        await seek(page, t)
        if await page.screenshot(type="png") != first:
            found[("determinism", "page")] = Issue(index, t, "determinism", "page", "seek(t) produced different frames for the same t")
    return list(found.values())


async def verify(carousel: Carousel, html_paths: list[Path]) -> list[Issue]:
    async with launch() as browser:
        results = await asyncio.gather(*(
            _verify_slide(browser, i, slide, html)
            for i, (slide, html) in enumerate(zip(carousel.slides, html_paths), 1)
        ))
    return [issue for slide_issues in results for issue in slide_issues]
