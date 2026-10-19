import asyncio
import shutil
import subprocess

import pytest

from engine import renderer, verifier
from engine.compiler import compile_carousel
from engine.schema import Carousel


def _qa(spec: dict, tmp_path):
    carousel = Carousel.model_validate(spec)
    html = compile_carousel(carousel, tmp_path)
    return carousel, html, asyncio.run(verifier.verify(carousel, html))


def test_example_passes_qa(spec, tmp_path):
    _, html, issues = _qa(spec, tmp_path)
    assert len(html) == 4
    assert issues == []


def test_qa_flags_overflowing_text(spec, tmp_path):
    spec["slides"][1]["lines"] = ["Antidisestablishmentarians"]
    _, _, issues = _qa(spec, tmp_path)
    assert any(i.slide == 2 and i.check == "overflow" and i.element == "line-1" for i in issues)


def test_qa_flags_low_contrast(spec, tmp_path):
    spec["brand"]["palette"]["muted"] = "#D8D6D0"
    _, _, issues = _qa(spec, tmp_path)
    assert any(i.check == "contrast" for i in issues)


def test_qa_flags_nondeterministic_seek(spec, tmp_path):
    spec["slides"] = spec["slides"][:1]
    carousel = Carousel.model_validate(spec)
    [html] = compile_carousel(carousel, tmp_path)
    html.write_text(html.read_text().replace("stage(loopT);", "stage(loopT + Math.random());"))
    issues = asyncio.run(verifier.verify(carousel, [html]))
    assert any(i.check == "determinism" for i in issues)


@pytest.mark.skipif(shutil.which("ffprobe") is None, reason="FFmpeg not installed")
def test_render_produces_exact_frames(spec, tmp_path):
    spec["slides"] = [dict(spec["slides"][0], duration=3.0)]
    carousel = Carousel.model_validate(spec)
    html = compile_carousel(carousel, tmp_path / "slides")
    [mp4] = asyncio.run(renderer.render(carousel, html, tmp_path / "mp4", parallel=1))
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v", "-count_frames",
         "-show_entries", "stream=width,height,r_frame_rate,nb_read_frames", "-of", "csv=p=0", str(mp4)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert probe == "1080,1350,30/1,90"
